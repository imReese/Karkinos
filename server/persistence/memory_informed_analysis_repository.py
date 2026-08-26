"""Read repository for offline memory-informed fixture analysis."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from server.contracts.memory_informed_analysis import MemoryInformedAnalysisRecord


class MemoryInformedAnalysisRepositoryMixin:
    """Own read-only projections and the SQLite connection lifecycle."""

    _path: Path
    _record_from_row: Callable[[sqlite3.Row], MemoryInformedAnalysisRecord]

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

    def _get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MemoryInformedAnalysisRecord | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return self._record_from_row(row) if row is not None else None

    def _get(self, analysis_id: str) -> MemoryInformedAnalysisRecord:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"memory-informed analysis not found: {analysis_id}")
        return self._record_from_row(row)

    def _list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[MemoryInformedAnalysisRecord, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "ORDER BY created_at DESC, analysis_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(self._record_from_row(row) for row in rows)
