"""Run a clean main checkout with supervised processes and persistent logs."""

from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import os
import signal
import socket
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .main_background import (
        Startup,
        acknowledge_interrupted_start,
        launch_background,
        redirect_output,
        run_preparation,
        startup_signals,
    )
    from .main_control import MainControl, request_stop
    from .main_logs import MainLogs
    from .main_readiness import startup_ready
    from .source_state import check_prepared, running_record, source_directory
else:
    from main_background import (
        Startup,
        acknowledge_interrupted_start,
        launch_background,
        redirect_output,
        run_preparation,
        startup_signals,
    )
    from main_control import MainControl, request_stop
    from main_logs import MainLogs
    from main_readiness import startup_ready
    from source_state import check_prepared, running_record, source_directory

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
    if any(
        key.startswith("KARKINOS_RELEASE_") or key == "KARKINOS_ARTIFACT_FINGERPRINT"
        for key in env
    ):
        raise ValueError("main source mode cannot inherit managed release environment")

    configured_workspace = env.get("KARKINOS_WORKSPACE")
    legacy_home = env.get("KARKINOS_HOME")
    if configured_workspace and legacy_home:
        workspace = Path(configured_workspace).expanduser()
        legacy = Path(legacy_home).expanduser()
        if not workspace.is_absolute() or not legacy.is_absolute():
            raise ValueError(
                "KARKINOS_WORKSPACE and legacy KARKINOS_HOME must be absolute paths"
            )
        if workspace.resolve() != legacy.resolve():
            raise ValueError(
                "KARKINOS_WORKSPACE and legacy KARKINOS_HOME select different paths"
            )

    selected = configured_workspace or legacy_home or str(root)
    workspace = Path(selected).expanduser()
    if not workspace.is_absolute():
        raise ValueError("KARKINOS_WORKSPACE must be a nonempty absolute path")
    workspace = workspace.resolve()
    env["KARKINOS_WORKSPACE"] = str(workspace)
    # Temporary compatibility for native-release/state code not yet renamed.
    env["KARKINOS_HOME"] = str(workspace)

    for key, default in (
        ("KARKINOS_DATA_DIR", workspace / "data/store"),
        ("KARKINOS_CONFIG_PATH", workspace / "config.json"),
        ("KARKINOS_ENV_FILE", workspace / ".env"),
    ):
        env.setdefault(key, str(default))
    for key in ("KARKINOS_DATA_DIR", "KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"):
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
    workspace = Path(env["KARKINOS_WORKSPACE"])
    default_data = workspace / "data/store"
    if data != default_data:
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
                f"data belongs to another runtime workspace: {data.parent}; "
                "set KARKINOS_WORKSPACE to that directory to retain its recovery protection"
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
            "check KARKINOS_WORKSPACE or use --init only for a new empty workspace"
        )


def require_runtime_idle(env: dict[str, str]) -> None:
    workspace = Path(env["KARKINOS_WORKSPACE"])
    for name in RECOVERY_JOURNALS:
        try:
            (workspace / name).lstat()
        except FileNotFoundError:
            continue
        raise ValueError(f"pending runtime recovery: {workspace / name}; recover it first")
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


def require_port_available(port: int) -> None:
    with socket.socket() as probe:
        address = ("127.0.0.1", port)
        try:
            probe.bind(address)
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            with socket.socket() as connection:
                connection.settimeout(0.5)
                if connection.connect_ex(address) != errno.ECONNREFUSED:
                    raise error
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(address)


def supervise(
    root: Path,
    env: dict[str, str],
    port: int,
    control: MainControl,
    *,
    startup: Startup | None = None,
    logs: MainLogs | None = None,
    ready_callback=None,
) -> int:
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
    started_at = datetime.now(timezone.utc)
    deadline = time.monotonic() + 90
    ready = False
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
            f"Main source service starting at http://127.0.0.1:{port}",
            flush=True,
        )
        while not stopping:
            if logs is not None:
                logs.check_running()
            if control.stop_requested():
                stopping = True
                continue
            if any(child.poll() is not None for child in children):
                print(
                    "A main source process exited; stopping the remaining processes.",
                    file=sys.stderr,
                )
                return 1
            if startup is not None and not ready:
                startup.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("API and worker startup readiness timed out")
                if startup_ready(port, children[1].pid, started_at):
                    if any(child.poll() is not None for child in children):
                        raise ValueError("a main process exited during startup")
                    startup.check()
                    if control.stop_requested():
                        return 1
                    if logs is not None:
                        logs.check_running()
                    if ready_callback is not None:
                        ready_callback()
                    startup.confirm()
                    ready = True
                    print(f"Main ready at http://127.0.0.1:{port}", flush=True)
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
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in the terminal for debugging; Ctrl+C stops the service",
    )
    parser.add_argument("--startup-fd", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--prepared", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    startup = Startup(args.startup_fd)
    try:
        env = runtime_environment(ROOT)
        workspace = Path(env["KARKINOS_WORKSPACE"])
        if args.stop:
            if (
                args.check
                or args.init
                or args.foreground
                or args.startup_fd is not None
            ):
                raise ValueError("--stop cannot be combined with startup options")
            runtime = workspace / ".run" / "main"
            if args.prepared:
                runtime = source_directory(workspace) / "run"
            return request_stop(runtime)
        verify = (
            (lambda root: check_prepared(root, workspace))
            if args.prepared
            else check_source
        )
        sha = verify(ROOT)
        if args.check:
            print(f"Main checkout: {sha}")
            return 0
        port = int(os.environ.get("KARKINOS_MAIN_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("KARKINOS_MAIN_PORT must be between 1 and 65535")
        runtime = (
            source_directory(workspace) / "run"
            if args.prepared
            else workspace / ".run" / "main"
        )
        require_runtime_files(env, initialize=args.init)
        if not args.foreground and args.startup_fd is None:
            command = [sys.executable, str(ROOT / "scripts/service/run_main.py")]
            if args.init:
                command.append("--init")
            if args.prepared:
                command.append("--prepared")
            return launch_background(command, env, workspace / "logs/main.log")
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.ExitStack() as locks:
            locks.enter_context(startup_signals())
            locks.enter_context(exclusive_lock(runtime / "service.lock"))
            locks.enter_context(exclusive_lock(workspace / ".release.lock"))
            require_runtime_idle(env)
            data = Path(env["KARKINOS_DATA_DIR"])
            data.mkdir(parents=True, exist_ok=True, mode=0o700)
            locks.enter_context(exclusive_lock(data / ".source-runtime.lock"))
            require_port_available(port)
            logs = None
            if args.startup_fd is not None:
                logs = locks.enter_context(MainLogs(workspace / "logs"))
                locks.enter_context(redirect_output(logs.stream))
            control = locks.enter_context(MainControl(runtime))
            ready_callback = None
            if args.prepared:
                ready_callback = locks.enter_context(
                    running_record(workspace, ROOT, sha, port, env)
                )

            def monitor():
                startup.check()
                if logs is not None:
                    logs.check_running()
                if control.stop_requested():
                    raise InterruptedError("main startup was stopped")

            print(f"Workspace: {workspace}", flush=True)
            print(
                f"Starting source SHA {sha}; data directory: {env['KARKINOS_DATA_DIR']}",
                flush=True,
            )
            print(f"Configuration: {env['KARKINOS_CONFIG_PATH']}", flush=True)
            print(f"Environment file: {env['KARKINOS_ENV_FILE']}", flush=True)
            with acknowledge_interrupted_start(control):
                commands = (
                    ()
                    if args.prepared
                    else (
                        ["uv", "sync", "--locked", "--extra", "server"],
                        ["npm", "ci", "--prefix", "web"],
                        ["npm", "--prefix", "web", "run", "build"],
                    )
                )
                for command in commands:
                    run_preparation(command, cwd=ROOT, env=env, monitor=monitor)
                if verify(ROOT) != sha:
                    raise ValueError(
                        "main changed during preparation; nothing was started"
                    )
                require_runtime_files(env, initialize=args.init)
                require_runtime_idle(env)
                run_preparation(
                    [str(ROOT / ".venv/bin/python"), "-m", "server", "--check-state"],
                    cwd=ROOT,
                    env=env,
                    monitor=monitor,
                )
                if verify(ROOT) != sha:
                    raise ValueError(
                        "main changed during preflight; nothing was started"
                    )
            return supervise(
                ROOT,
                env,
                port,
                control,
                startup=startup,
                logs=logs,
                ready_callback=ready_callback,
            )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        startup.fail(str(exc))
        print(f"Main source startup refused: {exc}", file=sys.stderr)
        return 1
    finally:
        startup.close()


if __name__ == "__main__":
    raise SystemExit(main())
