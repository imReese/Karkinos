"""Deterministic tests for checkpointed current-quote reconciliation."""

from __future__ import annotations

import sqlite3

import pytest

from server.db import AppDatabase
from server.persistence.financial_fact_event_payloads import quote_instant_storage_key
from server.persistence.quote_current_materialization import (
    advance_quote_snapshot_checkpoint_on_connection,
    assert_quote_current_materialization_on_connection,
    current_quote_revision_on_connection,
    increment_quote_current_revision_on_connection,
)

pytestmark = pytest.mark.unit


def _insert_snapshot(
    conn: sqlite3.Connection,
    *,
    symbol: str = "600001",
    asset_class: str = "stock",
    price: float,
    timestamp: str,
    quote_status: str = "live",
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO quote_snapshots (
            symbol, asset_class, price, volume, timestamp, created_at,
            quote_status, quote_instant_utc
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            symbol,
            asset_class,
            price,
            timestamp,
            "2026-08-28T00:00:00+00:00",
            quote_status,
            quote_instant_storage_key(timestamp),
        ),
    )
    return int(cursor.lastrowid or 0)


def test_initialization_creates_an_empty_complete_materialization(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        state = assert_quote_current_materialization_on_connection(conn)
        indexes = {str(row[0]) for row in conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'quote_snapshots'
                """).fetchall()}
    assert state.snapshot_cutoff_id == 0
    assert state.revision == 0
    assert "idx_quote_snapshots_symbol_instant" in indexes
    assert "uq_quote_snapshots_fetch_run_identity" in indexes


def test_startup_reconciliation_ignores_superseded_conflict(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        _insert_snapshot(
            conn,
            price=10.0,
            timestamp="2026-08-27T15:00:00+08:00",
        )
        _insert_snapshot(
            conn,
            price=10.1,
            timestamp="2026-08-27T07:00:00Z",
        )
        newest_id = _insert_snapshot(
            conn,
            price=10.2,
            timestamp="2026-08-28T15:00:00+08:00",
        )
        conn.commit()

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        row = conn.execute(
            "SELECT price, quote_timestamp FROM latest_quotes"
        ).fetchone()
        state = assert_quote_current_materialization_on_connection(conn)
    assert row == (10.2, "2026-08-28T15:00:00+08:00")
    assert state.snapshot_cutoff_id == newest_id
    assert state.revision == 1


def test_startup_reconciliation_rejects_only_current_instant_conflict(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        first_id = _insert_snapshot(
            conn,
            price=10.0,
            timestamp="2026-08-28T15:00:00+08:00",
        )
        _insert_snapshot(
            conn,
            price=10.1,
            timestamp="2026-08-28T07:00:00Z",
        )
        conn.commit()

    with pytest.raises(ValueError, match="conflict at the newest timestamp"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        state = conn.execute("""
            SELECT snapshot_cutoff_id, revision
            FROM quote_current_materialization_state
            WHERE singleton_id = 1
            """).fetchone()
        latest_count = conn.execute("SELECT COUNT(*) FROM latest_quotes").fetchone()
        audit_head = conn.execute("SELECT MAX(id) FROM quote_snapshots").fetchone()[0]
    assert state == (0, 0)
    assert first_id < audit_head
    assert latest_count == (0,)


def test_index_reconciliation_advances_cutoff_without_account_revision(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        snapshot_id = _insert_snapshot(
            conn,
            symbol="000001.SH",
            asset_class="index",
            price=3300.0,
            timestamp="2026-08-28T15:00:00+08:00",
        )
        conn.commit()

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        state = assert_quote_current_materialization_on_connection(conn)
        latest = conn.execute(
            "SELECT price FROM latest_quotes WHERE asset_type = 'index'"
        ).fetchone()
    assert state.snapshot_cutoff_id == snapshot_id
    assert state.revision == 0
    assert latest == (3300.0,)


def test_checkpoint_and_latest_only_revision_helpers_are_strict(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        snapshot_id = _insert_snapshot(
            conn,
            price=10.0,
            timestamp="2026-08-28T15:00:00+08:00",
        )
        with pytest.raises(RuntimeError, match="does not cover audit history"):
            current_quote_revision_on_connection(conn)
        state = advance_quote_snapshot_checkpoint_on_connection(
            conn,
            snapshot_id=snapshot_id,
            current_changed=True,
            updated_at="2026-08-28T07:00:01+00:00",
        )
        assert state.snapshot_cutoff_id == snapshot_id
        assert state.revision == 1
        state = increment_quote_current_revision_on_connection(
            conn,
            updated_at="2026-08-28T07:00:02+00:00",
        )
        assert state.snapshot_cutoff_id == snapshot_id
        assert state.revision == 2
