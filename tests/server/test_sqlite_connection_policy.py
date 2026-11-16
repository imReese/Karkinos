"""SQLite lifecycle connection policy contracts."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from server.persistence.connection import (
    SQLITE_BUSY_TIMEOUT_MS,
    assert_foreign_key_integrity,
    assert_sqlite_write_baseline,
    connect_sqlite,
    immediate_transaction,
    retry_on_locked,
    run_immediate_transaction,
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


def test_write_connection_can_attach_readonly_market_evidence(tmp_path):
    from server.persistence.valuation_publication_recovery import (
        attach_recovery_market_database,
    )

    market = tmp_path / "market #1.db"
    with closing(connect_sqlite(market)) as conn:
        conn.execute("CREATE TABLE facts(value TEXT)")
        conn.execute("INSERT INTO facts VALUES ('original')")
        conn.commit()

    app = tmp_path / "app %23.db"
    with closing(connect_sqlite(app, uri_attachments=True)) as conn:
        attach_recovery_market_database(conn, market)
        conn.execute("CREATE TABLE audit(value TEXT)")
        conn.execute("INSERT INTO audit SELECT value FROM market_meta.facts")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM market_meta.facts")
        conn.commit()

    with closing(connect_sqlite(app, readonly=True)) as conn:
        assert conn.execute("SELECT value FROM audit").fetchall() == [("original",)]


def test_write_baseline_detects_weakened_connection():
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(RuntimeError, match="sqlite_write_baseline_mismatch"):
            assert_sqlite_write_baseline(conn, require_wal=False)


def test_foreign_key_integrity_detects_existing_violation(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path, foreign_keys=False)) as conn:
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO child(parent_id) VALUES (99)")
        conn.commit()
        with pytest.raises(RuntimeError, match="sqlite_foreign_key_check_failed"):
            assert_foreign_key_integrity(conn)


def test_foreign_key_integrity_accepts_valid_rows(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path)) as conn:
        conn.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
        conn.execute("INSERT INTO parent(id) VALUES (1)")
        conn.execute("INSERT INTO child(parent_id) VALUES (1)")
        assert_foreign_key_integrity(conn)


def test_immediate_transaction_commits_and_rolls_back(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path)) as conn:
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, balance REAL)")

        with immediate_transaction(conn):
            conn.execute("INSERT INTO accounts VALUES (1, 100.0)")

        # Verify committed
        row = conn.execute("SELECT balance FROM accounts WHERE id = 1").fetchone()
        assert row[0] == 100.0

        # Verify rollback on exception
        with pytest.raises(ValueError, match="fail_test"):
            with immediate_transaction(conn):
                conn.execute("INSERT INTO accounts VALUES (2, 200.0)")
                raise ValueError("fail_test")

        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_retry_on_locked_retries_transient_lock_and_succeeds():
    attempts = 0

    @retry_on_locked(max_retries=3, initial_delay_sec=0.01)
    def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        return "success"

    assert flaky_operation() == "success"
    assert attempts == 3


def test_retry_on_locked_fails_when_exhausted():
    attempts = 0

    @retry_on_locked(max_retries=2, initial_delay_sec=0.01)
    def always_locked():
        nonlocal attempts
        attempts += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        always_locked()
    assert attempts == 2


def test_connect_sqlite_supports_uri_and_uri_strings(tmp_path):
    path = tmp_path / "app.db"
    with closing(connect_sqlite(path)) as conn:
        conn.execute("CREATE TABLE items (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'alpha')")
        conn.commit()

    # Connect with standard uri=True parameter on file path
    with closing(connect_sqlite(path, uri=True)) as conn:
        assert conn.execute("SELECT name FROM items").fetchone() == ("alpha",)

    # Connect with pre-constructed file URI string and uri=True
    uri_string = f"{path.resolve().as_uri()}?mode=ro"
    with closing(connect_sqlite(uri_string, uri=True)) as conn:
        assert conn.execute("SELECT name FROM items").fetchone() == ("alpha",)
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)

    # Connect with pre-constructed file URI string and uri_attachments=True
    with closing(connect_sqlite(uri_string, uri_attachments=True)) as conn:
        assert conn.execute("SELECT name FROM items").fetchone() == ("alpha",)
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)

    # Connect with readonly=True on URI string
    with closing(connect_sqlite(path.resolve().as_uri(), readonly=True)) as conn:
        assert conn.execute("SELECT name FROM items").fetchone() == ("alpha",)
        assert conn.execute("PRAGMA query_only").fetchone() == (1,)

    # In-memory URI connection
    with closing(connect_sqlite(":memory:", uri=True)) as conn:
        conn.execute("CREATE TABLE mem (val INT)")
        conn.execute("INSERT INTO mem VALUES (42)")
        assert conn.execute("SELECT val FROM mem").fetchone() == (42,)
