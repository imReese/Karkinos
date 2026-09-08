"""Detach source startup with an explicit, cancellable readiness handoff."""

from __future__ import annotations

import contextlib
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

START_TIMEOUT_SECONDS = 600.0


class Startup:
    def __init__(self, descriptor: int | None = None):
        self.connection = (
            socket.socket(fileno=descriptor) if descriptor is not None else None
        )

    def check(self) -> None:
        if (
            self.connection is not None
            and select.select([self.connection], [], [], 0)[0]
        ):
            raise InterruptedError("startup caller disconnected or cancelled")

    def confirm(self) -> None:
        if self.connection is None:
            return
        self.connection.settimeout(5)
        self.connection.sendall(b"ready\n")
        response = b""
        while b"\n" not in response and len(response) < 32:
            chunk = self.connection.recv(32 - len(response))
            if not chunk:
                break
            response += chunk
        if response != b"detach\n":
            raise InterruptedError("startup caller did not accept readiness")
        self.connection.sendall(b"started\n")
        self.close()

    def fail(self, message: str) -> None:
        if self.connection is not None:
            with contextlib.suppress(OSError):
                self.connection.sendall(
                    ("failed: " + message.replace("\n", " ")[:2000] + "\n").encode()
                )

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


@contextlib.contextmanager
def startup_signals():
    def interrupted(signum, _frame):
        raise InterruptedError(f"startup interrupted by signal {signum}")

    previous = {
        sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def redirect_output(stream):
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    try:
        os.dup2(stream.fileno(), 1)
        os.dup2(stream.fileno(), 2)
        yield
    except BaseException as exc:
        with contextlib.suppress(OSError):
            print(f"Main source lifecycle failed: {exc}", file=sys.stderr, flush=True)
        raise
    finally:
        with contextlib.suppress(OSError):
            sys.stdout.flush()
        with contextlib.suppress(OSError):
            sys.stderr.flush()
        for target, descriptor in enumerate(saved, start=1):
            os.dup2(descriptor, target)
            os.close(descriptor)


@contextlib.contextmanager
def acknowledge_interrupted_start(control):
    try:
        yield
    except InterruptedError:
        control.complete_stop()
        raise


def _stop_group(process: subprocess.Popen, *, timeout: float = 30) -> None:
    # Only signal the group created by this Popen, never a saved/reused PID.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # npm/uv descendants may outlive their immediate parent.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def run_preparation(command, *, cwd: Path, env: dict[str, str], monitor) -> None:
    read_fd, write_fd = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--prepare",
                str(read_fd),
                *command,
            ],
            cwd=cwd,
            env=env,
            start_new_session=True,
            pass_fds=(read_fd,),
        )
        while process.poll() is None:
            monitor()
            time.sleep(0.1)
        monitor()
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    except BaseException:
        if process is not None:
            _stop_group(process, timeout=10)
        raise
    finally:
        os.close(write_fd)
        os.close(read_fd)


def _preparation_child(descriptor: int, command: list[str]) -> int:
    def watch():
        try:
            while os.read(descriptor, 1):
                pass
        finally:
            # This wrapper owns the session containing uv/npm and descendants.
            os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=watch, daemon=True).start()
    return subprocess.run(command, check=False).returncode


def launch_background(
    command: list[str],
    env: dict[str, str],
    log_path: Path,
    *,
    timeout: float = START_TIMEOUT_SECONDS,
) -> int:
    parent, child = socket.socketpair()
    process = None
    confirmed = False
    try:
        process = subprocess.Popen(
            [*command, "--startup-fd", str(child.fileno())],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            pass_fds=(child.fileno(),),
            start_new_session=True,
        )
        child.close()
        print(f"Starting main in the background; log: {log_path}", flush=True)
        deadline = time.monotonic() + timeout
        buffer = b""
        ready = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("main startup timed out")
            parent.settimeout(min(1, remaining))
            try:
                chunk = parent.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ValueError("main startup exited without readiness confirmation")
            buffer += chunk
            if len(buffer) > 4096:
                raise ValueError("invalid main startup response")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if line == b"ready" and not ready:
                    ready = True
                    parent.sendall(b"detach\n")
                elif line == b"started" and ready:
                    if process.poll() is not None:
                        raise ValueError("main exited during startup")
                    confirmed = True
                    print(f"Main started. Log: {log_path}")
                    print("Stop with ./scripts/stop_server.sh main")
                    return 0
                else:
                    raise ValueError(line.decode(errors="replace"))
    except (OSError, ValueError, KeyboardInterrupt) as exc:
        print(
            f"Main startup failed: {exc or 'cancelled'}. See {log_path}",
            file=sys.stderr,
        )
        return 1
    finally:
        parent.close()
        child.close()
        if process is not None and not confirmed:
            _stop_group(process)


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "--prepare":
        raise SystemExit("internal preparation wrapper requires an inherited pipe")
    raise SystemExit(_preparation_child(int(sys.argv[2]), sys.argv[3:]))
