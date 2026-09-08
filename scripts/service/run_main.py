"""Run a clean main checkout in the foreground, without tags or managed releases."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

if __package__:
    from .main_control import MainControl, request_stop
else:
    from main_control import MainControl, request_stop

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_JOURNALS = (".release-transaction.json", ".legacy-bootstrap-transaction.json")
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
    # Do not pretend source execution is an attested immutable release.
    if any(
        key.startswith("KARKINOS_RELEASE_") or key == "KARKINOS_ARTIFACT_FINGERPRINT"
        for key in env
    ):
        raise ValueError("main source mode cannot inherit managed release environment")
    env.setdefault(
        "KARKINOS_HOME", str(Path.home() / "Library/Application Support/Karkinos")
    )
    home = Path(env["KARKINOS_HOME"])
    for key, default in (
        ("KARKINOS_DATA_DIR", home / "data"),
        ("KARKINOS_CONFIG_PATH", home / "config/config.json"),
        ("KARKINOS_ENV_FILE", home / "config/.env"),
    ):
        env.setdefault(key, str(default))
    for key in (
        "KARKINOS_HOME",
        "KARKINOS_DATA_DIR",
        "KARKINOS_CONFIG_PATH",
        "KARKINOS_ENV_FILE",
    ):
        if not env[key] or not Path(env[key]).expanduser().is_absolute():
            raise ValueError(f"{key} must be a nonempty absolute path")
        env[key] = str(Path(env[key]).expanduser().resolve())
    env["KARKINOS_STATIC_DIR"] = str(root / "web/dist")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def require_runtime_files(env: dict[str, str], *, initialize: bool) -> None:
    for key in ("KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"):
        if not Path(env[key]).is_file():
            raise ValueError(f"missing {key}: {env[key]}; see scripts/README.md")
    data = Path(env["KARKINOS_DATA_DIR"])
    home = Path(env["KARKINOS_HOME"])
    if data.parent != home:
        for marker in (
            "current",
            ".service-config.json",
            ".release.lock",
            *RECOVERY_JOURNALS,
        ):
            try:
                (data.parent / marker).lstat()
            except FileNotFoundError:
                continue
            raise ValueError(
                f"data belongs to another runtime home: {data.parent}; "
                "set KARKINOS_HOME to that directory to retain its recovery protection"
            )
    databases = [data / name for name in ("app.db", "meta.db")]
    if initialize:
        if data.exists() and any(
            path.name != ".source-runtime.lock" for path in data.iterdir()
        ):
            raise ValueError(
                "--init requires an empty data directory; nothing replaced"
            )
    elif not all(
        path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
        for path in databases
    ):
        raise ValueError(
            f"existing account databases missing under {data}; "
            "check KARKINOS_HOME or use --init only for a new empty account"
        )


def require_runtime_idle(env: dict[str, str]) -> None:
    home = Path(env["KARKINOS_HOME"])
    for name in RECOVERY_JOURNALS:
        try:
            (home / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError(f"pending runtime recovery: {home / name}; recover it first")
    if sys.platform == "darwin":
        for label in ("com.karkinos.daily-candidate", "com.karkinos.research-worker"):
            result = subprocess.run(
                ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                capture_output=True,
                text=True,
                env={**os.environ, "LC_ALL": "C"},
                timeout=10,
            )
            if result.returncode == 0:
                raise ValueError(
                    f"managed service {label} is loaded; stop it with "
                    "./scripts/stop_server.sh prod before starting main"
                )
            if "Could not find service" not in result.stderr:
                raise ValueError(f"cannot verify managed service {label} is stopped")


@contextlib.contextmanager
def exclusive_lock(path: Path):
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "r+") as stream:
        opened, linked = os.fstat(stream.fileno()), path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise ValueError(f"unsafe runtime lock: {path}")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"runtime already in use: {path}") from exc
        yield


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


def supervise(root: Path, env: dict[str, str], port: int, control: MainControl) -> int:
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
            if control.stop_requested():
                stopping = True
                continue
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
            control.complete_stop()
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
    parser.add_argument(
        "--init", action="store_true", help="Explicitly initialize a new empty account"
    )
    parser.add_argument("--stop", action="store_true", help="Stop this main supervisor")
    args = parser.parse_args(argv)
    try:
        if args.stop:
            if args.check or args.init:
                raise ValueError("--stop cannot be combined with --check or --init")
            return request_stop(ROOT / ".run/main")
        sha = check_source(ROOT)
        if args.check:
            print(f"Main checkout: {sha}")
            return 0
        port = int(os.environ.get("KARKINOS_MAIN_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("KARKINOS_MAIN_PORT must be between 1 and 65535")
        runtime = ROOT / ".run" / "main"
        env = runtime_environment(ROOT)
        require_runtime_files(env, initialize=args.init)
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.ExitStack() as locks:
            locks.enter_context(exclusive_lock(runtime / "service.lock"))
            home = Path(env["KARKINOS_HOME"])
            locks.enter_context(exclusive_lock(home / ".release.lock"))
            require_runtime_idle(env)
            data = Path(env["KARKINOS_DATA_DIR"])
            data.mkdir(parents=True, exist_ok=True, mode=0o700)
            locks.enter_context(exclusive_lock(data / ".source-runtime.lock"))
            # Never stop an existing production service or an unknown listener.
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            print(
                f"Starting source SHA {sha}; data directory: {env['KARKINOS_DATA_DIR']}",
                flush=True,
            )
            print(f"Configuration: {env['KARKINOS_CONFIG_PATH']}", flush=True)
            print(f"Environment file: {env['KARKINOS_ENV_FILE']}", flush=True)
            for command in (
                ["uv", "sync", "--locked", "--extra", "server"],
                ["npm", "ci", "--prefix", "web"],
                ["npm", "--prefix", "web", "run", "build"],
            ):
                subprocess.run(command, cwd=ROOT, env=env, check=True)
            if check_source(ROOT) != sha:
                raise ValueError("main changed during preparation; nothing was started")
            require_runtime_files(env, initialize=args.init)
            require_runtime_idle(env)
            subprocess.run(
                [str(ROOT / ".venv/bin/python"), "-m", "server", "--check-state"],
                cwd=ROOT,
                env=env,
                check=True,
            )
            if check_source(ROOT) != sha:
                raise ValueError("main changed during preflight; nothing was started")
            with MainControl(runtime) as control:
                return supervise(ROOT, env, port, control)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Main source startup refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
