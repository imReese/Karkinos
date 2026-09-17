"""Shared SQLite connection policy for the market metadata store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

META_SQLITE_BUSY_TIMEOUT_MS = 2_000


def connect_meta_sqlite(
    database_path: str | Path,
    *,
    readonly: bool = False,
    timeout: float = 2,
) -> sqlite3.Connection:
    """Open ``meta.db`` with one deterministic durability policy."""

    path = Path(database_path)
    if readonly:
        resolved = path.expanduser().absolute()
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro",
            uri=True,
            timeout=timeout,
        )
        connection.execute(f"PRAGMA busy_timeout={META_SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA query_only=ON")
        return connection

    connection = sqlite3.connect(path, timeout=timeout)
    connection.execute(f"PRAGMA busy_timeout={META_SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


__all__ = ["META_SQLITE_BUSY_TIMEOUT_MS", "connect_meta_sqlite"]
