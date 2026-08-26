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

FROZEN_V1_MIGRATION_NAME = "v0.3.0_legacy_schema_baseline"
FROZEN_V1_MIGRATION_CHECKSUM = (
    "0fc8b607a73a51af5822a76a6f9e3e91630287316617450ce6ccb25a0b674ef4"
)
FROZEN_MIGRATION_MANIFEST = (
    (1, "v0.3.0_legacy_schema_baseline", FROZEN_V1_MIGRATION_CHECKSUM),
    (
        2,
        "canonicalize_legacy_portfolio_trades",
        "375e7439dfe4517a361e5831eb8dc4472884861c17b78bb3f1e886f209edf462",
    ),
    (
        3,
        "canonicalize_portfolio_cash_flows_and_bind_fund_nav_evidence",
        "343ac4bdf3930235f3ff91df8d704dcb060bd8da5edb499a993eac1d3fe8b5fd",
    ),
    (
        4,
        "claim_operator_ledger_mutations",
        "a8320b7b4f26e935fb8859e7255170874267b6f6a0b306a5108ab2b794f90914",
    ),
    (
        5,
        "claim_atomic_order_state_commands",
        "1d85347c9e34afdafec2243075755bc9c836996ced09e3bd0f62c537e0b82055",
    ),
    (
        6,
        "claim_atomic_portfolio_mutations",
        "fdc3015daac5a942078af3145f5fa175d73b9fbde0f635eb809fffe93ccdcd4d",
    ),
    (
        7,
        "bind_market_calendar_official_evidence",
        "dc29822e72edc15f8c2388800b96b4841cc2f9b97d59be7a23a246064f1321bb",
    ),
    (
        8,
        "stage_quote_ingestion_items",
        "2b5c9280194dca0b531938c3cbdc436f2ec765f294ab3cebe686be449a977346",
    ),
)


def _create_frozen_v1_database(database: AppDatabase) -> None:
    with sqlite3.connect(database.path) as conn:
        db_module._initialize_v1_baseline_schema(conn)
        conn.execute(migrations._MIGRATION_TABLE_SQL)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (1, ?, ?, ?)
            """,
            (
                FROZEN_V1_MIGRATION_NAME,
                FROZEN_V1_MIGRATION_CHECKSUM,
                "2026-08-23T00:00:00+00:00",
            ),
        )
        conn.commit()


def test_database_initialization_records_idempotent_schema_versions(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")

    database.init_sync()
    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        rows = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert rows == [
        (migration.version, migration.name, migration.checksum)
        for migration in migrations._MIGRATIONS
    ]


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
    assert versions == [(migration.version,) for migration in migrations._MIGRATIONS]


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
    assert migrations._MIGRATIONS[0].checksum == FROZEN_V1_MIGRATION_CHECKSUM


def test_published_migration_manifest_is_append_only() -> None:
    actual = tuple(
        (migration.version, migration.name, migration.checksum)
        for migration in migrations._MIGRATIONS[: len(FROZEN_MIGRATION_MANIFEST)]
    )

    assert actual == FROZEN_MIGRATION_MANIFEST


def test_frozen_v1_ledger_upgrades_through_quote_ingestion_migration(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute("""
            INSERT INTO watchlist_assets (
                symbol, asset_class, display_name, source, created_at, updated_at
            ) VALUES ('600000.SH', 'stock', '浦发银行', 'manual', 'before', 'before')
            """)
        conn.commit()

    database.init_sync()
    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        asset = conn.execute(
            "SELECT symbol, display_name FROM watchlist_assets"
        ).fetchone()
        migrations_applied = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        quote_table = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'quote_ingestion_items'
            """).fetchone()
        quote_index = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_quote_ingestion_items_run'
            """).fetchone()

    assert asset == ("600000.SH", "浦发银行")
    assert migrations_applied == [
        (migration.version, migration.name, migration.checksum)
        for migration in migrations._MIGRATIONS
    ]
    assert migrations_applied[0] == (
        1,
        FROZEN_V1_MIGRATION_NAME,
        FROZEN_V1_MIGRATION_CHECKSUM,
    )
    assert quote_table == (1,)
    assert quote_index == (1,)


def test_migration_rejects_legacy_positive_infinity_cash_flow(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO cash_flows (
                timestamp, amount, flow_type, note, created_at
            ) VALUES (?, ?, 'deposit', 'invalid legacy row', ?)
            """,
            ("2026-08-26T10:00:00+08:00", float("inf"), "2026-08-26T10:00:00+08:00"),
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="legacy portfolio cash flow cannot be canonicalized safely",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        ledger_rows = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()
    assert versions == [(1,), (2,)]
    assert ledger_rows == (0,)


@pytest.mark.parametrize(
    ("quantity", "price", "commission"),
    [
        (float("inf"), 1.0, 0.0),
        (1.0, float("inf"), 0.0),
        (1.0, 1.0, float("inf")),
        (1.0e308, 2.0, 0.0),
        (1.0e308, 1.0, 1.0e308),
    ],
)
def test_migration_rejects_non_finite_legacy_trade_economics(
    tmp_path,
    quantity: float,
    price: float,
    commission: float,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, direction, quantity, price, commission,
                asset_class, note, created_at
            ) VALUES (?, '600000.SH', 'buy', ?, ?, ?, 'stock', '', ?)
            """,
            (
                "2026-08-26T10:00:00+08:00",
                quantity,
                price,
                commission,
                "2026-08-26T10:00:00+08:00",
            ),
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="legacy portfolio trade cannot be canonicalized safely",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        ledger_rows = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()
    assert versions == [(1,)]
    assert ledger_rows == (0,)


def test_database_missing_migration_ledger_rejects_versioned_artifacts(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute("DROP TABLE schema_migrations")
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=r"schema_migrations is missing.*table:quote_ingestion_items",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        migration_table = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """).fetchone()
    assert migration_table is None


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
