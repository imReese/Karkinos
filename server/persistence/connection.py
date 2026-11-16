"""Shared SQLite connection policy and repository identity."""

from __future__ import annotations

import random
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, tzinfo
from functools import wraps
from pathlib import Path
from typing import Any, Protocol

SQLITE_BUSY_TIMEOUT_MS = 5_000


class DateTimeNow(Protocol):
    def __call__(self, tz: tzinfo | None = None) -> datetime: ...


def _system_now(tz: tzinfo | None = None) -> datetime:
    return datetime.now(tz)


def connect_sqlite(
    database_path: str | Path,
    *,
    readonly: bool = False,
    uri: bool = False,
    uri_attachments: bool = False,
    timeout: float = 5.0,
    factory: type[sqlite3.Connection] = sqlite3.Connection,
    foreign_keys: bool = True,
) -> sqlite3.Connection:
    """Open one SQLite connection with Karkinos' lifecycle safety baseline."""

    is_uri_str = isinstance(database_path, str) and database_path.startswith("file:")
    is_readonly = readonly or (
        isinstance(database_path, str)
        and database_path.startswith("file:")
        and "mode=ro" in database_path
    )

    if is_readonly:
        if isinstance(database_path, str) and database_path.startswith("file:"):
            readonly_target = database_path
            if "mode=ro" not in readonly_target:
                readonly_target += ("&" if "?" in readonly_target else "?") + "mode=ro"
        else:
            path = Path(database_path).expanduser().resolve()
            readonly_target = path.as_uri() + "?mode=ro"
        conn = sqlite3.connect(
            readonly_target,
            uri=True,
            timeout=timeout,
            factory=factory,
        )
        conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only=ON")
        return conn

    # ATTACH inherits URI handling from this open. Keep the primary filename
    # literal, including SQLite's in-memory and temporary database names.
    use_uri = uri or uri_attachments or is_uri_str
    write_target: str | Path
    if use_uri:
        if database_path in ("", ":memory:"):
            write_target = database_path
        elif isinstance(database_path, str) and database_path.startswith("file:"):
            write_target = database_path
        else:
            write_target = Path(database_path).expanduser().resolve().as_uri()
    else:
        write_target = database_path

    conn = sqlite3.connect(write_target, uri=use_uri, timeout=timeout, factory=factory)
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


def retry_on_locked(
    max_retries: int = 5,
    initial_delay_sec: float = 0.05,
    max_delay_sec: float = 1.0,
    backoff_factor: float = 2.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Retry a transaction-level operation if SQLite raises database is locked/busy."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay_sec
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as exc:
                    err_msg = str(exc).lower()
                    if (
                        "database is locked" in err_msg
                        or "database table is locked" in err_msg
                    ) and attempt < max_retries - 1:
                        jittered_delay = delay * random.uniform(0.5, 1.5)
                        time.sleep(min(jittered_delay, max_delay_sec))
                        delay = min(delay * backoff_factor, max_delay_sec)
                        continue
                    raise
            return None

        return wrapper

    return decorator


@contextmanager
def immediate_transaction(conn: sqlite3.Connection):
    """Context manager executing write operations inside BEGIN IMMEDIATE.

    Acquires reserved write lock immediately, preventing mid-transaction deadlocks.
    """

    if conn.in_transaction:
        raise RuntimeError("write operation requires its own immediate transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def run_immediate_transaction(
    conn: sqlite3.Connection,
    operation: Callable[[], Any],
    *,
    retries: int = 5,
) -> Any:
    """Run one caller-supplied operation in its own immediate transaction with retries."""

    @retry_on_locked(max_retries=retries)
    def _execute() -> Any:
        with immediate_transaction(conn):
            return operation()

    return _execute()


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
