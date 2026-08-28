"""Pure response and latest-event selection for the signal journal."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.database_normalization import json_dict, json_list
from server.persistence.signal_journal_event_index import (
    SignalJournalEventIndex,
    index_signal_journal_events,
    latest_indexed_signal_journal_event,
)


def apply_manual_confirmation_readiness(
    task: dict[str, Any],
    *,
    risk_gate_status: str,
) -> None:
    task["manual_confirmation_required"] = True
    if risk_gate_status == "passed":
        task["manual_confirmation_status"] = "ready_for_manual_confirmation"
        task["manual_confirmation_reason"] = (
            "Risk gate passed; manual confirmation is required before execution."
        )
    elif risk_gate_status == "blocked":
        task["manual_confirmation_status"] = "blocked_by_risk_gate"
        task["manual_confirmation_reason"] = (
            "Risk gate blocked this action; do not execute without review."
        )
    else:
        task["manual_confirmation_status"] = "awaiting_risk_gate"
        task["manual_confirmation_reason"] = (
            "Risk gate has not produced a decision yet."
        )


def risk_decision_journal_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "decision_id": row["decision_id"],
        "intent_id": row["intent_id"],
        "timestamp": row["timestamp"],
        "passed": bool(row["passed"]),
        "symbol": row["symbol"],
        "side": row["side"],
        "reasons": row.get("reasons") or json_list(row.get("reasons_json")),
        "resulting_order_id": row["resulting_order_id"],
        "severity": row["severity"],
        "payload": row.get("payload") or json_dict(row.get("payload_json")),
        "created_at": row["created_at"],
    }


def event_log_response(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    event = dict(row)
    event["payload"] = json_dict(event.get("payload_json"))
    return event


def latest_signal_journal_event(
    *,
    signal_id: int,
    action_task: dict[str, Any] | None,
    risk_decision: dict[str, Any] | None,
    events: list[dict[str, Any]],
    event_index: SignalJournalEventIndex | None = None,
) -> dict[str, Any] | None:
    action_ref = str(action_task["id"]) if action_task is not None else None
    risk_ref = str(risk_decision["decision_id"]) if risk_decision is not None else None
    if event_index is not None:
        return latest_indexed_signal_journal_event(
            signal_id=signal_id,
            action_ref=action_ref,
            risk_ref=risk_ref,
            event_index=event_index,
        )
    for event in events:
        if (
            event["source"] == "decision_outcome_reviews"
            and event.get("payload", {}).get("signal_id") == signal_id
        ):
            return event
    for event in events:
        if event["source"] == "signal_reviews" and event["source_ref"] == str(
            signal_id
        ):
            return event
    for source in ("manual_orders", "orders"):
        for event in events:
            if (
                event["source"] == source
                and event["event_type"] == "order.status_changed"
                and event_matches_signal_journal_entry(
                    event,
                    signal_id=signal_id,
                    action_ref=action_ref,
                )
            ):
                return event
    for event in events:
        if event["source"] == "risk_decisions" and event["source_ref"] == risk_ref:
            return event
        if event["source"] == "action_tasks" and event["source_ref"] == action_ref:
            return event
        if event_matches_signal_journal_entry(
            event,
            signal_id=signal_id,
            action_ref=action_ref,
        ):
            return event
    return None


def event_matches_signal_journal_entry(
    event: dict[str, Any],
    *,
    signal_id: int,
    action_ref: str | None,
) -> bool:
    payload = event.get("payload", {})
    if payload.get("source_signal_id") == signal_id:
        return True
    nested_payload = payload.get("payload")
    if not isinstance(nested_payload, dict):
        return False
    if nested_payload.get("source_signal_id") == signal_id:
        return True
    return (
        action_ref is not None
        and nested_payload.get("action_id") is not None
        and str(nested_payload["action_id"]) == action_ref
    )


__all__ = [
    "apply_manual_confirmation_readiness",
    "event_log_response",
    "event_matches_signal_journal_entry",
    "index_signal_journal_events",
    "latest_signal_journal_event",
    "risk_decision_journal_response",
]
