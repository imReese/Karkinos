"""Source startup never takes over listeners or leaves partially started peers."""

from __future__ import annotations

import os
import signal
import subprocess
from unittest.mock import Mock

import pytest

from scripts.service import run_main as runtime


@pytest.fixture
def prepared_source(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setenv("KARKINOS_MAIN_PORT", "8000")
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    home = tmp_path / "runtime"
    (home / "config").mkdir(parents=True)
    (home / "data").mkdir()
    for name in ("config/config.json", "config/.env", "data/app.db", "data/meta.db"):
        (home / name).write_text("original fixture")
    env = {
        "KARKINOS_HOME": str(home),
        "KARKINOS_DATA_DIR": str(home / "data"),
        "KARKINOS_CONFIG_PATH": str(home / "config/config.json"),
        "KARKINOS_ENV_FILE": str(home / "config/.env"),
    }
    monkeypatch.setattr(runtime, "runtime_environment", lambda root: env)
    monkeypatch.setattr(runtime, "require_runtime_idle", lambda env: None)
    return tmp_path


def test_occupied_port_refuses_before_preparation_or_launch(
    prepared_source, monkeypatch
):
    class OccupiedPort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, address):
            assert address == ("127.0.0.1", 8000)
            raise OSError("address already in use")

    def unexpected(*args, **kwargs):
        pytest.fail("an occupied port must not install, build, or start processes")

    monkeypatch.setattr(runtime.socket, "socket", OccupiedPort)
    monkeypatch.setattr(runtime.subprocess, "run", unexpected)
    monkeypatch.setattr(runtime, "supervise", unexpected)
    assert runtime.main([]) == 1


def test_checkout_changed_during_preparation_never_launches(
    prepared_source, monkeypatch
):
    identities = iter(("a" * 40, "b" * 40))
    monkeypatch.setattr(runtime, "check_source", lambda root: next(identities))

    class AvailablePort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def bind(self, address):
            return None

    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    def unexpected(*args):
        pytest.fail("the verified checkout identity changed")

    monkeypatch.setattr(runtime.socket, "socket", AvailablePort)
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "supervise", unexpected)
    assert runtime.main([]) == 1
    assert len(commands) == 3
    assert all("--check-state" not in command for command in commands)


def test_spawn_failure_stops_peer_and_restores_signals(tmp_path, monkeypatch):
    class Child:
        terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            assert timeout == 10
            return 0

    child = Child()
    calls = []
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 2:
            raise OSError("research worker spawn failed")
        return child

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    with pytest.raises(OSError, match="spawn failed"):
        runtime.supervise(tmp_path, {}, 8000, Mock())
    assert child.terminated is True
    for sig, handler in previous.items():
        assert signal.getsignal(sig) == handler
    for _, kwargs in calls:
        for fd in kwargs["pass_fds"]:
            with pytest.raises(OSError):
                os.fstat(fd)


def test_check_only_has_no_runtime_side_effects(prepared_source, monkeypatch):
    before = sorted(str(path) for path in prepared_source.rglob("*"))

    def unexpected(*args, **kwargs):
        pytest.fail("check-only mode must not prepare or launch the runtime")

    monkeypatch.setattr(runtime, "runtime_environment", unexpected)
    monkeypatch.setattr(runtime.subprocess, "run", unexpected)
    monkeypatch.setattr(runtime, "supervise", unexpected)
    assert runtime.main(["--check"]) == 0
    assert sorted(str(path) for path in prepared_source.rglob("*")) == before
