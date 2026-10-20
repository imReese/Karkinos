"""Canonical values and pure validation for execution batch reconciliation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION = (
    "karkinos.execution_batch_reconciliation.v1"
)
EXECUTION_BATCH_RECONCILIATION_STATUS_SCHEMA_VERSION = (
    "karkinos.execution_batch_reconciliation_status.v1"
)
EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE = (
    "execution_reconciliation.batch_evidence_recorded"
)
EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE = "execution_batch_reconciliation"
EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE = "execution_batch_reconciliation"
EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT = (
    "record_exact_batch_reconciliation_without_authority_change"
)

MAX_BATCH_ORDER_COUNT = 100
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TERMINAL_OMS_STATUSES = frozenset({"filled", "rejected", "cancelled", "expired"})
REAL_EXECUTION_MODES = frozenset({"manual", "controlled_live", "live"})


def resolution_summary(
    fingerprint: str,
    recorded: dict[str, Any],
    blockers: list[str],
    *,
    expected_strategy_id: str | None = None,
) -> dict[str, Any]:
    orders = [item for item in recorded.get("orders") or [] if isinstance(item, dict)]
    strategy_ids = sorted(
        {
            str(item.get("strategy_id") or "").strip()
            for item in orders
            if str(item.get("strategy_id") or "").strip()
        }
    )
    strategy_binding_complete = bool(orders) and all(
        str(item.get("strategy_id") or "").strip() for item in orders
    )
    normalized_expected_strategy_id = (
        str(expected_strategy_id or "").strip()
        if expected_strategy_id is not None
        else ""
    )
    if expected_strategy_id is not None:
        if not normalized_expected_strategy_id:
            blockers.append("prior_batch_reconciliation_expected_strategy_missing")
        if not strategy_binding_complete:
            blockers.append("prior_batch_reconciliation_strategy_binding_incomplete")
        if strategy_ids != [normalized_expected_strategy_id]:
            blockers.append("prior_batch_reconciliation_strategy_mismatch")
    blockers = list(dict.fromkeys(blockers))
    return {
        "status": "pass" if not blockers else "blocked",
        "batch_reconciliation_fingerprint": fingerprint,
        "batch_id": str(recorded.get("batch_id") or ""),
        "order_ids": [str(item) for item in recorded.get("order_ids") or []],
        "order_count": int(recorded.get("order_count") or 0),
        "reconciliation_run_id": str(recorded.get("reconciliation_run_id") or ""),
        "record_status": str(recorded.get("record_status") or "missing"),
        "source_recorded_at": str(recorded.get("recorded_at") or ""),
        "source_refs": [str(item) for item in recorded.get("source_refs") or []],
        "expected_strategy_id": normalized_expected_strategy_id,
        "strategy_ids": strategy_ids,
        "strategy_binding_complete": strategy_binding_complete,
        "blockers": blockers,
        "evidence_ref": (
            f"execution_batch_reconciliation:{fingerprint}" if fingerprint else ""
        ),
        "authorizes_next_batch": False,
        "does_not_submit_broker_order": True,
    }


def derive_effective_terminal_status(
    current_status: str,
    transitions: list[dict[str, Any]],
) -> str:
    if current_status in TERMINAL_OMS_STATUSES:
        return current_status
    if current_status == "reconciled":
        for transition in reversed(transitions):
            status = str(transition.get("to_status") or "").strip().lower()
            if status in TERMINAL_OMS_STATUSES:
                return status
    return current_status


def is_real_fill(fill: dict[str, Any]) -> bool:
    mode = str(fill.get("execution_mode") or "").strip().lower()
    source = str(fill.get("source") or "").strip().lower()
    return mode in REAL_EXECUTION_MODES and not any(
        marker in source for marker in ("paper", "shadow", "simulat")
    )


def order_strategy_id(db: Any, order_payload: dict[str, Any]) -> str:
    gateway_evidence = json_object(order_payload.get("gateway_evidence"))
    research_evidence = json_object(gateway_evidence.get("research_evidence"))
    kind, separator, identifier = str(
        research_evidence.get("evidence_ref") or ""
    ).partition(":")
    if separator != ":" or kind != "decision_action":
        return ""
    try:
        action_id = int(identifier)
    except (TypeError, ValueError):
        return ""
    reader = getattr(db, "get_action_task_sync", None)
    action = reader(action_id) if callable(reader) else None
    return str(action.get("strategy_id") or "") if isinstance(action, dict) else ""


def valid_plan_paper_actual_comparison(
    value: dict[str, Any],
    *,
    expected_order_id: str,
    expected_strategy_id: str,
) -> bool:
    payload = dict(value)
    fingerprint = str(payload.pop("evidence_fingerprint", "")).lower()
    planned = json_object(value.get("planned"))
    decision_action = json_object(planned.get("decision_action"))
    paper = json_object(value.get("paper"))
    actual = json_object(value.get("actual"))
    planned_quantity = decimal_value(planned.get("quantity"))
    planned_limit_price = decimal_value(planned.get("limit_price"))
    action_price = decimal_value(decision_action.get("price"))
    action_target_weight = decimal_value(decision_action.get("target_weight"))
    paper_planned_quantity = decimal_value(paper.get("planned_quantity"))
    paper_planned_price = decimal_value(paper.get("planned_price"))
    paper_quantity = decimal_value(paper.get("filled_quantity"))
    actual_quantity = decimal_value(actual.get("quantity"))
    paper_average_price = decimal_value(paper.get("average_fill_price"))
    actual_average_price = decimal_value(actual.get("average_fill_price"))
    paper_execution_cost = decimal_value(paper.get("total_execution_cost"))
    actual_execution_cost = decimal_value(actual.get("total_execution_cost"))
    import_run_ids = actual.get("import_run_ids")
    import_run_ids = import_run_ids if isinstance(import_run_ids, list) else []
    event_fingerprints = string_list(actual.get("event_fingerprints"))
    actual_symbols = string_list(actual.get("symbols"))
    actual_event_types = string_list(actual.get("event_types"))
    actual_asset_classes = string_list(actual.get("asset_classes"))
    actual_currencies = string_list(actual.get("currencies"))
    raw_event_links = actual.get("event_links")
    raw_event_links = raw_event_links if isinstance(raw_event_links, list) else []
    event_links = [item for item in raw_event_links if isinstance(item, dict)]
    action_id = str(decision_action.get("action_id") or "")
    strategy_ref = f"strategy:{expected_strategy_id}"
    strategy_refs = string_list(paper.get("strategy_refs"))
    advancement_refs = string_list(paper.get("strategy_advancement_refs"))
    risk_refs = string_list(paper.get("risk_refs"))
    account_truth_refs = string_list(paper.get("account_truth_refs"))
    return (
        value.get("schema_version") == "karkinos.plan_paper_actual_comparison.v1"
        and value.get("status") == "pass"
        and str(value.get("order_id") or "") == expected_order_id
        and str(planned.get("order_id") or "") == expected_order_id
        and str(planned.get("strategy_id") or "") == expected_strategy_id
        and action_id.isdigit()
        and int(action_id) > 0
        and str(planned.get("research_evidence_ref") or "")
        == f"decision_action:{action_id}"
        and valid_evidence_ref(planned.get("risk_ref"), expected_kind="risk")
        and valid_evidence_ref(
            planned.get("account_truth_ref"),
            expected_kind="account_truth",
        )
        and bool(str(planned.get("symbol") or "").strip())
        and str(decision_action.get("symbol") or "") == str(planned.get("symbol") or "")
        and str(planned.get("symbol") or "") == str(paper.get("symbol") or "")
        and str(planned.get("side") or "") in {"buy", "sell"}
        and str(decision_action.get("side") or "") == str(planned.get("side") or "")
        and str(planned.get("side") or "") == str(paper.get("side") or "")
        and bool(str(planned.get("asset_class") or ""))
        and normalized_asset_class(decision_action.get("asset_class"))
        == normalized_asset_class(planned.get("asset_class"))
        and str(decision_action.get("strategy_id") or "") == expected_strategy_id
        and action_target_weight is not None
        and decision_action.get("source_signal_id") is not None
        and bool(str(decision_action.get("timestamp") or "").strip())
        and planned_quantity is not None
        and planned_quantity > 0
        and paper_planned_quantity == planned_quantity
        and paper_quantity == planned_quantity
        and actual_quantity == planned_quantity
        and bool(str(paper.get("run_id") or "").strip())
        and re.fullmatch(
            r"[a-f0-9]{64}",
            str(paper.get("input_fingerprint") or "").lower(),
        )
        is not None
        and paper.get("run_status") == "within_expectations"
        and paper.get("divergence_status") == "within_expectations"
        and paper.get("order_status") == "filled"
        and paper.get("order_divergence_status") == "within_expectations"
        and bool(str(paper.get("order_id") or "").strip())
        and str(paper.get("action_ref") or "") == f"action:{action_id}"
        and str(planned.get("paper_shadow_ref") or "")
        == f"paper_shadow:{paper.get('run_id')}"
        and (
            str(planned.get("order_type") or "").lower() != "limit"
            or (
                planned_limit_price is not None
                and planned_limit_price > 0
                and action_price == planned_limit_price
                and paper_planned_price == planned_limit_price
            )
        )
        and positive_int(paper.get("fill_count"))
        and paper_average_price is not None
        and paper_average_price > 0
        and paper_execution_cost is not None
        and paper_execution_cost >= 0
        and strategy_refs == [strategy_ref]
        and len(advancement_refs) == 1
        and re.fullmatch(
            r"strategy_advancement:[a-f0-9]{64}",
            advancement_refs[0].lower(),
        )
        is not None
        and risk_refs == [str(planned.get("risk_ref") or "")]
        and account_truth_refs == [str(planned.get("account_truth_ref") or "")]
        and paper.get("does_not_submit_broker_order") is True
        and paper.get("does_not_mutate_production_ledger") is True
        and actual.get("exact_identity_linked") is True
        and len(import_run_ids) == 1
        and bool(str(import_run_ids[0] or "").strip())
        and bool(event_fingerprints)
        and len(event_fingerprints) == len(set(event_fingerprints))
        and all(
            re.fullmatch(r"[a-f0-9]{64}", item.lower()) is not None
            for item in event_fingerprints
        )
        and actual_average_price is not None
        and actual_average_price > 0
        and actual_execution_cost is not None
        and actual_execution_cost >= 0
        and actual_symbols == [str(planned.get("symbol") or "")]
        and actual_event_types
        == ["trade_buy" if planned.get("side") == "buy" else "trade_sell"]
        and bool(actual_asset_classes)
        and all(
            normalized_asset_class(item)
            == normalized_asset_class(planned.get("asset_class"))
            for item in actual_asset_classes
        )
        and actual_currencies == ["CNY"]
        and len(event_links) == len(raw_event_links) == len(event_fingerprints)
        and [str(item.get("event_fingerprint") or "") for item in event_links]
        == event_fingerprints
        and all(
            str(item.get("import_run_id") or "") == str(import_run_ids[0])
            and re.fullmatch(
                r"[a-f0-9]{64}",
                str(item.get("row_fingerprint") or "").lower(),
            )
            is not None
            and re.fullmatch(
                r"[a-f0-9]{64}",
                str(item.get("broker_identity_fingerprint") or "").lower(),
            )
            is not None
            and (
                item.get("has_broker_order_id") is True
                or item.get("has_client_order_id") is True
            )
            for item in event_links
        )
        and value.get("blockers") == []
        and value.get("differences") == []
        and value.get("persisted_evidence_only") is True
        and value.get("human_review_required") is False
        and value.get("authorizes_execution") is False
        and value.get("does_not_mutate_oms") is True
        and value.get("does_not_mutate_production_ledger") is True
        and value.get("does_not_change_capital_authority") is True
        and re.fullmatch(r"[a-f0-9]{64}", fingerprint) is not None
        and fingerprint == stable_fingerprint(payload)
    )


def order_contract(order: dict[str, Any]) -> dict[str, Any]:
    return {
        key: order.get(key)
        for key in (
            "order_id",
            "intent_key",
            "symbol",
            "side",
            "asset_class",
            "quantity",
            "order_type",
            "limit_price",
            "status",
            "broker_submission_enabled",
            "source",
            "source_ref",
            "payload_json",
            "created_at",
            "updated_at",
        )
    }


def positive_int(value: Any) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def valid_evidence_ref(value: Any, *, expected_kind: str) -> bool:
    kind, separator, identifier = str(value or "").strip().partition(":")
    return separator == ":" and kind == expected_kind and bool(identifier.strip())


def normalized_asset_class(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"fund", "etf"}:
        return "fund"
    return normalized


def transition_contract(transition: dict[str, Any]) -> dict[str, Any]:
    return {
        key: transition.get(key)
        for key in (
            "id",
            "order_id",
            "from_status",
            "to_status",
            "reason",
            "actor",
            "payload_json",
            "transitioned_at",
            "created_at",
        )
    }


def fill_contract(fill: dict[str, Any]) -> dict[str, Any]:
    return {
        key: fill.get(key)
        for key in (
            "fill_id",
            "order_id",
            "timestamp",
            "symbol",
            "side",
            "fill_price",
            "fill_quantity",
            "commission",
            "slippage",
            "asset_class",
            "execution_mode",
            "provider_name",
            "broker_order_id",
            "source",
            "source_ref",
            "metadata_json",
        )
    }


def reconciliation_item_contract(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "run_id",
            "order_id",
            "item_status",
            "suggested_action",
            "gateway_event_count",
            "broker_event_count",
            "detail",
            "payload_json",
            "created_at",
        )
    }


def reconciliation_run_summary(run: dict[str, Any] | None) -> dict[str, Any]:
    if run is None:
        return {
            "status": "missing",
            "run_id": "",
            "run_date": "",
            "item_count": None,
            "open_item_count": None,
            "source_fingerprint": "",
        }
    contract = {
        key: run.get(key)
        for key in (
            "run_id",
            "run_date",
            "status",
            "item_count",
            "open_item_count",
            "payload_json",
            "created_at",
            "updated_at",
        )
    }
    return {
        "status": str(run.get("status") or ""),
        "run_id": str(run.get("run_id") or ""),
        "run_date": str(run.get("run_date") or ""),
        "item_count": int(run.get("item_count") or 0),
        "open_item_count": int(run.get("open_item_count") or 0),
        "source_fingerprint": stable_fingerprint(contract),
    }


def decimal_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def decimal_string(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        **json_object(row.get("payload_json")),
    }


def json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def stable_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_or_expand_authority": True,
        "does_not_enable_or_resume_execution": True,
        "does_not_reserve_or_consume_budget": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_contact_broker": True,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
    }
