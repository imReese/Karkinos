"""Run a clean main checkout in the foreground, without tags or managed releases."""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHILD_ENTRY = (
    "from server.workers.supervisor import watch_supervisor_lifetime; "
    "watch_supervisor_lifetime(); "
    "from server.__main__ import main; main()"
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def check_source(root: Path) -> str:
    if git(root, "symbolic-ref", "--short", "HEAD") != "main":
        raise ValueError(
            "main source mode requires the main branch; no checkout was changed"
        )
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError(
            "main source mode requires a clean checkout; commit or move local changes first"
        )
    sha = git(root, "rev-parse", "HEAD")
    if sha != git(root, "rev-parse", "refs/remotes/origin/main"):
        raise ValueError(
            "local main differs from fetched origin/main; use git pull --ff-only"
        )
    return sha


def runtime_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("KARKINOS_DATA_DIR", str(root / ".run" / "main" / "data"))
    env.setdefault("KARKINOS_CONFIG_PATH", str(root / "config.json"))
    env.setdefault("KARKINOS_ENV_FILE", str(root / ".env"))
    # Do not pretend source execution is an attested immutable release.
    if any(
        key.startswith("KARKINOS_RELEASE_") or key == "KARKINOS_ARTIFACT_FINGERPRINT"
        for key in env
    ):
        raise ValueError("main source mode cannot inherit managed release environment")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def stop_children(children) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def supervise(root: Path, env: dict[str, str], port: int) -> int:
    """Own both processes; inherited lifetime pipes also handle abrupt parent death."""
    children = []
    read_fd, write_fd = os.pipe()
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        python = str(root / ".venv" / "bin" / "python")
        for args in (
            ("--host", "127.0.0.1", "--port", str(port)),
            ("--research-worker",),
        ):
            children.append(
                subprocess.Popen(
                    [python, "-c", CHILD_ENTRY, *args],
                    cwd=root,
                    env={**env, "KARKINOS_SUPERVISOR_FD": str(read_fd)},
                    pass_fds=(read_fd,),
                    start_new_session=True,
                )
            )
        print(
            f"Main source service starting at http://127.0.0.1:{port}; Ctrl+C stops both processes.",
            flush=True,
        )
        while not stopping:
            if any(child.poll() is not None for child in children):
                print(
                    "A main source process exited; stopping the remaining processes.",
                    file=sys.stderr,
                )
                return 1
            time.sleep(0.2)
        return 0
    finally:
        try:
            stop_children(children)
        finally:
            os.close(write_fd)
            os.close(read_fd)
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check checkout identity without installing or starting anything",
    )
    args = parser.parse_args(argv)
    try:
        sha = check_source(ROOT)
        if args.check:
            print(f"Main checkout: {sha}")
            return 0
        port = int(os.environ.get("KARKINOS_MAIN_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("KARKINOS_MAIN_PORT must be between 1 and 65535")
        runtime = ROOT / ".run" / "main"
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (runtime / "service.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("a main source supervisor is already running") from exc
            # Never stop an existing production service or an unknown listener.
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            env = runtime_environment(ROOT)
            print(
                f"Starting source SHA {sha}; data directory: {env['KARKINOS_DATA_DIR']}",
                flush=True,
            )
            for command in (
                ["uv", "sync", "--locked", "--extra", "server"],
                ["npm", "ci", "--prefix", "web"],
                ["npm", "--prefix", "web", "run", "build"],
                [str(ROOT / ".venv/bin/python"), "-m", "server", "--check-state"],
            ):
                subprocess.run(command, cwd=ROOT, env=env, check=True)
            if check_source(ROOT) != sha:
                raise ValueError("main changed during preparation; nothing was started")
            return supervise(ROOT, env, port)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Main source startup refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
