"""Controlled session persistence capability: controlled_session_replacement_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.automatic_trading import timestamp_epoch_ms
from server.persistence.automatic_trading_session_binding import (
    AutomaticTradingSessionBindingUnavailable,
    automatic_trading_session_reuse_blockers,
    bind_session_payload_to_automatic_trading_control,
)
from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_authority_rejection,
)
from server.persistence.database_normalization import json_dict, json_list
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


def _replacement_validation_blockers(
    conn: sqlite3.Connection,
    requested: dict[str, Any],
) -> tuple[int, list[str]]:
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
        return 0, ["runtime_session_replacement_paused_predecessor_missing"]

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
        return 0, predecessor_blockers

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
        return 0, ["runtime_session_replacement_target_conflict"]

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
        return 0, ["runtime_session_replacement_reservation_missing"]

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
        if str(old_reservation[field] or "") != str(reservation[field] or ""):
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
        for key, value in json_dict(old_reservation["reserved_by_symbol_json"]).items()
    }
    replacement_symbols = {
        str(key): int(value)
        for key, value in json_dict(reservation["reserved_by_symbol_json"]).items()
    }
    if not replacement_symbols or not set(replacement_symbols).issubset(old_symbols):
        reservation_blockers.append("runtime_session_replacement_symbol_scope_widened")
    elif any(
        value > old_symbols[symbol] for symbol, value in replacement_symbols.items()
    ):
        reservation_blockers.append("runtime_session_replacement_symbol_budget_widened")
    old_order_ids = set(json_list(predecessor["order_ids_json"]))
    if not set(requested["order_ids"]).issubset(old_order_ids):
        reservation_blockers.append("runtime_session_replacement_order_scope_widened")
    if int(requested["max_order_rate_per_minute"]) > int(
        predecessor["max_order_rate_per_minute"]
    ):
        reservation_blockers.append("runtime_session_replacement_rate_widened")
    old_duration = int(predecessor["expires_at_epoch_ms"]) - int(
        predecessor["effective_at_epoch_ms"]
    )
    new_duration = int(requested["expires_at_epoch_ms"]) - int(
        requested["effective_at_epoch_ms"]
    )
    if new_duration <= 0 or new_duration > old_duration:
        reservation_blockers.append("runtime_session_replacement_duration_widened")
    if int(requested["effective_at_epoch_ms"]) < int(pause_state["paused_at_epoch_ms"]):
        reservation_blockers.append("runtime_session_replacement_starts_before_pause")
    now_epoch_ms = int(requested["reviewed_at_epoch_ms"])
    if not (
        int(requested["effective_at_epoch_ms"])
        <= now_epoch_ms
        < int(requested["expires_at_epoch_ms"])
    ):
        reservation_blockers.append("runtime_session_replacement_window_not_current")
    if reservation_blockers:
        return now_epoch_ms, reservation_blockers

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
                snapshot["session_id"] != requested["predecessor_session_id"]
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
            or latest_snapshot["snapshot_id"] != snapshots[-1]["snapshot_id"]
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
            snapshot_blockers.append("runtime_session_replacement_recovery_interrupted")
        if first_ms <= int(pause_state["paused_at_epoch_ms"]):
            snapshot_blockers.append(
                "runtime_session_replacement_recovery_not_post_pause"
            )
        if last_ms - first_ms < int(requested["minimum_recovery_stability_ms"]):
            snapshot_blockers.append("runtime_session_replacement_recovery_not_stable")
        if last_ms > now_epoch_ms or now_epoch_ms - last_ms > int(
            requested["maximum_snapshot_age_ms"]
        ):
            snapshot_blockers.append(
                "runtime_session_replacement_recovery_snapshot_stale"
            )
    return now_epoch_ms, snapshot_blockers


class ControlledSessionReplacementUnitOfWorkMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
                        created_at_epoch_ms = timestamp_epoch_ms(
                            requested.get("created_at")
                        )
                        if created_at_epoch_ms is None:
                            conn.rollback()
                            return controlled_session_authority_rejection(
                                requested,
                                ["runtime_session_created_at_invalid"],
                            )
                        reuse_blockers = automatic_trading_session_reuse_blockers(
                            conn,
                            session_payload=(
                                existing_session["payload_json"]
                                if existing_session is not None
                                else None
                            ),
                            observed_at_epoch_ms=created_at_epoch_ms,
                        )
                        if reuse_blockers:
                            conn.rollback()
                            return controlled_session_authority_rejection(
                                requested,
                                reuse_blockers,
                            )
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

                now_epoch_ms, validation_blockers = _replacement_validation_blockers(
                    conn,
                    requested,
                )
                if validation_blockers:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        validation_blockers,
                    )
                created_at_epoch_ms = timestamp_epoch_ms(requested.get("created_at"))
                if created_at_epoch_ms is None:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_created_at_invalid"],
                    )
                try:
                    session_payload = bind_session_payload_to_automatic_trading_control(
                        conn,
                        payload=dict(requested["session_payload"]),
                        observed_at_epoch_ms=created_at_epoch_ms,
                    )
                except AutomaticTradingSessionBindingUnavailable:
                    conn.rollback()
                    return controlled_session_authority_rejection(
                        requested,
                        ["runtime_session_automatic_trading_not_enabled"],
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
                        _serialize_event_payload_json(session_payload),
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
