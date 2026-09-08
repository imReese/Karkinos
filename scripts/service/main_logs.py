"""Drain main supervisor output into a private, bounded rotating log."""

from __future__ import annotations

import argparse
import fcntl
import os
import select
import stat
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO

LOG_NAME = "main.log"
MAX_BYTES = 20 * 1024 * 1024
BACKUP_COUNT = 3
READ_BYTES = 64 * 1024


def _identity(entry: os.stat_result) -> tuple[int, int]:
    return entry.st_dev, entry.st_ino


class _LogWriter:
    def __init__(self, directory: Path, max_bytes: int, backups: int):
        if max_bytes <= 0 or backups <= 0:
            raise ValueError("log size and archive count must be positive")
        self.directory = directory.absolute()
        self.max_bytes = max_bytes
        self.backups = backups
        self.directory_fd: int | None = None
        self.lock_fd: int | None = None
        self.log_fd: int | None = None

    def _entry(self, name: str) -> os.stat_result | None:
        try:
            entry = os.stat(name, dir_fd=self.directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if (
            not stat.S_ISREG(entry.st_mode)
            or entry.st_uid != os.getuid()
            or entry.st_nlink != 1
        ):
            raise ValueError(f"unsafe main log entry: {name}")
        return entry

    def _open_file(self, name: str) -> int:
        self._entry(name)
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=self.directory_fd,
        )
        try:
            opened, linked = os.fstat(descriptor), self._entry(name)
            if linked is None or _identity(opened) != _identity(linked):
                raise ValueError(f"main log entry changed while opening: {name}")
            os.fchmod(descriptor, 0o600)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _validate(self) -> None:
        opened = os.fstat(self.directory_fd)
        linked = self.directory.lstat()
        if (
            not stat.S_ISDIR(linked.st_mode)
            or _identity(opened) != _identity(linked)
            or linked.st_uid != os.getuid()
            or linked.st_mode & 0o022
        ):
            raise ValueError("main log directory changed or became unsafe")
        for name in (
            LOG_NAME,
            *(f"{LOG_NAME}.{i}" for i in range(1, self.backups + 1)),
        ):
            self._entry(name)
        if self.lock_fd is not None:
            current_lock = self._entry(".main.log.lock")
            if current_lock is None or _identity(os.fstat(self.lock_fd)) != _identity(
                current_lock
            ):
                raise ValueError("main log lock changed while running")
        if self.log_fd is not None:
            current = self._entry(LOG_NAME)
            if current is None or _identity(os.fstat(self.log_fd)) != _identity(
                current
            ):
                raise ValueError("main log file changed while running")

    def __enter__(self):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        try:
            self.directory_fd = os.open(
                self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            )
            self._validate()
            os.fchmod(self.directory_fd, 0o700)
            self.lock_fd = self._open_file(".main.log.lock")
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("another main log writer is already running") from exc
            for number in range(1, self.backups + 1):
                name = f"{LOG_NAME}.{number}"
                if self._entry(name) is not None:
                    os.close(self._open_file(name))
            self.log_fd = self._open_file(LOG_NAME)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _rotate(self) -> None:
        self._validate()
        os.close(self.log_fd)
        self.log_fd = None
        for number in range(self.backups, 0, -1):
            source = LOG_NAME if number == 1 else f"{LOG_NAME}.{number - 1}"
            if self._entry(source) is not None:
                os.replace(
                    source,
                    f"{LOG_NAME}.{number}",
                    src_dir_fd=self.directory_fd,
                    dst_dir_fd=self.directory_fd,
                )
        self.log_fd = self._open_file(LOG_NAME)

    def write(self, chunk: bytes) -> None:
        view = memoryview(chunk)
        while view:
            self._validate()
            remaining = self.max_bytes - os.fstat(self.log_fd).st_size
            if remaining <= 0:
                self._rotate()
                remaining = self.max_bytes
            written = os.write(self.log_fd, view[:remaining])
            if written <= 0:
                raise OSError("main log write made no progress")
            view = view[written:]

    def __exit__(self, *_args):
        for attribute in ("log_fd", "lock_fd", "directory_fd"):
            descriptor = getattr(self, attribute)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, attribute, None)


class MainLogs:
    """Own the single logger child; redirect output to stream after entering.

    Poll check_running during preparation and serving. Before finish, stop all
    output-producing children and close or restore any duplicated stream fds.
    The child has its own session so terminal signals cannot interrupt draining.
    """

    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int = MAX_BYTES,
        backups: int = BACKUP_COUNT,
    ):
        self.directory = Path(directory)
        self.max_bytes = max_bytes
        self.backups = backups
        self.process: subprocess.Popen | None = None
        self.failure_detail: str | None = None
        self.finished = False

    @property
    def stream(self) -> BinaryIO:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("main logger has not started")
        return self.process.stdin

    def _failure(self) -> RuntimeError:
        if self.failure_detail is None:
            self.failure_detail = (
                self.process.stderr.read(2048).decode("utf-8", errors="replace").strip()
            )
        return RuntimeError(
            f"main log writer exited ({self.process.returncode}): {self.failure_detail}"
        )

    def __enter__(self):
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--directory",
                str(self.directory),
                "--max-bytes",
                str(self.max_bytes),
                "--backups",
                str(self.backups),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=True,
        )
        try:
            ready, _, _ = select.select([self.process.stdout], [], [], 10)
            if not ready:
                raise TimeoutError("main log writer did not become ready")
            if self.process.stdout.readline(32) != b"ready\n":
                self.process.wait(timeout=3)
                raise self._failure()
            return self
        except BaseException:
            self._abort()
            raise

    def check_running(self) -> None:
        if self.process is None:
            raise RuntimeError("main logger has not started")
        if self.process.poll() is not None:
            raise self._failure()

    def _close_pipes(self) -> None:
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()

    def _abort(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=3)
        self._close_pipes()

    def finish(self, *, timeout: float = 10) -> None:
        if self.process is None or self.finished:
            return
        self.stream.close()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._abort()
            self.finished = True
            raise TimeoutError("main log writer did not finish draining") from exc
        try:
            if self.process.returncode != 0:
                raise self._failure()
        finally:
            self._close_pipes()
            self.finished = True

    def __exit__(self, *_args):
        self.finish()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--backups", type=int, default=BACKUP_COUNT)
    args = parser.parse_args(argv)
    try:
        with _LogWriter(args.directory, args.max_bytes, args.backups) as writer:
            print("ready", flush=True)
            while chunk := os.read(sys.stdin.fileno(), READ_BYTES):
                writer.write(chunk)
        return 0
    except (OSError, ValueError) as exc:
        print(f"main log sink failed: {str(exc)[:1024]}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
