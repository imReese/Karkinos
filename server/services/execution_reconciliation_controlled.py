"""Fail-closed controlled-submission reconciliation policy."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from server.contracts.execution_reconciliation import (
    CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
)
from server.services.execution_identity import build_order_fingerprint
from server.services.execution_reconciliation_broker_evidence import (
    broker_event_evidence,
    broker_order_lifecycle_terminal_outcome,
    controlled_broker_event_sets,
)
from server.services.execution_reconciliation_values import (
    decimal_value,
    fingerprint,
    json_object,
)


def controlled_submission_reconciliation(
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
    controlled_events = controlled_broker_event_sets(order, intent, broker_events)
    controlled_matching = controlled_events["matching"]
    controlled_quantity_mismatch = controlled_events["quantity_mismatch"]
    controlled_identity_incomplete = controlled_events["identity_incomplete"]
    controlled_identity_conflicts = controlled_events["identity_conflicts"]
    lifecycle_summary = summarize_order_lifecycle(order_lifecycle_evidence)
    if isinstance(clearance, dict) and clearance:
        return classify_controlled_clearance(
            order,
            intent,
            clearance=clearance,
            fills=fills,
            controlled_matching=controlled_matching,
            controlled_quantity_mismatch=controlled_quantity_mismatch,
            controlled_identity_conflicts=controlled_identity_conflicts,
            order_lifecycle_evidence=order_lifecycle_evidence,
            lifecycle_summary=lifecycle_summary,
        )
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
        elif lifecycle_classification := classify_order_lifecycle(
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
                broker_event_evidence(event) for event in reported_broker_events
            ],
            "broker_evidence_fingerprint": fingerprint(
                [broker_event_evidence(event) for event in reported_broker_events]
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


def classify_controlled_clearance(
    order: dict[str, Any],
    intent: dict[str, Any],
    *,
    clearance: dict[str, Any],
    fills: list[dict[str, Any]],
    controlled_matching: list[Any],
    controlled_quantity_mismatch: list[Any],
    controlled_identity_conflicts: list[Any],
    order_lifecycle_evidence: dict[str, Any],
    lifecycle_summary: dict[str, Any],
) -> dict[str, Any]:
    intent_status = str(intent.get("status") or "unknown")
    oms_status = str(order.get("status") or "unknown")
    controlled_fills = [
        fill
        for fill in fills
        if str(fill.get("source") or "") == "controlled_submission_clearance"
        and str(json_object(fill.get("metadata_json")).get("clearance_id") or "")
        == str(clearance.get("clearance_id") or "")
    ]
    cleared_quantity = sum(
        (
            abs(decimal_value(fill.get("fill_quantity")) or Decimal("0"))
            for fill in controlled_fills
        ),
        Decimal("0"),
    )
    expected_quantity = abs(decimal_value(order.get("quantity")) or Decimal("0"))
    clearance_payload = json_object(clearance.get("payload_json"))
    terminal_status = str(
        clearance.get("terminal_status")
        or clearance_payload.get("terminal_status")
        or "filled"
    )
    persisted_fill_quantity = abs(
        decimal_value(clearance.get("fill_quantity")) or Decimal("0")
    )
    cancelled_quantity = abs(
        decimal_value(
            clearance.get("cancelled_quantity")
            or clearance_payload.get("cancelled_quantity")
        )
        or Decimal("0")
    )
    clearance_blockers: list[str] = []
    if str(clearance.get("status") or "") != "cleared":
        clearance_blockers.append("controlled_submission_clearance_status_invalid")
    if str(clearance.get("submit_intent_id") or "") != str(
        intent.get("submit_intent_id") or ""
    ):
        clearance_blockers.append("controlled_submission_clearance_intent_mismatch")
    if oms_status != terminal_status:
        clearance_blockers.append(
            "controlled_submission_clearance_oms_terminal_status_changed"
        )
    if len(controlled_fills) != int(clearance.get("fill_count") or 0):
        clearance_blockers.append("controlled_submission_clearance_fill_count_changed")
    if cleared_quantity != persisted_fill_quantity:
        clearance_blockers.append(
            "controlled_submission_clearance_fill_quantity_changed"
        )
    if terminal_status == "filled" and (
        cleared_quantity <= 0
        or cleared_quantity != expected_quantity
        or cancelled_quantity != 0
    ):
        clearance_blockers.append(
            "controlled_submission_clearance_full_fill_quantity_invalid"
        )
    elif terminal_status == "cancelled" and (
        cancelled_quantity <= 0
        or cleared_quantity + cancelled_quantity != expected_quantity
    ):
        clearance_blockers.append(
            "controlled_submission_clearance_cancel_quantity_invalid"
        )
    elif terminal_status not in {"filled", "cancelled"}:
        clearance_blockers.append(
            "controlled_submission_clearance_terminal_status_invalid"
        )
    terminal_lifecycle = broker_order_lifecycle_terminal_outcome(
        order,
        order_lifecycle_evidence,
    )
    clearance_blockers.extend(terminal_lifecycle.get("blockers") or [])
    if terminal_lifecycle.get("status") == "non_terminal":
        clearance_blockers.append(
            "controlled_submission_clearance_lifecycle_not_terminal"
        )
    elif terminal_lifecycle.get("status") == "terminal":
        lifecycle_comparisons = {
            "terminal_status": terminal_status,
            "filled_quantity": str(persisted_fill_quantity),
            "cancelled_quantity": str(cancelled_quantity),
        }
        for field, expected in lifecycle_comparisons.items():
            if str(terminal_lifecycle.get(field) or "") != expected:
                clearance_blockers.append(
                    f"controlled_submission_clearance_lifecycle_{field}_changed"
                )
        persisted_lifecycle_fingerprint = str(
            clearance.get("lifecycle_evidence_fingerprint")
            or clearance_payload.get("lifecycle_evidence_fingerprint")
            or ""
        )
        if persisted_lifecycle_fingerprint and (
            str(terminal_lifecycle.get("evidence_fingerprint") or "")
            != persisted_lifecycle_fingerprint
        ):
            clearance_blockers.append(
                "controlled_submission_clearance_lifecycle_evidence_changed"
            )
    elif terminal_status == "cancelled":
        clearance_blockers.append(
            "controlled_submission_clearance_lifecycle_evidence_missing"
        )
    if clearance_blockers:
        return {
            "item_status": "controlled_submission_clearance_evidence_mismatch",
            "suggested_action": "enable_kill_switch_and_review_controlled_submission",
            "detail": (
                "Persisted controlled-submission clearance no longer matches "
                "OMS or real-fill evidence; keep new submissions blocked."
            ),
            "reported_broker_events": controlled_matching
            or controlled_quantity_mismatch
            or controlled_identity_conflicts,
            "mismatch_reasons": clearance_blockers,
            "evidence_summary": {
                "schema_version": CONTROLLED_SUBMISSION_RECONCILIATION_SCHEMA_VERSION,
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
            "Signed controlled-submission terminal clearance and exact fill/cancel "
            "evidence remain current; production ledger is separate."
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
            "terminal_status": terminal_status,
            "filled_quantity": str(persisted_fill_quantity),
            "cancelled_quantity": str(cancelled_quantity),
            "new_submissions_blocked": False,
            "recovery_resubmission_enabled": False,
            "review_required_before_ledger_update": True,
            "ledger_posting_status": "not_started",
            "production_ledger_mutated": False,
            "does_not_mutate_production_ledger": True,
            "broker_order_lifecycle_evidence": lifecycle_summary,
        },
    }


def classify_order_lifecycle(
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
            "suggested_action": "enable_kill_switch_and_review_controlled_submission",
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

    collector_evidence = json_object(evidence.get("collector_evidence"))
    if (
        bool(collector_evidence.get("required"))
        and str(collector_evidence.get("status") or "") != "healthy"
    ):
        collector_blockers = [
            str(item) for item in collector_evidence.get("blockers") or []
        ]
        return {
            "item_status": "controlled_submission_order_lifecycle_collector_unhealthy",
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

    lifecycle_order = json_object(evidence.get("order"))
    mismatch_reasons: list[str] = []
    if str(lifecycle_order.get("symbol") or "") != str(order.get("symbol") or ""):
        mismatch_reasons.append("controlled_submission_lifecycle_symbol_mismatch")
    if str(lifecycle_order.get("side") or "") != str(order.get("side") or ""):
        mismatch_reasons.append("controlled_submission_lifecycle_side_mismatch")
    expected_quantity = abs(decimal_value(order.get("quantity")) or Decimal("0"))
    lifecycle_quantity = abs(
        decimal_value(lifecycle_order.get("order_quantity")) or Decimal("0")
    )
    if lifecycle_quantity != expected_quantity:
        mismatch_reasons.append("controlled_submission_lifecycle_quantity_mismatch")
    if mismatch_reasons:
        return {
            "item_status": "controlled_submission_order_lifecycle_evidence_mismatch",
            "suggested_action": "enable_kill_switch_and_review_controlled_submission",
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
            decimal_value(lifecycle_order.get("cumulative_filled_quantity"))
            or Decimal("0")
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
            "suggested_action": "import_order_linked_broker_statement_and_account_truth",
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
            "suggested_action": "enable_kill_switch_and_review_controlled_submission",
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


def summarize_order_lifecycle(evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, dict) or not evidence:
        return {}
    observation = json_object(evidence.get("observation"))
    order = json_object(evidence.get("order"))
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
        "collector_evidence": json_object(evidence.get("collector_evidence")),
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
