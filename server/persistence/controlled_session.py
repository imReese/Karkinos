"""SQLite repository for controlled-session reservations, authority, gates, rate admission, and pause."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from server.persistence.connection import DateTimeNow, SQLiteRepository
from server.persistence.database_support import (
    account_truth_review_identity_from_connection,
    action_task_event_payload,
    apply_manual_confirmation_readiness,
    controlled_broker_submit_rejection,
    controlled_lifecycle_invalidated_clearance_rows,
    controlled_session_authority_rejection,
    controlled_session_budget_rejection,
    controlled_session_gate_snapshot_rejection,
    controlled_session_pause_rejection,
    controlled_session_rate_admission_rejection,
    controlled_submission_clearance_rejection,
    controlled_submission_ledger_correction_rejection,
    controlled_submission_ledger_posting_rejection,
    decimal_values_equal,
    event_log_response,
    event_matches_signal_journal_entry,
    fill_event_payload,
    json_dict,
    json_list,
    latest_quote_event_payload,
    latest_signal_journal_event,
    manual_order_event_payload,
    metadata_payload_value,
    normalize_timestamp,
    order_event_payload,
    paper_shadow_run_review_next_step,
    quote_observation_rank,
    risk_decision_journal_response,
    serialize_metadata_json,
    stable_json_fingerprint,
    validate_paper_shadow_run_review_transition,
    verify_controlled_ledger_entry,
)
from server.persistence.event_log import (
    insert_event_sync,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)

logger = logging.getLogger(__name__)


class ControlledSessionRepository(SQLiteRepository):
    """Own controlled-session reservations, authority, gates, rate admission, and pause."""

    def reserve_controlled_session_budget_sync(
        self,
        *,
        reservation: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically reserve bounded capital without issuing execution authority."""
        requested = dict(reservation)
        money_fields = (
            "reserved_gross_units",
            "reserved_buy_units",
            "reserved_turnover_units",
            "capital_capacity_units",
            "cash_capacity_units",
            "turnover_capacity_units",
        )
        count_fields = ("reserved_order_count", "order_count_capacity")
        try:
            requested_by_symbol = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("reserved_by_symbol_units") or {}
                ).items()
            }
            symbol_capacities = {
                str(symbol): int(value)
                for symbol, value in (
                    requested.get("symbol_capacity_units") or {}
                ).items()
            }
            invalid_money_units = any(
                int(requested.get(field) or 0) < 0 for field in money_fields
            )
            invalid_count_units = any(
                int(requested.get(field) or 0) <= 0 for field in count_fields
            )
        except (AttributeError, TypeError, ValueError):
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_units_invalid"],
            )
        if invalid_money_units:
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_money_units_invalid"],
            )
        if invalid_count_units:
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_order_count_invalid"],
            )
        if (
            not requested_by_symbol
            or set(requested_by_symbol) != set(symbol_capacities)
            or any(value < 0 for value in requested_by_symbol.values())
            or any(value <= 0 for value in symbol_capacities.values())
        ):
            return controlled_session_budget_rejection(
                requested,
                ["budget_reservation_symbol_units_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "status": "reserved",
                        "blockers": [],
                        "reused": True,
                        "reservation": dict(existing),
                    }
                attestation_conflict = conn.execute(
                    """
                    SELECT reservation_id
                    FROM controlled_session_budget_reservations
                    WHERE attestation_id = ?
                    LIMIT 1
                    """,
                    (requested["attestation_id"],),
                ).fetchone()
                if attestation_conflict is not None:
                    conn.rollback()
                    return controlled_session_budget_rejection(
                        requested,
                        ["budget_reservation_attestation_already_reserved"],
                    )

                scope = (
                    requested["authorization_id"],
                    requested["account_alias"],
                )
                overlap = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(reserved_gross_units), 0) AS gross_units,
                        COALESCE(SUM(reserved_buy_units), 0) AS buy_units,
                        COALESCE(SUM(reserved_order_count), 0) AS order_count,
                        MIN(order_count_capacity) AS minimum_order_capacity
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND status = 'reserved'
                      AND requested_start_at < ?
                      AND requested_expires_at > ?
                    """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchone()
                overlap_symbol_rows = conn.execute(
                    """
                    SELECT reserved_by_symbol_json, symbol_capacity_json
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND status = 'reserved'
                      AND requested_start_at < ?
                      AND requested_expires_at > ?
                    """,
                    (
                        *scope,
                        requested["requested_expires_at"],
                        requested["requested_start_at"],
                    ),
                ).fetchall()
                daily = conn.execute(
                    """
                    SELECT COALESCE(SUM(reserved_turnover_units), 0) AS turnover_units
                    FROM controlled_session_budget_reservations
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND trading_day = ?
                      AND status = 'reserved'
                    """,
                    (*scope, requested["trading_day"]),
                ).fetchone()
                before = {
                    "overlapping_gross_units": int(overlap["gross_units"] or 0),
                    "overlapping_buy_units": int(overlap["buy_units"] or 0),
                    "overlapping_order_count": int(overlap["order_count"] or 0),
                    "daily_turnover_units": int(daily["turnover_units"] or 0),
                    "overlapping_by_symbol_units": {
                        symbol: 0 for symbol in sorted(requested_by_symbol)
                    },
                }
                effective_symbol_capacities = dict(symbol_capacities)
                symbol_evidence_blockers: list[str] = []
                for row in overlap_symbol_rows:
                    existing_reserved = json_dict(row["reserved_by_symbol_json"])
                    existing_capacities = json_dict(row["symbol_capacity_json"])
                    if not existing_reserved or not existing_capacities:
                        symbol_evidence_blockers.extend(
                            f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            for symbol in requested_by_symbol
                        )
                        continue
                    for symbol in requested_by_symbol:
                        reserved_present = symbol in existing_reserved
                        capacity_present = symbol in existing_capacities
                        if reserved_present != capacity_present:
                            symbol_evidence_blockers.append(
                                f"atomic_existing_symbol_budget_evidence_missing:{symbol}"
                            )
                            continue
                        if not reserved_present:
                            continue
                        before["overlapping_by_symbol_units"][symbol] += int(
                            existing_reserved[symbol]
                        )
                        effective_symbol_capacities[symbol] = min(
                            effective_symbol_capacities[symbol],
                            int(existing_capacities[symbol]),
                        )
                minimum_order_capacity = min(
                    int(requested["order_count_capacity"]),
                    int(
                        overlap["minimum_order_capacity"]
                        or requested["order_count_capacity"]
                    ),
                )
                after = {
                    "overlapping_gross_units": before["overlapping_gross_units"]
                    + int(requested["reserved_gross_units"]),
                    "overlapping_buy_units": before["overlapping_buy_units"]
                    + int(requested["reserved_buy_units"]),
                    "overlapping_order_count": before["overlapping_order_count"]
                    + int(requested["reserved_order_count"]),
                    "daily_turnover_units": before["daily_turnover_units"]
                    + int(requested["reserved_turnover_units"]),
                    "overlapping_by_symbol_units": {
                        symbol: before["overlapping_by_symbol_units"][symbol]
                        + requested_by_symbol[symbol]
                        for symbol in sorted(requested_by_symbol)
                    },
                }
                blockers: list[str] = list(dict.fromkeys(symbol_evidence_blockers))
                if after["overlapping_gross_units"] > int(
                    requested["capital_capacity_units"]
                ):
                    blockers.append("atomic_capital_budget_unavailable")
                if after["overlapping_buy_units"] > int(
                    requested["cash_capacity_units"]
                ):
                    blockers.append("atomic_cash_budget_unavailable")
                if after["daily_turnover_units"] > int(
                    requested["turnover_capacity_units"]
                ):
                    blockers.append("atomic_daily_turnover_budget_unavailable")
                if after["overlapping_order_count"] > minimum_order_capacity:
                    blockers.append("atomic_order_count_budget_unavailable")
                for symbol, after_units in after["overlapping_by_symbol_units"].items():
                    if after_units > effective_symbol_capacities[symbol]:
                        blockers.append(f"atomic_symbol_budget_unavailable:{symbol}")
                if blockers:
                    conn.rollback()
                    return controlled_session_budget_rejection(
                        requested,
                        blockers,
                        before=before,
                        after=after,
                    )

                created_at = str(requested["created_at"])
                conn.execute(
                    """
                    INSERT INTO controlled_session_budget_reservations (
                        reservation_id, attestation_id, envelope_fingerprint,
                        capital_evaluation_input_fingerprint, authorization_id,
                        policy_version, account_alias, strategy_id, trading_day,
                        requested_start_at, requested_expires_at,
                        reserved_gross_units, reserved_buy_units,
                        reserved_turnover_units, reserved_order_count,
                        capital_capacity_units, cash_capacity_units,
                        turnover_capacity_units, order_count_capacity,
                        reserved_by_symbol_json, symbol_capacity_json,
                        status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["capital_evaluation_input_fingerprint"],
                        requested["authorization_id"],
                        requested["policy_version"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["trading_day"],
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["reserved_gross_units"]),
                        int(requested["reserved_buy_units"]),
                        int(requested["reserved_turnover_units"]),
                        int(requested["reserved_order_count"]),
                        int(requested["capital_capacity_units"]),
                        int(requested["cash_capacity_units"]),
                        int(requested["turnover_capacity_units"]),
                        int(requested["order_count_capacity"]),
                        _serialize_event_payload_json(requested_by_symbol),
                        _serialize_event_payload_json(symbol_capacities),
                        "reserved",
                        _serialize_event_payload_json(requested["payload"]),
                        created_at,
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "reserved",
                    "blockers": [],
                    "reused": False,
                    "reservation": dict(saved) if saved is not None else {},
                    "aggregate_before": before,
                    "aggregate_after": after,
                }
            except (sqlite3.OperationalError, TypeError, ValueError):
                conn.rollback()
                return controlled_session_budget_rejection(
                    requested,
                    ["budget_reservation_transaction_unavailable"],
                )

    def list_controlled_session_budget_reservations_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable reservation records newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_budget_reservations
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_budget_reservation_sync(
        self,
        reservation_id: str,
    ) -> dict[str, Any] | None:
        """Read one reservation by its deterministic id."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_budget_reservations
                WHERE reservation_id = ?
                LIMIT 1
                """,
                (reservation_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def issue_controlled_session_sync(
        self,
        *,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """Issue one persisted bounded session for one exact reservation."""
        requested = dict(session)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ? OR reservation_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["reservation_id"]),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["session_id"] == requested["session_id"]
                        and existing["session_fingerprint"]
                        == requested["session_fingerprint"]
                        and existing["issuance_fingerprint"]
                        == requested["issuance_fingerprint"]
                        and existing["reservation_id"] == requested["reservation_id"]
                    ):
                        conn.commit()
                        return {
                            "status": str(existing["status"]),
                            "blockers": [],
                            "reused": True,
                            "session": dict(existing),
                        }
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_or_identity_conflict"],
                    )

                reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if reservation is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_reservation_not_found"],
                    )
                reservation_blockers: list[str] = []
                for field in (
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "requested_start_at",
                    "requested_expires_at",
                ):
                    if str(reservation[field] or "") != str(requested[field] or ""):
                        reservation_blockers.append(
                            f"runtime_session_reservation_{field}_mismatch"
                        )
                if str(reservation["status"] or "") != "reserved":
                    reservation_blockers.append(
                        "runtime_session_reservation_not_reserved"
                    )
                if reservation_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        reservation_blockers,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_sessions (
                        session_id, session_fingerprint, issuance_fingerprint,
                        reservation_id, attestation_id, envelope_fingerprint,
                        authorization_id, account_alias, strategy_id,
                        operator_id, operator_approval_id, order_ids_json,
                        effective_at_epoch_ms, expires_at_epoch_ms,
                        effective_at, expires_at, max_order_rate_per_minute,
                        token_salt, token_hash, status, payload_json, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["issuance_fingerprint"],
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        _serialize_event_payload_json(requested["order_ids"]),
                        int(requested["effective_at_epoch_ms"]),
                        int(requested["expires_at_epoch_ms"]),
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["max_order_rate_per_minute"]),
                        requested["token_salt"],
                        requested["token_hash"],
                        "enabled",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "enabled",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_issuance_transaction_unavailable"],
                )

    def replace_paused_controlled_session_sync(
        self,
        *,
        replacement: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically retire one paused session and issue one bounded replacement."""
        requested = dict(replacement)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_event = conn.execute(
                    """
                    SELECT * FROM controlled_session_replacement_events
                    WHERE replacement_id = ? OR predecessor_session_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (
                        requested["replacement_id"],
                        requested["predecessor_session_id"],
                    ),
                ).fetchone()
                if existing_event is not None:
                    if (
                        existing_event["replacement_id"] == requested["replacement_id"]
                        and existing_event["replacement_fingerprint"]
                        == requested["replacement_fingerprint"]
                        and existing_event["replacement_session_id"]
                        == requested["session_id"]
                    ):
                        existing_session = conn.execute(
                            """
                            SELECT * FROM controlled_session_runtime_sessions
                            WHERE session_id = ?
                            LIMIT 1
                            """,
                            (requested["session_id"],),
                        ).fetchone()
                        conn.commit()
                        return {
                            "status": str(existing_session["status"]),
                            "blockers": [],
                            "reused": True,
                            "session": (
                                dict(existing_session)
                                if existing_session is not None
                                else {}
                            ),
                            "replacement": dict(existing_event),
                        }
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_conflict"],
                    )

                predecessor = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["predecessor_session_id"],),
                ).fetchone()
                pause_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["predecessor_session_id"],),
                ).fetchone()
                if predecessor is None or pause_state is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_paused_predecessor_missing"],
                    )
                predecessor_blockers: list[str] = []
                if predecessor["status"] != "enabled":
                    predecessor_blockers.append(
                        "runtime_session_replacement_predecessor_not_enabled"
                    )
                if (
                    predecessor["session_fingerprint"]
                    != requested["predecessor_session_fingerprint"]
                ):
                    predecessor_blockers.append(
                        "runtime_session_replacement_predecessor_identity_mismatch"
                    )
                if (
                    pause_state["status"] != "paused"
                    or pause_state["pause_event_id"] != requested["pause_event_id"]
                ):
                    predecessor_blockers.append(
                        "runtime_session_replacement_pause_identity_mismatch"
                    )
                if predecessor_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        predecessor_blockers,
                    )

                existing_session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ? OR reservation_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["reservation_id"]),
                ).fetchone()
                if existing_session is not None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_target_conflict"],
                    )

                old_reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (predecessor["reservation_id"],),
                ).fetchone()
                reservation = conn.execute(
                    """
                    SELECT * FROM controlled_session_budget_reservations
                    WHERE reservation_id = ?
                    LIMIT 1
                    """,
                    (requested["reservation_id"],),
                ).fetchone()
                if old_reservation is None or reservation is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_replacement_reservation_missing"],
                    )
                reservation_blockers: list[str] = []
                for field in (
                    "attestation_id",
                    "envelope_fingerprint",
                    "authorization_id",
                    "account_alias",
                    "strategy_id",
                    "requested_start_at",
                    "requested_expires_at",
                ):
                    if str(reservation[field] or "") != str(requested[field] or ""):
                        reservation_blockers.append(
                            f"runtime_session_replacement_reservation_{field}_mismatch"
                        )
                if reservation["status"] != "reserved":
                    reservation_blockers.append(
                        "runtime_session_replacement_reservation_not_reserved"
                    )
                for field in ("authorization_id", "account_alias", "strategy_id"):
                    if str(old_reservation[field] or "") != str(
                        reservation[field] or ""
                    ):
                        reservation_blockers.append(
                            f"runtime_session_replacement_scope_widened:{field}"
                        )
                for field in (
                    "reserved_gross_units",
                    "reserved_buy_units",
                    "reserved_turnover_units",
                    "reserved_order_count",
                ):
                    if int(reservation[field]) > int(old_reservation[field]):
                        reservation_blockers.append(
                            f"runtime_session_replacement_budget_widened:{field}"
                        )
                old_symbols = {
                    str(key): int(value)
                    for key, value in json_dict(
                        old_reservation["reserved_by_symbol_json"]
                    ).items()
                }
                replacement_symbols = {
                    str(key): int(value)
                    for key, value in json_dict(
                        reservation["reserved_by_symbol_json"]
                    ).items()
                }
                if not replacement_symbols or not set(replacement_symbols).issubset(
                    old_symbols
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_symbol_scope_widened"
                    )
                elif any(
                    value > old_symbols[symbol]
                    for symbol, value in replacement_symbols.items()
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_symbol_budget_widened"
                    )
                old_order_ids = set(json_list(predecessor["order_ids_json"]))
                if not set(requested["order_ids"]).issubset(old_order_ids):
                    reservation_blockers.append(
                        "runtime_session_replacement_order_scope_widened"
                    )
                if int(requested["max_order_rate_per_minute"]) > int(
                    predecessor["max_order_rate_per_minute"]
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_rate_widened"
                    )
                old_duration = int(predecessor["expires_at_epoch_ms"]) - int(
                    predecessor["effective_at_epoch_ms"]
                )
                new_duration = int(requested["expires_at_epoch_ms"]) - int(
                    requested["effective_at_epoch_ms"]
                )
                if new_duration <= 0 or new_duration > old_duration:
                    reservation_blockers.append(
                        "runtime_session_replacement_duration_widened"
                    )
                if int(requested["effective_at_epoch_ms"]) < int(
                    pause_state["paused_at_epoch_ms"]
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_starts_before_pause"
                    )
                now_epoch_ms = int(requested["reviewed_at_epoch_ms"])
                if not (
                    int(requested["effective_at_epoch_ms"])
                    <= now_epoch_ms
                    < int(requested["expires_at_epoch_ms"])
                ):
                    reservation_blockers.append(
                        "runtime_session_replacement_window_not_current"
                    )
                if reservation_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        reservation_blockers,
                    )

                snapshots = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id IN (?, ?)
                    ORDER BY observed_at_epoch_ms ASC, id ASC
                    """,
                    tuple(requested["recovery_snapshot_ids"]),
                ).fetchall()
                snapshot_blockers: list[str] = []
                if len(snapshots) != 2:
                    snapshot_blockers.append(
                        "runtime_session_replacement_recovery_snapshots_missing"
                    )
                else:
                    for snapshot in snapshots:
                        if (
                            snapshot["session_id"]
                            != requested["predecessor_session_id"]
                            or snapshot["status"] != "clear"
                            or json_list(snapshot["blockers_json"])
                        ):
                            snapshot_blockers.append(
                                "runtime_session_replacement_recovery_snapshot_not_clear"
                            )
                    first_ms = int(snapshots[0]["observed_at_epoch_ms"])
                    last_ms = int(snapshots[-1]["observed_at_epoch_ms"])
                    latest_snapshot = conn.execute(
                        """
                        SELECT * FROM controlled_session_gate_snapshots
                        WHERE session_id = ? AND observed_at_epoch_ms > ?
                        ORDER BY observed_at_epoch_ms DESC, id DESC
                        LIMIT 1
                        """,
                        (
                            requested["predecessor_session_id"],
                            int(pause_state["paused_at_epoch_ms"]),
                        ),
                    ).fetchone()
                    if (
                        latest_snapshot is None
                        or latest_snapshot["snapshot_id"]
                        != snapshots[-1]["snapshot_id"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_snapshot_superseded"
                        )
                    blocked_during_recovery = conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM controlled_session_gate_snapshots
                        WHERE session_id = ?
                          AND observed_at_epoch_ms >= ?
                          AND observed_at_epoch_ms <= ?
                          AND status != 'clear'
                        """,
                        (
                            requested["predecessor_session_id"],
                            first_ms,
                            now_epoch_ms,
                        ),
                    ).fetchone()
                    if int(blocked_during_recovery["count"] or 0) > 0:
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_interrupted"
                        )
                    if first_ms <= int(pause_state["paused_at_epoch_ms"]):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_not_post_pause"
                        )
                    if last_ms - first_ms < int(
                        requested["minimum_recovery_stability_ms"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_not_stable"
                        )
                    if last_ms > now_epoch_ms or now_epoch_ms - last_ms > int(
                        requested["maximum_snapshot_age_ms"]
                    ):
                        snapshot_blockers.append(
                            "runtime_session_replacement_recovery_snapshot_stale"
                        )
                if snapshot_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        snapshot_blockers,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_revocation_events (
                        revocation_id, revocation_fingerprint, session_id,
                        session_fingerprint, reason_code, operator_id,
                        operator_approval_id, revoked_at_epoch_ms, revoked_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["retirement_revocation_id"],
                        requested["retirement_revocation_fingerprint"],
                        requested["predecessor_session_id"],
                        requested["predecessor_session_fingerprint"],
                        "signed_replacement_after_pause_review",
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        now_epoch_ms,
                        requested["reviewed_at"],
                        _serialize_event_payload_json(requested["retirement_payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE controlled_session_runtime_sessions
                    SET status = 'revoked', updated_at = ?
                    WHERE session_id = ? AND status = 'enabled'
                    """,
                    (requested["created_at"], requested["predecessor_session_id"]),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_sessions (
                        session_id, session_fingerprint, issuance_fingerprint,
                        reservation_id, attestation_id, envelope_fingerprint,
                        authorization_id, account_alias, strategy_id,
                        operator_id, operator_approval_id, order_ids_json,
                        effective_at_epoch_ms, expires_at_epoch_ms,
                        effective_at, expires_at, max_order_rate_per_minute,
                        token_salt, token_hash, status, payload_json, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["issuance_fingerprint"],
                        requested["reservation_id"],
                        requested["attestation_id"],
                        requested["envelope_fingerprint"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        _serialize_event_payload_json(requested["order_ids"]),
                        int(requested["effective_at_epoch_ms"]),
                        int(requested["expires_at_epoch_ms"]),
                        requested["requested_start_at"],
                        requested["requested_expires_at"],
                        int(requested["max_order_rate_per_minute"]),
                        requested["token_salt"],
                        requested["token_hash"],
                        "enabled",
                        _serialize_event_payload_json(requested["session_payload"]),
                        requested["created_at"],
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_replacement_events (
                        replacement_id, replacement_fingerprint,
                        predecessor_session_id, predecessor_session_fingerprint,
                        pause_event_id, recovery_snapshot_ids_json,
                        replacement_session_id, replacement_session_fingerprint,
                        replacement_reservation_id, operator_id,
                        operator_approval_id, reviewed_at_epoch_ms, reviewed_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["replacement_id"],
                        requested["replacement_fingerprint"],
                        requested["predecessor_session_id"],
                        requested["predecessor_session_fingerprint"],
                        requested["pause_event_id"],
                        _serialize_event_payload_json(
                            requested["recovery_snapshot_ids"]
                        ),
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        now_epoch_ms,
                        requested["reviewed_at"],
                        _serialize_event_payload_json(requested["replacement_payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_replacement_events
                    WHERE replacement_id = ?
                    LIMIT 1
                    """,
                    (requested["replacement_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "enabled",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                    "replacement": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_replacement_transaction_unavailable"],
                )

    def revoke_controlled_session_sync(
        self,
        *,
        revocation: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist an operator-signed one-way session revocation."""
        requested = dict(revocation)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_not_found"],
                    )
                if session["session_fingerprint"] != requested["session_fingerprint"]:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_revocation_identity_mismatch"],
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_revocation_events
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session["status"] == "revoked":
                    if (
                        existing is None
                        or existing["revocation_id"] != requested["revocation_id"]
                        or existing["revocation_fingerprint"]
                        != requested["revocation_fingerprint"]
                        or existing["reason_code"] != requested["reason_code"]
                    ):
                        conn.rollback()
                        return controlled_session_authority_rejection(
                            requested,
                            ["runtime_session_revocation_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": "revoked",
                        "blockers": [],
                        "reused": True,
                        "session": dict(session),
                        "revocation": dict(existing) if existing is not None else {},
                    }
                if session["status"] != "enabled":
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_not_enabled"],
                    )
                conn.execute(
                    """
                    INSERT INTO controlled_session_revocation_events (
                        revocation_id, revocation_fingerprint, session_id,
                        session_fingerprint, reason_code, operator_id,
                        operator_approval_id, revoked_at_epoch_ms, revoked_at,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["revocation_id"],
                        requested["revocation_fingerprint"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reason_code"],
                        requested["operator_id"],
                        requested["operator_approval_id"],
                        int(requested["revoked_at_epoch_ms"]),
                        requested["revoked_at"],
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    UPDATE controlled_session_runtime_sessions
                    SET status = 'revoked', updated_at = ?
                    WHERE session_id = ? AND status = 'enabled'
                    """,
                    (requested["created_at"], requested["session_id"]),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_revocation_events
                    WHERE revocation_id = ?
                    LIMIT 1
                    """,
                    (requested["revocation_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "revoked",
                    "blockers": [],
                    "reused": False,
                    "session": dict(saved) if saved is not None else {},
                    "revocation": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_authority_rejection(
                    requested,
                    ["runtime_session_revocation_transaction_unavailable"],
                )

    def get_controlled_session_runtime_session_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read one runtime session including private hash fields for verification."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_sessions
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_runtime_sessions_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List runtime sessions without interpreting current authority."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_sessions
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def find_enabled_paused_controlled_session_sync(
        self,
        *,
        authorization_id: str,
        account_alias: str,
        strategy_id: str,
        now_epoch_ms: int,
    ) -> dict[str, Any] | None:
        """Find active paused authority that requires signed replacement review."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT s.*, rs.pause_event_id, rs.paused_at_epoch_ms, rs.paused_at
                FROM controlled_session_runtime_sessions s
                JOIN controlled_session_runtime_states rs
                  ON rs.session_id = s.session_id
                WHERE s.authorization_id = ?
                  AND s.account_alias = ?
                  AND s.strategy_id = ?
                  AND s.status = 'enabled'
                  AND rs.status = 'paused'
                  AND s.expires_at_epoch_ms > ?
                ORDER BY rs.paused_at_epoch_ms DESC, s.id DESC
                LIMIT 1
                """,
                (
                    authorization_id,
                    account_alias,
                    strategy_id,
                    int(now_epoch_ms),
                ),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_replacements_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable signed replacement evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_replacement_events
                ORDER BY reviewed_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_replacement_for_predecessor_sync(
        self,
        predecessor_session_id: str,
    ) -> dict[str, Any] | None:
        """Read immutable replacement evidence for one retired predecessor."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_replacement_events
                WHERE predecessor_session_id = ?
                LIMIT 1
                """,
                (predecessor_session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_revocations_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable signed revocation evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_revocation_events
                ORDER BY revoked_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_controlled_session_gate_snapshot_sync(
        self,
        *,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one sanitized runtime-gate observation idempotently."""
        requested = dict(snapshot)
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if session is None:
                    conn.rollback()
                    return controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_not_found"],
                    )
                if session["session_fingerprint"] != requested["session_fingerprint"]:
                    conn.rollback()
                    return controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_identity_mismatch"],
                    )
                if session["status"] != "enabled":
                    conn.rollback()
                    return controlled_session_gate_snapshot_rejection(
                        requested,
                        ["live_gate_session_not_enabled"],
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id = ?
                    LIMIT 1
                    """,
                    (requested["snapshot_id"],),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["snapshot_fingerprint"]
                        != requested["snapshot_fingerprint"]
                        or existing["session_id"] != requested["session_id"]
                    ):
                        conn.rollback()
                        return controlled_session_gate_snapshot_rejection(
                            requested,
                            ["live_gate_snapshot_identity_conflict"],
                        )
                    conn.commit()
                    return {
                        "status": str(existing["status"]),
                        "blockers": [],
                        "reused": True,
                        "snapshot": dict(existing),
                    }
                conn.execute(
                    """
                    INSERT INTO controlled_session_gate_snapshots (
                        snapshot_id, snapshot_fingerprint, session_id,
                        session_fingerprint, source_fingerprint,
                        observed_at_epoch_ms, observed_at, status,
                        gate_snapshot_json, source_evidence_json,
                        blockers_json, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["snapshot_id"],
                        requested["snapshot_fingerprint"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["source_fingerprint"],
                        int(requested["observed_at_epoch_ms"]),
                        requested["observed_at"],
                        requested["status"],
                        _serialize_event_payload_json(requested["gate_snapshot"]),
                        _serialize_event_payload_json(requested["source_evidence"]),
                        _serialize_event_payload_json(requested["blockers"]),
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE snapshot_id = ?
                    LIMIT 1
                    """,
                    (requested["snapshot_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": requested["status"],
                    "blockers": [],
                    "reused": False,
                    "snapshot": dict(saved) if saved is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_gate_snapshot_rejection(
                    requested,
                    ["live_gate_snapshot_transaction_unavailable"],
                )

    def latest_controlled_session_gate_snapshot_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read the newest persisted gate snapshot for one session."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                WHERE session_id = ?
                ORDER BY observed_at_epoch_ms DESC, id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_gate_snapshots_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List sanitized runtime-gate snapshots newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                ORDER BY observed_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_controlled_session_gate_snapshots_for_session_sync(
        self,
        *,
        session_id: str,
        since_epoch_ms: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List one session's persisted gate snapshots oldest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_gate_snapshots
                WHERE session_id = ? AND observed_at_epoch_ms >= ?
                ORDER BY observed_at_epoch_ms ASC, id ASC
                LIMIT ?
                """,
                (
                    session_id,
                    max(0, int(since_epoch_ms)),
                    max(1, min(int(limit), 500)),
                ),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_controlled_session_runtime_metrics_sync(
        self,
        *,
        session_id: str,
        window_start_epoch_ms: int,
        observed_at_epoch_ms: int,
    ) -> dict[str, Any]:
        """Read admission counters and the exact reserved order capacity."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    s.session_id,
                    s.reservation_id,
                    s.max_order_rate_per_minute,
                    r.reserved_order_count,
                    COUNT(a.id) AS admitted_total,
                    SUM(
                        CASE
                            WHEN a.admitted_at_epoch_ms > ?
                             AND a.admitted_at_epoch_ms <= ?
                            THEN 1 ELSE 0
                        END
                    ) AS admitted_in_window,
                    MAX(a.admitted_at_epoch_ms) AS latest_admitted_at_epoch_ms
                FROM controlled_session_runtime_sessions s
                LEFT JOIN controlled_session_budget_reservations r
                  ON r.reservation_id = s.reservation_id
                LEFT JOIN controlled_session_rate_admissions a
                  ON a.session_id = s.session_id
                WHERE s.session_id = ?
                GROUP BY s.session_id, s.reservation_id,
                         s.max_order_rate_per_minute, r.reserved_order_count
                """,
                (
                    int(window_start_epoch_ms),
                    int(observed_at_epoch_ms),
                    session_id,
                ),
            ).fetchone()
            return dict(row) if row is not None else {}

    def admit_controlled_session_order_sync(
        self,
        *,
        admission: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically admit one order under fresh gates and a shared rate window."""
        requested = dict(admission)
        try:
            now_epoch_ms = int(requested["admitted_at_epoch_ms"])
            requested_rate = int(requested["max_order_rate_per_minute"])
            gate_snapshot_max_age_ms = (
                int(requested["gate_snapshot_max_age_seconds"]) * 1000
            )
        except (KeyError, TypeError, ValueError):
            return controlled_session_rate_admission_rejection(
                requested,
                ["runtime_rate_admission_input_invalid"],
            )
        if (
            now_epoch_ms < 0
            or requested_rate <= 0
            or gate_snapshot_max_age_ms <= 0
            or gate_snapshot_max_age_ms > 60_000
        ):
            return controlled_session_rate_admission_rejection(
                requested,
                ["runtime_rate_admission_limit_invalid"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                runtime_session = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_sessions
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                session_blockers: list[str] = []
                if runtime_session is None:
                    session_blockers.append("runtime_session_persistent_state_missing")
                else:
                    if runtime_session["status"] != "enabled":
                        session_blockers.append("runtime_session_not_enabled")
                    if (
                        runtime_session["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        session_blockers.append("runtime_session_fingerprint_changed")
                    if runtime_session["reservation_id"] != requested["reservation_id"]:
                        session_blockers.append("runtime_session_reservation_changed")
                    if int(runtime_session["effective_at_epoch_ms"]) > now_epoch_ms:
                        session_blockers.append("runtime_session_not_yet_effective")
                    if int(runtime_session["expires_at_epoch_ms"]) <= now_epoch_ms:
                        session_blockers.append("runtime_session_expired")
                if session_blockers:
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        session_blockers,
                    )
                pause_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if pause_state is not None and pause_state["status"] == "paused":
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        ["runtime_session_paused"],
                        pause_event_id=str(pause_state["pause_event_id"] or ""),
                    )
                latest_gate_snapshot = conn.execute(
                    """
                    SELECT * FROM controlled_session_gate_snapshots
                    WHERE session_id = ?
                    ORDER BY observed_at_epoch_ms DESC, id DESC
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                gate_blockers: list[str] = []
                if latest_gate_snapshot is None:
                    gate_blockers.append("runtime_live_gate_snapshot_missing")
                else:
                    if latest_gate_snapshot["status"] != "clear":
                        gate_blockers.append("runtime_live_gate_snapshot_not_clear")
                    if (
                        latest_gate_snapshot["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        gate_blockers.append(
                            "runtime_live_gate_snapshot_session_identity_changed"
                        )
                    if (
                        latest_gate_snapshot["snapshot_id"]
                        != requested["gate_snapshot_id"]
                        or latest_gate_snapshot["snapshot_fingerprint"]
                        != requested["gate_snapshot_fingerprint"]
                        or latest_gate_snapshot["observed_at"]
                        != requested["gate_snapshot_observed_at"]
                    ):
                        gate_blockers.append(
                            "runtime_live_gate_snapshot_changed_before_admission"
                        )
                    gate_observed_at_epoch_ms = int(
                        latest_gate_snapshot["observed_at_epoch_ms"]
                    )
                    if gate_observed_at_epoch_ms > now_epoch_ms:
                        gate_blockers.append("runtime_live_gate_snapshot_in_future")
                    elif now_epoch_ms - gate_observed_at_epoch_ms > (
                        gate_snapshot_max_age_ms
                    ):
                        gate_blockers.append("runtime_live_gate_snapshot_stale")
                if gate_blockers:
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        gate_blockers,
                    )
                existing = conn.execute(
                    """
                    SELECT * FROM controlled_session_rate_admissions
                    WHERE admission_id = ?
                    LIMIT 1
                    """,
                    (requested["admission_id"],),
                ).fetchone()
                if existing is not None:
                    conn.commit()
                    return {
                        "status": "admitted",
                        "blockers": [],
                        "reused": True,
                        "admission": dict(existing),
                    }
                order_conflict = conn.execute(
                    """
                    SELECT admission_id FROM controlled_session_rate_admissions
                    WHERE session_id = ? AND order_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["order_id"]),
                ).fetchone()
                request_conflict = conn.execute(
                    """
                    SELECT admission_id FROM controlled_session_rate_admissions
                    WHERE session_id = ? AND request_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"], requested["request_id"]),
                ).fetchone()
                conflict_blockers: list[str] = []
                if order_conflict is not None:
                    conflict_blockers.append("runtime_rate_order_already_admitted")
                if request_conflict is not None:
                    conflict_blockers.append("runtime_rate_request_id_reused")
                if conflict_blockers:
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        conflict_blockers,
                    )

                window_start_epoch_ms = now_epoch_ms - 60_000
                window = conn.execute(
                    """
                    SELECT
                        COUNT(*) AS admitted_count,
                        MIN(max_order_rate_per_minute) AS minimum_rate
                    FROM controlled_session_rate_admissions
                    WHERE authorization_id = ?
                      AND account_alias = ?
                      AND admitted_at_epoch_ms > ?
                      AND admitted_at_epoch_ms <= ?
                    """,
                    (
                        requested["authorization_id"],
                        requested["account_alias"],
                        window_start_epoch_ms,
                        now_epoch_ms,
                    ),
                ).fetchone()
                admitted_before = int(window["admitted_count"] or 0)
                effective_rate = min(
                    requested_rate,
                    int(window["minimum_rate"] or requested_rate),
                )
                if admitted_before >= effective_rate:
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        ["runtime_order_rate_limit_reached"],
                        admitted_before=admitted_before,
                        admitted_after=admitted_before,
                        effective_rate=effective_rate,
                    )

                conn.execute(
                    """
                    INSERT INTO controlled_session_rate_admissions (
                        admission_id, session_id, session_fingerprint,
                        reservation_id, authorization_id, account_alias,
                        strategy_id, order_id, request_id,
                        max_order_rate_per_minute, admitted_at_epoch_ms,
                        admitted_at, status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["admission_id"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["authorization_id"],
                        requested["account_alias"],
                        requested["strategy_id"],
                        requested["order_id"],
                        requested["request_id"],
                        requested_rate,
                        now_epoch_ms,
                        requested["admitted_at"],
                        "admitted",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                saved = conn.execute(
                    """
                    SELECT * FROM controlled_session_rate_admissions
                    WHERE admission_id = ?
                    LIMIT 1
                    """,
                    (requested["admission_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "admitted",
                    "blockers": [],
                    "reused": False,
                    "admission": dict(saved) if saved is not None else {},
                    "admitted_before": admitted_before,
                    "admitted_after": admitted_before + 1,
                    "effective_rate": effective_rate,
                    "window_start_epoch_ms": window_start_epoch_ms,
                }
            except (sqlite3.IntegrityError, sqlite3.OperationalError, KeyError):
                conn.rollback()
                return controlled_session_rate_admission_rejection(
                    requested,
                    ["runtime_rate_admission_transaction_unavailable"],
                )

    def list_controlled_session_rate_admissions_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable runtime rate-admission evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_rate_admissions
                ORDER BY admitted_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def pause_controlled_session_sync(
        self,
        *,
        pause: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist the first automatic pause; no automatic resume path exists."""
        requested = dict(pause)
        reasons = [str(item) for item in requested.get("reasons") or [] if str(item)]
        if not reasons:
            return controlled_session_pause_rejection(
                requested,
                ["automatic_pause_reason_missing"],
            )
        with sqlite3.connect(self._path, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            try:
                conn.execute("BEGIN IMMEDIATE")
                existing_state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                if existing_state is not None:
                    if (
                        existing_state["session_fingerprint"]
                        != requested["session_fingerprint"]
                    ):
                        conn.rollback()
                        return controlled_session_pause_rejection(
                            requested,
                            ["automatic_pause_session_identity_conflict"],
                        )
                    existing_event = conn.execute(
                        """
                        SELECT * FROM controlled_session_pause_events
                        WHERE pause_event_id = ?
                        LIMIT 1
                        """,
                        (existing_state["pause_event_id"],),
                    ).fetchone()
                    conn.commit()
                    return {
                        "status": "paused",
                        "blockers": [],
                        "reused": True,
                        "state": dict(existing_state),
                        "event": (
                            dict(existing_event) if existing_event is not None else {}
                        ),
                    }

                conn.execute(
                    """
                    INSERT INTO controlled_session_pause_events (
                        pause_event_id, session_id, session_fingerprint,
                        reservation_id, gate_fingerprint, reason_fingerprint,
                        reasons_json, gate_snapshot_json, paused_at_epoch_ms,
                        paused_at, status, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["pause_event_id"],
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        requested["gate_fingerprint"],
                        requested["reason_fingerprint"],
                        _serialize_event_payload_json(reasons),
                        _serialize_event_payload_json(requested["gate_snapshot"]),
                        int(requested["paused_at_epoch_ms"]),
                        requested["paused_at"],
                        "paused",
                        _serialize_event_payload_json(requested["payload"]),
                        requested["created_at"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO controlled_session_runtime_states (
                        session_id, session_fingerprint, reservation_id,
                        status, pause_event_id, reason_fingerprint,
                        reasons_json, paused_at_epoch_ms, paused_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        requested["session_id"],
                        requested["session_fingerprint"],
                        requested["reservation_id"],
                        "paused",
                        requested["pause_event_id"],
                        requested["reason_fingerprint"],
                        _serialize_event_payload_json(reasons),
                        int(requested["paused_at_epoch_ms"]),
                        requested["paused_at"],
                        requested["created_at"],
                    ),
                )
                state = conn.execute(
                    """
                    SELECT * FROM controlled_session_runtime_states
                    WHERE session_id = ?
                    LIMIT 1
                    """,
                    (requested["session_id"],),
                ).fetchone()
                event = conn.execute(
                    """
                    SELECT * FROM controlled_session_pause_events
                    WHERE pause_event_id = ?
                    LIMIT 1
                    """,
                    (requested["pause_event_id"],),
                ).fetchone()
                conn.commit()
                return {
                    "status": "paused",
                    "blockers": [],
                    "reused": False,
                    "state": dict(state) if state is not None else {},
                    "event": dict(event) if event is not None else {},
                }
            except (
                sqlite3.IntegrityError,
                sqlite3.OperationalError,
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()
                return controlled_session_pause_rejection(
                    requested,
                    ["automatic_pause_transaction_unavailable"],
                )

    def get_controlled_session_runtime_state_sync(
        self,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Read the durable pause state for one session."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_runtime_states
                WHERE session_id = ?
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_controlled_session_pause_event_sync(
        self,
        pause_event_id: str,
    ) -> dict[str, Any] | None:
        """Read one immutable automatic-pause event by fingerprint."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM controlled_session_pause_events
                WHERE pause_event_id = ?
                LIMIT 1
                """,
                (pause_event_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_controlled_session_pause_events_sync(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List immutable automatic-pause evidence newest first."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM controlled_session_pause_events
                ORDER BY paused_at_epoch_ms DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
            return [dict(row) for row in rows]
