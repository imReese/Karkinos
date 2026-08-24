"""Audit workflow for fail-closed controlled cancellation attempts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from server.contracts.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION,
    CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION,
    cancellation_aware_utc,
    cancellation_fingerprint,
)
from server.projections.controlled_broker_cancellation import (
    controlled_broker_cancellation_safety_flags,
)


def record_controlled_broker_cancellation_rejection(
    *,
    db: Any,
    clock: Callable[[], datetime],
    preview: dict[str, Any],
    submitted_fingerprint: str,
    operator_approval_id: str,
    rejection_reasons: list[str],
    transaction_blockers: list[str],
    recovery: bool,
) -> dict[str, Any]:
    """Append sanitized rejection evidence without granting retry authority."""

    now = cancellation_aware_utc(clock())
    payload = {
        "schema_version": (
            CONTROLLED_BROKER_CANCELLATION_RECOVERY_SCHEMA_VERSION
            if recovery
            else CONTROLLED_BROKER_CANCELLATION_SCHEMA_VERSION
        ),
        "status": "rejected",
        "action": "recovery_query" if recovery else "cancel",
        "submit_intent_id": str(preview.get("submit_intent_id") or ""),
        "order_id": str(preview.get("order_id") or ""),
        "cancel_command_id": str(preview.get("cancel_command_id") or ""),
        "expected_fingerprint": str(
            preview.get("recovery_fingerprint" if recovery else "cancel_fingerprint")
            or ""
        ),
        "submitted_fingerprint": submitted_fingerprint,
        "operator_approval_id": str(operator_approval_id or ""),
        "review_blockers": [str(item) for item in preview.get("blockers") or []],
        "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
        "transaction_blockers": list(dict.fromkeys(transaction_blockers)),
        "broker_cancel_performed": False,
        "broker_query_performed": False,
        "cancellation_proven": False,
        "oms_mutated": False,
        "production_ledger_mutated": False,
        "capital_authority_changed": False,
    }
    attempt_id = cancellation_fingerprint({**payload, "attempted_at": now.isoformat()})
    event_id = db.append_event_sync(
        event_type=(
            "controlled_broker.cancellation_recovery_rejected"
            if recovery
            else "controlled_broker.cancellation_rejected"
        ),
        timestamp=now.isoformat(),
        entity_type=(
            "controlled_broker_cancellation_recovery_rejection"
            if recovery
            else "controlled_broker_cancellation_rejection"
        ),
        entity_id=attempt_id,
        source="controlled_broker_cancellation",
        source_ref=payload["expected_fingerprint"],
        payload={"attempt_id": attempt_id, **payload},
    )
    return {
        "event_id": event_id,
        "attempt_id": attempt_id,
        "recorded_at": now.isoformat(),
        "persisted": True,
        **payload,
        "safety": controlled_broker_cancellation_safety_flags(),
    }
