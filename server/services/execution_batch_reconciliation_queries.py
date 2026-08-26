"""Persisted queries for execution batch reconciliation evidence."""

from __future__ import annotations

import re
from typing import Any, Callable

from server.services.execution_batch_reconciliation_values import (
    EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
    EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
    EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION,
    event_response,
    resolution_summary,
)


def resolve_recorded_execution_batch_reconciliation(
    *,
    db: Any,
    preview_builder: Callable[..., dict[str, Any]],
    fingerprint: str,
    expected_strategy_id: str | None = None,
) -> dict[str, Any]:
    normalized = str(fingerprint or "").strip().lower()
    blockers: list[str] = []
    if not re.fullmatch(r"[a-f0-9]{64}", normalized):
        blockers.append("prior_batch_reconciliation_fingerprint_invalid")
    rows = (
        db.list_events_sync(
            event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
            entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
            entity_id=normalized,
            source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
            limit=1,
        )
        if not blockers
        else []
    )
    if not rows:
        blockers.append("prior_batch_reconciliation_not_found")
        return resolution_summary(
            normalized,
            {},
            blockers,
            expected_strategy_id=expected_strategy_id,
        )
    recorded = event_response(rows[0], reused=False)
    if recorded.get("schema_version") != (
        EXECUTION_BATCH_RECONCILIATION_SCHEMA_VERSION
    ):
        blockers.append("prior_batch_reconciliation_schema_invalid")
    if recorded.get("record_status") != "recorded_clear":
        blockers.append("prior_batch_reconciliation_record_not_clear")
    if recorded.get("status") != "clear" or not recorded.get(
        "batch_reconciliation_clear"
    ):
        blockers.append("prior_batch_reconciliation_not_clear")
    current = preview_builder(
        batch_id=str(recorded.get("batch_id") or ""),
        order_ids=[str(item) for item in recorded.get("order_ids") or []],
        reconciliation_run_id=str(recorded.get("reconciliation_run_id") or ""),
    )
    if current["batch_reconciliation_fingerprint"] != normalized:
        blockers.append("prior_batch_reconciliation_source_changed")
    return resolution_summary(
        normalized,
        recorded,
        blockers,
        expected_strategy_id=expected_strategy_id,
    )


def list_execution_batch_reconciliations(
    *,
    db: Any,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = db.list_events_sync(
        event_type=EXECUTION_BATCH_RECONCILIATION_EVENT_TYPE,
        entity_type=EXECUTION_BATCH_RECONCILIATION_EVENT_ENTITY_TYPE,
        source=EXECUTION_BATCH_RECONCILIATION_EVENT_SOURCE,
        limit=max(1, min(int(limit), 500)),
    )
    return [event_response(row, reused=False) for row in rows]
