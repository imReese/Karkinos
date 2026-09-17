from __future__ import annotations

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
    migration = meta_migration_registry()[0]
    with sqlite3.connect(store._meta_path) as connection:
        row = connection.execute(
            "SELECT version, name, checksum FROM meta_schema_migrations"
        ).fetchone()
    assert row == (META_DATABASE_FORMAT_VERSION, migration.name, migration.checksum)
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
