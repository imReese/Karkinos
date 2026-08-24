"""SQLite adapter for explicit AI context capture lifecycle records."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

CONTEXT_CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_context_capture_runs (
    capture_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    context_snapshot_id TEXT,
    evidence_reference_ids_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_context_capture_runs_status
ON ai_context_capture_runs(status, updated_at DESC);
"""


class ContextCaptureSqliteRepository:
    """Own connections and SQL for ``ai_context_capture_runs``."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(CONTEXT_CAPTURE_SCHEMA)

    def create_or_get(
        self,
        *,
        capture_id: str,
        idempotency_key: str,
        request_json: str,
        request_fingerprint: str,
        status: str,
        created_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO ai_context_capture_runs (
                    capture_id, idempotency_key, request_json,
                    request_fingerprint, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    idempotency_key,
                    request_json,
                    request_fingerprint,
                    status,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return (dict(row) if row is not None else None), cursor.rowcount == 0

    def get(self, capture_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def update(
        self,
        *,
        capture_id: str,
        status: str,
        context_snapshot_id: str | None,
        evidence_reference_ids_json: str,
        failure_code: str | None,
        updated_at: str,
        preserve_status: str | None,
    ) -> tuple[dict[str, Any] | None, bool]:
        with self.connection() as conn:
            completed_guard = " AND status != ?" if preserve_status else ""
            params: list[Any] = [
                status,
                context_snapshot_id,
                evidence_reference_ids_json,
                failure_code,
                updated_at,
                capture_id,
            ]
            if preserve_status:
                params.append(preserve_status)
            cursor = conn.execute(
                f"""
                UPDATE ai_context_capture_runs
                SET status = ?, context_snapshot_id = ?,
                    evidence_reference_ids_json = ?, failure_code = ?,
                    updated_at = ?
                WHERE capture_id = ?{completed_guard}
                """,
                params,
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        return (dict(row) if row is not None else None), cursor.rowcount == 1
