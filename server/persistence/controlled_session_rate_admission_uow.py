"""Controlled session persistence capability: controlled_session_rate_admission_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.contracts.automatic_trading import (
    resolve_persisted_automatic_trading_control,
    timestamp_epoch_ms,
)
from server.persistence.automatic_trading_session_binding import (
    automatic_trading_binding_from_session_payload,
    read_automatic_trading_control_in_transaction,
)
from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_rate_admission_rejection,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionRateAdmissionUnitOfWorkMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
            automatic_trading_revision = int(requested["automatic_trading_revision"])
            automatic_trading_control_fingerprint = str(
                requested["automatic_trading_control_fingerprint"]
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
            or automatic_trading_revision <= 0
            or len(automatic_trading_control_fingerprint) != 64
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
                automatic_control_value, _ = (
                    read_automatic_trading_control_in_transaction(
                        conn,
                        now_epoch_ms=now_epoch_ms,
                    )
                )
                automatic_trading = resolve_persisted_automatic_trading_control(
                    automatic_control_value,
                    now_epoch_ms=now_epoch_ms,
                    expected_revision=automatic_trading_revision,
                    expected_fingerprint=automatic_trading_control_fingerprint,
                )
                automatic_blockers = [
                    str(item) for item in automatic_trading.get("blockers") or []
                ]
                if (
                    automatic_trading.get("status") != "enabled"
                    or automatic_trading.get("enabled") is not True
                ):
                    if not automatic_blockers:
                        automatic_blockers.append(
                            "runtime_automatic_trading_not_enabled"
                        )
                session_binding = automatic_trading_binding_from_session_payload(
                    runtime_session["payload_json"]
                )
                if session_binding is None:
                    automatic_blockers.append(
                        "runtime_automatic_trading_session_binding_missing"
                    )
                else:
                    if session_binding["revision"] != automatic_trading.get("revision"):
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_binding_revision_mismatch"
                        )
                    if session_binding["control_fingerprint"] != automatic_trading.get(
                        "control_fingerprint"
                    ):
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_binding_fingerprint_mismatch"
                        )
                    if session_binding["status"] != "enabled":
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_binding_not_enabled"
                        )
                    if any(
                        session_binding[field] != automatic_trading.get(field)
                        for field in (
                            "last_disabled_at_epoch_ms",
                            "last_disabled_revision",
                            "last_disabled_control_identity",
                        )
                    ):
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_binding_lineage_mismatch"
                        )
                last_disabled_revision = automatic_trading.get("last_disabled_revision")
                last_disabled_at_epoch_ms = automatic_trading.get(
                    "last_disabled_at_epoch_ms"
                )
                if last_disabled_revision is not None:
                    session_created_at_epoch_ms = timestamp_epoch_ms(
                        runtime_session["created_at"]
                    )
                    if session_created_at_epoch_ms is None:
                        automatic_blockers.append(
                            "runtime_session_created_at_invalid_for_automatic_trading"
                        )
                    elif session_created_at_epoch_ms <= last_disabled_at_epoch_ms:
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_predates_last_disable"
                        )
                    if (
                        session_binding is not None
                        and session_binding["revision"] <= last_disabled_revision
                    ):
                        automatic_blockers.append(
                            "runtime_automatic_trading_session_predates_last_disable"
                        )
                if automatic_blockers:
                    conn.rollback()
                    return controlled_session_rate_admission_rejection(
                        requested,
                        automatic_blockers,
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
