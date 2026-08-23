"""Deterministic contracts for the versioned SQLite schema ledger."""

from __future__ import annotations

import sqlite3

import pytest

from server import db as db_module
from server.db import AppDatabase
from server.persistence import migrations
from server.persistence.migrations import (
    CURRENT_SCHEMA_VERSION,
    V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM,
)

pytestmark = pytest.mark.unit


def test_database_initialization_records_one_idempotent_schema_version(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")

    database.init_sync()
    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        rows = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == CURRENT_SCHEMA_VERSION
    assert rows[0][1] == "v0.3.0_legacy_schema_baseline"
    assert len(rows[0][2]) == 64


def test_legacy_database_without_ledger_upgrades_and_preserves_data(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    with sqlite3.connect(database.path) as conn:
        db_module._initialize_v1_baseline_schema(conn)
        conn.execute("""
            INSERT INTO watchlist_assets (
                symbol, asset_class, display_name, source, created_at, updated_at
            ) VALUES ('600000.SH', 'stock', '浦发银行', 'manual', 'before', 'before')
            """)
        conn.commit()

    database.init_sync()
    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        row = conn.execute(
            "SELECT symbol, display_name FROM watchlist_assets"
        ).fetchone()
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert row == ("600000.SH", "浦发银行")
    assert versions == [(CURRENT_SCHEMA_VERSION,)]


def test_v1_schema_contract_checksum_is_frozen() -> None:
    with sqlite3.connect(":memory:") as conn:
        db_module._initialize_v1_baseline_schema(conn)
        contract = migrations._read_schema_contract(conn)

    assert migrations._schema_contract_checksum(contract) == (
        V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM
    )
    assert migrations._MIGRATIONS[0].schema_contract_checksum == (
        V1_BASELINE_SCHEMA_CONTRACT_CHECKSUM
    )


def test_v1_database_missing_core_table_fails_before_repair(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute("DROP TABLE watchlist_assets")
        conn.commit()

    with pytest.raises(RuntimeError, match="missing table watchlist_assets"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'watchlist_assets'"
            ).fetchone()
            is None
        )


def test_v1_database_empty_migration_history_fails_before_repair(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute("DELETE FROM schema_migrations")
        conn.execute("DROP TABLE watchlist_assets")
        conn.commit()

    with pytest.raises(RuntimeError, match="history is unexpectedly empty"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        assert conn.execute("SELECT * FROM schema_migrations").fetchall() == []
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'watchlist_assets'"
            ).fetchone()
            is None
        )


def test_v1_database_missing_explicit_index_fails_before_repair(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute("DROP INDEX idx_signals_timestamp")
        conn.commit()

    with pytest.raises(RuntimeError, match="index idx_signals_timestamp"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'idx_signals_timestamp'"
            ).fetchone()
            is None
        )


def test_v1_database_weakened_column_fails_before_repair(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.executescript("""
            ALTER TABLE watchlist_assets RENAME TO watchlist_assets_old;
            CREATE TABLE watchlist_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                asset_class TEXT NOT NULL DEFAULT 'stock',
                display_name TEXT NOT NULL,
                source TEXT DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(symbol)
            );
            INSERT INTO watchlist_assets SELECT * FROM watchlist_assets_old;
            DROP TABLE watchlist_assets_old;
            CREATE INDEX idx_watchlist_assets_symbol ON watchlist_assets(symbol);
            CREATE INDEX idx_watchlist_assets_asset_class
            ON watchlist_assets(asset_class);
            """)
        conn.commit()

    with pytest.raises(RuntimeError, match=r"column watchlist_assets\.source"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        source_column = next(
            row
            for row in conn.execute("PRAGMA table_xinfo(watchlist_assets)")
            if row[1] == "source"
        )
    assert source_column[3] == 0


def test_v1_database_missing_unique_constraint_fails_before_repair(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.executescript("""
            ALTER TABLE watchlist_assets RENAME TO watchlist_assets_old;
            CREATE TABLE watchlist_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                asset_class TEXT NOT NULL DEFAULT 'stock',
                display_name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO watchlist_assets SELECT * FROM watchlist_assets_old;
            DROP TABLE watchlist_assets_old;
            CREATE INDEX idx_watchlist_assets_symbol ON watchlist_assets(symbol);
            CREATE INDEX idx_watchlist_assets_asset_class
            ON watchlist_assets(asset_class);
            """)
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=r"unique constraint watchlist_assets\(symbol\)",
    ):
        database.init_sync()


def test_app_database_default_path_uses_runtime_data_directory(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))

    assert AppDatabase().path == tmp_path / "app.db"


def test_v1_database_allows_additive_service_owned_schema(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.executescript("""
            ALTER TABLE signals ADD COLUMN service_note TEXT;
            CREATE TABLE service_owned_artifacts (
                id INTEGER PRIMARY KEY,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_service_owned_artifacts_payload
            ON service_owned_artifacts(payload_json);
            CREATE INDEX idx_signals_service_note ON signals(service_note);
            """)
        conn.commit()

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'service_owned_artifacts'"
        ).fetchone() == (1,)


def test_database_initialization_fails_closed_on_unknown_schema_version(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (CURRENT_SCHEMA_VERSION + 1, "future", "unknown", "2026-08-23T00:00:00Z"),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="newer than this Karkinos build"):
        database.init_sync()


def test_database_initialization_fails_closed_on_changed_migration_history(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = ?",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="history mismatch"):
        database.init_sync()


def test_migration_ledger_rejects_non_prefix_history(monkeypatch, tmp_path) -> None:
    first = migrations.SchemaMigration(version=1, name="first")
    second = migrations.SchemaMigration(version=2, name="second")
    monkeypatch.setattr(migrations, "_MIGRATIONS", (first, second))
    database_path = tmp_path / "app.db"
    with sqlite3.connect(database_path) as conn:
        conn.execute(migrations._MIGRATION_TABLE_SQL)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (second.version, second.name, second.checksum, "2026-08-23T00:00:00Z"),
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="ordered registry prefix"):
            migrations.apply_schema_migrations(conn)

        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert versions == [(2,)]


@pytest.mark.parametrize(
    "table_sql",
    [
        """
        CREATE TABLE schema_migrations (
            version INTEGER,
            name TEXT,
            checksum TEXT,
            applied_at TEXT
        )
        """,
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY CHECK(version > 0),
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """,
    ],
)
def test_database_initialization_fails_closed_on_damaged_migration_table(
    tmp_path,
    table_sql,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    with sqlite3.connect(database.path) as conn:
        conn.execute(table_sql)
        conn.commit()

    with pytest.raises(
        RuntimeError, match="schema_migrations table structure mismatch"
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        signals_table = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'signals'
            """).fetchone()
    assert signals_table is None
