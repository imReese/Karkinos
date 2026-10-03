"""Market metadata is prepared and backed up before runtime processes start."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from contextlib import closing, contextmanager

import pytest

from data import meta_store_schema
from server import __main__
from server.db import AppDatabase
from server.persistence import initializer


def _ledger(path, table="meta_schema_migrations"):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            f"SELECT version,name,checksum,applied_at FROM {table} ORDER BY version"
        ).fetchall()


def _old_workspace(tmp_path, monkeypatch):
    app = AppDatabase(tmp_path / "app.db")
    app.init_sync()
    path = tmp_path / "meta.db"
    with monkeypatch.context() as old:
        old.setattr(
            meta_store_schema,
            "_META_MIGRATIONS",
            (
                meta_store_schema.meta_migration_registry()[0],
                meta_store_schema._LEGACY_V2_MIGRATION,
            ),
        )
        meta_store_schema.prepare_meta_database(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            "INSERT INTO market_universe_snapshots "
            "(snapshot_id,trade_date,provider_name,member_count,snapshot_json,created_at) "
            "VALUES ('fixture-id','2026-09-01','fixture',0,'{\"members\": []}', 'original')"
        )
        conn.commit()
    return app.path, path


def test_metadata_upgrade_backs_up_wal_and_preserves_both_ledgers(
    tmp_path, monkeypatch
):
    app, meta = _old_workspace(tmp_path, monkeypatch)
    prior = _ledger(meta)
    app_prior = _ledger(app, "schema_migrations")
    # Keep a committed WAL page alive: copying only meta.db would miss this row.
    with closing(sqlite3.connect(meta)) as writer:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute(
            "UPDATE market_universe_snapshots SET created_at='committed-in-wal'"
        )
        writer.commit()
        initializer.initialize_market_metadata_database(app)
    records = list((tmp_path / "backups/schema/meta.db").glob("*/migration.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record["state"] == "committed"
    saved = records[0].parent / "meta.db"
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == record["backup"]["sha256"]
    assert _ledger(saved) == prior
    assert _ledger(meta)[:2] == prior
    assert _ledger(meta)[-1][0] == 3
    assert _ledger(app, "schema_migrations") == app_prior
    with closing(sqlite3.connect(saved)) as conn:
        assert conn.execute(
            "SELECT snapshot_json,created_at,available_at FROM market_universe_snapshots"
        ).fetchone() == ('{"members": []}', "committed-in-wal", None)
    registry_path = records[0].parent / record["registry"]["file"]
    assert (
        hashlib.sha256(registry_path.read_bytes()).hexdigest()
        == record["registry"]["sha256"]
    )
    registry = json.loads(registry_path.read_text())
    assert registry["migrations"][-1]["statements"]
    initializer.initialize_market_metadata_database(app)
    assert (
        list((tmp_path / "backups/schema/meta.db").glob("*/migration.json")) == records
    )
    assert _ledger(meta)[:2] == prior


def test_metadata_backup_failure_does_not_enter_schema_migration(tmp_path, monkeypatch):
    app, meta = _old_workspace(tmp_path, monkeypatch)
    prior = _ledger(meta)

    def failed_backup(*args, **kwargs):
        raise OSError("synthetic backup failure")

    monkeypatch.setattr(initializer, "backup_database", failed_backup)
    with pytest.raises(OSError, match="synthetic backup failure"):
        initializer.initialize_market_metadata_database(app)
    assert _ledger(meta) == prior


def test_metadata_upgrade_waits_for_runtime_ownership(tmp_path, monkeypatch):
    app, meta = _old_workspace(tmp_path, monkeypatch)
    prior = _ledger(meta)
    with initializer.database_runtime(app):
        with pytest.raises(TimeoutError, match="stop API/worker"):
            initializer.initialize_market_metadata_database(app, lock_timeout_seconds=0)
    assert _ledger(meta) == prior
    assert not (tmp_path / "backups/schema/meta.db").exists()


def test_concurrent_preparer_finishing_does_not_require_stopping_current_runtime(
    tmp_path, monkeypatch
):
    app, meta = _old_workspace(tmp_path, monkeypatch)

    @contextmanager
    def other_preparer_has_entered_runtime(*args, **kwargs):
        meta_store_schema.prepare_meta_database(meta)
        raise TimeoutError("another process now holds a shared runtime lock")
        yield

    monkeypatch.setattr(
        initializer, "_initialization_lock", other_preparer_has_entered_runtime
    )
    initializer.initialize_market_metadata_database(app, lock_timeout_seconds=1)
    meta_store_schema.require_meta_database_ready(meta)
    assert not (tmp_path / "backups/schema/meta.db").exists()


def test_dangling_meta_symlink_is_rejected_without_creating_target(tmp_path):
    target = tmp_path / "unrelated/target.db"
    path = tmp_path / "meta.db"
    path.symlink_to(target)
    with pytest.raises(meta_store_schema.MetaDatabaseSchemaError, match="path_invalid"):
        meta_store_schema.prepare_meta_database(path)
    assert path.is_symlink()
    assert not target.parent.exists()


def test_metadata_inspection_uses_one_snapshot_during_concurrent_upgrade(
    tmp_path, monkeypatch
):
    _, meta = _old_workspace(tmp_path, monkeypatch)
    original_assert = meta_store_schema._assert_migration_history
    upgraded = False

    def upgrade_after_reading_old_history(connection, *, allow_prefix=False):
        nonlocal upgraded
        count = original_assert(connection, allow_prefix=allow_prefix)
        if not upgraded:
            upgraded = True
            meta_store_schema.prepare_meta_database(meta)
        return count

    monkeypatch.setattr(
        meta_store_schema,
        "_assert_migration_history",
        upgrade_after_reading_old_history,
    )
    assert meta_store_schema.meta_database_requires_preparation(meta)
    assert not meta_store_schema.meta_database_requires_preparation(meta)


def _entrypoint_environment(tmp_path, monkeypatch):
    (tmp_path / "empty.env").touch()
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(tmp_path / "missing-config.json"))
    monkeypatch.setenv("KARKINOS_ENV_FILE", str(tmp_path / "empty.env"))
    monkeypatch.setenv("KARKINOS_WORKSPACE_ROLE", "development")
    monkeypatch.setenv("KARKINOS_HOME", str(tmp_path))
    monkeypatch.setattr(
        __main__, "_run_runtime", lambda *args: pytest.fail("runtime must not start")
    )


def test_prepare_cli_checks_both_databases_before_reporting_ready(
    tmp_path, monkeypatch, capsys
):
    _, meta = _old_workspace(tmp_path, monkeypatch)
    _entrypoint_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["server", "--prepare-database"])
    __main__.main()
    assert _ledger(meta)[-1][0] == 3
    output = capsys.readouterr()
    assert "Karkinos databases ready" in output.out
    assert str(tmp_path / "app.db") in output.out
    assert str(meta) in output.out
    assert not output.err


def test_unknown_meta_history_refuses_runtime_with_actionable_error(
    tmp_path, monkeypatch, capsys
):
    app, meta = _old_workspace(tmp_path, monkeypatch)
    with closing(sqlite3.connect(meta)) as conn:
        conn.execute(
            "UPDATE meta_schema_migrations SET checksum='unknown' WHERE version=2"
        )
        conn.commit()
    prior = _ledger(meta)
    app_prior = _ledger(app, "schema_migrations")
    _entrypoint_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["server"])
    with pytest.raises(SystemExit) as exc:
        __main__.main()
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "Market metadata database is incompatible" in output.err
    assert "meta_database_migration_history_mismatch" in output.err
    assert str(meta) in output.err
    assert "Keep this database and its migration history" in output.err
    assert "Traceback" not in output.err
    assert _ledger(meta) == prior
    assert _ledger(app, "schema_migrations") == app_prior
    assert not (tmp_path / "backups/schema/meta.db").exists()
