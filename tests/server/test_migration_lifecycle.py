"""Backup/transaction behavior without production data or external providers."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from server.persistence import migration_lifecycle as lifecycle


def test_schema_scripts_participate_in_outer_transaction(tmp_path):
    path = tmp_path / "app.db"
    with closing(
        sqlite3.connect(path, factory=lifecycle.AtomicSchemaConnection)
    ) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript("""
            CREATE TABLE values_log(value TEXT);
            CREATE TABLE copies(value TEXT);
            CREATE TRIGGER copy_value AFTER INSERT ON values_log BEGIN
                INSERT INTO copies VALUES (NEW.value);
                INSERT INTO copies VALUES ('quoted;semicolon');
            END;
            INSERT INTO values_log VALUES ('retained;within transaction');
        """)
        assert conn.in_transaction
        assert conn.execute("SELECT COUNT(*) FROM copies").fetchone() == (2,)
        conn.rollback()
        assert (
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            == []
        )


def test_schema_script_failure_rolls_back_all_ddl(tmp_path):
    with closing(
        sqlite3.connect(tmp_path / "app.db", factory=lifecycle.AtomicSchemaConnection)
    ) as conn:
        conn.execute("CREATE TABLE previous(value INTEGER)")
        conn.execute("INSERT INTO previous VALUES (7)")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            conn.executescript("""
                CREATE TABLE new_table(value INTEGER);
                INSERT INTO previous VALUES (8);
                INSERT INTO missing_table VALUES (1);
            """)
        conn.rollback()
        assert conn.execute("SELECT * FROM previous").fetchall() == [(7,)]
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name='new_table'"
            ).fetchone()
            is None
        )


def test_backup_includes_committed_wal_and_excludes_uncommitted_data(tmp_path):
    source = tmp_path / "app.db"
    saved = tmp_path / "backup.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE facts(value TEXT)")
        conn.execute("INSERT INTO facts VALUES ('committed')")
        conn.commit()
        conn.execute("INSERT INTO facts VALUES ('uncommitted')")
        assert Path(str(source) + "-wal").is_file()
        digest = lifecycle.backup_database(source, saved)
        with closing(sqlite3.connect(saved)) as backup:
            assert backup.execute("SELECT * FROM facts").fetchall() == [("committed",)]
        assert digest == hashlib.sha256(saved.read_bytes()).hexdigest()
        assert saved.stat().st_mode & 0o777 == 0o600
        conn.rollback()


def test_backup_does_not_overwrite_an_existing_file(tmp_path):
    source = tmp_path / "app.db"
    source.touch()
    saved = tmp_path / "backup.db"
    saved.write_bytes(b"existing backup")
    with pytest.raises(FileExistsError):
        lifecycle.backup_database(source, saved)
    assert saved.read_bytes() == b"existing backup"


def test_failed_backup_is_not_marked_ready(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    path.write_bytes(b"not a database")
    status = lifecycle.DatabaseStatus(path, "upgrade", (), ())
    monkeypatch.setattr(lifecycle, "migration_definitions", lambda: ())
    monkeypatch.setattr(lifecycle, "source_identity", lambda: {"commit": None})
    with pytest.raises(sqlite3.DatabaseError):
        lifecycle.begin_preparation(status)
    records = list(lifecycle.history_directory(path).glob("*/migration.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["state"] == "backup_failed"
    assert path.read_bytes() == b"not a database"


def test_archived_definitions_survive_later_worktree_edits(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    definition = {
        "version": 14,
        "name": "synthetic_migration",
        "checksum": "fixture-checksum",
        "statements": ["CREATE INDEX sample ON facts(value)"],
    }
    monkeypatch.setattr(lifecycle, "migration_definitions", lambda: (definition,))
    monkeypatch.setattr(
        lifecycle,
        "source_identity",
        lambda: {"commit": "a" * 40, "persistence_worktree_dirty": True},
    )
    record_path, record = lifecycle.begin_preparation(
        lifecycle.DatabaseStatus(path, "new", (), ())
    )
    definition["statements"] = ["SELECT 1"]
    saved = json.loads(record_path.read_text())
    assert saved["target"][0]["statements"] == ["CREATE INDEX sample ON facts(value)"]
    assert saved["source"]["persistence_worktree_dirty"] is True
    registry_path = record_path.parent / saved["registry_snapshot"]["file"]
    registry = json.loads(registry_path.read_text())
    assert registry["migrations"][0]["statements"] == [
        "CREATE INDEX sample ON facts(value)"
    ]
    assert not path.exists()
    lifecycle.finish_preparation(record_path, record, succeeded=False)
    finished = json.loads(record_path.read_text())
    assert finished["state"] == "failed"
    assert finished["target"][0]["statements"] == [
        "CREATE INDEX sample ON facts(value)"
    ]


def test_atomic_record_write_preserves_previous_record_on_failure(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "migration.json"
    lifecycle.write_record(path, {"state": "backed_up"})

    def fail(*_args):
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(lifecycle.os, "replace", fail)
    with pytest.raises(OSError, match="synthetic disk failure"):
        lifecycle.write_record(path, {"state": "committed"})
    assert json.loads(path.read_text()) == {"state": "backed_up"}
    assert list(tmp_path.iterdir()) == [path]


def test_archive_rejects_symlinked_parent(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "backups").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        lifecycle._private_directory(tmp_path / "backups/schema/app.db/run")
    assert not list(elsewhere.iterdir())


def test_interrupted_record_is_compared_with_ledger_not_replayed(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE facts(value TEXT)")
    row = {"version": 1, "name": "fixture", "checksum": "fixture", "applied_at": "then"}
    monkeypatch.setattr(lifecycle, "migration_definitions", lambda: (row,))
    monkeypatch.setattr(lifecycle, "source_identity", lambda: {"commit": None})
    status = lifecycle.DatabaseStatus(path, "upgrade", (), (row,))
    record_path, _record = lifecycle.begin_preparation(status)
    current = lifecycle.DatabaseStatus(path, "current", (row,), (row,))
    recovery = lifecycle.recovery_records(current)
    assert recovery[0]["ledger_comparison"] == "target_present"
    assert recovery[0]["state"] == "backed_up"
    assert recovery[0]["verified_registry_snapshot"] == str(
        record_path.parent / "migration-registry.json"
    )
    assert recovery[0]["verified_backups"] == [str(record_path.parent / path.name)]
    assert json.loads(record_path.read_text())["state"] == "backed_up"
    # Altered recovery material must not be advertised as verified.
    (record_path.parent / "migration-registry.json").write_text("corrupt")
    assert lifecycle.recovery_records(current)[0]["verified_registry_snapshot"] is None
    (record_path.parent / path.name).write_bytes(b"corrupt backup")
    assert lifecycle.recovery_records(current)[0]["verified_backups"] == []


def test_source_identity_does_not_archive_environment(monkeypatch):
    monkeypatch.setenv("KARKINOS_TEST_SECRET", "never-record-this-fixture")
    result = lifecycle.source_identity()
    assert "never-record-this-fixture" not in json.dumps(result)
    assert set(result) == {"source_root", "commit", "persistence_worktree_dirty"}


def test_unknown_version_diagnostic_does_not_suggest_reset(tmp_path):
    row = {
        "version": 14,
        "name": "index_published_fund_nav_marks",
        "checksum": "synthetic",
        "applied_at": "2026-09-16T07:37:48+00:00",
    }
    status = lifecycle.DatabaseStatus(
        tmp_path / "app.db", "unknown_migration", (row,), ()
    )
    assert status.blocked
    assert not status.needs_preparation
    assert "index_published_fund_nav_marks" in status.explain()
    assert "do not delete" in status.explain()
    assert not list(tmp_path.iterdir())


def test_status_reports_stable_database_format_and_migration_head(tmp_path):
    row = {
        "version": 17,
        "name": "enforce_financial_fact_invariants",
        "checksum": "fixture",
        "applied_at": "2026-09-17T12:00:00+00:00",
    }
    status = lifecycle.DatabaseStatus(tmp_path / "app.db", "current", (row,), (row,))

    payload = status.as_dict()
    assert payload["database_format_version"] == 1
    assert payload["migration_head"] == 17
    assert "Database format: v1" in status.explain()
    assert "Migration head: code=17; database=17" in status.explain()
