"""Exercise the real registry and schema on disposable SQLite databases."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from server.db import AppDatabase
from server.persistence import initializer, migration_lifecycle, migrations


def _ledger(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute(
            "SELECT version, name, checksum, applied_at "
            "FROM schema_migrations ORDER BY version"
        ).fetchall()


def _records(path):
    return list(migration_lifecycle.history_directory(path).glob("*/migration.json"))


def _previous_database(tmp_path, monkeypatch):
    registered = migrations._MIGRATIONS
    with monkeypatch.context() as old:
        old.setattr(migrations, "_MIGRATIONS", registered[:-1])
        database = AppDatabase(tmp_path / "app.db")
        database.init_sync()
    with closing(sqlite3.connect(database.path)) as conn:
        conn.execute("""
            INSERT INTO watchlist_assets (
                symbol, asset_class, display_name, source, created_at, updated_at
            ) VALUES ('600000.SH', 'stock', 'fixture', 'manual', 'before', 'before')
        """)
        conn.commit()
    return database


def test_readonly_status_and_runtime_open_never_create_a_database(tmp_path):
    path = tmp_path / "missing/app.db"
    status = migration_lifecycle.inspect_database(path)
    assert status.state == "new"
    with pytest.raises(RuntimeError, match="normal Karkinos launcher"):
        migration_lifecycle.require_database_ready(path)
    assert not path.parent.exists()


def test_already_current_database_does_not_create_another_backup_or_archive(tmp_path):
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    before = _ledger(database.path)
    records = _records(database.path)
    database.init_sync()
    asyncio.run(database.init())
    assert _ledger(database.path) == before
    assert _records(database.path) == records
    assert migration_lifecycle.inspect_database(database.path).state == "current"


def test_async_runtime_initialization_requires_explicit_preparation(tmp_path):
    database = AppDatabase(tmp_path / "app.db")
    with pytest.raises(RuntimeError, match="normal Karkinos launcher"):
        asyncio.run(database.init())
    assert not database.path.exists()
    assert not _records(database.path)


@pytest.mark.parametrize("conflict", ["unknown", "checksum"])
def test_history_conflicts_fail_before_backup_or_schema_mutation(tmp_path, conflict):
    database = AppDatabase(tmp_path / "app.db")
    database.init_sync()
    with closing(sqlite3.connect(database.path)) as conn:
        if conflict == "unknown":
            conn.execute(
                "INSERT INTO schema_migrations VALUES (?, ?, ?, ?)",
                (
                    migrations._MIGRATIONS[-1].version + 1,
                    "synthetic_future_migration",
                    "synthetic-unknown-checksum",
                    "2026-09-16T07:37:48+00:00",
                ),
            )
        else:
            conn.execute(
                "UPDATE schema_migrations SET checksum='changed' WHERE version=1",
            )
        conn.commit()
    before = _ledger(database.path)
    records = _records(database.path)
    status = migration_lifecycle.inspect_database(database.path)
    assert status.state == (
        "unknown_migration" if conflict == "unknown" else "history_mismatch"
    )
    with pytest.raises(RuntimeError, match=status.state):
        database.init_sync()
    assert _ledger(database.path) == before
    assert _records(database.path) == records


def test_upgrade_backs_up_previous_version_and_preserves_business_rows(
    tmp_path,
    monkeypatch,
):
    database = _previous_database(tmp_path, monkeypatch)
    before = _ledger(database.path)
    previous_records = set(_records(database.path))
    assert migration_lifecycle.inspect_database(database.path).state == "upgrade"
    database.init_sync()
    created = set(_records(database.path)) - previous_records
    assert len(created) == 1
    record_path = created.pop()
    record = json.loads(record_path.read_text())
    assert record["state"] == "committed"
    assert _ledger(record_path.parent / "app.db") == before
    assert record["target"][-1]["checksum"] == migrations._MIGRATIONS[-1].checksum
    with closing(sqlite3.connect(database.path)) as conn:
        assert conn.execute("SELECT display_name FROM watchlist_assets").fetchone() == (
            "fixture",
        )


def test_known_mutated_v14_preserves_provenance_and_upgrades_forward(
    tmp_path, monkeypatch
):
    path = tmp_path / "app.db"
    legacy_registry = tuple(
        migrations._LEGACY_MUTATED_V14 if item.version == 14 else item
        for item in migrations._MIGRATIONS
        if item.version <= 14
    )
    with monkeypatch.context() as legacy:
        legacy.setattr(migrations, "_MIGRATIONS", legacy_registry)
        AppDatabase(path).init_sync()

    before = _ledger(path)
    assert before[-1][0:3] == (
        14,
        "index_published_fund_nav_marks",
        "885fdab9c4d2d3b9c95d07ba53a45506787690421ed19a9ea6ebcbda25b700a1",
    )
    assert migration_lifecycle.inspect_database(path).state == "upgrade"

    AppDatabase(path).init_sync()

    after = _ledger(path)
    assert after[: len(before)] == before
    assert [(row[0], row[1]) for row in after[-5:]] == [
        (15, "reindex_published_fund_nav_marks"),
        (16, "add_exact_financial_decimal_storage"),
        (17, "enforce_financial_fact_invariants"),
        (18, "enforce_canonical_financial_decimal_writes"),
        (19, "enforce_structured_fact_json"),
    ]
    assert after[-1][2] == migrations._MIGRATIONS[-1].checksum
    assert migration_lifecycle.inspect_database(path).state == "current"


def test_failure_after_migration_rolls_back_entire_preparation(tmp_path, monkeypatch):
    database = _previous_database(tmp_path, monkeypatch)
    before = _ledger(database.path)

    def fail(_conn):
        raise RuntimeError("synthetic failure after migration SQL")

    monkeypatch.setattr(initializer, "_backfill_quote_snapshot_instants", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        database.init_sync()
    assert _ledger(database.path) == before
    with closing(sqlite3.connect(database.path)) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert conn.execute("SELECT display_name FROM watchlist_assets").fetchone() == (
            "fixture",
        )
    assert any(
        json.loads(path.read_text())["state"] == "failed"
        for path in _records(database.path)
    )


def test_foreign_key_violation_rolls_back_entire_preparation(tmp_path, monkeypatch):
    database = _previous_database(tmp_path, monkeypatch)
    before = _ledger(database.path)

    def inject_violation(conn):
        conn.execute("CREATE TABLE b1_parent(id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE b1_child(parent_id INTEGER REFERENCES b1_parent(id))"
        )
        conn.execute("INSERT INTO b1_child(parent_id) VALUES (99)")

    monkeypatch.setattr(
        initializer, "_backfill_quote_snapshot_instants", inject_violation
    )
    with pytest.raises(RuntimeError, match="sqlite_foreign_key_check_failed"):
        database.init_sync()

    assert _ledger(database.path) == before
    with closing(sqlite3.connect(database.path)) as conn:
        assert conn.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name IN ('b1_parent', 'b1_child')"
            ).fetchone()
            is None
        )
        assert conn.execute("SELECT display_name FROM watchlist_assets").fetchone() == (
            "fixture",
        )


def test_runtime_shared_lock_blocks_a_different_builds_upgrade(tmp_path, monkeypatch):
    database = _previous_database(tmp_path, monkeypatch)
    before = _ledger(database.path)
    records = _records(database.path)
    # Model a running older build holding the same managed-runtime lease.
    with initializer._initialization_lock(database.path, 0, shared=True):
        with pytest.raises(TimeoutError, match="stop API/worker"):
            initializer.initialize_database(database.path, lock_timeout_seconds=0)
    assert _ledger(database.path) == before
    assert _records(database.path) == records


def test_failed_backup_never_enters_migration_transaction(tmp_path, monkeypatch):
    database = _previous_database(tmp_path, monkeypatch)
    before = _ledger(database.path)

    def fail(*_args, **_kwargs):
        raise OSError("synthetic full disk")

    monkeypatch.setattr(migration_lifecycle, "backup_database", fail)
    with pytest.raises(OSError, match="full disk"):
        database.init_sync()
    assert _ledger(database.path) == before


def test_published_migrations_nine_through_nineteen_remain_frozen():
    # Earlier versions already have frozen fixtures in test_schema_migrations.py.
    expected = {
        9: "655b449d41b35726ff0a7175918a6ab29ce86b8c92651d8d8e6258bb3c123240",
        10: "05250f76f73c606ce13b19f2189445751740430f3fb731f93af8e680587a86ee",
        11: "b76210eb65a2a42c9f50c67b77344ff0fee48248d8c63aac8af062fd725480a0",
        12: "582da11b15221bdc463ad4a10b936908d8b9cd2cac2e5014be87a33d6b9270ab",
        13: "7be894d95be8d29a4c0e2164d10079ed1f0837284d4a6702ba0a2d0ff89c7d78",
        14: "273163e5cdca99dd11c19645e3cda9b56988b1ea0faa27f4374f87eaeb2eb223",
        15: "3cbbfd222119247e2f2038da4f27c79896a8a9f78861de6998e6b05c482cba3a",
        16: "97a6e233b141aa9179962d17bfa4450c7a0939c80b7d394b195af5b601903271",
        17: "9df70bbf4736f38b3bc7c3a4de6a180a1e5e6deafafbdfe9751bf708a81fb607",
        18: "fe018f8c55b0098494f7826865cf098fca07b9a61c61c753fca7e160126eaab0",
        19: "627efd139fa91db21bc820177ef6a1bb9bd284055cebc92d784f869eff719776",
    }
    actual = {item.version: item.checksum for item in migrations._MIGRATIONS}
    assert {version: actual[version] for version in expected} == expected
