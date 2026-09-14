from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.service import run_dev


def test_development_initializes_only_its_own_state(tmp_path, monkeypatch):
    production = tmp_path / "production"
    production.mkdir()
    sentinel = production / "app.db"
    sentinel.write_bytes(b"untouched synthetic production state")
    for name in (
        "KARKINOS_HOME",
        "KARKINOS_WORKSPACE",
        "KARKINOS_DATA_DIR",
        "KARKINOS_CONFIG_PATH",
        "KARKINOS_ENV_FILE",
    ):
        monkeypatch.setenv(name, str(production))
    monkeypatch.setenv("KARKINOS_RELEASE_SHA", "a" * 40)
    monkeypatch.setenv("KARKINOS_ARTIFACT_FINGERPRINT", "b" * 64)
    development = tmp_path / "development"
    environment = run_dev.development_environment(development)
    assert environment["KARKINOS_BACKTEST_REPORT_DIR"] == str(
        development / "data/reports/backtest"
    )
    assert "KARKINOS_RELEASE_SHA" not in environment
    assert "KARKINOS_ARTIFACT_FINGERPRINT" not in environment
    (development / "config/.env").write_text(
        f"KARKINOS_HOME={production}\n"
        f"KARKINOS_WORKSPACE={production}\n"
        f"KARKINOS_DATA_DIR={production}\n"
        f"KARKINOS_CONFIG_PATH={production / 'config.json'}\n"
        f"KARKINOS_BACKTEST_REPORT_DIR={production}\n"
    )
    result = subprocess.run(
        [sys.executable, "-m", "server", "--check-state"],
        cwd=run_dev.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (development / "data/app.db").is_file()
    assert (development / "data/meta.db").is_file()
    assert sentinel.read_bytes() == b"untouched synthetic production state"
    assert list(production.iterdir()) == [sentinel]
    config = development / "config/config.json"
    config.write_text('{"server": {"market_calendar_auto_sync": false}}\n')
    before = config.read_bytes()
    run_dev.development_environment(development)
    assert config.read_bytes() == before


def test_development_rejects_installed_or_aliased_state(tmp_path):
    production = tmp_path / "production"
    (production / "releases").mkdir(parents=True)
    with pytest.raises(ValueError, match="installed runtime"):
        run_dev.development_environment(production)
    assert not (production / "config").exists()
    development = tmp_path / "development"
    development.mkdir()
    (development / "data").symlink_to(production, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        run_dev.development_environment(development)
    assert list(production.iterdir()) == [production / "releases"]


def test_existing_data_without_configuration_is_not_reinitialized(tmp_path):
    (tmp_path / "data").mkdir()
    database = tmp_path / "data/app.db"
    database.write_bytes(b"original")
    with pytest.raises(ValueError, match="original configuration"):
        run_dev.development_environment(tmp_path)
    assert database.read_bytes() == b"original"
    assert not (tmp_path / "config").exists()


@pytest.mark.parametrize(
    "trigger", ["signal", "peer_exit", "spawn_failure", "startup_timeout"]
)
def test_foreground_exit_stops_only_created_children(tmp_path, trigger):
    pid_file = tmp_path / "child.pid"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    )
    commands = [[sys.executable, "-c", child]]
    if trigger == "peer_exit":
        commands.append([sys.executable, "-c", "import time; time.sleep(1)"])
    elif trigger == "spawn_failure":
        commands.append([str(tmp_path / "missing-executable")])
    health_url = (
        "http://127.0.0.1:1/api/health" if trigger == "startup_timeout" else None
    )
    program = (
        "import os; from scripts.service.run_dev import supervise; "
        f"raise SystemExit(supervise({commands!r}, dict(os.environ), health_url={health_url!r}, startup_timeout=1))"
    )
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    parent = subprocess.Popen([sys.executable, "-c", program], cwd=run_dev.ROOT)
    try:
        if trigger == "signal":
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                assert parent.poll() is None
                time.sleep(0.05)
            assert pid_file.exists()
            parent.send_signal(signal.SIGTERM)
        assert parent.wait(timeout=15) != 0
        assert unrelated.poll() is None
        if trigger == "startup_timeout":
            assert parent.returncode == 1
        if pid_file.exists():
            child_pid = int(pid_file.read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=10)


def test_occupied_port_fails_without_starting_or_creating_state(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(run_dev.shutil, "which", lambda _: sys.executable)
    root = tmp_path / "source"
    (root / "web/node_modules/.bin").mkdir(parents=True)
    (root / "web/node_modules/.bin/vite").touch()
    monkeypatch.setattr(run_dev, "ROOT", root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        occupied = listener.getsockname()[1]
        assert (
            run_dev.main(["--home", str(tmp_path / "home"), "--port", str(occupied)])
            == 1
        )
        assert listener.getsockname()[1] == occupied
    assert not (tmp_path / "home").exists()
