"""Controlled session persistence capability: controlled_session_pause_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_pause_rejection,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionPauseUnitOfWorkMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
