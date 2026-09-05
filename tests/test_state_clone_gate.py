from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from server.db import AppDatabase
from tools.state_clone_gate import (
    _quiescent_database_copy,
    clone_state,
    run_state_clone_gate,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_replay(tmp_path, monkeypatch):
    with tempfile.TemporaryDirectory(prefix="karkinos-state-clone-") as directory:
        root = Path(directory).resolve()
        data = root / "candidate"
        data.mkdir()
        db = AppDatabase(data / "app.db")
        db.init_sync()
        (root / ".release-transaction.json").write_text("{}")
        (root / ".state-clone.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "token": "fixture",
                    "data_dir": str(data),
                    "device": data.stat().st_dev,
                    "inode": data.stat().st_ino,
                }
            )
        )
        config = root / "config.json"
        config.write_text("{}")
        env_file = root / ".env"
        env_file.write_text("")
        for key, value in {
            "KARKINOS_HOME": root,
            "KARKINOS_DATA_DIR": data,
            "KARKINOS_CONFIG_PATH": config,
            "KARKINOS_ENV_FILE": env_file,
            "KARKINOS_STATE_CLONE": "1",
            "KARKINOS_STATE_CLONE_TOKEN": "fixture",
        }.items():
            monkeypatch.setenv(key, str(value))
        yield db


def test_replay_checks_actual_financial_endpoints_when_publication_missing(
    isolated_replay, monkeypatch
):
    from server.app import create_app
    from server.state_replay import replay_persistent_state

    monkeypatch.setattr(
        AppDatabase,
        "publish_current_valuation_snapshot_sync",
        lambda *args, **kwargs: None,
    )
    report = replay_persistent_state(create_app)
    assert report["current_publication_read"] == "unavailable"
    assert report["read_database_writes"] is False


def test_replay_rejects_semantic_ledger_change_during_migration(
    isolated_replay, monkeypatch
):
    from server.app import create_app
    from server.state_replay import preflight_persistent_state, replay_persistent_state

    def corrupt():
        preflight_persistent_state()
        isolated_replay.insert_ledger_entry_sync(
            entry_type="cash_deposit", timestamp="2026-09-04T10:00:00+08:00", amount=1
        )

    monkeypatch.setattr("server.state_replay.preflight_persistent_state", corrupt)
    with pytest.raises(ValueError, match="state_replay_ledger_changed"):
        replay_persistent_state(create_app)


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="managed native release isolation is macOS-specific",
)
def test_os_network_denial_is_inherited_by_candidate_descendants(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    child = "import socket\ntry: socket.create_connection(('127.0.0.1', 9))\nexcept PermissionError: pass\nelse: raise AssertionError('network not denied')"
    command = f"import subprocess,sys,json; subprocess.run([sys.executable, '-c', {child!r}], check=True); print(json.dumps({{'schema_version': 'karkinos.state_clone_replay.v1', 'status': 'passed'}}))"
    report = run_state_clone_gate(
        source_data=source,
        candidate_command=[sys.executable, "-c", command],
        candidate_cwd=ROOT,
        network_isolation=True,
    )
    assert report["network_isolation"] == "os_process_tree_denied"


@pytest.mark.parametrize("flag,guard", [(None, True), ("1", False), ("1", True)])
def test_replay_rejects_non_clone_before_any_database_write(
    tmp_path, monkeypatch, flag, guard
):
    from server.state_replay import replay_persistent_state

    data = tmp_path / "data"
    data.mkdir()
    db = AppDatabase(data / "app.db")
    db.init_sync()
    if guard:
        (tmp_path / ".release-transaction.json").write_text("{}")
    monkeypatch.setenv("KARKINOS_HOME", str(tmp_path))
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(data))
    if flag:
        monkeypatch.setenv("KARKINOS_STATE_CLONE", flag)
    else:
        monkeypatch.delenv("KARKINOS_STATE_CLONE", raising=False)
    before = {path.name: path.read_bytes() for path in data.iterdir()}
    with pytest.raises(ValueError, match="state_replay_"):
        replay_persistent_state(lambda: pytest.fail("must not start API"))
    assert {path.name: path.read_bytes() for path in data.iterdir()} == before


def test_candidate_migrates_reads_restarts_and_restores_disposable_state(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    db = AppDatabase(source / "app.db")
    db.init_sync()
    db.publish_current_valuation_snapshot_sync()
    with sqlite3.connect(db.path) as conn:
        # A schema-12 state is a real migration input, not an empty database.
        conn.execute("DROP TABLE job_runs")
        conn.execute("DELETE FROM schema_migrations WHERE version=13")
        conn.commit()
        before = list(conn.iterdump())
    report = run_state_clone_gate(
        source_data=source,
        candidate_command=[sys.executable, "-m", "server"],
        candidate_cwd=ROOT,
        rollback_command=[
            sys.executable,
            "-c",
            "import os,sqlite3; c=sqlite3.connect(os.path.join(os.environ['KARKINOS_DATA_DIR'],'app.db')); assert c.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] == 12; assert not c.execute(\"SELECT name FROM sqlite_master WHERE name='job_runs'\").fetchall()",
        ],
        rollback_cwd=ROOT,
    )
    assert (
        report["status"]
        == report["process_restart"]
        == report["restored_baseline_preflight"]
        == "passed"
    )
    assert report["application_start_read_stop"] == "passed"
    assert report["python_socket_attempts"] == 0
    assert report["network_isolation"] == "not_checked"
    assert report["release_eligible"] is False
    with sqlite3.connect(db.path) as conn:
        assert list(conn.iterdump()) == before


def test_clone_uses_committed_wal_state_and_rejects_symlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "backups").mkdir()
    (source / "backups" / "archived.db").write_bytes(b"not an active database")
    with sqlite3.connect(source / "app.db") as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE facts(value TEXT)")
        conn.execute("INSERT INTO facts VALUES ('committed')")
        conn.commit()
        conn.execute("INSERT INTO facts VALUES ('uncommitted')")
        clone_state(source, tmp_path / "clone")
        assert not (tmp_path / "clone" / "backups").exists()
        with sqlite3.connect(tmp_path / "clone" / "app.db") as copied:
            assert copied.execute("SELECT value FROM facts").fetchall() == [
                ("committed",)
            ]
    (source / "bad-link").symlink_to(source / "app.db")
    with pytest.raises(ValueError, match="symlink"):
        clone_state(source, tmp_path / "bad")


def test_invalid_candidate_report_stops_before_rollback(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="report_invalid"):
        run_state_clone_gate(
            source_data=source,
            candidate_command=[sys.executable, "-c", "print('{}')"],
            candidate_cwd=ROOT,
            rollback_command=["must-not-run"],
        )


def test_quiescent_copy_rejects_a_concurrent_change(tmp_path, monkeypatch):
    import shutil

    source = tmp_path / "closed.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE facts(value TEXT)")
    copy = shutil.copyfile

    def mutate_after_copy(source, destination):
        copy(source, destination)
        with sqlite3.connect(source) as conn:
            conn.execute("INSERT INTO facts VALUES ('new')")

    monkeypatch.setattr("tools.state_clone_gate.shutil.copyfile", mutate_after_copy)
    with pytest.raises(ValueError, match="changed_during_copy"):
        _quiescent_database_copy(source, tmp_path / "copy.db")


def test_native_tcp_gate_rejects_an_already_listening_port():
    from tools.state_clone_gate import _tcp_port

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(ValueError, match="port_unavailable"):
            _tcp_port(listener.getsockname()[1])


@pytest.mark.parametrize(
    "output,owned", [("p42\nf16\n", True), ("p43\nf16\n", False), ("f16\n", False)]
)
def test_listener_identity_parses_lsof_process_records(monkeypatch, output, owned):
    from tools.state_clone_gate import _listener_owned_by

    monkeypatch.setattr(
        "tools.state_clone_gate.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, output, ""),
    )
    assert _listener_owned_by(42, 12345) is owned


@pytest.mark.parametrize(
    "worker_pid,group,status,expected",
    [
        (43, 42, "ready", 43),
        (42, 42, "ready", None),
        (43, 41, "ready", None),
        (43, 42, "stopped", None),
    ],
)
def test_native_worker_identity_requires_a_distinct_ready_group_member(
    tmp_path, monkeypatch, worker_pid, group, status, expected
):
    from tools.state_clone_gate import _native_worker_pid

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "INSERT INTO runtime_controls(key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (
                "data_worker_heartbeat",
                json.dumps(
                    {"owner": f"data-worker:{worker_pid}:fixture", "status": status}
                ),
            ),
        )
    monkeypatch.setattr("tools.state_clone_gate.os.getpgid", lambda pid: group)
    assert _native_worker_pid(tmp_path, 42) == expected


@pytest.mark.parametrize("variant", ["snapshot", "cutoff", "database_drift"])
def test_tcp_reads_require_the_current_database_financial_identity(
    tmp_path, monkeypatch, variant
):
    from tools.state_clone_gate import _tcp_financial_read_identity

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    publication = db.publish_current_valuation_snapshot_sync()
    calls = []

    def response(port, endpoint):
        calls.append(endpoint)
        result = {
            "valuation_snapshot_id": publication["snapshot_id"],
            "ledger_cutoff_id": publication["ledger_cutoff_id"],
        }
        if variant == "snapshot":
            result["valuation_snapshot_id"] = "wrong"
        elif variant == "cutoff":
            result["ledger_cutoff_id"] += 1
        elif len(calls) == 2:
            with sqlite3.connect(db.path) as other:
                other.execute(
                    "UPDATE runtime_controls SET value_json='{}' WHERE key='valuation_snapshot_publication'"
                )
        return result

    monkeypatch.setattr("tools.state_clone_gate._tcp_json", response)
    with pytest.raises(ValueError, match="financial_identity_(mismatch|drift)"):
        _tcp_financial_read_identity(tmp_path, 12345)


@pytest.mark.parametrize(
    "variant,reason",
    [
        ("listener", "health_identity_failed"),
        ("listener_gone", "health_identity_failed"),
        ("descendant", "descendant_survived"),
        ("stop_exit", "stop_failed"),
    ],
)
def test_native_tcp_gate_cannot_pass_wrong_listener_or_incomplete_stop(
    tmp_path, monkeypatch, variant, reason
):
    from tools import state_clone_gate as gate

    cleanup = []

    class Process:
        pid = 123456

        def poll(self):
            return None

        def terminate(self):
            cleanup.append("terminate")

        def wait(self, timeout=None):
            cleanup.append("wait")
            return 1 if variant == "stop_exit" else 0

    monkeypatch.setattr(gate, "_tcp_port", lambda port=None: 12345)
    monkeypatch.setattr(gate, "_assert_native_identity", lambda *a: None)
    monkeypatch.setattr(gate, "_tcp_isolation_command", lambda port: [])
    monkeypatch.setattr(gate, "_verify_native_network_isolation", lambda *a: None)
    monkeypatch.setattr(gate.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(gate, "_tcp_json", lambda *a: {})
    monkeypatch.setattr(
        "scripts.release.manage_release._health_payload_matches", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        gate, "_listener_owned_by", lambda *a: not variant.startswith("listener")
    )
    monkeypatch.setattr(gate, "_tcp_financial_read_identity", lambda *a: {})
    monkeypatch.setattr(gate, "_process_group_exists", lambda pid: True)
    monkeypatch.setattr(gate, "_wait_process_group_exit", lambda pid: False)

    def kill_group(*args):
        cleanup.append("kill_group")
        if variant == "listener_gone":
            raise ProcessLookupError

    monkeypatch.setattr(gate.os, "killpg", kill_group)
    with pytest.raises(ValueError, match=reason):
        gate._native_tcp_probe(
            ["fixture"],
            tmp_path,
            {"KARKINOS_DATA_DIR": str(tmp_path)},
            {},
            timeout=0.01,
        )
    assert cleanup[-2:] == ["kill_group", "wait"]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS network isolation")
def test_tcp_isolation_allows_only_the_test_listener_including_descendants():
    from tools.state_clone_gate import _tcp_isolation_command, _tcp_port

    port = _tcp_port()
    denied = "import socket\nfor address in [('127.0.0.1',1),('198.51.100.1',443)]:\n try: socket.create_connection(address,timeout=1)\n except PermissionError: pass\n else: raise AssertionError('connection unexpectedly allowed')"
    code = f"import socket,subprocess,sys; subprocess.run([sys.executable,'-c',{denied!r}],check=True); s=socket.socket(); s.bind(('127.0.0.1',{port})); s.listen(); print('listening',flush=True); s.settimeout(5); c,_=s.accept(); c.sendall(b'ok'); c.close(); s.close()"
    child = subprocess.Popen(
        [*_tcp_isolation_command(port), sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        import selectors

        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(10)
        assert child.stdout.readline().strip() == "listening"
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            assert client.recv(2) == b"ok"
        assert child.wait(timeout=5) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS network isolation")
def test_native_network_preflight_does_not_create_python_bytecode(tmp_path):
    import os
    import shlex

    from tools.state_clone_gate import (
        _tcp_isolation_command,
        _tcp_port,
        _verify_native_network_isolation,
    )

    runtime = tmp_path / "runtime/bin/python3.12"
    runtime.parent.mkdir(parents=True)
    cache = tmp_path / "unexpected-bytecode"
    # Redirect standard-library cache writes to a fresh directory so the test
    # does not depend on whether the host already has compiled Python modules.
    runtime.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -X {shlex.quote("pycache_prefix=" + str(cache))} "$@"\n'
    )
    runtime.chmod(0o755)
    cwd = tmp_path / "app"
    cwd.mkdir()
    _verify_native_network_isolation(
        _tcp_isolation_command(_tcp_port()), cwd, dict(os.environ)
    )
    assert not cache.exists()
