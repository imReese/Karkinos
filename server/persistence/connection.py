"""Shared SQLite connection policy and repository identity."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Any, Protocol

SQLITE_BUSY_TIMEOUT_MS = 2_000


class DateTimeNow(Protocol):
    def __call__(self, tz: tzinfo | None = None) -> datetime: ...


def _system_now(tz: tzinfo | None = None) -> datetime:
    return datetime.now(tz)


def connect_sqlite(
    database_path: str | Path,
    *,
    readonly: bool = False,
    timeout: float = 2,
    factory: type[sqlite3.Connection] = sqlite3.Connection,
    foreign_keys: bool = True,
) -> sqlite3.Connection:
    """Open one SQLite connection with Karkinos' lifecycle safety baseline."""

    if readonly:
        path = Path(database_path).expanduser().absolute()
        conn = sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
            timeout=timeout,
            factory=factory,
        )
        conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only=ON")
        return conn

    conn = sqlite3.connect(database_path, timeout=timeout, factory=factory)
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def sqlite_runtime_profile(conn: sqlite3.Connection) -> dict[str, object]:
    """Return effective settings used for diagnostics and startup verification."""

    return {
        "sqlite_version": sqlite3.sqlite_version,
        "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
        "synchronous": int(conn.execute("PRAGMA synchronous").fetchone()[0]),
        "foreign_keys": int(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
        "busy_timeout_ms": int(conn.execute("PRAGMA busy_timeout").fetchone()[0]),
        "fullfsync": int(conn.execute("PRAGMA fullfsync").fetchone()[0]),
    }


def assert_sqlite_write_baseline(
    conn: sqlite3.Connection,
    *,
    require_wal: bool = True,
    require_foreign_keys: bool = True,
) -> dict[str, object]:
    """Fail closed when a lifecycle write connection is weaker than expected."""

    profile = sqlite_runtime_profile(conn)
    expected = {
        "synchronous": 2,  # SQLITE_SYNC_FULL
        "busy_timeout_ms": SQLITE_BUSY_TIMEOUT_MS,
    }
    if require_foreign_keys:
        expected["foreign_keys"] = 1
    mismatches = [
        f"{key}={profile[key]!r}"
        for key, value in expected.items()
        if profile[key] != value
    ]
    if require_wal and profile["journal_mode"] != "wal":
        mismatches.append(f"journal_mode={profile['journal_mode']!r}")
    if mismatches:
        raise RuntimeError("sqlite_write_baseline_mismatch: " + ", ".join(mismatches))
    return profile


def assert_foreign_key_integrity(conn: sqlite3.Connection) -> None:
    """Fail closed when committed rows would violate declared foreign keys."""

    violations = conn.execute("PRAGMA foreign_key_check").fetchmany(20)
    if violations:
        details = ", ".join(
            f"{row[0]}:rowid={row[1]}:parent={row[2]}:fk={row[3]}" for row in violations
        )
        raise RuntimeError("sqlite_foreign_key_check_failed: " + details)


def run_immediate_transaction(
    conn: sqlite3.Connection,
    operation,
):
    """Run one caller-supplied operation in its own immediate transaction."""

    if conn.in_transaction:
        raise RuntimeError("schema operation requires its own write transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = operation()
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


class SQLiteRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        now: DateTimeNow | None = None,
    ) -> None:
        self._path = Path(database_path)
        self._now = now or _system_now

    @property
    def path(self) -> Path:
        """Expose the repository's immutable SQLite identity to composition code."""

        return self._path
