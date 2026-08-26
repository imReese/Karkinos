"""Append-only commands for execution batch reconciliation evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.services.execution_batch_reconciliation_values import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    aware_utc,
    event_response,
    safety_flags,
    stable_fingerprint,
)


def record_execution_batch_reconciliation(
    *,
    db: Any,
    clock: Callable[[], datetime],
    preview_builder: Callable[..., dict[str, Any]],
    rejected_type: Callable[..., Exception],
    batch_id: str,
    order_ids: list[str] | tuple[str, ...],
    reconciliation_run_id: str,
    batch_reconciliation_fingerprint: str,
    operator_label: str,
    acknowledgement: str,
) -> dict[str, Any]:
    preview = preview_builder(
        batch_id=batch_id,
        order_ids=order_ids,
        reconciliation_run_id=reconciliation_run_id,
    )
    rejection_reasons: list[str] = []
    if not str(operator_label or "").strip():
        rejection_reasons.append("operator_label_missing")
    if acknowledgement != EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT:
        rejection_reasons.append("acknowledgement_mismatch")
    if batch_reconciliation_fingerprint != preview["batch_reconciliation_fingerprint"]:
        rejection_reasons.append("batch_reconciliation_fingerprint_mismatch")
    if rejection_reasons:
        evidence = _record_rejected_attempt(
            db=db,
            clock=clock,
            preview=preview,
            submitted_fingerprint=batch_reconciliation_fingerprint,
            operator_label=str(operator_label or "").strip(),
            acknowledgement=acknowledgement,
            rejection_reasons=rejection_reasons,
        )
        raise rejected_type(
            "execution batch reconciliation rejected: " + ", ".join(rejection_reasons),
            evidence=evidence,
        )

    fingerprint = str(preview["batch_reconciliation_fingerprint"])
    existing = db.list_events_sync(
        event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
        entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
        entity_id=fingerprint,
        source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
        limit=1,
    )
    if existing:
        return event_response(existing[0], reused=True)
    record_status = (
        "recorded_clear" if preview["status"] == "clear" else "recorded_blocked"
    )
    payload = {
        key: value
        for key, value in preview.items()
        if key not in {"generated_at", "persisted", "reused"}
    }
    payload.update(
        {
            "record_status": record_status,
            "operator_label": str(operator_label or "").strip(),
            "operator_identity_verified": False,
            "acknowledgement": acknowledgement,
            "rejection_reasons": [],
        }
    )
    db.append_event_sync(
        event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
        timestamp=aware_utc(clock()).isoformat(),
        entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
        entity_id=fingerprint,
        source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
        source_ref=str(preview.get("reconciliation_run_id") or ""),
        payload=payload,
    )
    saved = db.list_events_sync(
        event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
        entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
        entity_id=fingerprint,
        source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
        limit=1,
    )
    if not saved:
        raise RuntimeError("execution batch reconciliation was not recorded")
    return event_response(saved[0], reused=False)


def _record_rejected_attempt(
    *,
    db: Any,
    clock: Callable[[], datetime],
    preview: dict[str, Any],
    submitted_fingerprint: str,
    operator_label: str,
    acknowledgement: str,
    rejection_reasons: list[str],
) -> dict[str, Any]:
    attempt_id = stable_fingerprint(
        {
            "batch_reconciliation_fingerprint": preview.get(
                "batch_reconciliation_fingerprint"
            ),
            "submitted_fingerprint": submitted_fingerprint,
            "operator_label": operator_label,
            "acknowledgement": acknowledgement,
            "rejection_reasons": rejection_reasons,
        }
    )
    payload = {
        "schema_version": EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
        "record_status": "rejected",
        "attempt_id": attempt_id,
        "batch_id": preview.get("batch_id"),
        "order_ids": preview.get("order_ids"),
        "reconciliation_run_id": preview.get("reconciliation_run_id"),
        "batch_reconciliation_fingerprint": preview.get(
            "batch_reconciliation_fingerprint"
        ),
        "submitted_fingerprint": submitted_fingerprint,
        "operator_label": operator_label,
        "operator_identity_verified": False,
        "acknowledgement": acknowledgement,
        "rejection_reasons": rejection_reasons,
        "batch_reconciliation_clear": False,
        "authorizes_next_batch": False,
        "safety": safety_flags(),
    }
    existing = db.list_events_sync(
        event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
        entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
        entity_id=attempt_id,
        source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
        limit=1,
    )
    if not existing:
        db.append_event_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            timestamp=aware_utc(clock()).isoformat(),
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=attempt_id,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            source_ref=str(preview.get("reconciliation_run_id") or ""),
            payload=payload,
        )
        existing = db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=attempt_id,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=1,
        )
    if not existing:
        raise RuntimeError("rejected batch reconciliation was not audited")
    return event_response(existing[0], reused=False)
