"""Source startup never takes over listeners or leaves partially started peers."""

from __future__ import annotations

import errno
import os
import signal
import socket
import subprocess
from unittest.mock import Mock

import pytest

from scripts.service import run_main as runtime


@pytest.fixture
def prepared_source(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setenv("KARKINOS_MAIN_PORT", "8000")
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    workspace = tmp_path / "workspace"
    (workspace / "data/store").mkdir(parents=True)
    (workspace / "config.json").write_text("{}\n")
    (workspace / ".env").write_text("\n")
    for name in ("app.db", "meta.db"):
        (workspace / "data/store" / name).write_text("fixture")
    env = {
        "KARKINOS_WORKSPACE": str(workspace),
        "KARKINOS_HOME": str(workspace),
        "KARKINOS_DATA_DIR": str(workspace / "data/store"),
        "KARKINOS_CONFIG_PATH": str(workspace / "config.json"),
        "KARKINOS_ENV_FILE": str(workspace / ".env"),
        "KARKINOS_STATIC_DIR": str(tmp_path / "web/dist"),
    }
    monkeypatch.setattr(runtime, "runtime_environment", lambda root: env)
    monkeypatch.setattr(runtime, "require_runtime_idle", lambda workspace: None)
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
    assert runtime.main(["--foreground"]) == 1


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

    def unexpected(*args, **kwargs):
        pytest.fail("the verified checkout identity changed")

    native_socket = runtime.socket.socket
    monkeypatch.setattr(
        runtime.socket,
        "socket",
        lambda *args: native_socket(*args) if args else AvailablePort(),
    )
    monkeypatch.setattr(runtime, "run_preparation", run)
    monkeypatch.setattr(runtime, "supervise", unexpected)
    assert runtime.main(["--foreground"]) == 1
    assert len(commands) == 3
    assert all("--check-state" not in command for command in commands)


def test_closed_connection_time_wait_allows_immediate_restart():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(2)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                connection.shutdown(socket.SHUT_WR)
                assert client.recv(1) == b""
                client.shutdown(socket.SHUT_WR)
                assert connection.recv(1) == b""
    with socket.socket() as plain_probe:
        with pytest.raises(OSError) as error:
            plain_probe.bind(("127.0.0.1", port))
        assert error.value.errno == errno.EADDRINUSE
    runtime.require_port_available(port)


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
@pytest.mark.parametrize("reuse", [False, True])
def test_restart_probe_still_refuses_live_listener_without_disturbing_it(host, reuse):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, int(reuse))
        listener.settimeout(2)
        listener.bind((host, 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        with pytest.raises(OSError) as error:
            runtime.require_port_available(port)
        assert error.value.errno == errno.EADDRINUSE
        probe_connection, _ = listener.accept()
        with probe_connection:
            probe_connection.settimeout(2)
            assert probe_connection.recv(1) == b""
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            client.sendall(b"still running")
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(2)
                connection.sendall(connection.recv(32))
            assert client.recv(32) == b"still running"


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

    monkeypatch.setattr(runtime, "run_preparation", unexpected)
    monkeypatch.setattr(runtime, "supervise", unexpected)
    assert runtime.main(["--check"]) == 0
    assert sorted(str(path) for path in prepared_source.rglob("*")) == before
