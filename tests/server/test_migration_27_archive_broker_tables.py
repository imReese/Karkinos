"""Tests for Migration 27: Archive and drop deprecated broker tables."""

from __future__ import annotations

import sqlite3

from server.persistence.migration_27_archive_broker_tables import (
    DEPRECATED_BROKER_TABLES,
    V27_STATEMENTS,
    archive_deprecated_broker_tables,
    drop_deprecated_broker_tables,
    get_deprecated_broker_tables_status,
    revert_archived_broker_tables,
    verify_archived_broker_tables,
)


def _setup_test_db(conn: sqlite3.Connection) -> None:
    for table in DEPRECATED_BROKER_TABLES:
        conn.execute(
            f'CREATE TABLE "{table}" ('
            "id INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "created_at TEXT NOT NULL"
            ");"
        )
        conn.execute(f'CREATE INDEX "idx_{table}_created" ON "{table}"(created_at);')


def test_archive_status_detection() -> None:
    conn = sqlite3.connect(":memory:")
    _setup_test_db(conn)

    status = get_deprecated_broker_tables_status(conn)
    assert all(s == "active" for s in status.values())
    assert set(status.keys()) == set(DEPRECATED_BROKER_TABLES)


def test_archive_and_verification_cycle() -> None:
    conn = sqlite3.connect(":memory:")
    _setup_test_db(conn)

    # Archive
    actions = archive_deprecated_broker_tables(conn)
    assert all(a == "renamed_to_deprecated" for a in actions.values())

    status = get_deprecated_broker_tables_status(conn)
    assert all(s == "archived" for s in status.values())

    # Idempotent re-run
    actions2 = archive_deprecated_broker_tables(conn)
    assert all(a == "already_archived" for a in actions2.values())

    # Verify
    report = verify_archived_broker_tables(conn)
    assert report["ready_for_drop"] is True
    assert report["integrity_ok"] is True
    assert report["foreign_keys_ok"] is True
    assert len(report["active_leaks"]) == 0
    assert len(report["archived_details"]) == len(DEPRECATED_BROKER_TABLES)


def test_revert_cycle() -> None:
    conn = sqlite3.connect(":memory:")
    _setup_test_db(conn)

    archive_deprecated_broker_tables(conn)
    assert all(
        s == "archived" for s in get_deprecated_broker_tables_status(conn).values()
    )

    revert_actions = revert_archived_broker_tables(conn)
    assert all(a == "reverted_to_original" for a in revert_actions.values())
    assert all(
        s == "active" for s in get_deprecated_broker_tables_status(conn).values()
    )


def test_physical_drop_cycle() -> None:
    conn = sqlite3.connect(":memory:")
    _setup_test_db(conn)

    archive_deprecated_broker_tables(conn)
    drop_actions = drop_deprecated_broker_tables(conn)
    assert all(a == "dropped" for a in drop_actions.values())

    status = get_deprecated_broker_tables_status(conn)
    assert all(s == "dropped" for s in status.values())

    # Re-run drop is idempotent
    drop_actions2 = drop_deprecated_broker_tables(conn)
    assert all(a == "already_absent" for a in drop_actions2.values())

    # Master check
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    remaining_tables = [r[0] for r in cur.fetchall()]
    for t in DEPRECATED_BROKER_TABLES:
        assert t not in remaining_tables
        assert f"_deprecated_{t}" not in remaining_tables


def test_v27_statements_execution() -> None:
    conn = sqlite3.connect(":memory:")
    _setup_test_db(conn)

    for stmt in V27_STATEMENTS:
        conn.execute(stmt)

    status = get_deprecated_broker_tables_status(conn)
    assert all(s == "archived" for s in status.values())
