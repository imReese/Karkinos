"""Current plan, paper, and actual execution-evidence comparison."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from server.services.execution_reconciliation_broker_evidence import (
    candidate_broker_events,
    exact_broker_events_for_order,
)
from server.services.execution_reconciliation_values import (
    asset_class_equivalent,
    decimal_text,
    decimal_value,
    decision_action_ref,
    decision_action_side,
    evidence_identifier,
    fingerprint,
    json_object,
    object_value,
    order_payload,
    reference_list,
    sum_event_decimal,
    valid_strategy_advancement_refs,
)


def build_plan_paper_actual_comparison(
    db: Any,
    order: dict[str, Any],
    *,
    broker_events: list[Any],
    controlled_intent: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare one OMS plan with exact paper and imported broker outcomes."""

    payload = order_payload(order)
    if str(payload.get("execution_mode") or "") == "paper_shadow":
        return {
            "schema_version": "karkinos.plan_paper_actual_comparison.v1",
            "status": "not_applicable_paper_shadow_order",
            "order_id": str(order.get("order_id") or ""),
            "blockers": [],
            "differences": [],
            "authorizes_execution": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
        }

    planned, action_ref, paper_run_id, blockers = build_planned_projection(
        db,
        order,
        payload,
    )
    paper, paper_blockers, paper_differences = build_paper_projection(
        db,
        planned=planned,
        action_ref=action_ref,
        paper_run_id=paper_run_id,
    )
    blockers.extend(paper_blockers)
    differences = list(paper_differences)
    actual, actual_blockers, actual_differences = build_actual_projection(
        order,
        planned=planned,
        paper=paper,
        broker_events=broker_events,
        controlled_intent=controlled_intent,
    )
    blockers.extend(actual_blockers)
    differences.extend(actual_differences)

    blockers = list(dict.fromkeys(blockers))
    differences = list(dict.fromkeys(differences))
    status = "blocked" if blockers else "review_required" if differences else "pass"
    core = {
        "schema_version": "karkinos.plan_paper_actual_comparison.v1",
        "status": status,
        "order_id": str(order.get("order_id") or ""),
        "planned": planned,
        "paper": paper,
        "actual": actual,
        "blockers": blockers,
        "differences": differences,
        "persisted_evidence_only": True,
        "human_review_required": status != "pass",
        "authorizes_execution": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_change_capital_authority": True,
    }
    return {**core, "evidence_fingerprint": fingerprint(core)}


def build_planned_projection(
    db: Any,
    order: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str | None, str | None, list[str]]:
    planned = {
        "order_id": str(order.get("order_id") or ""),
        "source": str(order.get("source") or ""),
        "source_ref": str(order.get("source_ref") or ""),
        "symbol": str(order.get("symbol") or ""),
        "side": str(order.get("side") or "").lower(),
        "asset_class": str(order.get("asset_class") or "").lower(),
        "quantity": decimal_text(decimal_value(order.get("quantity"))),
        "order_type": str(order.get("order_type") or ""),
        "limit_price": decimal_text(decimal_value(order.get("limit_price"))),
    }
    blockers: list[str] = []
    gateway_evidence = object_value(payload.get("gateway_evidence"))
    account_truth_gate = object_value(gateway_evidence.get("account_truth"))
    research_gate = object_value(gateway_evidence.get("research_evidence"))
    risk_gate = object_value(gateway_evidence.get("risk"))
    paper_gate = object_value(gateway_evidence.get("paper_shadow"))
    action_ref = decision_action_ref(research_gate.get("evidence_ref"))
    action_reader = getattr(db, "get_action_task_sync", None)
    action = (
        action_reader(int(action_ref.removeprefix("action:")))
        if callable(action_reader) and action_ref is not None
        else None
    )
    decision_action: dict[str, Any] = {}
    if isinstance(action, dict):
        decision_action = {
            "action_id": action.get("id"),
            "source_signal_id": action.get("source_signal_id"),
            "symbol": str(action.get("symbol") or ""),
            "side": decision_action_side(action.get("direction")),
            "asset_class": str(action.get("asset_class") or "").lower(),
            "price": decimal_text(decimal_value(action.get("price"))),
            "target_weight": decimal_text(decimal_value(action.get("target_weight"))),
            "strategy_id": str(action.get("strategy_id") or ""),
            "timestamp": str(action.get("timestamp") or ""),
            "status": str(action.get("status") or ""),
        }
    planned["decision_action"] = decision_action
    planned["strategy_id"] = str(decision_action.get("strategy_id") or "")
    planned["research_evidence_ref"] = str(research_gate.get("evidence_ref") or "")
    planned["risk_ref"] = str(risk_gate.get("evidence_ref") or "")
    planned["account_truth_ref"] = str(account_truth_gate.get("evidence_ref") or "")
    planned["paper_shadow_ref"] = str(paper_gate.get("evidence_ref") or "")
    paper_run_id = evidence_identifier(
        paper_gate.get("evidence_ref"), expected_kind="paper_shadow"
    )
    if action_ref is None:
        blockers.append("planned_decision_action_reference_missing_or_invalid")
    elif not isinstance(action, dict):
        blockers.append("planned_decision_action_not_found")
    else:
        if str(decision_action.get("action_id") or "") != action_ref.removeprefix(
            "action:"
        ):
            blockers.append("planned_decision_action_identity_mismatch")
        if decision_action.get("symbol") != planned["symbol"]:
            blockers.append("planned_decision_action_symbol_mismatch")
        if decision_action.get("side") != planned["side"]:
            blockers.append("planned_decision_action_side_mismatch")
        if not asset_class_equivalent(
            decision_action.get("asset_class"),
            order.get("asset_class"),
        ):
            blockers.append("planned_decision_action_asset_class_mismatch")
        if planned["order_type"].lower() == "limit" and decimal_value(
            decision_action.get("price")
        ) != decimal_value(planned["limit_price"]):
            blockers.append("planned_decision_action_price_mismatch")
        if decimal_value(decision_action.get("target_weight")) is None:
            blockers.append("planned_decision_action_target_weight_missing")
        if decision_action.get("source_signal_id") is None:
            blockers.append("planned_decision_action_signal_missing")
        if not planned["strategy_id"]:
            blockers.append("planned_decision_action_strategy_missing")
        if not decision_action.get("timestamp"):
            blockers.append("planned_decision_action_timestamp_missing")
    if (
        evidence_identifier(
            account_truth_gate.get("evidence_ref"), expected_kind="account_truth"
        )
        is None
    ):
        blockers.append("planned_account_truth_reference_missing_or_invalid")
    if evidence_identifier(risk_gate.get("evidence_ref"), expected_kind="risk") is None:
        blockers.append("planned_risk_reference_missing_or_invalid")
    if paper_run_id is None:
        blockers.append("paper_shadow_run_reference_missing_or_invalid")
    return planned, action_ref, paper_run_id, blockers


def build_paper_projection(
    db: Any,
    *,
    planned: dict[str, Any],
    action_ref: str | None,
    paper_run_id: str | None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    differences: list[str] = []
    paper: dict[str, Any] = {}
    paper_run_reader = getattr(db, "get_paper_shadow_run_sync", None)
    paper_run = (
        paper_run_reader(paper_run_id)
        if callable(paper_run_reader) and paper_run_id is not None
        else None
    )
    if paper_run_id is not None and not isinstance(paper_run, dict):
        blockers.append("paper_shadow_run_not_found")
    if not isinstance(paper_run, dict):
        return paper, blockers, differences

    paper_payload = json_object(paper_run.get("payload_json"))
    matching_orders = [
        item
        for item in paper_payload.get("orders") or []
        if isinstance(item, dict)
        and str(object_value(item.get("order_intent")).get("action_ref") or "")
        == str(action_ref or "")
    ]
    if len(matching_orders) != 1:
        blockers.append("paper_shadow_order_lineage_not_unique")
        return paper, blockers, differences

    paper_order = matching_orders[0]
    paper_order_id = str(paper_order.get("order_id") or "")
    paper_fills = [
        item
        for item in paper_payload.get("fills") or []
        if isinstance(item, dict) and str(item.get("order_id") or "") == paper_order_id
    ]
    paper_fill_quantity = sum(
        (
            abs(decimal_value(item.get("fill_quantity")) or Decimal("0"))
            for item in paper_fills
        ),
        Decimal("0"),
    )
    paper_gross_amount = sum(
        (
            abs(decimal_value(item.get("fill_price")) or Decimal("0"))
            * abs(decimal_value(item.get("fill_quantity")) or Decimal("0"))
            for item in paper_fills
        ),
        Decimal("0"),
    )
    paper_average_price = (
        paper_gross_amount / paper_fill_quantity if paper_fill_quantity > 0 else None
    )
    paper_commission = sum(
        (decimal_value(item.get("commission")) or Decimal("0") for item in paper_fills),
        Decimal("0"),
    )
    paper_slippage = sum(
        (decimal_value(item.get("slippage")) or Decimal("0") for item in paper_fills),
        Decimal("0"),
    )
    intent = object_value(paper_order.get("order_intent"))
    paper = {
        "run_id": str(paper_run.get("run_id") or ""),
        "input_fingerprint": str(
            paper_run.get("input_fingerprint")
            or paper_payload.get("input_fingerprint")
            or ""
        ),
        "run_status": str(paper_run.get("status") or ""),
        "divergence_status": str(paper_run.get("divergence_status") or ""),
        "order_id": paper_order_id,
        "order_status": str(paper_order.get("status") or ""),
        "order_divergence_status": str(paper_order.get("divergence_status") or ""),
        "action_ref": str(intent.get("action_ref") or ""),
        "symbol": str(intent.get("symbol") or ""),
        "side": str(intent.get("side") or "").lower(),
        "planned_quantity": decimal_text(
            decimal_value(intent.get("estimated_quantity"))
        ),
        "planned_price": decimal_text(decimal_value(intent.get("estimated_price"))),
        "fill_count": len(paper_fills),
        "filled_quantity": decimal_text(paper_fill_quantity),
        "average_fill_price": decimal_text(paper_average_price),
        "commission_and_tax": decimal_text(paper_commission),
        "slippage": decimal_text(paper_slippage),
        "total_execution_cost": decimal_text(paper_commission + paper_slippage),
        "strategy_refs": reference_list(intent.get("strategy_refs")),
        "strategy_advancement_refs": reference_list(
            intent.get("strategy_advancement_refs")
        ),
        "risk_refs": reference_list(intent.get("risk_refs")),
        "account_truth_refs": reference_list(intent.get("account_truth_refs")),
        "does_not_submit_broker_order": (
            paper_payload.get("does_not_submit_broker_order") is True
        ),
        "does_not_mutate_production_ledger": (
            paper_payload.get("does_not_mutate_production_ledger") is True
        ),
    }
    if (
        paper_run.get("status") != "within_expectations"
        or paper_run.get("divergence_status") != "within_expectations"
        or paper_order.get("status") != "filled"
        or paper_order.get("divergence_status") != "within_expectations"
        or len(paper_fills) < 1
    ):
        blockers.append("paper_shadow_outcome_not_clear")
    if paper["symbol"] != planned["symbol"]:
        blockers.append("paper_shadow_symbol_mismatch")
    if paper["side"] != planned["side"]:
        blockers.append("paper_shadow_side_mismatch")
    if decimal_value(paper["filled_quantity"]) != decimal_value(planned["quantity"]):
        blockers.append("paper_shadow_quantity_mismatch")
    if decimal_value(paper["planned_quantity"]) != decimal_value(planned["quantity"]):
        blockers.append("paper_shadow_planned_quantity_mismatch")
    if planned["order_type"].lower() == "limit" and decimal_value(
        paper["planned_price"]
    ) != decimal_value(planned["limit_price"]):
        blockers.append("paper_shadow_planned_price_mismatch")
    if decimal_value(paper["average_fill_price"]) != decimal_value(
        planned["limit_price"]
    ):
        differences.append("planned_paper_fill_price_difference")
    if paper["strategy_refs"] != [f"strategy:{planned['strategy_id']}"]:
        blockers.append("paper_shadow_strategy_lineage_mismatch")
    if not valid_strategy_advancement_refs(paper["strategy_advancement_refs"]):
        blockers.append("paper_shadow_strategy_advancement_lineage_invalid")
    if paper["risk_refs"] != [planned["risk_ref"]]:
        blockers.append("paper_shadow_risk_lineage_mismatch")
    if paper["account_truth_refs"] != [planned["account_truth_ref"]]:
        blockers.append("paper_shadow_account_truth_lineage_mismatch")
    if (
        paper["does_not_submit_broker_order"] is not True
        or paper["does_not_mutate_production_ledger"] is not True
    ):
        blockers.append("paper_shadow_authority_boundary_invalid")
    return paper, blockers, differences


def build_actual_projection(
    order: dict[str, Any],
    *,
    planned: dict[str, Any],
    paper: dict[str, Any],
    broker_events: list[Any],
    controlled_intent: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    differences: list[str] = []
    actual_events = exact_broker_events_for_order(
        order,
        broker_events,
        controlled_intent=controlled_intent,
    )
    candidate_actual_events = candidate_broker_events(order, broker_events)
    if not actual_events:
        blockers.append(
            "actual_broker_evidence_not_exactly_linked"
            if candidate_actual_events
            else "actual_broker_evidence_missing"
        )
    actual: dict[str, Any] = {}
    if not actual_events:
        return actual, blockers, differences

    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in actual_events
    }
    actual_quantity = sum(
        (
            abs(decimal_value(getattr(event, "quantity", None)) or Decimal("0"))
            for event in actual_events
        ),
        Decimal("0"),
    )
    actual_gross_amount = sum_event_decimal(actual_events, "gross_amount")
    actual_average_price = (
        abs(actual_gross_amount) / actual_quantity if actual_quantity > 0 else None
    )
    actual_fee = sum_event_decimal(actual_events, "fee")
    actual_tax = sum_event_decimal(actual_events, "tax")
    actual_transfer_fee = sum_event_decimal(actual_events, "transfer_fee")
    actual_symbols = sorted(
        {str(getattr(event, "symbol", "") or "") for event in actual_events}
    )
    actual_event_types = sorted(
        {str(getattr(event, "event_type", "") or "") for event in actual_events}
    )
    actual_asset_classes = sorted(
        {str(getattr(event, "asset_class", "") or "") for event in actual_events}
    )
    actual_currencies = sorted(
        {str(getattr(event, "currency", "") or "") for event in actual_events}
    )
    actual = {
        "import_run_ids": sorted(import_run_ids),
        "event_fingerprints": [
            fingerprint({"event_id": str(getattr(event, "event_id", "") or "")})
            for event in actual_events
        ],
        "quantity": decimal_text(actual_quantity),
        "average_fill_price": decimal_text(actual_average_price),
        "gross_amount": decimal_text(actual_gross_amount),
        "fee": decimal_text(actual_fee),
        "tax": decimal_text(actual_tax),
        "transfer_fee": decimal_text(actual_transfer_fee),
        "total_execution_cost": decimal_text(
            actual_fee + actual_tax + actual_transfer_fee
        ),
        "net_amount": decimal_text(sum_event_decimal(actual_events, "net_amount")),
        "symbols": actual_symbols,
        "event_types": actual_event_types,
        "asset_classes": actual_asset_classes,
        "currencies": actual_currencies,
        "event_links": [
            {
                "event_fingerprint": fingerprint(
                    {"event_id": str(getattr(event, "event_id", "") or "")}
                ),
                "import_run_id": str(getattr(event, "import_run_id", "") or ""),
                "row_fingerprint": str(getattr(event, "row_fingerprint", "") or ""),
                "broker_identity_fingerprint": fingerprint(
                    {
                        "broker_order_id": str(
                            getattr(event, "broker_order_id", "") or ""
                        ),
                        "client_order_id": str(
                            getattr(event, "client_order_id", "") or ""
                        ),
                    }
                ),
                "has_broker_order_id": bool(
                    str(getattr(event, "broker_order_id", "") or "")
                ),
                "has_client_order_id": bool(
                    str(getattr(event, "client_order_id", "") or "")
                ),
            }
            for event in actual_events
        ],
        "exact_identity_linked": True,
    }
    if len(import_run_ids) != 1:
        blockers.append("actual_broker_import_identity_conflict")
    if actual_quantity != abs(decimal_value(order.get("quantity")) or Decimal("0")):
        blockers.append("actual_broker_quantity_incomplete_or_conflicting")
    expected_event_type = "trade_buy" if planned["side"] == "buy" else "trade_sell"
    if actual_symbols != [planned["symbol"]]:
        blockers.append("actual_broker_symbol_scope_mismatch")
    if actual_event_types != [expected_event_type]:
        blockers.append("actual_broker_side_scope_mismatch")
    if not actual_asset_classes or any(
        not asset_class_equivalent(item, planned["asset_class"])
        for item in actual_asset_classes
    ):
        blockers.append("actual_broker_asset_class_scope_mismatch")
    if actual_currencies != ["CNY"]:
        blockers.append("actual_broker_currency_scope_mismatch")
    if any(
        re.fullmatch(
            r"[a-f0-9]{64}",
            str(link.get("event_fingerprint") or "").lower(),
        )
        is None
        or not str(link.get("import_run_id") or "")
        or re.fullmatch(
            r"[a-f0-9]{64}",
            str(link.get("row_fingerprint") or "").lower(),
        )
        is None
        or re.fullmatch(
            r"[a-f0-9]{64}",
            str(link.get("broker_identity_fingerprint") or "").lower(),
        )
        is None
        or not (
            link.get("has_broker_order_id") is True
            or link.get("has_client_order_id") is True
        )
        for link in actual["event_links"]
    ):
        blockers.append("actual_broker_identity_linkage_incomplete")
    if paper:
        if actual_quantity != abs(
            decimal_value(paper.get("filled_quantity")) or Decimal("0")
        ):
            differences.append("paper_actual_quantity_difference")
        if actual_average_price != decimal_value(paper.get("average_fill_price")):
            differences.append("paper_actual_fill_price_difference")
        if actual_fee + actual_tax + actual_transfer_fee != decimal_value(
            paper.get("total_execution_cost")
        ):
            differences.append("paper_actual_execution_cost_difference")
    return actual, blockers, differences
