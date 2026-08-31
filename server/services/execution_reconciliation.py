"""Stable facade for OMS and broker-evidence reconciliation."""

from __future__ import annotations

from datetime import date
from typing import Any

from server.contracts.execution_reconciliation import (
    CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
    EXECUTION_RECONCILIATION_SCHEMA_VERSION,
)
from server.services.execution_reconciliation_broker_evidence import (
    broker_trade_cost_summary,
    manual_execution_broker_comparison,
    manual_execution_evidence_summary,
    matching_broker_events,
    mismatched_broker_events,
    read_broker_trade_events,
    resolve_order_lifecycle_evidence,
)
from server.services.execution_reconciliation_comparison import (
    build_plan_paper_actual_comparison,
)
from server.services.execution_reconciliation_controlled import (
    controlled_submission_reconciliation,
)
from server.services.execution_reconciliation_values import fingerprint, order_payload

__all__ = [
    "CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION",
    "EXECUTION_RECONCILIATION_SCHEMA_VERSION",
    "ExecutionReconciliationService",
    "build_current_plan_paper_actual_comparison",
]

_CONTROLLED_INTENT_UNSET = object()


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
        payload = order_payload(order)
        execution_mode = str(payload.get("execution_mode") or "")
        manual_execution_summary = manual_execution_evidence_summary(events)
        matching_events = matching_broker_events(order, broker_events)
        mismatched_events = mismatched_broker_events(order, broker_events)
        manual_broker_comparison = manual_execution_broker_comparison(
            manual_execution_summary,
            matching_events,
        )
        controlled_intent = (
            self._db.get_controlled_broker_submit_intent_for_order_sync(
                str(order["order_id"])
            )
            if hasattr(
                self._db,
                "get_controlled_broker_submit_intent_for_order_sync",
            )
            else None
        )
        controlled_clearance = (
            self._db.get_controlled_submission_reconciliation_clearance_for_intent_sync(
                str(controlled_intent.get("submit_intent_id") or "")
            )
            if controlled_intent
            and hasattr(
                self._db,
                "get_controlled_submission_reconciliation_clearance_for_intent_sync",
            )
            else None
        )
        controlled_fills = (
            self._db.list_fills_sync(order_id=str(order["order_id"]), limit=1000)
            if controlled_clearance is not None
            else []
        )
        controlled_order_lifecycle = self._controlled_order_lifecycle_evidence(
            controlled_intent
        )
        controlled = controlled_submission_reconciliation(
            order,
            controlled_intent,
            clearance=controlled_clearance,
            fills=controlled_fills,
            broker_events=broker_events,
            matching_broker_events=matching_events,
            mismatched_broker_events=mismatched_events,
            order_lifecycle_evidence=controlled_order_lifecycle,
        )
        plan_paper_actual_comparison = build_current_plan_paper_actual_comparison(
            self._db,
            order,
            broker_events=broker_events,
            controlled_intent=controlled_intent,
        )
        reported_broker_events = matching_events
        mismatch_reasons: list[str] = []
        if execution_mode == "paper_shadow":
            item_status = "paper_shadow_simulation"
            suggested_action = "no_action"
            detail = (
                "Paper/shadow OMS order is simulation evidence and does not "
                "require broker execution reconciliation."
            )
        elif controlled:
            item_status = str(controlled["item_status"])
            suggested_action = str(controlled["suggested_action"])
            detail = str(controlled["detail"])
            reported_broker_events = list(controlled["reported_broker_events"])
            mismatch_reasons = list(controlled["mismatch_reasons"])
        elif status == "awaiting_manual_confirmation":
            item_status = "awaiting_manual_confirmation"
            suggested_action = "confirm_or_cancel_order"
            detail = "OMS order is waiting for manual confirmation."
        elif status == "manually_confirmed" and not events:
            item_status = "gateway_action_missing"
            suggested_action = "create_manual_ticket_or_cancel"
            detail = "OMS order is confirmed but no gateway action is recorded."
        elif status == "manual_ticket_created":
            if manual_broker_comparison["status"] == "mismatch":
                mismatch_reasons = list(manual_broker_comparison["mismatch_reasons"])
                item_status = "broker_evidence_mismatch"
                suggested_action = "review_broker_evidence_mismatch"
                detail = (
                    "Manual execution evidence differs from staged broker trade "
                    "evidence; review price, costs, and net cash impact before "
                    "any ledger update."
                )
            elif matching_events:
                item_status = "broker_evidence_available"
                suggested_action = "review_broker_evidence_match"
                detail = "Matching broker trade evidence is staged; review before ledger sync."
            elif mismatched_events:
                reported_broker_events = mismatched_events
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
                "broker_trade_cost_summary": broker_trade_cost_summary(
                    reported_broker_events
                ),
                "manual_execution_evidence_summary": manual_execution_summary,
                "manual_broker_comparison": manual_broker_comparison,
                "plan_paper_actual_comparison": plan_paper_actual_comparison,
                "controlled_submission_evidence_summary": (
                    controlled.get("evidence_summary") if controlled else {}
                ),
            },
        }

    def _broker_trade_events(self) -> list[Any]:
        return read_broker_trade_events(self._db)

    def _controlled_order_lifecycle_evidence(
        self,
        intent: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return resolve_order_lifecycle_evidence(self._db, intent)


def build_current_plan_paper_actual_comparison(
    db: Any,
    order: dict[str, Any],
    *,
    broker_events: list[Any] | None = None,
    controlled_intent: Any = _CONTROLLED_INTENT_UNSET,
) -> dict[str, Any]:
    """Rebuild one comparison from current persisted sources, failing closed."""

    try:
        resolved_broker_events = (
            broker_events
            if broker_events is not None
            else ExecutionReconciliationService(db=db)._broker_trade_events()
        )
        if controlled_intent is _CONTROLLED_INTENT_UNSET:
            reader = getattr(
                db,
                "get_controlled_broker_submit_intent_for_order_sync",
                None,
            )
            controlled_intent = (
                reader(str(order.get("order_id") or "")) if callable(reader) else None
            )
        return build_plan_paper_actual_comparison(
            db,
            order,
            broker_events=resolved_broker_events,
            controlled_intent=(
                controlled_intent if isinstance(controlled_intent, dict) else None
            ),
        )
    except Exception:
        core = {
            "schema_version": "karkinos.plan_paper_actual_comparison.v1",
            "status": "blocked",
            "order_id": str(order.get("order_id") or ""),
            "planned": {},
            "paper": {},
            "actual": {},
            "blockers": ["plan_paper_actual_current_source_unavailable"],
            "differences": [],
            "persisted_evidence_only": True,
            "human_review_required": True,
            "authorizes_execution": False,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "does_not_change_capital_authority": True,
        }
        return {**core, "evidence_fingerprint": fingerprint(core)}
