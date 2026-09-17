"""Explicit SQLite preparation, separate from application lifespan."""

from __future__ import annotations

import fcntl
import logging
import math
import os
import sqlite3
import stat
import time
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from server.persistence.connection import (
    assert_sqlite_write_baseline,
    connect_sqlite,
)
from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.persistence.market_identity_migrations import (
    legacy_daily_close_reconciliation_needed_on_connection,
    migrate_legacy_daily_closes_on_connection,
)
from server.persistence.migration_lifecycle import (
    AtomicSchemaConnection,
    DatabasePreparationError,
    begin_preparation,
    finish_preparation,
    inspect_database,
    require_database_ready,
)
from server.persistence.migrations import (
    apply_schema_migrations,
    assert_schema_compatible,
)
from server.persistence.quote_current_materialization import (
    quote_current_materialization_needs_reconciliation_on_connection,
    reconcile_quote_current_materialization_on_connection,
)
from server.persistence.schema_v1 import initialize_v1_baseline_schema

logger = logging.getLogger(__name__)


@contextmanager
def _initialization_lock(
    database_path: Path,
    timeout_seconds: float,
    *,
    shared: bool = False,
):
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
                fcntl.flock(
                    descriptor,
                    (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB,
                )
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
                        "database_initialization_lock_timeout "
                        f"(owner_pid={owner or 'unknown'}); "
                        "stop API/worker processes before upgrading this database"
                    ) from None
                time.sleep(min(0.05, remaining))
        current = lock_path.lstat()
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("database_initialization_lock_changed")
        if not shared:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        logger.info(
            "Database %s lock acquired: pid=%d waited=%.3fs",
            "runtime" if shared else "initialization",
            os.getpid(),
            time.monotonic() - started,
        )
        yield
    finally:
        # Never unlink: waiters and managed runtime processes share this inode.
        os.close(descriptor)


@contextmanager
def database_runtime(database_path: str | Path):
    """Keep managed API/worker processes from racing a schema upgrade."""
    path = Path(database_path).expanduser().absolute()
    with _initialization_lock(path, 0, shared=True):
        require_database_ready(path)
        yield


def initialize_database(
    database_path: str | Path, *, lock_timeout_seconds: float = 30
) -> None:
    """Prepare once, with backup and provenance, before starting runtime writers.

    Schema-current databases remain read-only unless derived persistence is
    stale. Unknown migrations and changed history are rejected before writing.
    """
    if not math.isfinite(lock_timeout_seconds) or lock_timeout_seconds < 0:
        raise ValueError("database_initialization_timeout_invalid")
    path = Path(database_path).expanduser().absolute()
    status = inspect_database(path)
    if status.blocked:
        raise DatabasePreparationError(status)
    if status.state == "current" and not _database_requires_maintenance(path):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + lock_timeout_seconds
    with ExitStack() as ownership:
        while True:
            # Another preparer may have finished and already entered runtime.
            # Do not wait for an exclusive lock when no upgrade remains.
            status = inspect_database(path)
            if status.blocked:
                raise DatabasePreparationError(status)
            if status.state == "current" and not _database_requires_maintenance(path):
                return
            try:
                ownership.enter_context(_initialization_lock(path, 0))
                break
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        # Revalidate after acquiring exclusive ownership.
        status = inspect_database(path)
        if status.blocked:
            raise DatabasePreparationError(status)
        if status.state == "current" and not _database_requires_maintenance(path):
            return
        record_path, record = begin_preparation(status)
        logger.info("Preparing database %s; migration record: %s", path, record_path)
        try:
            with closing(
                # Frozen legacy schema repair predates FK enforcement and may
                # rebuild child tables before historical parent facts exist.
                # Keep preparation compatibility-scoped; ordinary write
                # connections use foreign_keys=ON by default.
                connect_sqlite(
                    path,
                    factory=AtomicSchemaConnection,
                    foreign_keys=False,
                ),
            ) as conn:
                _initialize_on_connection(conn, path)
        except BaseException:
            try:
                finish_preparation(record_path, record, succeeded=False)
            except OSError:
                logger.exception(
                    "Could not finalize failed migration record: %s",
                    record_path,
                )
            raise
        # A record-write failure after COMMIT is not a rolled-back migration.
        # Never restore or rerun blindly; inspect the authoritative schema ledger.
        try:
            finish_preparation(record_path, record, succeeded=True)
        except OSError:
            logger.exception(
                "Database committed; migration record needs reconciliation: %s",
                record_path,
            )
            raise RuntimeError(
                "database migration committed but provenance write failed: "
                f"{record_path}; "
                "inspect database status before retrying; do not restore automatically"
            ) from None


def _database_requires_maintenance(database_path: Path) -> bool:
    """Detect drift in rebuildable persisted projections without writing."""

    if not database_path.is_file():
        return False
    with closing(connect_sqlite(database_path, readonly=True)) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "quote_snapshots" in tables:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(quote_snapshots)")
            }
            if (
                "quote_instant_utc" in columns
                and conn.execute(
                    "SELECT 1 FROM quote_snapshots "
                    "WHERE quote_instant_utc IS NULL LIMIT 1"
                ).fetchone()
                is not None
            ):
                return True
        if (
            "quote_current_materialization_state" in tables
            and quote_current_materialization_needs_reconciliation_on_connection(conn)
        ):
            return True
        if {"daily_close_snapshots", "daily_close_snapshots_v2"}.issubset(tables):
            return legacy_daily_close_reconciliation_needed_on_connection(
                conn,
                meta_database_path=database_path.parent / "meta.db",
            )
    return False


def _initialize_on_connection(conn: sqlite3.Connection, database_path: Path) -> None:
    phase = "compatibility"
    started = time.monotonic()
    try:
        assert_schema_compatible(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        phase = "journal_mode"
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
        if journal_mode and str(journal_mode[0]).lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
        profile = assert_sqlite_write_baseline(conn, require_foreign_keys=False)
        logger.info("SQLite migration profile: %s", profile)
        conn.execute("BEGIN IMMEDIATE")
        # Recheck while holding SQLite's write reservation as well as the
        # managed-process lock. Migration SQL must not commit the outer unit.
        assert_schema_compatible(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        forbidden = {
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
        }
        conn.set_authorizer(
            lambda action, *_: (
                sqlite3.SQLITE_DENY if action in forbidden else sqlite3.SQLITE_OK
            )
        )
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
        phase = "verification"
        assert_schema_compatible(
            conn,
            baseline_initializer=initialize_v1_baseline_schema,
        )
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise RuntimeError("database_initialization_integrity_failed")
        conn.set_authorizer(None)
        conn.commit()
    except BaseException as exc:
        conn.set_authorizer(None)
        conn.rollback()
        logger.exception(
            "Database initialization failed: pid=%d connection=%x phase=%s "
            "elapsed=%.3fs sqlite_errorcode=%s",
            os.getpid(),
            id(conn),
            phase,
            time.monotonic() - started,
            getattr(exc, "sqlite_errorcode", None),
        )
        raise


def _backfill_quote_snapshot_instants(conn: sqlite3.Connection) -> None:
    """Populate the indexed canonical instant during explicit preparation."""
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
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone()
        is not None
    )
