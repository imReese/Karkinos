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
FROZEN_LEGACY_V1_MIGRATION_CHECKSUM = (
    "01efbdc71a58a8e0952553ec947b270a69f2d7bb789e6b34b27764da9ac97b74"
)
FROZEN_LEGACY_V1_SCHEMA_CONTRACT_CHECKSUM = (
    "6303b923017e88941dff596eecc30c5dd9b9c76ca2e82f7ee35ebb6193430a7a"
)
FROZEN_V2_MIGRATION_CHECKSUM = (
    "375e7439dfe4517a361e5831eb8dc4472884861c17b78bb3f1e886f209edf462"
)
FROZEN_MIGRATION_MANIFEST = (
    (1, "v0.3.0_legacy_schema_baseline", FROZEN_V1_MIGRATION_CHECKSUM),
    (
        2,
        "canonicalize_legacy_portfolio_trades",
        FROZEN_V2_MIGRATION_CHECKSUM,
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


def _create_known_legacy_v1_database(database: AppDatabase) -> None:
    with sqlite3.connect(database.path) as conn:
        db_module._initialize_v1_baseline_schema(conn)
        conn.execute(
            "ALTER TABLE controlled_submission_ledger_postings "
            "DROP COLUMN account_truth_review_fingerprint"
        )
        contract = migrations._read_schema_contract(conn)
        assert migrations._schema_contract_checksum(contract) == (
            FROZEN_LEGACY_V1_SCHEMA_CONTRACT_CHECKSUM
        )
        conn.execute(migrations._MIGRATION_TABLE_SQL)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (1, ?, ?, ?)
            """,
            (
                FROZEN_V1_MIGRATION_NAME,
                FROZEN_LEGACY_V1_MIGRATION_CHECKSUM,
                "2026-08-23T09:51:38.483167+00:00",
            ),
        )
        conn.commit()


def _insert_legacy_fund_trade_with_ledger_duplicate(
    conn: sqlite3.Connection,
    *,
    legacy_timestamp: str = "2026-08-20T15:00:00+08:00",
    ledger_overrides: dict[str, object | None] | None = None,
) -> tuple[int, int]:
    created_at = "2026-08-20T15:01:00+08:00"
    trade_id = int(
        conn.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, direction, quantity, price, commission,
                asset_class, note, created_at
            ) VALUES (?, '012710', 'buy', 100, 1.25, 0.5, 'fund', '', ?)
            """,
            (legacy_timestamp, created_at),
        ).lastrowid
        or 0
    )
    ledger = {
        "entry_type": "trade_buy",
        "timestamp": legacy_timestamp,
        "amount": 125.0,
        "symbol": "012710",
        "direction": "buy",
        "quantity": 100.0,
        "price": 1.25,
        "commission": 0.5,
        "gross_amount": 125.0,
        "net_cash_impact": -125.5,
        "asset_class": "fund",
    }
    ledger.update(ledger_overrides or {})
    ledger_id = int(
        conn.execute(
            """
            INSERT INTO ledger_entries (
                entry_type, timestamp, amount, symbol, direction, quantity,
                price, commission, gross_amount, net_cash_impact, asset_class,
                note, source, source_ref, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'manual', ?, ?)
            """,
            (
                ledger["entry_type"],
                ledger["timestamp"],
                ledger["amount"],
                ledger["symbol"],
                ledger["direction"],
                ledger["quantity"],
                ledger["price"],
                ledger["commission"],
                ledger["gross_amount"],
                ledger["net_cash_impact"],
                ledger["asset_class"],
                f"pre-v2-ledger:{trade_id}",
                created_at,
            ),
        ).lastrowid
        or 0
    )
    return trade_id, ledger_id


def _insert_required_placeholder_row(
    conn: sqlite3.Connection,
    table_name: str,
) -> None:
    overrides: dict[str, object] = {
        "terminal_status": "filled",
        "status": "applied",
        "reason_code": "broker_evidence_superseded",
        "pre_ledger_cutoff_id": 1,
        "post_ledger_cutoff_id": 1,
        "correction_ledger_entry_id": 1,
    }
    columns: list[str] = []
    values: list[object] = []
    for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall():
        column_name = str(row[1])
        column_type = str(row[2]).upper()
        not_null = bool(row[3])
        default = row[4]
        primary_key = bool(row[5])
        if primary_key or not not_null or default is not None:
            continue
        columns.append(column_name)
        values.append(
            overrides.get(
                column_name,
                0 if "INT" in column_type else f"{table_name}:{column_name}",
            )
        )
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )


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


def test_quote_instant_index_migration_backfills_legacy_snapshots(
    monkeypatch,
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    registered = migrations._MIGRATIONS
    monkeypatch.setattr(
        migrations,
        "_MIGRATIONS",
        tuple(migration for migration in registered if migration.version < 9),
    )
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, volume, timestamp, created_at
            ) VALUES (?, 'stock', 10.5, NULL, ?, ?)
            """,
            (
                "600001",
                "2026-08-27T15:00:00+08:00",
                "2026-08-27T15:00:01+08:00",
            ),
        )
        conn.commit()

    monkeypatch.setattr(migrations, "_MIGRATIONS", registered)
    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        quote_instant = conn.execute(
            "SELECT quote_instant_utc FROM quote_snapshots"
        ).fetchone()[0]
        indexes = {row[0] for row in conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'quote_snapshots'
                """).fetchall()}
    assert quote_instant == "2026-08-27T07:00:00.000000+00:00"
    assert "idx_quote_snapshots_identity_instant" in indexes
    assert "idx_quote_snapshots_missing_instant" in indexes


def test_quote_materialization_migration_rejects_duplicate_fetch_identity(
    monkeypatch,
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    registered = migrations._MIGRATIONS
    monkeypatch.setattr(
        migrations,
        "_MIGRATIONS",
        tuple(migration for migration in registered if migration.version < 10),
    )
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.executemany(
            """
            INSERT INTO quote_snapshots (
                symbol, asset_class, price, volume, timestamp, created_at,
                fetch_run_id, quote_instant_utc
            ) VALUES ('600001', 'stock', ?, NULL, ?, ?, 'duplicate-run', ?)
            """,
            (
                (
                    10.5,
                    "2026-08-27T15:00:00+08:00",
                    "2026-08-27T15:00:01+08:00",
                    "2026-08-27T07:00:00.000000+00:00",
                ),
                (
                    10.6,
                    "2026-08-27T15:01:00+08:00",
                    "2026-08-27T15:01:01+08:00",
                    "2026-08-27T07:01:00.000000+00:00",
                ),
            ),
        )
        conn.commit()

    monkeypatch.setattr(migrations, "_MIGRATIONS", registered)
    with pytest.raises(
        RuntimeError,
        match="quote snapshot fetch-run identity is not unique",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        state_table = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'quote_current_materialization_state'
            """).fetchone()
    assert versions == [
        (migration.version,) for migration in registered if migration.version < 10
    ]
    assert state_table is None


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


def test_v2_registered_migration_checksum_remains_frozen() -> None:
    migration = next(
        migration for migration in migrations._MIGRATIONS if migration.version == 2
    )

    assert migration.name == "canonicalize_legacy_portfolio_trades"
    assert migration.checksum == FROZEN_V2_MIGRATION_CHECKSUM


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


def test_known_legacy_v1_ledger_repairs_and_upgrades_without_rewriting_provenance(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
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
        applied = conn.execute("""
            SELECT version, name, checksum, applied_at
            FROM schema_migrations ORDER BY version
            """).fetchall()
        repaired_column = next(
            row
            for row in conn.execute(
                "PRAGMA table_xinfo(controlled_submission_ledger_postings)"
            )
            if row[1] == "account_truth_review_fingerprint"
        )
        integrity = conn.execute("PRAGMA quick_check").fetchone()

    assert asset == ("600000.SH", "浦发银行")
    assert [(row[0], row[1], row[2]) for row in applied] == [
        (
            1,
            FROZEN_V1_MIGRATION_NAME,
            FROZEN_LEGACY_V1_MIGRATION_CHECKSUM,
        ),
        *[
            (migration.version, migration.name, migration.checksum)
            for migration in migrations._MIGRATIONS[1:]
        ],
    ]
    assert applied[0][3] == "2026-08-23T09:51:38.483167+00:00"
    assert repaired_column[2:6] == ("TEXT", 1, None, 0)
    assert integrity == ("ok",)


@pytest.mark.parametrize(
    "table_name",
    [
        "controlled_submission_ledger_postings",
        "controlled_submission_ledger_corrections",
    ],
)
def test_known_legacy_v1_repair_rejects_nonempty_controlled_ledger_tables(
    tmp_path,
    table_name: str,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        _insert_required_placeholder_row(conn, table_name)
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=rf"legacy v1 schema repair requires an empty table: {table_name}",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert "account_truth_review_fingerprint" not in columns
    assert versions == [(1,)]


@pytest.mark.parametrize(
    "artifact_sql",
    [
        """
        ALTER TABLE pending_fund_orders
        ADD COLUMN confirmation_quote_snapshot_id INTEGER
        """,
        """
        ALTER TABLE market_calendar_snapshots
        ADD COLUMN verification_source_fingerprint TEXT
        """,
        "CREATE TABLE quote_ingestion_items (id INTEGER PRIMARY KEY)",
    ],
)
def test_known_legacy_v1_repair_rejects_unrecorded_versioned_artifacts(
    tmp_path,
    artifact_sql: str,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(artifact_sql)
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="versioned artifacts missing from migration history",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert "account_truth_review_fingerprint" not in columns
    assert versions == [(1,)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "tampered_v1_name"),
        ("checksum", "tampered_v1_checksum"),
    ],
)
def test_known_legacy_v1_repair_rejects_ledger_tampering(
    tmp_path,
    field: str,
    value: str,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            f"UPDATE schema_migrations SET {field} = ? WHERE version = 1",
            (value,),
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="history mismatch at version 1"):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
    assert "account_truth_review_fingerprint" not in columns


def test_known_legacy_v1_repair_rejects_additional_schema_drift(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            "ALTER TABLE controlled_submission_ledger_postings "
            "ADD COLUMN unexpected_legacy_column TEXT"
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match="legacy v1 schema contract mismatch: table",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
    assert "account_truth_review_fingerprint" not in columns


def test_known_legacy_v1_repair_revalidates_under_write_transaction(
    monkeypatch,
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    transaction_states: list[bool] = []
    original = migrations._assert_known_legacy_v1_schema

    def record_transaction_state(*args, **kwargs) -> None:
        transaction_states.append(bool(args[0].in_transaction))
        original(*args, **kwargs)

    monkeypatch.setattr(
        migrations,
        "_assert_known_legacy_v1_schema",
        record_transaction_state,
    )

    database.init_sync()

    assert transaction_states == [False, True]


def test_known_legacy_v1_repair_rolls_back_when_post_contract_check_fails(
    monkeypatch,
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    original = migrations._assert_applied_schema_contract

    def fail_after_contract_check(*args, **kwargs) -> None:
        original(*args, **kwargs)
        raise RuntimeError("injected post-repair contract failure")

    monkeypatch.setattr(
        migrations,
        "_assert_applied_schema_contract",
        fail_after_contract_check,
    )

    with pytest.raises(
        RuntimeError,
        match="injected post-repair contract failure",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
        migration = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchone()
    assert "account_truth_review_fingerprint" not in columns
    assert migration == (
        1,
        FROZEN_V1_MIGRATION_NAME,
        FROZEN_LEGACY_V1_MIGRATION_CHECKSUM,
    )


def test_known_legacy_v1_repair_commits_before_later_migration_blocker(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_known_legacy_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        conn.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, direction, quantity, price, commission,
                asset_class, note, created_at
            ) VALUES (?, '600000.SH', 'buy', ?, 1, 0, 'stock', '', ?)
            """,
            (
                "2026-08-26T10:00:00+08:00",
                float("inf"),
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
        repaired_column = next(
            row
            for row in conn.execute(
                "PRAGMA table_xinfo(controlled_submission_ledger_postings)"
            )
            if row[1] == "account_truth_review_fingerprint"
        )
        migrations_applied = conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert repaired_column[2:6] == ("TEXT", 1, None, 0)
    assert migrations_applied == [
        (
            1,
            FROZEN_V1_MIGRATION_NAME,
            FROZEN_LEGACY_V1_MIGRATION_CHECKSUM,
        )
    ]


def test_ledgerless_legacy_schema_cannot_claim_current_v1_checksum(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    with sqlite3.connect(database.path) as conn:
        db_module._initialize_v1_baseline_schema(conn)
        conn.execute(
            "ALTER TABLE controlled_submission_ledger_postings "
            "DROP COLUMN account_truth_review_fingerprint"
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            "database schema contract mismatch: column "
            "controlled_submission_ledger_postings.account_truth_review_fingerprint"
        ),
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        migration_table = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'schema_migrations'
            """).fetchone()
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(controlled_submission_ledger_postings)"
            ).fetchall()
        }
    assert migration_table is None
    assert "account_truth_review_fingerprint" not in columns


@pytest.mark.parametrize(
    ("damage_sql", "error_pattern"),
    [
        (
            "ALTER TABLE pending_fund_orders DROP COLUMN confirmation_note",
            r"column pending_fund_orders\.confirmation_note",
        ),
        (
            "ALTER TABLE ledger_mutation_claims ADD COLUMN unexpected TEXT",
            "table ledger_mutation_claims",
        ),
        (
            "DROP TABLE order_state_command_claims",
            "missing table order_state_command_claims",
        ),
        (
            "DROP INDEX idx_portfolio_mutation_claims_kind",
            "index idx_portfolio_mutation_claims_kind",
        ),
        (
            """
            DROP TRIGGER market_calendar_verified_insert_guard;
            CREATE TRIGGER market_calendar_verified_insert_guard
            BEFORE INSERT ON market_calendar_snapshots
            BEGIN
                SELECT 1;
            END;
            """,
            "trigger market_calendar_verified_insert_guard",
        ),
        (
            "DROP TABLE quote_ingestion_items",
            "missing table quote_ingestion_items",
        ),
    ],
)
def test_applied_migration_artifact_contract_rejects_missing_or_malformed_shape(
    tmp_path,
    damage_sql: str,
    error_pattern: str,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.executescript(damage_sql)
        conn.commit()

    with pytest.raises(RuntimeError, match=error_pattern):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(migration.version,) for migration in migrations._MIGRATIONS]


def test_migration_history_prefix_rejects_later_schema_artifacts(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version >= 4")
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=r"versioned artifacts missing from migration history:.*ledger_mutation",
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(1,), (2,), (3,)]


def test_pending_v2_rejects_existing_semantic_fund_trade_duplicate(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, ledger_id = _insert_legacy_fund_trade_with_ledger_duplicate(conn)
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"legacy portfolio trade duplicates an existing ledger entry: "
            rf"trade_id={trade_id}, ledger_entry_id={ledger_id}"
        ),
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        ledger_rows = conn.execute(
            "SELECT source, source_ref FROM ledger_entries ORDER BY id"
        ).fetchall()
    assert versions == [(1,)]
    assert ledger_rows == [("manual", f"pre-v2-ledger:{trade_id}")]


def test_pending_v2_rejects_timezone_equivalent_ledger_duplicate(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, ledger_id = _insert_legacy_fund_trade_with_ledger_duplicate(
            conn,
            ledger_overrides={"timestamp": "2026-08-20T07:00:00Z"},
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"legacy portfolio trade duplicates an existing ledger entry: "
            rf"trade_id={trade_id}, ledger_entry_id={ledger_id}"
        ),
    ):
        database.init_sync()

    with sqlite3.connect(database.path) as conn:
        versions = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(1,)]


def test_pending_v2_treats_naive_legacy_timestamp_as_shanghai_time(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, ledger_id = _insert_legacy_fund_trade_with_ledger_duplicate(
            conn,
            legacy_timestamp="2026-08-20T15:00:00",
            ledger_overrides={"timestamp": "2026-08-20T15:00:00+08:00"},
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"legacy portfolio trade duplicates an existing ledger entry: "
            rf"trade_id={trade_id}, ledger_entry_id={ledger_id}"
        ),
    ):
        database.init_sync()


def test_pending_v2_rejects_duplicate_with_optional_gross_and_net_missing(
    tmp_path,
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, ledger_id = _insert_legacy_fund_trade_with_ledger_duplicate(
            conn,
            ledger_overrides={"gross_amount": None, "net_cash_impact": None},
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"legacy portfolio trade duplicates an existing ledger entry: "
            rf"trade_id={trade_id}, ledger_entry_id={ledger_id}"
        ),
    ):
        database.init_sync()


def test_pending_v2_normalizes_symbol_and_asset_class_formatting(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, ledger_id = _insert_legacy_fund_trade_with_ledger_duplicate(
            conn,
            ledger_overrides={"symbol": " 012710 ", "asset_class": " FUND "},
        )
        conn.commit()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"legacy portfolio trade duplicates an existing ledger entry: "
            rf"trade_id={trade_id}, ledger_entry_id={ledger_id}"
        ),
    ):
        database.init_sync()


@pytest.mark.parametrize(
    "ledger_overrides",
    [
        pytest.param(
            {"timestamp": "2026-08-20T15:00:01+08:00"},
            id="timestamp",
        ),
        pytest.param({"symbol": "012711"}, id="symbol"),
        pytest.param({"direction": "sell"}, id="side"),
        pytest.param({"quantity": 101.0}, id="quantity"),
        pytest.param({"price": 1.5}, id="price"),
        pytest.param({"commission": 0.75}, id="commission"),
        pytest.param({"gross_amount": 126.0}, id="gross-amount"),
        pytest.param({"gross_amount": 125.000000001}, id="gross-amount-tiny"),
        pytest.param({"net_cash_impact": -126.0}, id="net-cash-impact"),
        pytest.param(
            {"net_cash_impact": -125.500000001},
            id="net-cash-impact-tiny",
        ),
        pytest.param({"asset_class": "stock"}, id="asset-class"),
    ],
)
def test_pending_v2_allows_migration_when_ledger_trade_field_drifts(
    tmp_path,
    ledger_overrides: dict[str, object],
) -> None:
    database = AppDatabase(tmp_path / "app.db")
    _create_frozen_v1_database(database)
    with sqlite3.connect(database.path) as conn:
        trade_id, _ = _insert_legacy_fund_trade_with_ledger_duplicate(
            conn,
            ledger_overrides=ledger_overrides,
        )
        conn.commit()

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        v2 = conn.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 2"
        ).fetchone()
        ledger_rows = conn.execute(
            "SELECT source, source_ref FROM ledger_entries ORDER BY id"
        ).fetchall()
    assert v2 == (
        "canonicalize_legacy_portfolio_trades",
        FROZEN_V2_MIGRATION_CHECKSUM,
    )
    assert ledger_rows == [
        ("manual", f"pre-v2-ledger:{trade_id}"),
        ("portfolio_trade", f"trade:{trade_id}"),
    ]


def test_applied_v2_is_unaffected_by_semantic_duplicate_preflight(tmp_path) -> None:
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with sqlite3.connect(database.path) as conn:
        trade_id, _ = _insert_legacy_fund_trade_with_ledger_duplicate(conn)
        conn.commit()

    database.init_sync()

    with sqlite3.connect(database.path) as conn:
        v2 = conn.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version = 2"
        ).fetchone()
        ledger_rows = conn.execute(
            "SELECT source, source_ref FROM ledger_entries ORDER BY id"
        ).fetchall()
    assert v2 == (
        "canonicalize_legacy_portfolio_trades",
        FROZEN_V2_MIGRATION_CHECKSUM,
    )
    assert ledger_rows == [("manual", f"pre-v2-ledger:{trade_id}")]


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
