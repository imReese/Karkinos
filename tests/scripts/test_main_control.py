"""Exercise the real local handshake without production paths or PID signaling."""

from __future__ import annotations

import fcntl
import os
import socket
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts.service.main_control import SOCKET_NAME, MainControl, request_stop

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/service/main_control.py"


@pytest.fixture
def runtime(tmp_path):
    # Longer than macOS sockaddr_un permits when used as an absolute pathname.
    directory = tmp_path / ("long-checkout-" * 8) / ".run" / "main"
    directory.mkdir(parents=True, mode=0o700)
    return directory


@contextmanager
def locked(runtime):
    with (runtime / "service.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


@pytest.fixture
def client():
    processes = []

    def start(runtime, *, timeout=2, waiting_marker=None):
        arguments = ["--runtime-dir", str(runtime), "--timeout", str(timeout)]
        command = [sys.executable, str(SCRIPT), *arguments]
        if waiting_marker is not None:
            # Observe two real held-lock probes after the socket acknowledgement.
            # No delay in this wrapper keeps a prematurely successful client alive.
            code = """
import sys
from pathlib import Path
from scripts.service import main_control as control
probe = control._lock_held
count = 0
def record_wait(runtime):
    global count
    held = probe(runtime)
    if held:
        count += 1
        Path(sys.argv[1]).write_text(str(count))
    return held
control._lock_held = record_wait
raise SystemExit(control.main(sys.argv[2:]))
"""
            command = [sys.executable, "-c", code, str(waiting_marker), *arguments]
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        return process

    yield start
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=3)


def wait_for_stop(control):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if control.stop_requested():
            return
        time.sleep(0.005)
    pytest.fail("client did not deliver its stop request")


@contextmanager
def connect(runtime):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        previous = Path.cwd()
        try:
            os.chdir(runtime)
            connection.connect(SOCKET_NAME)
        finally:
            os.chdir(previous)
        connection.settimeout(0.2)
        yield connection


def test_stop_waits_for_completion_and_handles_long_paths(runtime, client):
    previous = Path.cwd()
    with locked(runtime), MainControl(runtime) as control:
        assert Path.cwd() == previous
        assert stat.S_IMODE((runtime / SOCKET_NAME).stat().st_mode) == 0o600
        assert control.stop_requested() is False
        processes = [client(runtime), client(runtime)]
        wait_for_stop(control)
        deadline = time.monotonic() + 3
        while len(control.waiting) != 2 and time.monotonic() < deadline:
            control.stop_requested()
            time.sleep(0.005)
        assert len(control.waiting) == 2
        assert all(process.poll() is None for process in processes)
        control.complete_stop()
    for process in processes:
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "Stopped main source service."
    assert Path.cwd() == previous
    assert not (runtime / SOCKET_NAME).exists()


def test_acknowledgement_waits_for_lock_release_before_restart(runtime, client):
    marker = runtime / "waiting-for-lock"
    with locked(runtime):
        with MainControl(runtime) as control:
            process = client(runtime, waiting_marker=marker)
            wait_for_stop(control)
            control.complete_stop()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                if marker.exists() and marker.read_text() not in {"", "1"}:
                    break
                assert process.poll() is None
                time.sleep(0.005)
            else:
                pytest.fail(
                    "client did not wait for lock release after acknowledgement"
                )
            assert process.poll() is None
        assert not (runtime / SOCKET_NAME).exists()
        assert process.poll() is None
    stdout, stderr = process.communicate(timeout=3)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "Stopped main source service."
    # A successful stop permits an immediate new startup to acquire the lock.
    with locked(runtime), MainControl(runtime) as restarted:
        assert restarted.stop_requested() is False


def test_acknowledgement_without_lock_release_times_out(runtime, client):
    with locked(runtime), MainControl(runtime) as control:
        process = client(runtime, timeout=0.5)
        wait_for_stop(control)
        control.complete_stop()
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 1
        assert "timed out awaiting main service lock release" in stderr
        assert "Stopped" not in stdout


def test_exception_closes_request_without_false_confirmation(runtime, client):
    with locked(runtime):
        with pytest.raises(RuntimeError, match="child shutdown failed"):
            with MainControl(runtime) as control:
                process = client(runtime)
                wait_for_stop(control)
                raise RuntimeError("child shutdown failed")
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 1
        assert "not confirmed" in stderr
        assert "Stopped" not in stdout


def test_client_timeout_never_claims_success(runtime, client):
    with locked(runtime), MainControl(runtime) as control:
        process = client(runtime, timeout=0.5)
        wait_for_stop(control)
        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 1
        assert "not confirmed" in stderr
        assert "Stopped" not in stdout
        # A caller that timed out cannot break the supervisor's eventual cleanup.
        control.complete_stop()


@pytest.mark.parametrize("command", [b"status\n", b"stop now\n", b"stop\nextra"])
def test_unknown_commands_do_not_stop_service(runtime, command):
    with (
        locked(runtime),
        MainControl(runtime) as control,
        connect(runtime) as connection,
    ):
        connection.sendall(command)
        assert control.stop_requested() is False
        assert connection.recv(32) == b"error\n"
        assert control.stop_requested() is False


def test_partial_command_does_not_block_supervisor(runtime):
    with (
        locked(runtime),
        MainControl(runtime) as control,
        connect(runtime) as connection,
    ):
        connection.sendall(b"st")
        assert control.stop_requested() is False
        assert control.stop_requested() is False
        connection.sendall(b"op\n")
        assert control.stop_requested() is True
        with pytest.raises(TimeoutError):
            connection.recv(32)
        control.complete_stop()
        assert connection.recv(32) == b"stopped\n"


def test_missing_socket_distinguishes_absence_from_preparation(runtime, capsys):
    assert request_stop(runtime) == 0
    assert "not running" in capsys.readouterr().out
    with locked(runtime):
        assert request_stop(runtime) == 1
        result = capsys.readouterr()
        assert "preparing or stopping" in result.err
        assert "not running" not in result.out
    assert request_stop(runtime) == 0


def test_missing_runtime_does_not_create_state(tmp_path):
    missing = tmp_path / "absent"
    assert request_stop(missing) == 0
    assert not missing.exists()


@pytest.mark.parametrize("kind", ["file", "directory", "symlink"])
def test_unexpected_endpoint_is_rejected_and_preserved(runtime, kind):
    endpoint = runtime / SOCKET_NAME
    if kind == "file":
        endpoint.write_text("unrelated")
    elif kind == "directory":
        endpoint.mkdir()
    else:
        endpoint.symlink_to(runtime / "missing-target")
    before = endpoint.lstat()
    previous = Path.cwd()
    with locked(runtime), pytest.raises(ValueError, match="not a socket"):
        with MainControl(runtime):
            pytest.fail("unexpected endpoint was accepted")
    assert request_stop(runtime) == 1
    assert endpoint.lstat() == before
    assert Path.cwd() == previous


def test_server_requires_service_lock(runtime):
    with pytest.raises(ValueError, match="requires.*service.lock"):
        with MainControl(runtime):
            pytest.fail("server started without supervisor lock")
    assert not (runtime / SOCKET_NAME).exists()


def test_stale_socket_is_recovered_only_during_locked_startup(runtime):
    code = "import socket; s = socket.socket(socket.AF_UNIX); s.bind('control.sock'); s.close()"
    subprocess.run([sys.executable, "-c", code], cwd=runtime, check=True)
    assert (runtime / SOCKET_NAME).exists()
    assert request_stop(runtime) == 0
    with locked(runtime):
        assert request_stop(runtime) == 1
        with MainControl(runtime) as control:
            assert control.stop_requested() is False
    assert not (runtime / SOCKET_NAME).exists()


def test_existing_listener_is_not_replaced(runtime):
    with locked(runtime), MainControl(runtime) as first:
        identity = (runtime / SOCKET_NAME).stat().st_ino
        with pytest.raises(ValueError, match="already accepting"):
            with MainControl(runtime):
                pytest.fail("live endpoint was replaced")
        assert (runtime / SOCKET_NAME).stat().st_ino == identity
        assert first.stop_requested() is False


def test_cleanup_preserves_replacement_file(runtime):
    endpoint = runtime / SOCKET_NAME
    with locked(runtime), MainControl(runtime):
        endpoint.unlink()
        endpoint.write_text("replacement")
    assert endpoint.read_text() == "replacement"
