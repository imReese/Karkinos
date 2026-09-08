"""Stop the main source supervisor through its private local control socket."""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import socket
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

SOCKET_NAME = "control.sock"
STOP_TIMEOUT_SECONDS = 45.0
_MAX_CLIENTS = 16
_COMMAND_TIMEOUT_SECONDS = 5.0


@contextmanager
def _working_directory(path: Path):
    # The supervisor is single-threaded. Relative socket names avoid macOS's
    # short sockaddr_un limit without moving the endpoint out of its private dir.
    previous = os.open(".", os.O_RDONLY)
    try:
        os.chdir(path)
        yield
    finally:
        try:
            os.fchdir(previous)
        finally:
            os.close(previous)


def _socket_identity(path: Path) -> tuple[int, int] | None:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISSOCK(entry.st_mode):
        raise ValueError("main control endpoint is not a socket; left untouched")
    return entry.st_dev, entry.st_ino


def _lock_held(runtime_dir: Path) -> bool:
    try:
        descriptor = os.open(runtime_dir / "service.lock", os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("main service lock is not a regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(descriptor)


class MainControl:
    """Poll stop requests while the caller holds service.lock for this context.

    Call complete_stop only after all owned children have stopped. Exiting the
    context without it closes requests without acknowledging successful shutdown.
    """

    def __init__(self, runtime_dir: Path):
        self.runtime_dir = Path(runtime_dir).absolute()
        self.path = self.runtime_dir / SOCKET_NAME
        self.server: socket.socket | None = None
        self.identity: tuple[int, int] | None = None
        self.pending: dict[socket.socket, tuple[bytes, float]] = {}
        self.waiting: list[socket.socket] = []
        self.requested = False

    def __enter__(self):
        if not _lock_held(self.runtime_dir):
            raise ValueError("main control requires the supervisor's service.lock")
        previous_identity = _socket_identity(self.path)
        if previous_identity is not None:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.2)
                try:
                    with _working_directory(self.runtime_dir):
                        probe.connect(SOCKET_NAME)
                except ConnectionRefusedError:
                    if _socket_identity(self.path) != previous_identity:
                        raise ValueError("main control endpoint changed during startup")
                    self.path.unlink()
                else:
                    raise ValueError(
                        "main control socket is already accepting requests"
                    )
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with _working_directory(self.runtime_dir):
                self.server.bind(SOCKET_NAME)
            self.identity = _socket_identity(self.path)
            self.path.chmod(0o600)
            self.server.listen(_MAX_CLIENTS)
            self.server.setblocking(False)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def stop_requested(self) -> bool:
        if self.server is None:
            raise RuntimeError("main control socket is not open")
        for _ in range(_MAX_CLIENTS - len(self.pending) - len(self.waiting)):
            try:
                connection, _ = self.server.accept()
            except BlockingIOError:
                break
            connection.setblocking(False)
            self.pending[connection] = (b"", time.monotonic())
        for connection, (buffer, started) in list(self.pending.items()):
            try:
                data = connection.recv(32)
            except BlockingIOError:
                if time.monotonic() - started < _COMMAND_TIMEOUT_SECONDS:
                    continue
                data = b""
            except OSError:
                data = b""
            buffer += data
            if buffer == b"stop\n":
                del self.pending[connection]
                self.waiting.append(connection)
                self.requested = True
            elif not data or not b"stop\n".startswith(buffer):
                del self.pending[connection]
                try:
                    connection.send(b"error\n")
                except OSError:
                    pass
                connection.close()
            else:
                self.pending[connection] = (buffer, started)
        return self.requested

    def complete_stop(self) -> None:
        self.stop_requested()
        for connection in self.waiting:
            try:
                connection.sendall(b"stopped\n")
            except OSError:
                pass
            finally:
                connection.close()
        self.waiting.clear()

    def __exit__(self, *_args):
        for connection in [*self.pending, *self.waiting]:
            connection.close()
        self.pending.clear()
        self.waiting.clear()
        if self.server is not None:
            self.server.close()
            self.server = None
        if self.identity is not None:
            try:
                if _socket_identity(self.path) == self.identity:
                    self.path.unlink()
            except ValueError:
                pass
            self.identity = None


def _unavailable(runtime_dir: Path) -> int:
    if _lock_held(runtime_dir):
        print(
            "Main source service is still preparing or stopping; retry shortly.",
            file=sys.stderr,
        )
        return 1
    print("Main source service is not running.")
    return 0


def request_stop(runtime_dir: Path, *, timeout: float = STOP_TIMEOUT_SECONDS) -> int:
    runtime_dir = Path(runtime_dir).absolute()
    try:
        if timeout <= 0:
            raise ValueError("stop timeout must be positive")
        if _socket_identity(runtime_dir / SOCKET_NAME) is None:
            return _unavailable(runtime_dir)
        deadline = time.monotonic() + timeout
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            try:
                with _working_directory(runtime_dir):
                    connection.connect(SOCKET_NAME)
            except OSError as exc:
                if exc.errno in {errno.ENOENT, errno.ECONNREFUSED}:
                    return _unavailable(runtime_dir)
                raise
            connection.sendall(b"stop\n")
            response = b""
            while b"\n" not in response and len(response) < 64:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out awaiting shutdown confirmation")
                connection.settimeout(remaining)
                chunk = connection.recv(64 - len(response))
                if not chunk:
                    break
                response += chunk
            if response != b"stopped\n":
                raise ValueError(
                    "supervisor closed or rejected the request without confirming shutdown"
                )
        # This outermost lifecycle lock is released after the control socket and
        # the data/home locks. The acknowledgement alone is too early to restart.
        while _lock_held(runtime_dir):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out awaiting main service lock release")
            time.sleep(min(0.02, remaining))
        print("Stopped main source service.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Main source stop was not confirmed: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=STOP_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    return request_stop(args.runtime_dir, timeout=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
