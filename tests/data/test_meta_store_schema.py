from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from data.meta_store_schema import (
    META_DATABASE_FORMAT_VERSION,
    MetaDatabaseSchemaError,
    meta_migration_registry,
    prepare_meta_database,
    require_meta_database_ready,
)
from data.store import DataStore


def test_meta_database_records_checksum_verified_format(tmp_path) -> None:
    store = DataStore(tmp_path)
    migrations = meta_migration_registry()
    with sqlite3.connect(store._meta_path) as connection:
        rows = connection.execute(
            "SELECT version, name, checksum FROM meta_schema_migrations ORDER BY version"
        ).fetchall()
    assert rows == [(item.version, item.name, item.checksum) for item in migrations]
    assert rows[-1][0] == migrations[-1].version
    assert META_DATABASE_FORMAT_VERSION == 1
    assert migrations[0].checksum == (
        "6aeca449864b925ee4686abc5757a8fd71dd9575373d8fa37c0d744f049ffb87"
    )
    require_meta_database_ready(store._meta_path)


def test_meta_database_rejects_changed_migration_history(tmp_path) -> None:
    store = DataStore(tmp_path)
    with sqlite3.connect(store._meta_path) as connection:
        connection.execute(
            "UPDATE meta_schema_migrations SET checksum = 'changed' WHERE version = 1"
        )
    with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
        require_meta_database_ready(store._meta_path)
    with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
        prepare_meta_database(store._meta_path)


def test_meta_database_adopts_legacy_schema_once(tmp_path) -> None:
    path = tmp_path / "meta.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE bar_meta (
                symbol TEXT NOT NULL,
                frequency TEXT NOT NULL,
                row_count INTEGER DEFAULT 0,
                PRIMARY KEY(symbol, frequency)
            )
            """
        )
        connection.execute(
            "INSERT INTO bar_meta(symbol, frequency, row_count) VALUES ('600519', '1d', 3)"
        )
    prepare_meta_database(path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(bar_meta)")}
        row = connection.execute(
            "SELECT symbol, frequency, row_count FROM bar_meta"
        ).fetchone()
    assert {"provider_name", "dataset_id", "diagnostics_json"} <= columns
    assert row == ("600519", "1d", 3)


@pytest.mark.parametrize(
    "change",
    [
        "ALTER TABLE market_universe_snapshots ADD COLUMN unknown_fact TEXT",
        "CREATE INDEX unknown_universe_index ON market_universe_snapshots(member_count)",
        "CREATE TRIGGER unknown_universe_trigger AFTER INSERT ON market_universe_snapshots BEGIN SELECT 1; END",
    ],
)
def test_upgrade_refuses_to_drop_unknown_universe_schema_objects(tmp_path, change):
    path = tmp_path / "meta.db"
    _, payload_json = _create_v1_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(change)
    with pytest.raises(
        MetaDatabaseSchemaError, match="market_universe_schema_mismatch"
    ):
        prepare_meta_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT snapshot_json FROM market_universe_snapshots"
        ).fetchone() == (payload_json,)
        assert connection.execute(
            "SELECT version FROM meta_schema_migrations"
        ).fetchall() == [(1,)]


def test_ready_rejects_completed_ledger_with_unmigrated_universe_table(tmp_path):
    path = tmp_path / "meta.db"
    _create_v1_database(path)
    migration = meta_migration_registry()[1]
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO meta_schema_migrations VALUES (?, ?, ?, ?)",
            (migration.version, migration.name, migration.checksum, "false-completion"),
        )
    with pytest.raises(
        MetaDatabaseSchemaError, match="market_universe_schema_mismatch"
    ):
        require_meta_database_ready(path)
    with pytest.raises(
        MetaDatabaseSchemaError, match="market_universe_schema_mismatch"
    ):
        prepare_meta_database(path)


def _create_v1_database(path):
    migration = meta_migration_registry()[0]
    core = {
        "schema_version": "karkinos.market_universe_snapshot.v1",
        "trade_date": "2026-08-21",
        "provider_name": "fixture",
        "members": [{"symbol": "600001", "asset_class": "stock"}],
        "member_count": 1,
        "asset_scope": ["stock"],
        "provider_contact_performed_during_ingestion": True,
        "read_endpoints_contact_providers": False,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "changes_capital_authority": False,
    }
    snapshot_id = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    # Preserve stored text even when its whitespace is not canonical.
    payload_json = json.dumps({**core, "snapshot_id": snapshot_id}, indent=3)
    with sqlite3.connect(path) as connection:
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "CREATE TABLE meta_schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)"
        )
        connection.execute(
            "INSERT INTO meta_schema_migrations VALUES (?, ?, ?, ?)",
            (
                migration.version,
                migration.name,
                migration.checksum,
                "legacy-applied-at",
            ),
        )
        connection.execute(
            "INSERT INTO market_universe_snapshots VALUES (?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                core["trade_date"],
                "fixture",
                1,
                payload_json,
                "old-created-at",
            ),
        )
    return snapshot_id, payload_json


def test_v1_upgrade_preserves_old_snapshot_bytes_id_and_unknown_availability(tmp_path):
    path = tmp_path / "meta.db"
    snapshot_id, payload_json = _create_v1_database(path)
    with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
        require_meta_database_ready(path)

    prepare_meta_database(path)
    prepare_meta_database(path)
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT snapshot_id, snapshot_json, created_at, capture_started_at, "
            "capture_completed_at, available_at FROM market_universe_snapshots"
        ).fetchone()
        ledger = connection.execute(
            "SELECT version, applied_at FROM meta_schema_migrations ORDER BY version"
        ).fetchall()
    assert row == (snapshot_id, payload_json, "old-created-at", None, None, None)
    assert ledger[0] == (1, "legacy-applied-at")
    assert [item[0] for item in ledger] == [1, 2]
    assert DataStore(tmp_path).get_market_universe_snapshot(
        snapshot_id=snapshot_id
    ) == json.loads(payload_json)
    require_meta_database_ready(path)


def test_failed_v2_upgrade_rolls_back_table_rebuild_and_migration_ledger(tmp_path):
    path = tmp_path / "meta.db"
    snapshot_id, payload_json = _create_v1_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE INDEX idx_market_universe_snapshots_available ON market_bars(timestamp)"
        )
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        prepare_meta_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT snapshot_id, snapshot_json FROM market_universe_snapshots"
        ).fetchone() == (snapshot_id, payload_json)
        assert connection.execute(
            "SELECT version FROM meta_schema_migrations"
        ).fetchall() == [(1,)]
        assert "available_at" not in {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(market_universe_snapshots)"
            )
        }


@pytest.mark.parametrize(
    "corruption", ["future_version", "changed_prefix", "missing_prefix"]
)
def test_upgrade_rejects_unknown_or_changed_history_before_mutation(
    tmp_path, corruption
):
    path = tmp_path / "meta.db"
    _, payload_json = _create_v1_database(path)
    with sqlite3.connect(path) as connection:
        if corruption == "future_version":
            connection.execute(
                "INSERT INTO meta_schema_migrations VALUES (3, 'future', 'unknown', 'future')"
            )
        elif corruption == "changed_prefix":
            connection.execute("UPDATE meta_schema_migrations SET checksum = 'changed'")
        else:
            connection.execute("DELETE FROM meta_schema_migrations")
    with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
        prepare_meta_database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT snapshot_json FROM market_universe_snapshots"
        ).fetchone() == (payload_json,)
        assert "available_at" not in {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(market_universe_snapshots)"
            )
        }
