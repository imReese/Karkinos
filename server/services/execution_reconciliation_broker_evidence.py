"""Broker-evidence reading and matching for execution reconciliation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_order_lifecycle import (
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_terminal_outcome,
)
from server.services.execution_reconciliation_values import (
    decimal_value,
    event_payload,
    fingerprint,
    json_object,
    object_value,
    sum_event_decimal,
)


def read_broker_trade_events(db: Any) -> list[Any]:
    db_path = getattr(db, "_path", None)
    if db_path is None:
        return []
    repository = BrokerEvidenceRepository(Path(db_path))
    events: list[Any] = []
    for import_run in repository.list_import_runs(limit=20):
        events.extend(repository.list_events(import_run.import_run_id))
    return [
        event
        for event in events
        if getattr(event, "event_type", "") in {"trade_buy", "trade_sell"}
    ]


def resolve_order_lifecycle_evidence(
    db: Any,
    intent: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(intent, dict) or not intent:
        return {}
    db_path = getattr(db, "_path", None)
    if db_path is None:
        return {}
    payload = json_object(intent.get("payload_json"))
    repository = BrokerOrderLifecycleEvidenceRepository(
        Path(db_path),
        ensure_schema=False,
    )
    return repository.resolve_order(
        gateway_id=str(intent.get("gateway_id") or ""),
        account_alias=str(
            intent.get("account_alias") or payload.get("account_alias") or ""
        ),
        broker_order_id=str(intent.get("broker_order_id") or ""),
        client_order_id=str(intent.get("client_order_id") or ""),
    )


def matching_broker_events(
    order: dict[str, Any], broker_events: list[Any]
) -> list[Any]:
    quantity = decimal_value(order.get("quantity"))
    if quantity is None:
        return []
    candidates = candidate_broker_events(order, broker_events)
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in candidates
    }
    candidate_quantity = sum(
        (
            abs(decimal_value(getattr(event, "quantity", None)) or Decimal("0"))
            for event in candidates
        ),
        Decimal("0"),
    )
    if candidates and len(import_run_ids) == 1 and candidate_quantity == abs(quantity):
        return candidates
    return []


def mismatched_broker_events(
    order: dict[str, Any],
    broker_events: list[Any],
) -> list[Any]:
    quantity = decimal_value(order.get("quantity"))
    if quantity is None:
        return []
    candidates = candidate_broker_events(order, broker_events)
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in candidates
    }
    candidate_quantity = sum(
        (
            abs(decimal_value(getattr(event, "quantity", None)) or Decimal("0"))
            for event in candidates
        ),
        Decimal("0"),
    )
    if candidates and (len(import_run_ids) != 1 or candidate_quantity != abs(quantity)):
        return candidates
    return []


def candidate_broker_events(
    order: dict[str, Any],
    broker_events: list[Any],
) -> list[Any]:
    expected_type = (
        "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
    )
    symbol = str(order.get("symbol") or "")
    candidates: list[Any] = []
    for event in broker_events:
        if getattr(event, "event_type", "") != expected_type:
            continue
        if str(getattr(event, "symbol", "")) != symbol:
            continue
        event_quantity = decimal_value(getattr(event, "quantity", None))
        if event_quantity is None or event_quantity == 0:
            continue
        candidates.append(event)
    return candidates


def controlled_broker_event_sets(
    order: dict[str, Any],
    intent: dict[str, Any],
    broker_events: list[Any],
) -> dict[str, list[Any]]:
    expected_broker_order_id = str(intent.get("broker_order_id") or "")
    expected_client_order_id = str(intent.get("client_order_id") or "")
    linked: list[Any] = []
    identity_incomplete: list[Any] = []
    identity_conflicts: list[Any] = []
    for event in candidate_broker_events(order, broker_events):
        broker_order_id = str(getattr(event, "broker_order_id", "") or "")
        client_order_id = str(getattr(event, "client_order_id", "") or "")
        if (
            broker_order_id == expected_broker_order_id
            and client_order_id == expected_client_order_id
        ):
            linked.append(event)
            continue
        if (
            (
                broker_order_id == expected_broker_order_id
                or client_order_id == expected_client_order_id
            )
            and broker_order_id
            and client_order_id
        ):
            identity_conflicts.append(event)
            continue
        if not broker_order_id or not client_order_id:
            identity_incomplete.append(event)

    expected_quantity = abs(decimal_value(order.get("quantity")) or Decimal("0"))
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in linked
    }
    linked_quantity = sum(
        (
            abs(decimal_value(getattr(event, "quantity", None)) or Decimal("0"))
            for event in linked
        ),
        Decimal("0"),
    )
    matching = (
        linked
        if linked
        and len(import_run_ids) == 1
        and expected_quantity > 0
        and linked_quantity == expected_quantity
        else []
    )
    return {
        "matching": matching,
        "quantity_mismatch": linked if linked and not matching else [],
        "identity_incomplete": identity_incomplete,
        "identity_conflicts": identity_conflicts,
    }


def broker_event_evidence(event: Any) -> dict[str, Any]:
    return {
        "import_run_id": str(getattr(event, "import_run_id", "") or ""),
        "row_fingerprint": str(getattr(event, "row_fingerprint", "") or ""),
        "event_id": str(getattr(event, "event_id", "") or ""),
        "event_type": str(getattr(event, "event_type", "") or ""),
        "occurred_at": str(getattr(event, "occurred_at", "") or ""),
        "symbol": str(getattr(event, "symbol", "") or ""),
        "asset_class": str(getattr(event, "asset_class", "") or ""),
        "currency": str(getattr(event, "currency", "") or ""),
        "quantity": str(getattr(event, "quantity", "") or ""),
        "price": str(getattr(event, "price", "") or ""),
        "gross_amount": str(getattr(event, "gross_amount", "") or ""),
        "fee": str(getattr(event, "fee", "") or ""),
        "tax": str(getattr(event, "tax", "") or ""),
        "transfer_fee": str(getattr(event, "transfer_fee", "") or ""),
        "net_amount": str(getattr(event, "net_amount", "") or ""),
        "broker_order_id": str(getattr(event, "broker_order_id", "") or ""),
        "client_order_id": str(getattr(event, "client_order_id", "") or ""),
    }


def broker_trade_cost_summary(events: list[Any]) -> dict[str, Any]:
    if not events:
        return {}
    currencies = sorted(
        {
            str(getattr(event, "currency", "")).strip()
            for event in events
            if str(getattr(event, "currency", "")).strip()
        }
    )
    return {
        "source": "staged_broker_evidence",
        "event_count": len(events),
        "event_ids": [str(getattr(event, "event_id", "")).strip() for event in events],
        "currency": currencies[0] if len(currencies) == 1 else "mixed",
        "gross_amount": str(sum_event_decimal(events, "gross_amount")),
        "fee": str(sum_event_decimal(events, "fee")),
        "tax": str(sum_event_decimal(events, "tax")),
        "transfer_fee": str(sum_event_decimal(events, "transfer_fee")),
        "net_amount": str(sum_event_decimal(events, "net_amount")),
        "review_required_before_ledger_update": True,
        "requires_reconciliation_before_ledger_update": True,
        "ledger_update_status": "review_required",
        "suggested_ledger_action": "review_staged_broker_evidence",
        "does_not_recommend_automatic_ledger_update": True,
        "does_not_mutate_production_ledger": True,
    }


def manual_execution_broker_comparison(
    manual_summary: dict[str, Any],
    broker_events: list[Any],
) -> dict[str, Any]:
    """Compare non-mutating manual execution evidence with staged broker facts."""
    base = {
        "schema_version": "karkinos.manual_broker_comparison.v1",
        "status": "not_available",
        "mismatch_reasons": [],
        "compared_values": {},
        "manual_execution_event_ids": list(manual_summary.get("event_ids") or []),
        "broker_event_ids": [
            str(getattr(event, "event_id", "")).strip() for event in broker_events
        ],
        "review_required_before_ledger_update": True,
        "does_not_recommend_automatic_ledger_update": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
    }
    if not manual_summary or not broker_events:
        return base

    broker_quantity = sum(
        (
            abs(decimal_value(getattr(event, "quantity", None)) or Decimal("0"))
            for event in broker_events
        ),
        Decimal("0"),
    )
    broker_gross_amount = sum_event_decimal(broker_events, "gross_amount")
    broker_average_price = (
        broker_gross_amount / broker_quantity
        if broker_quantity != Decimal("0")
        else Decimal("0")
    )
    comparisons = (
        ("quantity", manual_summary.get("quantity"), broker_quantity),
        ("fill_price", manual_summary.get("fill_price"), broker_average_price),
        ("gross_amount", manual_summary.get("gross_amount"), broker_gross_amount),
        ("fee", manual_summary.get("fee"), sum_event_decimal(broker_events, "fee")),
        ("tax", manual_summary.get("tax"), sum_event_decimal(broker_events, "tax")),
        (
            "transfer_fee",
            manual_summary.get("transfer_fee"),
            sum_event_decimal(broker_events, "transfer_fee"),
        ),
        (
            "net_amount",
            manual_summary.get("net_cash_impact"),
            sum_event_decimal(broker_events, "net_amount"),
        ),
    )
    compared_values: dict[str, dict[str, str]] = {}
    mismatch_reasons: list[str] = []
    for field, manual_value, broker_value in comparisons:
        normalized_manual = decimal_value(manual_value)
        if normalized_manual is None:
            continue
        compared_values[field] = {
            "manual": format(normalized_manual, "f"),
            "broker": format(broker_value, "f"),
        }
        if normalized_manual != broker_value:
            mismatch_reasons.append(f"manual_execution_{field}_mismatch")

    return {
        **base,
        "status": "mismatch" if mismatch_reasons else "match",
        "mismatch_reasons": mismatch_reasons,
        "compared_values": compared_values,
    }


def manual_execution_evidence_summary(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    manual_events = [
        event
        for event in events
        if str(event.get("event_type") or "") == "manual_execution_recorded"
    ]
    if not manual_events:
        return {}
    latest_event = manual_events[-1]
    latest_payload = event_payload(latest_event)
    execution_preview = object_value(latest_payload.get("execution_preview"))
    ledger_draft = object_value(latest_payload.get("ledger_entry_draft"))
    validation = object_value(latest_payload.get("validation"))
    required_gate_summary = object_value(validation.get("required_gate_summary"))
    summary = {
        "source": "broker_gateway_event",
        "event_count": len(manual_events),
        "event_ids": [event["id"] for event in manual_events],
        "latest_event_id": latest_event["id"],
        "preview_fingerprint": latest_payload.get("preview_fingerprint"),
        "fill_price": execution_preview.get("fill_price"),
        "quantity": execution_preview.get("quantity"),
        "gross_amount": execution_preview.get("gross_amount"),
        "fee": execution_preview.get("fee"),
        "tax": execution_preview.get("tax"),
        "transfer_fee": execution_preview.get("transfer_fee"),
        "net_cash_impact": execution_preview.get("net_cash_impact"),
        "ledger_entry_amount": ledger_draft.get("amount"),
        "operator_note": latest_payload.get("operator_note"),
        "review_required_before_ledger_update": True,
        "requires_operator_ledger_save": latest_payload.get(
            "requires_operator_ledger_save"
        )
        is True,
        "submitted_to_broker": latest_payload.get("submitted_to_broker") is True,
        "does_not_mutate_oms": latest_payload.get("does_not_mutate_oms") is True,
        "does_not_mutate_production_ledger": latest_payload.get(
            "does_not_mutate_production_ledger"
        )
        is True,
    }
    if required_gate_summary:
        summary["required_gate_summary"] = required_gate_summary
    return summary


def exact_broker_events_for_order(
    order: dict[str, Any],
    broker_events: list[Any],
    *,
    controlled_intent: dict[str, Any] | None,
) -> list[Any]:
    expected_client_ids = {str(order.get("order_id") or "")}
    expected_broker_ids: set[str] = set()
    if isinstance(controlled_intent, dict):
        client_order_id = str(controlled_intent.get("client_order_id") or "")
        broker_order_id = str(controlled_intent.get("broker_order_id") or "")
        if client_order_id:
            expected_client_ids.add(client_order_id)
        if broker_order_id:
            expected_broker_ids.add(broker_order_id)
    result: list[Any] = []
    for event in candidate_broker_events(order, broker_events):
        client_order_id = str(getattr(event, "client_order_id", "") or "")
        broker_order_id = str(getattr(event, "broker_order_id", "") or "")
        if client_order_id in expected_client_ids or (
            broker_order_id and broker_order_id in expected_broker_ids
        ):
            result.append(event)
    return result
