"""Shared serialization and invariant helpers for SQLite repositories."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)

__all__ = [
    "account_truth_review_identity_from_connection",
    "action_task_event_payload",
    "apply_manual_confirmation_readiness",
    "controlled_broker_submit_rejection",
    "controlled_lifecycle_invalidated_clearance_rows",
    "controlled_session_authority_rejection",
    "controlled_session_budget_rejection",
    "controlled_session_gate_snapshot_rejection",
    "controlled_session_pause_rejection",
    "controlled_session_rate_admission_rejection",
    "controlled_submission_clearance_rejection",
    "controlled_submission_ledger_correction_rejection",
    "controlled_submission_ledger_posting_rejection",
    "decimal_values_equal",
    "event_log_response",
    "event_matches_signal_journal_entry",
    "fill_event_payload",
    "json_dict",
    "json_list",
    "latest_quote_event_payload",
    "latest_signal_journal_event",
    "manual_order_event_payload",
    "metadata_payload_value",
    "normalize_timestamp",
    "order_event_payload",
    "paper_shadow_run_review_next_step",
    "quote_observation_rank",
    "risk_decision_journal_response",
    "serialize_metadata_json",
    "stable_json_fingerprint",
    "validate_paper_shadow_run_review_transition",
    "verify_controlled_ledger_entry",
]

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_QUOTE_TIMESTAMP = datetime.min.replace(tzinfo=timezone.utc)


def quote_observation_rank(row: dict[str, Any]) -> tuple[datetime, int]:
    """Order quote observations by instant, never by ISO string spelling."""
    raw = str(row.get("timestamp") or row.get("quote_timestamp") or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = _MIN_QUOTE_TIMESTAMP
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(timezone.utc), int(row.get("id") or 0)


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


def controlled_session_budget_rejection(
    reservation: dict[str, Any],
    blockers: list[str],
    *,
    before: dict[str, int] | None = None,
    after: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "reservation": {},
        "reservation_id": str(reservation.get("reservation_id") or ""),
        "attestation_id": str(reservation.get("attestation_id") or ""),
        "aggregate_before": before or {},
        "aggregate_after": after or {},
    }


def controlled_session_rate_admission_rejection(
    admission: dict[str, Any],
    blockers: list[str],
    *,
    admitted_before: int = 0,
    admitted_after: int = 0,
    effective_rate: int = 0,
    pause_event_id: str = "",
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "admission": {},
        "admission_id": str(admission.get("admission_id") or ""),
        "session_id": str(admission.get("session_id") or ""),
        "order_id": str(admission.get("order_id") or ""),
        "admitted_before": admitted_before,
        "admitted_after": admitted_after,
        "effective_rate": effective_rate,
        "pause_event_id": pause_event_id,
    }


def controlled_session_pause_rejection(
    pause: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "state": {},
        "event": {},
        "pause_event_id": str(pause.get("pause_event_id") or ""),
        "session_id": str(pause.get("session_id") or ""),
    }


def controlled_session_authority_rejection(
    payload: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "session": {},
        "revocation": {},
        "session_id": str(payload.get("session_id") or ""),
        "session_fingerprint": str(payload.get("session_fingerprint") or ""),
    }


def controlled_session_gate_snapshot_rejection(
    snapshot: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "snapshot": {},
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "session_id": str(snapshot.get("session_id") or ""),
    }


def controlled_broker_submit_rejection(
    intent: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "external_call_permitted": False,
        "submit_intent_id": str(intent.get("submit_intent_id") or ""),
        "order_id": str(intent.get("order_id") or ""),
        "intent": {},
    }


def controlled_submission_clearance_rejection(
    clearance: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "clearance_id": str(clearance.get("clearance_id") or ""),
        "submit_intent_id": str(clearance.get("submit_intent_id") or ""),
        "order_id": str(clearance.get("order_id") or ""),
        "clearance": {},
        "production_ledger_mutated": False,
    }


def normalize_timestamp(value: str) -> str:
    """Normalize timestamps to stable ISO-8601 text for ordering."""
    normalized_value = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized_value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds")


def serialize_metadata_json(value: dict[str, Any] | str | None) -> str | None:
    """Serialize optional metadata to stable JSON text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def metadata_payload_value(value: dict[str, Any] | str | None) -> Any:
    """Return metadata as a structured event payload value when possible."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted shared order row."""
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "asset_class": row["asset_class"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "payload": metadata_payload_value(row["payload_json"]),
    }


def manual_order_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted manual order row."""
    return {
        "order_row_id": row["id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": row["quantity"],
        "price": row["price"],
        "intent_id": row["intent_id"],
        "risk_decision_id": row["risk_decision_id"],
        "execution_mode": row["execution_mode"],
        "status": row["status"],
        "note": row["note"],
        "payload": metadata_payload_value(row["payload_json"]),
    }


def fill_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted execution fill row."""
    return {
        "fill_row_id": row["id"],
        "fill_id": row["fill_id"],
        "order_id": row["order_id"],
        "timestamp": row["timestamp"],
        "symbol": row["symbol"],
        "side": row["side"],
        "fill_price": row["fill_price"],
        "fill_quantity": row["fill_quantity"],
        "commission": row["commission"],
        "slippage": row["slippage"],
        "asset_class": row["asset_class"],
        "execution_mode": row["execution_mode"],
        "provider_name": row["provider_name"],
        "broker_order_id": row["broker_order_id"],
        "source": row["source"],
        "source_ref": row["source_ref"],
        "metadata": metadata_payload_value(row["metadata_json"]),
    }


def latest_quote_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a materialized latest quote row."""
    return {
        "quote_id": row["id"],
        "symbol": row["symbol"],
        "asset_type": row["asset_type"],
        "price": row["price"],
        "previous_close": row["previous_close"],
        "change": row["change"],
        "change_percent": row["change_percent"],
        "volume": row["volume"],
        "turnover": row["turnover"],
        "quote_timestamp": row["quote_timestamp"],
        "quote_source": row["quote_source"],
        "provider_name": row["provider_name"],
        "provider_status": row["provider_status"],
        "quote_status": row["quote_status"],
        "stale_reason": row["stale_reason"],
        "captured_at": row["captured_at"],
        "captured_reason": row["captured_reason"],
        "nav_date": row["nav_date"],
        "fetch_run_id": row["fetch_run_id"],
        "metadata": metadata_payload_value(row["metadata_json"]),
    }


def action_task_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    """Build a stable event payload from a persisted action task row."""
    return {
        "task_id": row["id"],
        "source_signal_id": row["source_signal_id"],
        "symbol": row["symbol"],
        "title": row["title"],
        "detail": row["detail"],
        "direction": row["direction"],
        "urgency": row["urgency"],
        "target_weight": row["target_weight"],
        "price": row["price"],
        "strategy_id": row["strategy_id"],
        "timestamp": row["timestamp"],
        "asset_class": row["asset_class"],
        "status": row["status"],
    }


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
) -> dict[str, Any] | None:
    action_ref = str(action_task["id"]) if action_task is not None else None
    risk_ref = str(risk_decision["decision_id"]) if risk_decision is not None else None
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
    for event in events:
        if (
            event["source"] == "manual_orders"
            and event["event_type"] == "order.status_changed"
            and event_matches_signal_journal_entry(
                event,
                signal_id=signal_id,
                action_ref=action_ref,
            )
        ):
            return event
    for event in events:
        if (
            event["source"] == "orders"
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


def controlled_lifecycle_invalidated_clearance_rows(
    conn: sqlite3.Connection,
    *,
    exclude_order_id: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Find cleared intents contradicted by newer persisted lifecycle facts."""

    from account_truth.broker_order_lifecycle import (
        broker_order_lifecycle_terminal_outcome,
        resolve_broker_order_lifecycle_from_connection,
    )

    rows = conn.execute(
        """
        SELECT intent.*, oms.status AS oms_status,
               oms.symbol AS oms_symbol, oms.side AS oms_side,
               oms.quantity AS oms_quantity,
               clearance.terminal_status AS clearance_terminal_status,
               clearance.fill_quantity AS clearance_fill_quantity,
               clearance.cancelled_quantity AS clearance_cancelled_quantity,
               clearance.lifecycle_observation_id AS clearance_lifecycle_observation_id,
               clearance.lifecycle_evidence_fingerprint AS clearance_lifecycle_evidence_fingerprint
        FROM controlled_broker_submit_intents AS intent
        JOIN controlled_submission_reconciliation_clearances AS clearance
          ON clearance.submit_intent_id = intent.submit_intent_id
         AND clearance.status = 'cleared'
        JOIN oms_orders AS oms ON oms.order_id = intent.order_id
        WHERE intent.status = 'submitted'
          AND intent.order_id != ?
        ORDER BY intent.prepared_at_epoch_ms ASC, intent.id ASC
        LIMIT ?
        """,
        (
            str(exclude_order_id or ""),
            max(1, min(int(limit), 500)),
        ),
    ).fetchall()
    invalidated: list[dict[str, Any]] = []
    for row in rows:
        intent = dict(row)
        account_alias = str(
            json_dict(intent.get("payload_json")).get("account_alias") or ""
        )
        if not account_alias:
            continue
        evidence = resolve_broker_order_lifecycle_from_connection(
            conn,
            gateway_id=str(intent.get("gateway_id") or ""),
            account_alias=account_alias,
            broker_order_id=str(intent.get("broker_order_id") or ""),
            client_order_id=str(intent.get("client_order_id") or ""),
        )
        terminal = broker_order_lifecycle_terminal_outcome(
            {
                "symbol": str(intent.get("oms_symbol") or ""),
                "side": str(intent.get("oms_side") or ""),
                "quantity": intent.get("oms_quantity"),
            },
            evidence,
        )
        lifecycle_blockers = list(terminal.get("blockers") or [])
        persisted_observation_id = str(
            intent.get("clearance_lifecycle_observation_id") or ""
        )
        persisted_evidence_fingerprint = str(
            intent.get("clearance_lifecycle_evidence_fingerprint") or ""
        )
        if terminal.get("status") == "non_terminal":
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_not_terminal"
            )
        elif terminal.get("status") == "not_available" and persisted_observation_id:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_lifecycle_missing"
            )
        elif terminal.get("status") == "terminal":
            comparisons = {
                "terminal_status": intent.get("clearance_terminal_status"),
                "filled_quantity": intent.get("clearance_fill_quantity"),
                "cancelled_quantity": intent.get("clearance_cancelled_quantity"),
            }
            for field, expected in comparisons.items():
                if str(terminal.get(field) or "") != str(expected or ""):
                    lifecycle_blockers.append(
                        f"controlled_submission_terminal_clearance_{field}_changed"
                    )
            if persisted_observation_id and persisted_observation_id != str(
                terminal.get("observation_id") or ""
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_observation_changed"
                )
            if (
                persisted_evidence_fingerprint
                and persisted_evidence_fingerprint
                != str(terminal.get("evidence_fingerprint") or "")
            ):
                lifecycle_blockers.append(
                    "controlled_submission_terminal_clearance_evidence_changed"
                )
        expected_oms_status = str(intent.get("clearance_terminal_status") or "")
        if str(intent.get("oms_status") or "") != expected_oms_status and evidence.get(
            "status"
        ) in {"found", "blocked", "identity_conflict"}:
            lifecycle_blockers.append(
                "controlled_submission_terminal_clearance_oms_status_changed"
            )
        if lifecycle_blockers:
            observation = evidence.get("observation")
            observation = observation if isinstance(observation, dict) else {}
            intent["interlock_reason"] = "lifecycle_clearance_invalidated"
            intent["lifecycle_blocker"] = lifecycle_blockers[0]
            intent["lifecycle_observation_id"] = str(
                observation.get("observation_id") or ""
            )
            invalidated.append(intent)
    return invalidated


def verify_controlled_ledger_entry(
    conn: sqlite3.Connection,
    *,
    entry: dict[str, Any],
    request: dict[str, Any],
) -> list[str]:
    """Re-check one proposed entry against immutable fill and broker evidence."""
    blockers: list[str] = []
    fill_id = str(entry.get("fill_id") or "")
    event_id = str(entry.get("broker_event_id") or "")
    row_fingerprint = str(entry.get("broker_row_fingerprint") or "")
    fill = conn.execute(
        "SELECT * FROM fills WHERE fill_id = ? LIMIT 1",
        (fill_id,),
    ).fetchone()
    event = conn.execute(
        """
        SELECT * FROM broker_evidence_events
        WHERE import_run_id = ? AND event_id = ? AND row_fingerprint = ?
        LIMIT 1
        """,
        (
            request["account_truth_import_run_id"],
            event_id,
            row_fingerprint,
        ),
    ).fetchone()
    if fill is None:
        blockers.append("controlled_ledger_posting_fill_missing")
    else:
        metadata = json_dict(fill["metadata_json"])
        fill_fields = {
            "order_id": request["order_id"],
            "execution_mode": "controlled_live",
            "source": "controlled_submission_clearance",
            "fill_id": fill_id,
        }
        for field, expected in fill_fields.items():
            if str(fill[field] or "") != str(expected or ""):
                blockers.append(f"controlled_ledger_posting_fill_{field}_changed")
        if str(metadata.get("clearance_id") or "") != request["clearance_id"]:
            blockers.append("controlled_ledger_posting_fill_clearance_changed")
        if str(metadata.get("broker_event_id") or "") != event_id:
            blockers.append("controlled_ledger_posting_fill_event_changed")
        if str(metadata.get("broker_row_fingerprint") or "") != row_fingerprint:
            blockers.append("controlled_ledger_posting_fill_row_changed")
    if event is None:
        blockers.append("controlled_ledger_posting_broker_event_missing")
        return blockers

    direction = str(entry.get("direction") or "")
    if direction not in {"buy", "sell"}:
        blockers.append("controlled_ledger_posting_entry_direction_invalid")
    expected_entry_type = f"trade_{direction}"
    textual_expectations = {
        "entry_type": expected_entry_type,
        "symbol": str(event["symbol"] or ""),
        "asset_class": str(event["asset_class"] or "stock"),
        "source": "controlled_submission_ledger_posting",
        "source_ref": fill_id,
        "settlement_status": "confirmed",
        "settlement_source": "broker_statement",
        "settlement_source_ref": (
            f"{request['account_truth_import_run_id']}:{event_id}"
        ),
        "fee_rule_id": "broker_statement_exact",
        "fee_rule_version": "broker_statement_exact.v1",
        "cost_basis_method": "broker_remaining_cost",
    }
    for field, expected in textual_expectations.items():
        if str(entry.get(field) or "") != expected:
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if str(event["broker_order_id"] or "") != request["broker_order_id"]:
        blockers.append("controlled_ledger_posting_event_broker_order_changed")
    if str(event["client_order_id"] or "") != request["client_order_id"]:
        blockers.append("controlled_ledger_posting_event_client_order_changed")
    if str(event["event_type"] or "") != expected_entry_type:
        blockers.append("controlled_ledger_posting_event_type_changed")

    numeric_expectations = {
        "quantity": event["quantity"],
        "price": event["price"],
        "amount": event["gross_amount"],
        "gross_amount": event["gross_amount"],
        "commission": event["fee"],
        "net_cash_impact": event["net_amount"],
    }
    for field, expected in numeric_expectations.items():
        if not decimal_values_equal(entry.get(field), expected):
            blockers.append(f"controlled_ledger_posting_entry_{field}_changed")
    if fill is not None:
        for entry_field, fill_field in (
            ("quantity", "fill_quantity"),
            ("price", "fill_price"),
            ("commission", "commission"),
        ):
            if not decimal_values_equal(entry.get(entry_field), fill[fill_field]):
                blockers.append(f"controlled_ledger_posting_fill_{fill_field}_changed")
    fee_breakdown = entry.get("fee_breakdown")
    fee_breakdown = fee_breakdown if isinstance(fee_breakdown, dict) else {}
    fee_expectations = {
        "commission": event["fee"],
        "stamp_tax": event["tax"],
        "transfer_fee": event["transfer_fee"],
        "other_fees": "0",
    }
    for field, expected in fee_expectations.items():
        if not decimal_values_equal(fee_breakdown.get(field), expected):
            blockers.append(f"controlled_ledger_posting_fee_{field}_changed")
    expected_total_fee = sum(
        (Decimal(str(event[field] or "0")) for field in ("fee", "tax", "transfer_fee")),
        Decimal("0"),
    )
    if not decimal_values_equal(fee_breakdown.get("total_fee"), expected_total_fee):
        blockers.append("controlled_ledger_posting_fee_total_changed")
    try:
        if normalize_timestamp(str(entry.get("timestamp") or "")) != (
            normalize_timestamp(str(event["occurred_at"] or ""))
        ):
            blockers.append("controlled_ledger_posting_entry_timestamp_changed")
        expected_settled_at = str(event["settled_at"] or event["occurred_at"] or "")
        if normalize_timestamp(str(entry.get("settled_at") or "")) != (
            normalize_timestamp(expected_settled_at)
        ):
            blockers.append("controlled_ledger_posting_entry_settlement_time_changed")
    except ValueError:
        blockers.append("controlled_ledger_posting_entry_timestamp_invalid")

    source_conflict = conn.execute(
        """
        SELECT id FROM ledger_entries
        WHERE (source = ? AND source_ref = ?)
           OR (settlement_source = ? AND settlement_source_ref = ?)
        LIMIT 1
        """,
        (
            entry.get("source"),
            entry.get("source_ref"),
            entry.get("settlement_source"),
            entry.get("settlement_source_ref"),
        ),
    ).fetchone()
    if source_conflict is not None:
        blockers.append("controlled_ledger_posting_entry_already_exists")
    return list(dict.fromkeys(blockers))


def account_truth_review_identity_from_connection(
    conn: sqlite3.Connection,
    *,
    import_run_id: str,
) -> dict[str, Any]:
    """Build a stable identity for current Account Truth review decisions."""
    table_exists = conn.execute("""
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'reconciliation_review_decisions'
        """).fetchone()
    if table_exists is None:
        rows: list[dict[str, Any]] = []
    else:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT import_run_id, item_key, category, symbol,
                       review_status, evidence_fingerprint, schema_version,
                       created_at, updated_at
                FROM reconciliation_review_decisions
                WHERE import_run_id = ?
                ORDER BY item_key ASC, id ASC
                """,
                (import_run_id,),
            ).fetchall()
        ]
    return {
        "import_run_id": import_run_id,
        "decision_count": len(rows),
        "fingerprint": stable_json_fingerprint(rows),
    }


def decimal_values_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (ArithmeticError, TypeError, ValueError):
        return False


def stable_json_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def controlled_submission_ledger_posting_rejection(
    requested: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "posting_id": str(requested.get("posting_id") or ""),
        "clearance_id": str(requested.get("clearance_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


def controlled_submission_ledger_correction_rejection(
    requested: dict[str, Any],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "correction_id": str(requested.get("correction_id") or ""),
        "posting_id": str(requested.get("posting_id") or ""),
        "blockers": list(dict.fromkeys(blockers)),
        "reused": False,
        "production_ledger_mutated": False,
    }


def json_dict(value) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_list(value) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def paper_shadow_run_review_next_step(review_status: str) -> str:
    status = str(review_status or "").strip().lower()
    if status == "accepted_for_manual_confirmation":
        return "review_manual_confirmation"
    if status == "needs_rerun":
        return "run_paper_shadow_daily"
    return "resolve_shadow_divergence"


def validate_paper_shadow_run_review_transition(
    *,
    run_status: str,
    review_status: str,
) -> None:
    normalized_run_status = str(run_status or "").strip().lower()
    normalized_review_status = str(review_status or "").strip().lower()
    if (
        normalized_run_status == "failed"
        and normalized_review_status == "accepted_for_manual_confirmation"
    ):
        raise ValueError(
            "failed paper/shadow run cannot be accepted for manual confirmation; "
            "inspect the failed run or rerun paper/shadow first"
        )
