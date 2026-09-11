"""Run a development source branch against the shared local workspace."""

from __future__ import annotations

import fcntl
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.__main__ import main  # noqa: E402


def _workspace() -> Path:
    return Path(os.environ.get("KARKINOS_WORKSPACE", str(ROOT))).expanduser().resolve()


def _lock_source_workspace(workspace: Path):
    runtime = workspace / ".run"
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = runtime / "source.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        os.close(descriptor)
        raise ValueError(f"unsafe source runtime lock: {path}")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise ValueError(
            "another Karkinos source backend is already using this workspace"
        ) from exc
    return descriptor


if __name__ == "__main__":
    try:
        lock_fd = _lock_source_workspace(_workspace())
    except (OSError, ValueError) as exc:
        print(f"Development startup refused: {exc}", file=sys.stderr)
        raise SystemExit(1)
    try:
        main()
    finally:
        os.close(lock_fd)
