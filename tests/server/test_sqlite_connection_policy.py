"""SQLite lifecycle connection policy contracts."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from server.persistence.connection import (
    SQLITE_BUSY_TIMEOUT_MS,
    assert_sqlite_write_baseline,
    connect_sqlite,
    sqlite_runtime_profile,
)


def test_write_connection_uses_financial_lifecycle_baseline(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        profile = assert_sqlite_write_baseline(conn)

    assert profile["journal_mode"] == "wal"
    assert profile["synchronous"] == 2
    assert profile["foreign_keys"] == 1
    assert profile["busy_timeout_ms"] == SQLITE_BUSY_TIMEOUT_MS
    assert isinstance(profile["sqlite_version"], str)
    assert isinstance(profile["fullfsync"], int)


def test_readonly_connection_never_creates_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect_sqlite(path, readonly=True)
    assert not path.exists()


def test_readonly_connection_is_query_only(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path)) as conn:
        conn.execute("CREATE TABLE facts(value TEXT)")
        conn.commit()

    with closing(connect_sqlite(path, readonly=True)) as conn:
        assert sqlite_runtime_profile(conn)["busy_timeout_ms"] == SQLITE_BUSY_TIMEOUT_MS
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO facts VALUES ('blocked')")


def test_write_baseline_detects_weakened_connection():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(RuntimeError, match="sqlite_write_baseline_mismatch"):
            assert_sqlite_write_baseline(conn, require_wal=False)
