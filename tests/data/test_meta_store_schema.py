from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

import data.meta_store_schema as meta_store_schema
from data.meta_store_schema import (
    META_DATABASE_FORMAT_VERSION,
    MetaDatabaseSchemaError,
    MetaSchemaMigration,
    meta_database_requires_preparation,
    meta_migration_registry,
    prepare_meta_database,
    require_meta_database_ready,
)
from data.store import DataStore

FROZEN_V1_CHECKSUM = "6aeca449864b925ee4686abc5757a8fd71dd9575373d8fa37c0d744f049ffb87"
FROZEN_V2_CHECKSUM = "743ed5840971f78da7c75b4ae340a41ea9ba5bda695dc2631a1a5c91390ffacf"
FROZEN_LEGACY_V2_CHECKSUM = (
    "ea6c96f5afc2b5273bf1de2fd8bd09fe03124952a25db9255b0d5d9e43ed372c"
)


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
    assert migrations[0].checksum == FROZEN_V1_CHECKSUM
    assert migrations[1].checksum == FROZEN_V2_CHECKSUM
    assert _v2_migration(legacy=True).checksum == FROZEN_LEGACY_V2_CHECKSUM
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
    with sqlite3.connect(path) as connection:
        for migration in meta_migration_registry()[1:]:
            connection.execute(
                "INSERT INTO meta_schema_migrations VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    "false-completion",
                ),
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


def _v2_migration(*, legacy):
    migration = meta_migration_registry()[1]
    if not legacy:
        return migration
    return MetaSchemaMigration(
        migration.version,
        migration.name,
        tuple(
            statement.replace("             AND available_at IS NOT NULL\n", "")
            for statement in migration.statements
        ),
    )


def _create_v2_database(path, *, legacy):
    _create_v1_database(path)
    migration = _v2_migration(legacy=legacy)
    core = {
        "schema_version": "karkinos.market_universe_snapshot.v2",
        "trade_date": "2026-08-22",
        "provider_name": "fixture",
        "members": [{"symbol": "600002", "asset_class": "stock"}],
        "member_count": 1,
        "capture_started_at": "2026-09-22T08:00:00.000000+00:00",
        "capture_completed_at": "2026-09-22T08:00:02.000000+00:00",
        "available_at": "2026-09-22T08:00:02.000000+00:00",
        "historical_membership_verified": False,
    }
    snapshot_id = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    payload_json = json.dumps({**core, "snapshot_id": snapshot_id}, indent=4)
    with sqlite3.connect(path) as connection:
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO meta_schema_migrations VALUES (?, ?, ?, ?)",
            (
                migration.version,
                migration.name,
                migration.checksum,
                "original-v2-applied-at",
            ),
        )
        connection.execute(
            "INSERT INTO market_universe_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                core["trade_date"],
                core["provider_name"],
                core["member_count"],
                payload_json,
                "original-v2-created-at",
                core["capture_started_at"],
                core["capture_completed_at"],
                core["available_at"],
            ),
        )
    return snapshot_id


def _database_state(path):
    with sqlite3.connect(path) as connection:
        return {
            "snapshots": connection.execute(
                "SELECT * FROM market_universe_snapshots ORDER BY snapshot_id"
            ).fetchall(),
            "ledger": connection.execute(
                "SELECT version, name, checksum, applied_at "
                "FROM meta_schema_migrations ORDER BY version"
            ).fetchall(),
            "schema": connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
            ).fetchall(),
        }


@pytest.mark.parametrize("legacy", [False, True], ids=["committed-v2", "legacy-v2"])
def test_v2_upgrade_preserves_snapshot_bytes_times_and_original_ledger(
    tmp_path, legacy
):
    path = tmp_path / "meta.db"
    snapshot_id = _create_v2_database(path, legacy=legacy)
    original = _database_state(path)
    assert len(original["snapshots"]) == 2
    assert original["ledger"][0] == (
        1,
        "market_metadata_format_v1",
        FROZEN_V1_CHECKSUM,
        "legacy-applied-at",
    )
    assert original["ledger"][1] == (
        2,
        "market_universe_observation_times_v2",
        FROZEN_LEGACY_V2_CHECKSUM if legacy else FROZEN_V2_CHECKSUM,
        "original-v2-applied-at",
    )
    assert meta_database_requires_preparation(path) is True
    with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
        require_meta_database_ready(path)

    prepare_meta_database(path)
    upgraded = _database_state(path)
    assert upgraded["snapshots"] == original["snapshots"]
    assert upgraded["ledger"][:2] == original["ledger"]
    assert [row[0] for row in upgraded["ledger"]] == [1, 2, 3]
    assert upgraded["ledger"][2][:3] == (
        meta_migration_registry()[2].version,
        meta_migration_registry()[2].name,
        meta_migration_registry()[2].checksum,
    )
    assert all(
        row[6:] == (None, None, None)
        for row in upgraded["snapshots"]
        if row[0] != snapshot_id
    )
    assert next(row[6:] for row in upgraded["snapshots"] if row[0] == snapshot_id) == (
        "2026-09-22T08:00:00.000000+00:00",
        "2026-09-22T08:00:02.000000+00:00",
        "2026-09-22T08:00:02.000000+00:00",
    )
    require_meta_database_ready(path)
    assert meta_database_requires_preparation(path) is False
    prepare_meta_database(path)
    assert _database_state(path) == upgraded


@pytest.mark.parametrize("legacy", [False, True], ids=["committed-v2", "legacy-v2"])
@pytest.mark.parametrize(
    "times",
    [
        (None, None, "2026-09-22T08:00:02.000000+00:00"),
        (None, "2026-09-22T08:00:02.000000+00:00", None),
        (None, "2026-09-22T08:00:02.000000+00:00", "2026-09-22T08:00:02.000000+00:00"),
        ("2026-09-22T08:00:00.000000+00:00", None, None),
        ("2026-09-22T08:00:00.000000+00:00", None, "2026-09-22T08:00:02.000000+00:00"),
        ("2026-09-22T08:00:00.000000+00:00", "2026-09-22T08:00:02.000000+00:00", None),
    ],
)
def test_upgraded_v3_rejects_partial_null_observation_times(tmp_path, legacy, times):
    path = tmp_path / "meta.db"
    snapshot_id = _create_v2_database(path, legacy=legacy)
    prepare_meta_database(path)
    original = _database_state(path)
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "UPDATE market_universe_snapshots SET capture_started_at=?, "
                "capture_completed_at=?, available_at=? WHERE snapshot_id=?",
                (*times, snapshot_id),
            )
    assert _database_state(path) == original


@pytest.mark.parametrize("legacy", [False, True], ids=["committed-v2", "legacy-v2"])
@pytest.mark.parametrize("field", ["name", "checksum"])
def test_v2_upgrade_rejects_unknown_identity_without_mutation(tmp_path, legacy, field):
    path = tmp_path / "meta.db"
    _create_v2_database(path, legacy=legacy)
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE meta_schema_migrations SET {field}=? WHERE version=2", ("unknown",)
        )
    original = _database_state(path)
    for operation in (
        meta_database_requires_preparation,
        prepare_meta_database,
        require_meta_database_ready,
    ):
        with pytest.raises(MetaDatabaseSchemaError, match="history_mismatch"):
            operation(path)
        assert _database_state(path) == original


@pytest.mark.parametrize("legacy", [False, True], ids=["committed-v2", "legacy-v2"])
@pytest.mark.parametrize("change", ["constraint", "column", "index", "trigger"])
def test_v2_known_identity_still_rejects_wrong_schema_without_mutation(
    tmp_path, legacy, change
):
    path = tmp_path / "meta.db"
    _create_v2_database(path, legacy=legacy)
    with sqlite3.connect(path) as connection:
        if change == "constraint":
            # The other known checksum cannot stand in for the actual table.
            other = _v2_migration(legacy=not legacy)
            connection.execute(
                "UPDATE meta_schema_migrations SET checksum=? WHERE version=2",
                (other.checksum,),
            )
        elif change == "column":
            connection.execute(
                "ALTER TABLE market_universe_snapshots ADD COLUMN unknown_fact TEXT"
            )
        elif change == "index":
            connection.execute("DROP INDEX idx_market_universe_snapshots_available")
            connection.execute(
                "CREATE INDEX idx_market_universe_snapshots_available "
                "ON market_universe_snapshots(member_count)"
            )
        else:
            connection.execute(
                "CREATE TRIGGER unknown_universe_trigger "
                "AFTER INSERT ON market_universe_snapshots BEGIN SELECT 1; END"
            )
    original = _database_state(path)
    for operation in (meta_database_requires_preparation, prepare_meta_database):
        with pytest.raises(
            MetaDatabaseSchemaError, match="market_universe_schema_mismatch"
        ):
            operation(path)
        assert _database_state(path) == original


def test_legacy_v2_partial_null_row_blocks_upgrade_without_inventing_availability(
    tmp_path,
):
    path = tmp_path / "meta.db"
    snapshot_id = _create_v2_database(path, legacy=True)
    with sqlite3.connect(path) as connection:
        # The old CHECK really accepts this row under SQLite NULL semantics.
        connection.execute(
            "UPDATE market_universe_snapshots SET available_at=NULL WHERE snapshot_id=?",
            (snapshot_id,),
        )
    original = _database_state(path)
    for operation in (meta_database_requires_preparation, prepare_meta_database):
        with pytest.raises(
            MetaDatabaseSchemaError, match="observation_times_incomplete"
        ):
            operation(path)
        assert _database_state(path) == original
    assert (
        next(row[8] for row in original["snapshots"] if row[0] == snapshot_id) is None
    )
    assert [row[0] for row in original["ledger"]] == [1, 2]


@pytest.mark.parametrize("legacy", [False, True], ids=["committed-v2", "legacy-v2"])
def test_failed_v3_upgrade_rolls_back_schema_snapshots_and_ledger(
    tmp_path, monkeypatch, legacy
):
    path = tmp_path / "meta.db"
    _create_v2_database(path, legacy=legacy)
    original = _database_state(path)
    migrations = meta_migration_registry()
    migration = migrations[-1]
    # Fail after the real rebuild has copied rows and dropped the old table.
    # The transaction must restore those rows, indexes and original provenance.
    failing_migration = MetaSchemaMigration(
        migration.version,
        migration.name,
        (*migration.statements, "CREATE TABLE market_bars (unexpected_column TEXT)"),
    )
    monkeypatch.setattr(
        meta_store_schema, "_META_MIGRATIONS", (*migrations[:-1], failing_migration)
    )
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        prepare_meta_database(path)
    assert _database_state(path) == original
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='market_universe_snapshots_v2'"
            ).fetchone()
            is None
        )


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
    assert [item[0] for item in ledger] == [
        migration.version for migration in meta_migration_registry()
    ]
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
