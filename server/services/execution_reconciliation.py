"""Execution reconciliation between OMS orders and gateway facts."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_order_lifecycle import (
    BrokerOrderLifecycleEvidenceRepository,
    broker_order_lifecycle_clearance_blockers,
)
from server.services.per_order_confirmation import build_order_fingerprint

EXECUTION_RECONCILIATION_SCHEMA_VERSION = "karkinos.execution_reconciliation.v1"
CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION = (
    "karkinos.controlled_submission_reconciliation.v2"
)


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
        manual_broker_comparison = _manual_execution_broker_comparison(
            manual_execution_summary,
            matching_broker_events,
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
        controlled = _controlled_submission_reconciliation(
            order,
            controlled_intent,
            clearance=controlled_clearance,
            fills=controlled_fills,
            broker_events=broker_events,
            matching_broker_events=matching_broker_events,
            mismatched_broker_events=mismatched_broker_events,
            order_lifecycle_evidence=controlled_order_lifecycle,
        )
        reported_broker_events = matching_broker_events
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
            elif matching_broker_events:
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
                "manual_broker_comparison": manual_broker_comparison,
                "controlled_submission_evidence_summary": (
                    controlled.get("evidence_summary") if controlled else {}
                ),
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

    def _controlled_order_lifecycle_evidence(
        self,
        intent: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(intent, dict) or not intent:
            return {}
        db_path = getattr(self._db, "_path", None)
        if db_path is None:
            return {}
        payload = _json_object(intent.get("payload_json"))
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


def _matching_broker_events(
    order: dict[str, Any], broker_events: list[Any]
) -> list[Any]:
    quantity = _decimal(order.get("quantity"))
    if quantity is None:
        return []
    candidates = _candidate_broker_events(order, broker_events)
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in candidates
    }
    candidate_quantity = sum(
        (
            abs(_decimal(getattr(event, "quantity", None)) or Decimal("0"))
            for event in candidates
        ),
        Decimal("0"),
    )
    if candidates and len(import_run_ids) == 1 and candidate_quantity == abs(quantity):
        return candidates
    return []


def _controlled_submission_reconciliation(
    order: dict[str, Any],
    intent: dict[str, Any] | None,
    *,
    clearance: dict[str, Any] | None,
    fills: list[dict[str, Any]],
    broker_events: list[Any],
    matching_broker_events: list[Any],
    mismatched_broker_events: list[Any],
    order_lifecycle_evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(intent, dict) or not intent:
        return {}
    intent_status = str(intent.get("status") or "unknown")
    oms_status = str(order.get("status") or "unknown")
    expected_oms_status = {
        "prepared": "submission_pending",
        "submission_unknown": "submission_unknown",
        "submitted": "submitted",
        "rejected": "rejected",
    }.get(intent_status)
    mismatch_reasons: list[str] = []
    controlled_events = _controlled_broker_event_sets(order, intent, broker_events)
    controlled_matching = controlled_events["matching"]
    controlled_quantity_mismatch = controlled_events["quantity_mismatch"]
    controlled_identity_incomplete = controlled_events["identity_incomplete"]
    controlled_identity_conflicts = controlled_events["identity_conflicts"]
    lifecycle_summary = _order_lifecycle_evidence_summary(order_lifecycle_evidence)
    if isinstance(clearance, dict) and clearance:
        controlled_fills = [
            fill
            for fill in fills
            if str(fill.get("source") or "") == "controlled_submission_clearance"
            and str(_json_object(fill.get("metadata_json")).get("clearance_id") or "")
            == str(clearance.get("clearance_id") or "")
        ]
        cleared_quantity = sum(
            (
                abs(_decimal(fill.get("fill_quantity")) or Decimal("0"))
                for fill in controlled_fills
            ),
            Decimal("0"),
        )
        expected_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
        clearance_blockers: list[str] = []
        if str(clearance.get("status") or "") != "cleared":
            clearance_blockers.append("controlled_submission_clearance_status_invalid")
        if str(clearance.get("submit_intent_id") or "") != str(
            intent.get("submit_intent_id") or ""
        ):
            clearance_blockers.append("controlled_submission_clearance_intent_mismatch")
        if oms_status != "filled":
            clearance_blockers.append("controlled_submission_clearance_oms_not_filled")
        if len(controlled_fills) != int(clearance.get("fill_count") or 0):
            clearance_blockers.append(
                "controlled_submission_clearance_fill_count_changed"
            )
        if cleared_quantity <= 0 or cleared_quantity != expected_quantity:
            clearance_blockers.append(
                "controlled_submission_clearance_fill_quantity_changed"
            )
        clearance_blockers.extend(
            broker_order_lifecycle_clearance_blockers(
                order,
                order_lifecycle_evidence,
            )
        )
        if clearance_blockers:
            return {
                "item_status": "controlled_submission_clearance_evidence_mismatch",
                "suggested_action": (
                    "enable_kill_switch_and_review_controlled_submission"
                ),
                "detail": (
                    "Persisted controlled-submission clearance no longer matches "
                    "OMS or real-fill evidence; keep new submissions blocked."
                ),
                "reported_broker_events": controlled_matching
                or controlled_quantity_mismatch
                or controlled_identity_conflicts,
                "mismatch_reasons": clearance_blockers,
                "evidence_summary": {
                    "schema_version": (
                        CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION
                    ),
                    "submit_intent_id": str(intent.get("submit_intent_id") or ""),
                    "clearance_id": str(clearance.get("clearance_id") or ""),
                    "intent_status": intent_status,
                    "oms_status": oms_status,
                    "new_submissions_blocked": True,
                    "recovery_resubmission_enabled": False,
                    "does_not_mutate_production_ledger": True,
                    "broker_order_lifecycle_evidence": lifecycle_summary,
                },
            }
        return {
            "item_status": "controlled_submission_reconciliation_cleared",
            "suggested_action": "no_action",
            "detail": (
                "Signed controlled-submission reconciliation clearance and exact "
                "real-fill evidence remain current; production ledger is separate."
            ),
            "reported_broker_events": controlled_matching,
            "mismatch_reasons": [],
            "evidence_summary": {
                "schema_version": CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
                "submit_intent_id": str(intent.get("submit_intent_id") or ""),
                "clearance_id": str(clearance.get("clearance_id") or ""),
                "clearance_reconciliation_run_id": str(
                    clearance.get("clearance_reconciliation_run_id") or ""
                ),
                "intent_status": intent_status,
                "oms_status": oms_status,
                "new_submissions_blocked": False,
                "recovery_resubmission_enabled": False,
                "review_required_before_ledger_update": False,
                "production_ledger_mutated": False,
                "does_not_mutate_production_ledger": True,
                "broker_order_lifecycle_evidence": lifecycle_summary,
            },
        }
    if expected_oms_status != oms_status:
        mismatch_reasons.append("controlled_submission_oms_status_mismatch")
    if str(intent.get("order_id") or "") != str(order.get("order_id") or ""):
        mismatch_reasons.append("controlled_submission_order_id_mismatch")
    if str(intent.get("order_fingerprint") or "") != build_order_fingerprint(order):
        mismatch_reasons.append("controlled_submission_order_fingerprint_mismatch")

    reported_broker_events: list[Any] = []
    if mismatch_reasons:
        item_status = "controlled_submission_evidence_mismatch"
        suggested_action = "enable_kill_switch_and_review_controlled_submission"
        detail = (
            "Controlled submission intent and current OMS evidence disagree; "
            "do not submit another order until the mismatch is resolved."
        )
    elif intent_status in {"prepared", "submission_unknown"}:
        reported_broker_events = (
            controlled_matching
            or controlled_quantity_mismatch
            or controlled_identity_conflicts
            or controlled_identity_incomplete
        )
        item_status = (
            "controlled_submission_unknown_broker_evidence_available"
            if controlled_matching
            else "controlled_submission_unknown"
        )
        suggested_action = "recover_controlled_submission_by_query"
        detail = (
            "Controlled broker submission outcome is unknown. Query only by the "
            "persisted client order id; never resubmit, and block every new order."
        )
    elif intent_status == "submitted":
        if controlled_identity_conflicts:
            reported_broker_events = controlled_identity_conflicts
            mismatch_reasons.append("controlled_submission_order_identity_conflict")
            item_status = "controlled_submission_broker_identity_conflict"
            suggested_action = "enable_kill_switch_and_review_controlled_submission"
            detail = (
                "Staged broker trade evidence reuses one controlled order identity "
                "but disagrees on the other; keep new submissions blocked."
            )
        elif lifecycle_classification := _order_lifecycle_classification(
            order,
            order_lifecycle_evidence,
            controlled_matching=controlled_matching,
            controlled_quantity_mismatch=controlled_quantity_mismatch,
        ):
            reported_broker_events = list(
                lifecycle_classification["reported_broker_events"]
            )
            mismatch_reasons.extend(lifecycle_classification["mismatch_reasons"])
            item_status = str(lifecycle_classification["item_status"])
            suggested_action = str(lifecycle_classification["suggested_action"])
            detail = str(lifecycle_classification["detail"])
        elif controlled_matching:
            reported_broker_events = controlled_matching
            item_status = "controlled_submission_broker_evidence_available"
            suggested_action = "review_controlled_submission_broker_evidence"
            detail = (
                "Broker-order and client-order linked staged trade evidence is "
                "available for the controlled submission; reconcile it before "
                "any new submission or production-ledger update."
            )
        elif controlled_quantity_mismatch:
            reported_broker_events = controlled_quantity_mismatch
            mismatch_reasons.append("controlled_submission_quantity_mismatch")
            item_status = "controlled_submission_broker_evidence_mismatch"
            suggested_action = "enable_kill_switch_and_review_controlled_submission"
            detail = (
                "Staged broker trade evidence disagrees with the controlled "
                "submission quantity; keep new submissions blocked."
            )
        elif controlled_identity_incomplete:
            reported_broker_events = controlled_identity_incomplete
            mismatch_reasons.append("controlled_submission_order_identity_incomplete")
            item_status = "controlled_submission_broker_identity_incomplete"
            suggested_action = "import_order_linked_controlled_submission_evidence"
            detail = (
                "Staged trade rows match symbol and side but do not carry both the "
                "exact broker order id and client order id; they cannot clear the "
                "controlled submission interlock."
            )
        else:
            item_status = "controlled_submission_awaiting_broker_evidence"
            suggested_action = "query_or_import_controlled_submission_evidence"
            detail = (
                "The broker accepted the controlled submission, but staged "
                "broker trade evidence is not yet available; keep new "
                "submissions blocked."
            )
    elif intent_status == "rejected":
        if (
            controlled_matching
            or controlled_quantity_mismatch
            or controlled_identity_conflicts
            or controlled_identity_incomplete
        ):
            reported_broker_events = (
                controlled_matching
                or controlled_quantity_mismatch
                or controlled_identity_conflicts
                or controlled_identity_incomplete
            )
            mismatch_reasons.append("controlled_rejection_has_broker_trade_evidence")
            item_status = "controlled_rejection_broker_evidence_conflict"
            suggested_action = "enable_kill_switch_and_review_controlled_submission"
            detail = (
                "The controlled intent records a definitive rejection but staged "
                "broker trade evidence matches the order; investigate before "
                "another submission."
            )
        else:
            item_status = "controlled_submission_rejected"
            suggested_action = "no_action"
            detail = (
                "The broker definitively rejected the controlled submission; no "
                "fill or production-ledger mutation was recorded."
            )
    else:
        mismatch_reasons.append("controlled_submission_intent_status_invalid")
        item_status = "controlled_submission_evidence_mismatch"
        suggested_action = "enable_kill_switch_and_review_controlled_submission"
        detail = "Controlled submission intent status is invalid or unsupported."

    return {
        "item_status": item_status,
        "suggested_action": suggested_action,
        "detail": detail,
        "reported_broker_events": reported_broker_events,
        "mismatch_reasons": mismatch_reasons,
        "evidence_summary": {
            "schema_version": CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
            "submit_intent_id": str(intent.get("submit_intent_id") or ""),
            "submit_fingerprint": str(intent.get("submit_fingerprint") or ""),
            "client_order_id": str(intent.get("client_order_id") or ""),
            "gateway_id": str(intent.get("gateway_id") or ""),
            "broker_order_id": str(intent.get("broker_order_id") or ""),
            "intent_status": intent_status,
            "oms_status": oms_status,
            "new_submissions_blocked": intent_status
            in {"prepared", "submitted", "submission_unknown"},
            "recovery_resubmission_enabled": False,
            "review_required_before_ledger_update": True,
            "does_not_mutate_oms": True,
            "does_not_mutate_production_ledger": True,
            "broker_event_evidence": [
                _broker_event_evidence(event) for event in reported_broker_events
            ],
            "broker_evidence_fingerprint": _fingerprint(
                [_broker_event_evidence(event) for event in reported_broker_events]
            ),
            "broker_order_identity_required": True,
            "broker_order_identity_match_count": len(controlled_matching),
            "broker_order_identity_incomplete_count": len(
                controlled_identity_incomplete
            ),
            "broker_order_identity_conflict_count": len(controlled_identity_conflicts),
            "broker_order_lifecycle_evidence": lifecycle_summary,
        },
    }


def _order_lifecycle_classification(
    order: dict[str, Any],
    evidence: dict[str, Any],
    *,
    controlled_matching: list[Any],
    controlled_quantity_mismatch: list[Any],
) -> dict[str, Any]:
    resolution_status = str(evidence.get("status") or "")
    if resolution_status in {"blocked", "identity_conflict"}:
        blockers = [str(item) for item in evidence.get("blockers") or []]
        return {
            "item_status": "controlled_submission_order_lifecycle_evidence_blocked",
            "suggested_action": ("enable_kill_switch_and_review_controlled_submission"),
            "detail": (
                "Persisted broker order-lifecycle evidence is blocked or conflicts "
                "with the controlled order identities; keep every new submission "
                "blocked."
            ),
            "reported_broker_events": (
                controlled_matching or controlled_quantity_mismatch
            ),
            "mismatch_reasons": blockers
            or ["controlled_submission_order_lifecycle_evidence_blocked"],
        }
    if resolution_status != "found":
        return {}

    collector_evidence = _json_object(evidence.get("collector_evidence"))
    if (
        bool(collector_evidence.get("required"))
        and str(collector_evidence.get("status") or "") != "healthy"
    ):
        collector_blockers = [
            str(item) for item in collector_evidence.get("blockers") or []
        ]
        return {
            "item_status": (
                "controlled_submission_order_lifecycle_collector_unhealthy"
            ),
            "suggested_action": (
                "review_collector_run_and_restore_read_only_evidence_ingestion"
            ),
            "detail": (
                "The latest broker-neutral collector run is blocked, awaiting "
                "restart recovery, inconsistent, or does not bind this lifecycle "
                "observation. Keep every new submission blocked."
            ),
            "reported_broker_events": (
                controlled_matching or controlled_quantity_mismatch
            ),
            "mismatch_reasons": collector_blockers
            or ["controlled_submission_order_lifecycle_collector_unhealthy"],
        }

    lifecycle_order = _json_object(evidence.get("order"))
    mismatch_reasons: list[str] = []
    if str(lifecycle_order.get("symbol") or "") != str(order.get("symbol") or ""):
        mismatch_reasons.append("controlled_submission_lifecycle_symbol_mismatch")
    if str(lifecycle_order.get("side") or "") != str(order.get("side") or ""):
        mismatch_reasons.append("controlled_submission_lifecycle_side_mismatch")
    expected_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
    lifecycle_quantity = abs(
        _decimal(lifecycle_order.get("order_quantity")) or Decimal("0")
    )
    if lifecycle_quantity != expected_quantity:
        mismatch_reasons.append("controlled_submission_lifecycle_quantity_mismatch")
    if mismatch_reasons:
        return {
            "item_status": "controlled_submission_order_lifecycle_evidence_mismatch",
            "suggested_action": ("enable_kill_switch_and_review_controlled_submission"),
            "detail": (
                "The exact-identity broker lifecycle fact disagrees with the current "
                "OMS order contract; do not infer execution or submit another order."
            ),
            "reported_broker_events": (
                controlled_matching or controlled_quantity_mismatch
            ),
            "mismatch_reasons": mismatch_reasons,
        }

    lifecycle_status = str(lifecycle_order.get("status") or "")
    reported_events = controlled_matching or controlled_quantity_mismatch
    if lifecycle_status in {"submitted", "open"}:
        return {
            "item_status": "controlled_submission_order_open_evidence_available",
            "suggested_action": "poll_or_import_controlled_submission_lifecycle_evidence",
            "detail": (
                "Fresh, exact-identity broker evidence still reports the order open. "
                "Continue explicit query/export ingestion; never resubmit."
            ),
            "reported_broker_events": reported_events,
            "mismatch_reasons": [],
        }
    if lifecycle_status == "partially_filled":
        return {
            "item_status": "controlled_submission_partial_fill_evidence_available",
            "suggested_action": "review_partial_fill_and_import_account_truth",
            "detail": (
                "Exact-identity broker evidence reports a partial fill. It is review "
                "evidence only and cannot mutate OMS/ledger or release the next order."
            ),
            "reported_broker_events": reported_events,
            "mismatch_reasons": [],
        }
    if lifecycle_status == "cancelled":
        filled_quantity = abs(
            _decimal(lifecycle_order.get("cumulative_filled_quantity")) or Decimal("0")
        )
        return {
            "item_status": (
                "controlled_submission_partial_fill_cancel_evidence_available"
                if filled_quantity > 0
                else "controlled_submission_cancel_evidence_available"
            ),
            "suggested_action": (
                "review_partial_fill_cancel_and_import_account_truth"
                if filled_quantity > 0
                else "review_cancel_evidence_before_interlock_clearance"
            ),
            "detail": (
                "Exact-identity lifecycle evidence reports a terminal broker cancellation. "
                "Cancellation is not an execution command and does not self-clear "
                "the controlled-submission interlock."
            ),
            "reported_broker_events": reported_events,
            "mismatch_reasons": [],
        }
    if lifecycle_status == "filled":
        if controlled_matching:
            return {}
        return {
            "item_status": "controlled_submission_filled_lifecycle_evidence_available",
            "suggested_action": (
                "import_order_linked_broker_statement_and_account_truth"
            ),
            "detail": (
                "Exact-identity broker lifecycle evidence reports a full fill, but the "
                "independent broker-statement and Account Truth evidence required "
                "for signed clearance is still missing."
            ),
            "reported_broker_events": reported_events,
            "mismatch_reasons": [],
        }
    if lifecycle_status == "rejected":
        return {
            "item_status": "controlled_submission_lifecycle_rejection_conflict",
            "suggested_action": ("enable_kill_switch_and_review_controlled_submission"),
            "detail": (
                "The controlled intent is persisted as broker-submitted while the "
                "latest exact-identity broker evidence reports rejection; investigate "
                "the conflicting terminal facts."
            ),
            "reported_broker_events": reported_events,
            "mismatch_reasons": ["controlled_submission_lifecycle_rejection_conflict"],
        }
    return {
        "item_status": "controlled_submission_order_lifecycle_evidence_blocked",
        "suggested_action": "enable_kill_switch_and_review_controlled_submission",
        "detail": "The persisted broker lifecycle status is unsupported.",
        "reported_broker_events": reported_events,
        "mismatch_reasons": ["controlled_submission_lifecycle_status_invalid"],
    }


def _order_lifecycle_evidence_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, dict) or not evidence:
        return {}
    observation = _json_object(evidence.get("observation"))
    order = _json_object(evidence.get("order"))
    return {
        "schema_version": str(evidence.get("schema_version") or ""),
        "resolution_status": str(evidence.get("status") or ""),
        "observation_id": str(observation.get("observation_id") or ""),
        "evidence_fingerprint": str(observation.get("evidence_fingerprint") or ""),
        "provider": str(observation.get("provider") or ""),
        "gateway_id": str(observation.get("gateway_id") or ""),
        "account_alias": str(observation.get("account_alias") or ""),
        "source_sequence": observation.get("source_sequence"),
        "captured_at": str(observation.get("captured_at") or ""),
        "validation_status": str(observation.get("validation_status") or ""),
        "blockers": [str(item) for item in evidence.get("blockers") or []],
        "collector_evidence": _json_object(evidence.get("collector_evidence")),
        "order_status": str(order.get("status") or ""),
        "order_quantity": str(order.get("order_quantity") or ""),
        "cumulative_filled_quantity": str(
            order.get("cumulative_filled_quantity") or ""
        ),
        "cancelled_quantity": str(order.get("cancelled_quantity") or ""),
        "fill_count": int(evidence.get("fill_count") or 0),
        "explicit_ingestion_required": True,
        "provider_contacted": False,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_release_submission_interlock": True,
        "authorizes_execution": False,
    }


def _mismatched_broker_events(
    order: dict[str, Any],
    broker_events: list[Any],
) -> list[Any]:
    quantity = _decimal(order.get("quantity"))
    if quantity is None:
        return []
    candidates = _candidate_broker_events(order, broker_events)
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in candidates
    }
    candidate_quantity = sum(
        (
            abs(_decimal(getattr(event, "quantity", None)) or Decimal("0"))
            for event in candidates
        ),
        Decimal("0"),
    )
    if candidates and (len(import_run_ids) != 1 or candidate_quantity != abs(quantity)):
        return candidates
    return []


def _candidate_broker_events(
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
        event_quantity = _decimal(getattr(event, "quantity", None))
        if event_quantity is None or event_quantity == 0:
            continue
        candidates.append(event)
    return candidates


def _controlled_broker_event_sets(
    order: dict[str, Any],
    intent: dict[str, Any],
    broker_events: list[Any],
) -> dict[str, list[Any]]:
    expected_broker_order_id = str(intent.get("broker_order_id") or "")
    expected_client_order_id = str(intent.get("client_order_id") or "")
    linked: list[Any] = []
    identity_incomplete: list[Any] = []
    identity_conflicts: list[Any] = []
    for event in _candidate_broker_events(order, broker_events):
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

    expected_quantity = abs(_decimal(order.get("quantity")) or Decimal("0"))
    import_run_ids = {
        str(getattr(event, "import_run_id", "") or "") for event in linked
    }
    linked_quantity = sum(
        (
            abs(_decimal(getattr(event, "quantity", None)) or Decimal("0"))
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


def _broker_event_evidence(event: Any) -> dict[str, Any]:
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


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def _manual_execution_broker_comparison(
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
            abs(_decimal(getattr(event, "quantity", None)) or Decimal("0"))
            for event in broker_events
        ),
        Decimal("0"),
    )
    broker_gross_amount = _sum_event_decimal(broker_events, "gross_amount")
    broker_average_price = (
        broker_gross_amount / broker_quantity
        if broker_quantity != Decimal("0")
        else Decimal("0")
    )
    comparisons = (
        ("quantity", manual_summary.get("quantity"), broker_quantity),
        ("fill_price", manual_summary.get("fill_price"), broker_average_price),
        ("gross_amount", manual_summary.get("gross_amount"), broker_gross_amount),
        ("fee", manual_summary.get("fee"), _sum_event_decimal(broker_events, "fee")),
        ("tax", manual_summary.get("tax"), _sum_event_decimal(broker_events, "tax")),
        (
            "transfer_fee",
            manual_summary.get("transfer_fee"),
            _sum_event_decimal(broker_events, "transfer_fee"),
        ),
        (
            "net_amount",
            manual_summary.get("net_cash_impact"),
            _sum_event_decimal(broker_events, "net_amount"),
        ),
    )
    compared_values: dict[str, dict[str, str]] = {}
    mismatch_reasons: list[str] = []
    for field, manual_value, broker_value in comparisons:
        normalized_manual = _decimal(manual_value)
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
