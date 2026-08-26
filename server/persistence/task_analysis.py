"""SQLite persistence for deterministic fixture task analysis mappings."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict

TASK_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_research_task_analyses (
    analysis_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    fixture_contract_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_research_task_analyses_task
ON ai_research_task_analyses(task_id, created_at DESC);
"""


class ResearchTaskAnalysisPersistenceMixin:
    """Own task-analysis mapping persistence behind the stable façade."""

    _path: Path
    _fixture_contract_version: str

    @staticmethod
    def _analysis_from_row(row: Any) -> Any:
        raise NotImplementedError

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(TASK_ANALYSIS_SCHEMA)

    def create_or_get(
        self,
        request: Any,
        *,
        workflow_id: str,
        context_snapshot_id: str,
        context_fingerprint: str,
        created_at: str,
    ) -> tuple[Any, bool]:
        analysis_identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "context_fingerprint": context_fingerprint,
        }
        analysis_id = f"ai-task-analysis-{content_fingerprint(analysis_identity)[:24]}"
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_research_task_analyses WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_fingerprint"]) != request.fingerprint
                    or str(existing["workflow_id"]) != workflow_id
                ):
                    raise IdempotencyConflict(
                        "fixture analysis idempotency key was reused with different input"
                    )
                return self._analysis_from_row(existing), True
            conn.execute(
                """
                INSERT INTO ai_research_task_analyses (
                    analysis_id, task_id, idempotency_key, request_json,
                    request_fingerprint, requested_by, workflow_id,
                    context_snapshot_id, context_fingerprint,
                    fixture_contract_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    request.task_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.requested_by,
                    workflow_id,
                    context_snapshot_id,
                    context_fingerprint,
                    self._fixture_contract_version,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_research_task_analyses WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("fixture analysis mapping persistence failed")
        return self._analysis_from_row(row), False

    def get(self, analysis_id: str) -> Any:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_research_task_analyses WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"fixture analysis not found: {analysis_id}")
        return self._analysis_from_row(row)

    def list(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> tuple[Any, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis list limit must be between 1 and 200")
        sql = "SELECT * FROM ai_research_task_analyses"
        params: list[object] = []
        if task_id is not None:
            sql += " WHERE task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at DESC, analysis_id DESC LIMIT ?"
        params.append(limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(self._analysis_from_row(row) for row in rows)
