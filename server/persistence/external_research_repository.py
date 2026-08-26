"""SQLite connection ownership for external backtest research requests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .external_research_schema import EXTERNAL_BACKTEST_REPORT_SCHEMA


class ExternalBacktestReportRepository:
    """Own the connection boundary, schema initialization, and no workflow logic."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
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
        with self.connection() as conn:
            conn.executescript(EXTERNAL_BACKTEST_REPORT_SCHEMA)


__all__ = ["ExternalBacktestReportRepository"]
