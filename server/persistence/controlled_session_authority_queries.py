"""Controlled session persistence capability: controlled_session_authority_queries."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.persistence.controlled_session_access import (
    ControlledSessionRepositoryAccess,
)


class ControlledSessionAuthorityQueryRepositoryMixin(ControlledSessionRepositoryAccess):
    """Cohesive SQLite capability mixed into the aggregate repository."""

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
