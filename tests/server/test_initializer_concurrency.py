"""Deterministic ownership tests for explicit database preparation."""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.persistence import initializer, migration_lifecycle, migrations


def _legacy_database(path: Path, monkeypatch) -> list[tuple[object, ...]]:
    with monkeypatch.context() as patch:
        patch.setattr(
            migrations,
            "_MIGRATIONS",
            tuple(m for m in migrations._MIGRATIONS if m.version <= 12),
        )
        initializer.initialize_database(path)
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()


def _hold_preparation_lock(path: Path, holding, release_read) -> None:
    with initializer._initialization_lock(path, 5):
        holding.set()
        if not release_read.poll(10):
            raise RuntimeError("test_owner_release_timeout")
        release_read.recv()


def _finish(process: mp.Process) -> None:
    if process.is_alive():
        process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    assert not process.is_alive()


def test_concurrent_preparer_times_out_without_mutating_database(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    original_rows = _legacy_database(path, monkeypatch)
    context = mp.get_context("spawn")
    holding = context.Event()
    release_read, release_send = context.Pipe(duplex=False)
    owner = context.Process(
        target=_hold_preparation_lock,
        args=(path, holding, release_read),
    )
    owner.start()
    try:
        assert holding.wait(10)
        with pytest.raises(TimeoutError, match="database_initialization_lock_timeout"):
            initializer.initialize_database(path, lock_timeout_seconds=0.15)
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute(
                    "SELECT * FROM schema_migrations ORDER BY version"
                ).fetchall()
                == original_rows
            )
        release_send.send(True)
        owner.join(5)
        assert owner.exitcode == 0
        initializer.initialize_database(path, lock_timeout_seconds=0)
        assert migration_lifecycle.inspect_database(path).state == "current"
    finally:
        if owner.is_alive():
            release_send.send(True)
        _finish(owner)


def test_stale_lock_metadata_is_not_initialization_authority(tmp_path):
    path = tmp_path / "app.db"
    (tmp_path / "app.db.initialize.lock").write_text("999999\n")
    initializer.initialize_database(path, lock_timeout_seconds=0)
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
            == migrations.CURRENT_SCHEMA_VERSION
        )


def test_io_failure_releases_initialization_ownership(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    with monkeypatch.context() as patch:

        def fail(*_args, **_kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        patch.setattr(initializer, "_initialize_on_connection", fail)
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            initializer.initialize_database(path)
    initializer.initialize_database(path, lock_timeout_seconds=0)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["api", "data", "research"])
async def test_runtime_processes_refuse_unprepared_database_before_business_loop(
    tmp_path, monkeypatch, role
):
    from server.app import create_app
    from server.config import ServerConfig
    from server.workers import ai_shadow_research_worker, data_worker

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("KARKINOS_ENV_FILE", str(tmp_path / "absent.env"))

    def business_loop(*_args, **_kwargs):
        pytest.fail("unprepared runtime must not enter business or ready state")

    monkeypatch.setattr(data_worker, "run_with_presence", business_loop)
    monkeypatch.setattr(ai_shadow_research_worker, "run_with_presence", business_loop)
    monkeypatch.setattr(
        AppDatabase, "publish_current_valuation_snapshot_sync", business_loop
    )

    with pytest.raises(
        migration_lifecycle.DatabasePreparationError,
        match="Database state: new",
    ):
        if role == "api":
            app = create_app()
            async with app.router.lifespan_context(app):
                business_loop()
        elif role == "data":
            await data_worker.run_data_worker(ServerConfig())
        else:
            await ai_shadow_research_worker.run_ai_shadow_research_worker(
                ServerConfig()
            )
