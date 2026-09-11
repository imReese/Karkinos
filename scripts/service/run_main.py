"""Run the selected clean source branch from the shared local workspace."""

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
    expected_branch = os.environ.get("KARKINOS_SOURCE_BRANCH", "main")
    current_branch = git(root, "symbolic-ref", "--short", "HEAD")
    if current_branch != expected_branch:
        raise ValueError(
            f"source runtime expected branch {expected_branch!r}, found {current_branch!r}"
        )
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("source runtime requires a clean checkout")
    return git(root, "rev-parse", "HEAD")


def _absolute_path(value: str, name: str) -> str:
    path = Path(value).expanduser()
    if not value or not path.is_absolute():
        raise ValueError(f"{name} must be a nonempty absolute path")
    return str(path.resolve())


def runtime_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    if any(
        key.startswith("KARKINOS_RELEASE_")
        or key == "KARKINOS_ARTIFACT_FINGERPRINT"
        for key in env
    ):
        raise ValueError(
            "source runtime cannot inherit managed release environment"
        )

    configured_workspace = env.get("KARKINOS_WORKSPACE")
    legacy_home = env.get("KARKINOS_HOME")
    if configured_workspace and legacy_home:
        workspace = _absolute_path(configured_workspace, "KARKINOS_WORKSPACE")
        legacy = _absolute_path(legacy_home, "KARKINOS_HOME")
        if workspace != legacy:
            raise ValueError(
                "KARKINOS_WORKSPACE and legacy KARKINOS_HOME select different paths"
            )

    selected = configured_workspace or legacy_home or str(root.resolve())
    workspace = _absolute_path(selected, "KARKINOS_WORKSPACE")
    env["KARKINOS_WORKSPACE"] = workspace
    # Compatibility for runtime code not yet renamed from HOME to WORKSPACE.
    env["KARKINOS_HOME"] = workspace

    defaults = {
        "KARKINOS_DATA_DIR": str(Path(workspace) / "data/store"),
        "KARKINOS_CONFIG_PATH": str(Path(workspace) / "config.json"),
        "KARKINOS_ENV_FILE": str(Path(workspace) / ".env"),
    }
    for name, default in defaults.items():
        env[name] = _absolute_path(env.get(name, default), name)

    env["KARKINOS_STATIC_DIR"] = str(root / "web/dist")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def require_runtime_files(env: dict[str, str], *, initialize: bool) -> None:
    for name in ("KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"):
        if not Path(env[name]).is_file():
            raise ValueError(f"missing {name}: {env[name]}; see scripts/README.md")

    data = Path(env["KARKINOS_DATA_DIR"])
    databases = [data / name for name in ("app.db", "meta.db")]
    if initialize:
        if data.exists() and any(data.iterdir()):
            raise ValueError(
                "--init requires an empty data directory; nothing replaced"
            )
        return

    if not all(
        path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
        for path in databases
    ):
        raise ValueError(
            f"existing account databases missing under {data}; "
            "use --init only for a new empty local workspace"
        )


def require_runtime_idle(workspace: Path) -> None:
    for name in RECOVERY_JOURNALS:
        path = workspace / name
        if path.exists():
            raise ValueError(f"pending runtime recovery: {path}; recover it first")


@contextlib.contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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
) -> int:
    """Own the API and research worker for one source-runtime instance."""

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
        python = str(root / ".venv/bin/python")
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
        print(f"Karkinos starting at http://127.0.0.1:{port}", flush=True)
        while not stopping:
            if logs is not None:
                logs.check_running()
            if control.stop_requested():
                stopping = True
                continue
            if any(child.poll() is not None for child in children):
                print(
                    "A Karkinos process exited; stopping the remaining processes.",
                    file=sys.stderr,
                )
                return 1
            if startup is not None and not ready:
                startup.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("API and worker startup readiness timed out")
                if startup_ready(port, children[1].pid, started_at):
                    if any(child.poll() is not None for child in children):
                        raise ValueError("a Karkinos process exited during startup")
                    startup.check()
                    if control.stop_requested():
                        return 1
                    if logs is not None:
                        logs.check_running()
                    startup.confirm()
                    ready = True
                    print(f"Karkinos ready at http://127.0.0.1:{port}", flush=True)
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
    parser.add_argument("--check", action="store_true", help="Check source identity")
    parser.add_argument(
        "--init", action="store_true", help="Initialize a new empty workspace"
    )
    parser.add_argument("--stop", action="store_true", help="Stop this workspace")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in this terminal; Ctrl+C stops the service",
    )
    parser.add_argument("--startup-fd", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    startup = Startup(args.startup_fd)
    try:
        env = runtime_environment(ROOT)
        workspace = Path(env["KARKINOS_WORKSPACE"])
        runtime = workspace / ".run/main"

        if args.stop:
            if (
                args.check
                or args.init
                or args.foreground
                or args.startup_fd is not None
            ):
                raise ValueError("--stop cannot be combined with startup options")
            return request_stop(runtime)

        sha = check_source(ROOT)
        if args.check:
            print(f"Source checkout: {sha}")
            return 0

        port = int(os.environ.get("KARKINOS_MAIN_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("KARKINOS_MAIN_PORT must be between 1 and 65535")

        require_runtime_files(env, initialize=args.init)
        if not args.foreground and args.startup_fd is None:
            command = [sys.executable, str(ROOT / "scripts/service/run_main.py")]
            if args.init:
                command.append("--init")
            return launch_background(command, env, workspace / "logs/main.log")

        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.ExitStack() as locks:
            locks.enter_context(startup_signals())
            locks.enter_context(exclusive_lock(runtime / "service.lock"))
            locks.enter_context(exclusive_lock(workspace / ".run/source.lock"))
            require_runtime_idle(workspace)

            data = Path(env["KARKINOS_DATA_DIR"])
            data.mkdir(parents=True, exist_ok=True, mode=0o700)
            require_port_available(port)

            logs = None
            if args.startup_fd is not None:
                logs = locks.enter_context(MainLogs(workspace / "logs"))
                locks.enter_context(redirect_output(logs.stream))
            control = locks.enter_context(MainControl(runtime))

            def monitor():
                startup.check()
                if logs is not None:
                    logs.check_running()
                if control.stop_requested():
                    raise InterruptedError("source startup was stopped")

            print(f"Workspace: {workspace}", flush=True)
            print(f"Data: {env['KARKINOS_DATA_DIR']}", flush=True)
            print(f"Configuration: {env['KARKINOS_CONFIG_PATH']}", flush=True)
            print(f"Environment file: {env['KARKINOS_ENV_FILE']}", flush=True)

            with acknowledge_interrupted_start(control):
                for command in (
                    ["uv", "sync", "--locked", "--extra", "server"],
                    ["npm", "ci", "--prefix", "web"],
                    ["npm", "--prefix", "web", "run", "build"],
                ):
                    run_preparation(command, cwd=ROOT, env=env, monitor=monitor)
                if check_source(ROOT) != sha:
                    raise ValueError(
                        "source changed during preparation; nothing was started"
                    )
                require_runtime_files(env, initialize=args.init)
                require_runtime_idle(workspace)
                run_preparation(
                    [str(ROOT / ".venv/bin/python"), "-m", "server", "--check-state"],
                    cwd=ROOT,
                    env=env,
                    monitor=monitor,
                )
                if check_source(ROOT) != sha:
                    raise ValueError(
                        "source changed during preflight; nothing was started"
                    )

            return supervise(ROOT, env, port, control, startup=startup, logs=logs)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        startup.fail(str(exc))
        print(f"Source startup refused: {exc}", file=sys.stderr)
        return 1
    finally:
        startup.close()


if __name__ == "__main__":
    raise SystemExit(main())
