"""Single-connection transaction boundary for AI strategy research storage."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from server.persistence.connection import connect_sqlite


class StrategyResearchUnitOfWorkMixin:
    @contextmanager
    def _connect(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect_sqlite(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if immediate:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _connect_readonly(self) -> Iterator[sqlite3.Connection]:
        if not self._path.exists():
            raise sqlite3.OperationalError("strategy research store is not initialized")
        conn = connect_sqlite(self._path, readonly=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
