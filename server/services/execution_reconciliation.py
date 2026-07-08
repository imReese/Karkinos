"""Execution reconciliation between OMS orders and gateway facts."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository

EXECUTION_RECONCILIATION_SCHEMA_VERSION = "karkinos.execution_reconciliation.v1"


class ExecutionReconciliationService:
    """Classify OMS orders by the next execution evidence gap."""

    def __init__(self, *, db: Any) -> None:
        self._db = db

    def run_reconciliation(self, *, run_date: str | None = None) -> dict[str, Any]:
        effective_date = run_date or date.today().isoformat()
        run_id = f"execution-reconciliation:{effective_date}"
        orders = self._db.list_oms_orders_sync(limit=1000)
        broker_events = self._broker_trade_events()
        items = [self._classify_order(order, broker_events) for order in orders]
        open_count = sum(1 for item in items if item["suggested_action"] != "no_action")
        status = "open_items" if open_count else "clear"
        saved = self._db.upsert_execution_reconciliation_run_sync(
            run_id=run_id,
            run_date=effective_date,
            status=status,
            item_count=len(items),
            open_item_count=open_count,
            payload={
                "schema_version": EXECUTION_RECONCILIATION_SCHEMA_VERSION,
                "source": "oms_and_broker_gateway_events",
            },
            items=items,
        )
        saved_items = self._db.list_execution_reconciliation_items_sync(run_id)
        return {
            **saved,
            "schema_version": EXECUTION_RECONCILIATION_SCHEMA_VERSION,
            "items": saved_items,
        }

    def _classify_order(
        self,
        order: dict[str, Any],
        broker_events: list[Any],
    ) -> dict[str, Any]:
        events = self._db.list_broker_gateway_events_sync(order_id=order["order_id"])
        status = str(order["status"])
        order_payload = _payload(order)
        execution_mode = str(order_payload.get("execution_mode") or "")
        manual_execution_summary = _manual_execution_evidence_summary(events)
        matching_broker_events = _matching_broker_events(order, broker_events)
        mismatched_broker_events = _mismatched_broker_events(order, broker_events)
        reported_broker_events = matching_broker_events
        mismatch_reasons: list[str] = []
        if execution_mode == "paper_shadow":
            item_status = "paper_shadow_simulation"
            suggested_action = "no_action"
            detail = (
                "Paper/shadow OMS order is simulation evidence and does not "
                "require broker execution reconciliation."
            )
        elif status == "awaiting_manual_confirmation":
            item_status = "awaiting_manual_confirmation"
            suggested_action = "confirm_or_cancel_order"
            detail = "OMS order is waiting for manual confirmation."
        elif status == "manually_confirmed" and not events:
            item_status = "gateway_action_missing"
            suggested_action = "create_manual_ticket_or_cancel"
            detail = "OMS order is confirmed but no gateway action is recorded."
        elif status == "manual_ticket_created":
            if matching_broker_events:
                item_status = "broker_evidence_available"
                suggested_action = "review_broker_evidence_match"
                detail = "Matching broker trade evidence is staged; review before ledger sync."
            elif mismatched_broker_events:
                reported_broker_events = mismatched_broker_events
                mismatch_reasons = ["quantity mismatch"]
                item_status = "broker_evidence_mismatch"
                suggested_action = "review_broker_evidence_mismatch"
                detail = (
                    "Broker trade evidence is staged for the same symbol and side, "
                    "but quantity mismatch requires review before ledger sync."
                )
            elif manual_execution_summary:
                item_status = "manual_execution_recorded"
                suggested_action = "review_manual_execution_and_import_broker_statement"
                detail = (
                    "Manual execution evidence is recorded; import broker statement "
                    "or explicitly review before any ledger update."
                )
            else:
                item_status = "awaiting_broker_evidence"
                suggested_action = "import_broker_statement_or_update_order"
                detail = (
                    "Manual broker ticket exists; broker evidence is still required."
                )
        elif status == "cancelled":
            item_status = "cancelled"
            suggested_action = "no_action"
            detail = "OMS order has been cancelled."
        else:
            item_status = "unknown"
            suggested_action = "review_order_state"
            detail = f"Unhandled OMS status: {status}"
        return {
            "order_id": order["order_id"],
            "item_status": item_status,
            "suggested_action": suggested_action,
            "gateway_event_count": len(events),
            "broker_event_count": len(reported_broker_events),
            "detail": detail,
            "payload": {
                "oms_status": status,
                "execution_mode": execution_mode,
                "gateway_event_ids": [event["id"] for event in events],
                "broker_event_ids": [
                    getattr(event, "event_id", "") for event in reported_broker_events
                ],
                "mismatch_reasons": mismatch_reasons,
                "broker_trade_cost_summary": _broker_trade_cost_summary(
                    reported_broker_events
                ),
                "manual_execution_evidence_summary": manual_execution_summary,
            },
        }

    def _broker_trade_events(self) -> list[Any]:
        db_path = getattr(self._db, "_path", None)
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


def _matching_broker_events(
    order: dict[str, Any], broker_events: list[Any]
) -> list[Any]:
    expected_type = (
        "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
    )
    symbol = str(order.get("symbol") or "")
    quantity = _decimal(order.get("quantity"))
    if quantity is None:
        return []
    matches: list[Any] = []
    for event in broker_events:
        if getattr(event, "event_type", "") != expected_type:
            continue
        if str(getattr(event, "symbol", "")) != symbol:
            continue
        event_quantity = _decimal(getattr(event, "quantity", None))
        if event_quantity is None:
            continue
        if abs(event_quantity) == abs(quantity):
            matches.append(event)
    return matches


def _mismatched_broker_events(
    order: dict[str, Any],
    broker_events: list[Any],
) -> list[Any]:
    expected_type = (
        "trade_buy" if str(order.get("side")).lower() == "buy" else "trade_sell"
    )
    symbol = str(order.get("symbol") or "")
    quantity = _decimal(order.get("quantity"))
    if quantity is None:
        return []
    mismatches: list[Any] = []
    for event in broker_events:
        if getattr(event, "event_type", "") != expected_type:
            continue
        if str(getattr(event, "symbol", "")) != symbol:
            continue
        event_quantity = _decimal(getattr(event, "quantity", None))
        if event_quantity is None:
            continue
        if abs(event_quantity) != abs(quantity):
            mismatches.append(event)
    return mismatches


def _broker_trade_cost_summary(events: list[Any]) -> dict[str, Any]:
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
        "gross_amount": str(_sum_event_decimal(events, "gross_amount")),
        "fee": str(_sum_event_decimal(events, "fee")),
        "tax": str(_sum_event_decimal(events, "tax")),
        "transfer_fee": str(_sum_event_decimal(events, "transfer_fee")),
        "net_amount": str(_sum_event_decimal(events, "net_amount")),
        "review_required_before_ledger_update": True,
        "requires_reconciliation_before_ledger_update": True,
        "ledger_update_status": "review_required",
        "suggested_ledger_action": "review_staged_broker_evidence",
        "does_not_recommend_automatic_ledger_update": True,
        "does_not_mutate_production_ledger": True,
    }


def _manual_execution_evidence_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    manual_events = [
        event
        for event in events
        if str(event.get("event_type") or "") == "manual_execution_recorded"
    ]
    if not manual_events:
        return {}
    latest_event = manual_events[-1]
    latest_payload = _event_payload(latest_event)
    execution_preview = _object(latest_payload.get("execution_preview"))
    ledger_draft = _object(latest_payload.get("ledger_entry_draft"))
    validation = _object(latest_payload.get("validation"))
    required_gate_summary = _object(validation.get("required_gate_summary"))
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


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("payload")
    if isinstance(raw, dict):
        return raw
    payload_json = event.get("payload_json")
    if not isinstance(payload_json, str) or not payload_json.strip():
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sum_event_decimal(events: list[Any], field: str) -> Decimal:
    total = Decimal("0")
    for event in events:
        total += _decimal(getattr(event, field, None)) or Decimal("0")
    return total


def _payload(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("payload")
    if isinstance(value, dict):
        return value
    raw = order.get("payload_json")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
