"""Controlled session persistence capability: controlled_session_gate_snapshots."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_gate_snapshot_rejection,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionGateSnapshotRepositoryMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
