"""Deterministic cold-start ownership and interrupted migration recovery."""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import sqlite3
import time
from pathlib import Path

import pytest

from server.db import AppDatabase
from server.persistence import initializer, migrations


def _legacy_database(path, monkeypatch):
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


def _initialize_process(path, role, events, results, *, timeout=5, hold=False):
    original_connect = sqlite3.connect
    started = time.monotonic()

    class Connection(sqlite3.Connection):
        def executescript(self, sql):
            location = super().execute("PRAGMA database_list").fetchone()[2]
            if (
                "baseline" in events
                and location
                and Path(location).resolve() == Path(path).resolve()
            ):
                events["baseline"].set()
            return super().executescript(sql)

        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if hold and sql.startswith("CREATE TABLE job_runs"):
                location = super().execute("PRAGMA database_list").fetchone()[2]
                if location and Path(location).resolve() == Path(path).resolve():
                    identity = Path(path).stat()
                    results.put(
                        {
                            "role": role,
                            "pid": os.getpid(),
                            "connection": id(self),
                            "dev": identity.st_dev,
                            "inode": identity.st_ino,
                            "phase": "migration_13_statement_0",
                            "in_transaction": self.in_transaction,
                        }
                    )
                    events["holding"].set()
                    if not events["release_read"].poll(10):
                        raise RuntimeError("test_owner_release_timeout")
                    events["release_read"].recv()
            return result

    def connect(*args, **kwargs):
        if str(args[0]) == str(path):
            events[role].set()
        kwargs["factory"] = Connection
        return original_connect(*args, **kwargs)

    initializer.sqlite3.connect = connect
    try:
        # Both async API/research and synchronous data-worker entrypoints delegate here.
        database = AppDatabase(path)
        if role == "timeout":
            initializer.initialize_database(path, lock_timeout_seconds=timeout)
        elif role == "data":
            database.init_sync()
        else:
            asyncio.run(database.init())
        results.put(
            {"role": role, "result": "ready", "elapsed": time.monotonic() - started}
        )
    except Exception as exc:
        results.put(
            {
                "role": role,
                "result": type(exc).__name__,
                "detail": str(exc),
                "sqlite_errorcode": getattr(exc, "sqlite_errorcode", None),
                "elapsed": time.monotonic() - started,
            }
        )


def _finish(processes):
    for process in processes:
        if process.is_alive():
            process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        assert not process.is_alive()


@pytest.mark.parametrize("kill_owner", [False, True])
def test_concurrent_api_data_research_initialization_recovers_at_migration_boundary(
    tmp_path, monkeypatch, kill_owner
):
    path = tmp_path / "app.db"
    original_rows = _legacy_database(path, monkeypatch)
    context = mp.get_context("spawn")
    events = {name: context.Event() for name in ("holding", "api", "data", "research")}
    events["release_read"], events["release_send"] = context.Pipe(duplex=False)
    results = context.Queue()
    owner = context.Process(
        target=_initialize_process,
        args=(path, "api", events, results),
        kwargs={"hold": True},
    )
    waiters = [
        context.Process(target=_initialize_process, args=(path, role, events, results))
        for role in ("data", "research")
    ]
    processes = [owner, *waiters]
    owner.start()
    try:
        assert events["holding"].wait(10)
        diagnostic = results.get(timeout=3)
        assert diagnostic["phase"] == "migration_13_statement_0"
        assert diagnostic["in_transaction"] is True
        assert diagnostic["pid"] == owner.pid
        assert (diagnostic["dev"], diagnostic["inode"]) == (
            path.stat().st_dev,
            path.stat().st_ino,
        )
        for process in waiters:
            process.start()
        # Longer than SQLite's unchanged two-second busy timeout: no waiter opens it.
        assert not events["data"].wait(2.1)
        assert not events["research"].is_set()
        if kill_owner:
            owner.kill()
            owner.join(5)
        else:
            events["release_send"].send(True)
        reports = [results.get(timeout=10) for _ in range(2 if kill_owner else 3)]
        assert all(report["result"] == "ready" for report in reports), reports
        for process in processes:
            process.join(5)
        with sqlite3.connect(path) as connection:
            rows = connection.execute(
                "SELECT * FROM schema_migrations ORDER BY version"
            ).fetchall()
            assert rows[:12] == original_rows
            assert [row[0] for row in rows] == list(range(1, 14))
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert (
                connection.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 0
            )
    finally:
        events["release_send"].send(True)
        _finish([p for p in processes if p.pid is not None])


def test_initialization_timeout_does_not_open_database(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    _legacy_database(path, monkeypatch)
    context = mp.get_context("spawn")
    events = {name: context.Event() for name in ("holding", "api", "timeout")}
    events["release_read"], events["release_send"] = context.Pipe(duplex=False)
    results = context.Queue()
    owner = context.Process(
        target=_initialize_process,
        args=(path, "api", events, results),
        kwargs={"hold": True},
    )
    waiter = context.Process(
        target=_initialize_process,
        args=(path, "timeout", events, results),
        kwargs={"timeout": 0.15},
    )
    owner.start()
    try:
        assert events["holding"].wait(10)
        results.get(timeout=3)
        waiter.start()
        result = results.get(timeout=5)
        assert result["result"] == "TimeoutError"
        assert "database_initialization_lock_timeout" in result["detail"]
        assert f"owner_pid={owner.pid}" in result["detail"]
        assert not events["timeout"].is_set()
        events["release_send"].send(True)
        assert results.get(timeout=5)["result"] == "ready"
    finally:
        events["release_send"].send(True)
        _finish([p for p in (owner, waiter) if p.pid is not None])


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

        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        patch.setattr(initializer, "_initialize_on_connection", fail)
        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            initializer.initialize_database(path)
    initializer.initialize_database(path, lock_timeout_seconds=0)


def _startup_heartbeat(path, events, results, old_writer):
    from server.persistence.runtime_controls import RuntimeControlRepository

    if old_writer:
        migrations._MIGRATIONS = tuple(
            m for m in migrations._MIGRATIONS if m.version <= 12
        )
    AppDatabase(path).init_sync()
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            result = super().execute(sql, *args, **kwargs)
            if "INSERT INTO runtime_controls" in sql:
                assert self.in_transaction
                events["holding"].set()
                if not events["release_read"].poll(10):
                    raise RuntimeError("test_heartbeat_release_timeout")
                events["release_read"].recv()
            return result

    def connect(*args, **kwargs):
        kwargs["factory"] = Connection
        return original_connect(*args, **kwargs)

    sqlite3.connect = connect
    RuntimeControlRepository(path).set_value(
        "data_worker_heartbeat", {"status": "ready"}
    )
    results.put({"role": "writer", "result": "ready"})


@pytest.mark.parametrize(
    "old_writer,release_writer", [(False, False), (True, False), (True, True)]
)
def test_initializer_preserves_sqlite_failure_boundary_during_startup_heartbeat(
    tmp_path, monkeypatch, old_writer, release_writer
):
    path = tmp_path / "app.db"
    if old_writer:
        _legacy_database(path, monkeypatch)
    else:
        initializer.initialize_database(path)
    context = mp.get_context("spawn")
    events = {name: context.Event() for name in ("holding", "data", "baseline")}
    events["release_read"], events["release_send"] = context.Pipe(duplex=False)
    results = context.Queue()
    writer = context.Process(
        target=_startup_heartbeat, args=(path, events, results, old_writer)
    )
    waiter = context.Process(
        target=_initialize_process, args=(path, "data", events, results)
    )
    writer.start()
    try:
        assert events["holding"].wait(10)
        waiter.start()
        assert events["baseline"].wait(5)
        if release_writer:
            events["release_send"].send(True)
            reports = [results.get(timeout=5) for _ in range(2)]
            assert all(report["result"] == "ready" for report in reports), reports
        else:
            report = results.get(timeout=5)
            assert report["role"] == "data"
            if old_writer:
                assert report["result"] == "OperationalError"
                assert report["sqlite_errorcode"] == sqlite3.SQLITE_BUSY
            else:
                # An up-to-date read-only initializer need not wait for WAL writes.
                assert report["result"] == "ready"
            events["release_send"].send(True)
            assert results.get(timeout=5)["result"] == "ready"
        for process in (waiter, writer):
            process.join(5)
            assert process.exitcode == 0
        initializer.initialize_database(path, lock_timeout_seconds=0)
    finally:
        events["release_send"].send(True)
        _finish([p for p in (writer, waiter) if p.pid is not None])


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["api", "data", "research"])
async def test_bootstrap_initialization_failure_cannot_enter_business_loop(
    tmp_path, monkeypatch, role
):
    from server import db as database_module
    from server.app import create_app
    from server.config import ServerConfig
    from server.workers import ai_shadow_research_worker, data_worker

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    monkeypatch.setenv("KARKINOS_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("KARKINOS_ENV_FILE", str(tmp_path / "absent.env"))

    def failed_initialization(*args, **kwargs):
        raise TimeoutError("fixture_initialization_failed")

    def business_loop(*args, **kwargs):
        pytest.fail("failed initialization must not enter business or ready state")

    monkeypatch.setattr(database_module, "initialize_database", failed_initialization)
    monkeypatch.setattr(data_worker, "run_with_presence", business_loop)
    monkeypatch.setattr(ai_shadow_research_worker, "run_with_presence", business_loop)
    monkeypatch.setattr(
        AppDatabase, "publish_current_valuation_snapshot_sync", business_loop
    )
    with pytest.raises(TimeoutError, match="fixture_initialization_failed"):
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
