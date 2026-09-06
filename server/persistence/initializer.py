"""SQLite schema initialization owned by the persistence layer."""

from __future__ import annotations

import fcntl
import logging
import math
import os
import sqlite3
import stat
import time
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.persistence.market_identity_migrations import (
    migrate_legacy_daily_closes_on_connection,
)
from server.persistence.migrations import (
    apply_schema_migrations,
    assert_schema_compatible,
)
from server.persistence.quote_current_materialization import (
    reconcile_quote_current_materialization_on_connection,
)
from server.persistence.schema_v1 import initialize_v1_baseline_schema

logger = logging.getLogger(__name__)


@contextmanager
def _initialization_lock(database_path: Path, timeout_seconds: float):
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("database_initialization_timeout_invalid")
    lock_path = database_path.with_name(database_path.name + ".initialize.lock")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    started = time.monotonic()
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("database_initialization_lock_invalid")
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    owner = (
                        os.pread(descriptor, 64, 0)
                        .decode("ascii", errors="replace")
                        .strip()
                    )
                    raise TimeoutError(
                        f"database_initialization_lock_timeout (owner_pid={owner or 'unknown'})"
                    ) from None
                time.sleep(min(0.05, remaining))
        current = lock_path.lstat()
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("database_initialization_lock_changed")
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        logger.info(
            "Database initialization lock acquired: pid=%d waited=%.3fs",
            os.getpid(),
            time.monotonic() - started,
        )
        yield
    finally:
        # Closing also releases ownership on failure; stale PID text is diagnostic.
        # Never unlink: a waiter may already hold a descriptor for this inode.
        os.close(descriptor)


def initialize_database(
    database_path: str | Path, *, lock_timeout_seconds: float = 30
) -> None:
    """Serialize schema initialization; preserve existing migration transactions."""
    path = Path(database_path).expanduser().resolve()
    with _initialization_lock(path, lock_timeout_seconds):
        with closing(sqlite3.connect(path, timeout=2)) as conn, conn:
            identity = path.stat()
            logger.info(
                "Database initialization started: pid=%d connection=%x dev=%d inode=%d",
                os.getpid(),
                id(conn),
                identity.st_dev,
                identity.st_ino,
            )
            _initialize_on_connection(conn, path)


def _initialize_on_connection(conn: sqlite3.Connection, database_path: Path) -> None:
    phase = "compatibility"
    started = time.monotonic()
    try:
        conn.execute("PRAGMA busy_timeout=2000")
        assert_schema_compatible(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        phase = "journal_mode"
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        if journal_mode and str(journal_mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        phase = "baseline"
        initialize_v1_baseline_schema(conn)
        phase = "migrations"
        apply_schema_migrations(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        phase = "quote_instants"
        _backfill_quote_snapshot_instants(conn)
        phase = "market_identity"
        if _table_exists(conn, "daily_close_snapshots_v2"):
            migrate_legacy_daily_closes_on_connection(
                conn,
                meta_database_path=database_path.parent / "meta.db",
            )
        phase = "quote_materialization"
        if _table_exists(conn, "quote_current_materialization_state"):
            reconcile_quote_current_materialization_on_connection(
                conn,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        conn.commit()
    except BaseException as exc:
        logger.exception(
            "Database initialization failed: pid=%d connection=%x phase=%s "
            "in_transaction=%s elapsed=%.3fs sqlite_errorcode=%s",
            os.getpid(),
            id(conn),
            phase,
            conn.in_transaction,
            time.monotonic() - started,
            getattr(exc, "sqlite_errorcode", None),
        )
        raise


def _backfill_quote_snapshot_instants(conn: sqlite3.Connection) -> None:
    """Populate the indexed canonical instant for legacy or direct quote rows."""

    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(quote_snapshots)")
    }
    if "quote_instant_utc" not in columns:
        return
    rows = conn.execute("""
        SELECT id, timestamp
        FROM quote_snapshots
        WHERE quote_instant_utc IS NULL
        ORDER BY id
        """).fetchall()
    conn.executemany(
        """
        UPDATE quote_snapshots
        SET quote_instant_utc = ?
        WHERE id = ? AND quote_instant_utc IS NULL
        """,
        ((quote_instant_storage_key(row[1]), int(row[0])) for row in rows),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        is not None
    )
