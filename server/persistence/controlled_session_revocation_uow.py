"""Controlled session persistence capability: controlled_session_revocation_uow."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)
from server.persistence.controlled_session_rejections import (
    controlled_session_authority_rejection,
)
from server.persistence.event_log import (
    serialize_event_payload_json as _serialize_event_payload_json,
)


class ControlledSessionRevocationUnitOfWorkMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
