"""Keep provider workers in separate processes owned by the server launcher."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from typing import Literal

logger = logging.getLogger(__name__)


def watch_supervisor_lifetime() -> None:
    """A inherited pipe closes even when the API is killed without cleanup."""
    descriptor = os.environ.pop("KARKINOS_SUPERVISOR_FD", None)
    if descriptor is None:
        return
    fd = int(descriptor)

    def watch():
        try:
            while os.read(fd, 1):
                pass
        finally:
            # Provider threads cannot be safely interrupted in Python. End the
            # worker process; uncommitted SQLite transactions roll back.
            os._exit(70)

    threading.Thread(target=watch, name="supervisor-lifetime", daemon=True).start()


@contextmanager
def supervised_worker(
    *,
    worker: Literal["data", "research"],
    enabled: bool,
    env_file: str | None = None,
):
    if worker not in {"data", "research"}:
        raise ValueError("unsupported worker")
    if not enabled:
        yield
        return
    command = [sys.executable, "-m", "server", f"--{worker}-worker"]
    if env_file is not None:
        command += ["--env-file", env_file]
    stop = threading.Event()
    read_fd, write_fd = os.pipe()
    process = None

    def start():
        return subprocess.Popen(
            command,
            env={**os.environ, "KARKINOS_SUPERVISOR_FD": str(read_fd)},
            pass_fds=(read_fd,),
        )

    try:
        process = start()
    except OSError:
        logger.exception("%s worker unavailable; API remains available", worker)

    def supervise():
        nonlocal process
        while not stop.wait(1):
            if process is None or process.poll() is not None:
                try:
                    process = start()
                except OSError:
                    logger.exception("Failed to restart %s worker", worker)
                    stop.wait(5)

    monitor = threading.Thread(
        target=supervise, name=f"{worker}-worker-supervisor", daemon=True
    )
    monitor.start()
    try:
        yield
    finally:
        stop.set()
        monitor.join()
        os.close(write_fd)
        os.close(read_fd)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
