"""Prepare remote main in an isolated checkout and manage its local service."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if __package__:
    from . import run_main, source_state
    from .main_background import redirect_output, run_preparation, startup_signals
    from .main_control import MainControl, _lock_held, request_stop
    from .main_logs import MainLogs
else:
    import run_main
    import source_state
    from main_background import redirect_output, run_preparation, startup_signals
    from main_control import MainControl, _lock_held, request_stop
    from main_logs import MainLogs

ROOT = Path(__file__).resolve().parents[2]
BINDINGS = source_state.RUNTIME_BINDINGS


@contextlib.contextmanager
def update_lock(source: Path):
    runtime = source / "update"
    source_state.private_directory(runtime)
    try:
        with (
            run_main.exclusive_lock(runtime / "service.lock"),
            MainControl(runtime) as control,
        ):
            try:
                yield control
            finally:
                control.complete_stop()
    except ValueError as exc:
        if str(exc) == f"runtime already in use: {runtime / 'service.lock'}":
            raise ValueError(
                "main update is in progress; use stop_server.sh main to cancel it, then retry"
            ) from exc
        raise


def isolated_environment(root: Path, env: dict[str, str]) -> dict[str, str]:
    """Keep imports, package installation and static output inside this checkout."""
    result = {
        key: value
        for key, value in env.items()
        if not key.startswith(("GIT_", "UV_", "PYTHON"))
        and not key.lower().startswith("npm_config_")
        and key not in {"VIRTUAL_ENV", "NODE_PATH", "NODE_OPTIONS", "BASH_ENV", "ENV"}
    }
    result.update(
        UV_PROJECT_ENVIRONMENT=str(root / ".venv"),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
        KARKINOS_STATIC_DIR=str(root / "web/dist"),
    )
    return result


def runtime_bindings(env: dict[str, str]) -> dict[str, str]:
    return {name: env[name] for name in BINDINGS}


def restore_bindings(home: Path, env: dict[str, str]) -> dict[str, str]:
    record = source_state.read_record(
        source_state.source_directory(home) / "selected.json"
    )
    bindings = record.get("bindings")
    if (
        not isinstance(bindings, dict)
        or set(bindings) != set(BINDINGS)
        or any(not isinstance(value, str) for value in bindings.values())
        or bindings["KARKINOS_HOME"] != str(home)
    ):
        raise ValueError("selected source has invalid runtime configuration")
    for name, value in bindings.items():
        if name.endswith("PORT"):
            if not 1 <= int(value) <= 65535:
                raise ValueError("selected source has invalid port")
        elif (
            not value
            or not Path(value).is_absolute()
            or str(Path(value).resolve()) != value
        ):
            raise ValueError(f"selected {name} is not a stable absolute path")
        supplied = os.environ.get(name)
        if supplied is not None:
            supplied = (
                str(int(supplied))
                if name.endswith("PORT")
                else str(Path(supplied).expanduser().resolve())
            )
            if supplied != value:
                raise ValueError(
                    f"{name} differs from the selected service; use an explicit update"
                )
    return {**env, **bindings}


def require_offline_identity(home: Path, checkout: Path, env: dict[str, str]) -> None:
    try:
        (source_state.source_directory(home) / "activation.json").lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError(
            "an earlier main activation was not completed; inspect --status and retry an online update before offline restart"
        )
    status = selected_status(home)
    process = status["process"]
    if status["running"] and (
        process is None
        or process.get("sha") != checkout.name
        or process.get("bindings") != runtime_bindings(env)
    ):
        raise ValueError(
            "running main differs from the saved selection; inspect --status and retry an online update before offline restart"
        )


def prepare(root: Path, home: Path, env: dict[str, str], monitor) -> Path:
    source = source_state.source_directory(home)
    repository = source / "repository.git"
    remote = source_state.git(root, "remote", "get-url", "origin")
    if not remote or remote.startswith("-"):
        raise ValueError("origin must name a Git remote")
    # Relative file remotes are relative to the developer's checkout, not HOME.
    if ":" not in remote and not Path(remote).is_absolute():
        remote = str((root / remote).resolve())
    git_env = isolated_environment(root, env)
    if not repository.exists():
        run_preparation(
            ["git", "init", "--bare", str(repository)],
            cwd=source,
            env=git_env,
            monitor=monitor,
        )
        source_state.git(repository, "remote", "add", "origin", remote)
    else:
        source_state.private_directory(repository)
        if source_state.git(repository, "remote", "get-url", "origin") != remote:
            raise ValueError(
                "managed source origin differs from this repository; left unchanged"
            )
    run_preparation(
        [
            "git",
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ],
        cwd=repository,
        env=git_env,
        monitor=monitor,
    )
    sha = source_state.git(repository, "rev-parse", "refs/remotes/origin/main^{commit}")
    source_state.revision({"sha": sha})
    checkout = source / "checkouts" / sha
    receipt = source / "prepared" / f"{sha}.json"
    if receipt.exists():
        source_state.check_prepared(checkout, home)
        return checkout
    if checkout.exists():
        # A cancelled build can be resumed; a published checkout is never rebuilt.
        source_state.check_checkout(checkout, home, sha)
        current = selected_status(home)
        if current["running"] and (
            current["process"] is None or current["process"].get("sha") == sha
        ):
            raise ValueError(
                "cannot rebuild a checkout used by the running main service"
            )
    else:
        run_preparation(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "worktree",
                "add",
                "--detach",
                str(checkout),
                sha,
            ],
            cwd=repository,
            env=git_env,
            monitor=monitor,
        )
    build_env = isolated_environment(checkout, env)
    # Package scripts have no reason to inherit daily account paths or credentials.
    build_env = {
        key: value
        for key, value in build_env.items()
        if not key.startswith("KARKINOS_")
    }
    for command in (
        ["uv", "sync", "--locked", "--extra", "server"],
        ["npm", "ci", "--prefix", "web"],
        ["npm", "--prefix", "web", "run", "build"],
    ):
        run_preparation(command, cwd=checkout, env=build_env, monitor=monitor)
    source_state.check_checkout(checkout, home, sha)
    source_state.write_record(
        receipt, {"sha": sha, "build_identity": source_state.build_identity(checkout)}
    )
    return checkout


def selected_status(home: Path) -> dict:
    source = source_state.source_directory(home)
    status = {"running": _lock_held(source / "run"), "log": str(home / "logs/main.log")}
    for name, path in (
        ("selected", source / "selected.json"),
        ("process", source / "run/running.json"),
        ("activation", source / "activation.json"),
    ):
        try:
            status[name] = source_state.read_record(path)
        except FileNotFoundError:
            status[name] = None
    if not status["running"]:
        status["process"] = None
    return status


def activate(
    checkout: Path,
    home: Path,
    env: dict[str, str],
    *,
    restart: bool,
    initialize: bool,
    monitor=lambda: None,
) -> int:
    env = isolated_environment(checkout, env)
    command = [
        str(checkout / ".venv/bin/python"),
        str(checkout / "scripts/service/run_main.py"),
        "--prepared",
    ]
    # Check the candidate's own protocol before stopping an existing supervisor.
    run_preparation([*command, "--check"], cwd=checkout, env=env, monitor=monitor)
    status = selected_status(home)
    if (
        status["running"]
        and not restart
        and status["process"] is not None
        and status["process"].get("sha") == checkout.name
        and status["process"].get("phase") == "ready"
        and status["process"].get("bindings") == runtime_bindings(env)
    ):
        complete_selection(checkout, home, env)
        print(f"Main already running at {checkout.name}; log: {status['log']}")
        return 0
    monitor()
    activation = source_state.source_directory(home) / "activation.json"
    source_state.write_record(
        activation, {"sha": checkout.name, "bindings": runtime_bindings(env)}
    )
    if request_stop(source_state.source_directory(home) / "run"):
        raise ValueError("existing main service did not confirm shutdown")
    if initialize:
        command.append("--init")
    run_preparation(command, cwd=checkout, env=env, monitor=monitor)
    complete_selection(checkout, home, env)
    return 0


def complete_selection(checkout: Path, home: Path, env: dict[str, str]) -> None:
    activation = source_state.source_directory(home) / "activation.json"
    try:
        source_state.write_record(
            source_state.source_directory(home) / "selected.json",
            {"sha": checkout.name, "bindings": runtime_bindings(env)},
        )
        activation.unlink(missing_ok=True)
        source_state.sync_directory(activation.parent)
    except OSError as exc:
        raise RuntimeError(
            "main started, but its selection could not be saved; inspect --status and retry an online update before offline restart"
        ) from exc


def follow_service(home: Path, token: str) -> int:
    """Follow only this instance; a later update must not inherit our Ctrl+C."""
    source = source_state.source_directory(home)
    process = selected_status(home)["process"]
    if process is None or process.get("token") != token:
        return 0
    tail = subprocess.Popen(["tail", "-n", "100", "-F", str(home / "logs/main.log")])
    try:
        while tail.poll() is None:
            current = selected_status(home)["process"]
            if current is None or current.get("token") != process.get("token"):
                return 0
            time.sleep(0.2)
        return tail.returncode
    except KeyboardInterrupt:
        return 0
    finally:
        if tail.poll() is None:
            tail.terminate()
            tail.wait(timeout=5)
        # A concurrent updater holds this lock across shutdown and startup.
        try:
            with update_lock(source):
                current = selected_status(home)["process"]
                if current is not None and current.get("token") == process.get("token"):
                    request_stop(source / "run")
        except ValueError:
            print(
                "A main update is in progress; its service was left running.",
                file=sys.stderr,
            )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--no-update",
        action="store_true",
        help="Start the last selected prepared version without network or builds",
    )
    action.add_argument(
        "--restart",
        action="store_true",
        help="Restart the last selected version without updating",
    )
    action.add_argument(
        "--status",
        action="store_true",
        help="Show selected version and live supervisor identity",
    )
    action.add_argument(
        "--stop", action="store_true", help="Stop the managed main supervisor"
    )
    action.add_argument(
        "--logs", action="store_true", help="Show the last 100 service log lines"
    )
    parser.add_argument(
        "--follow", action="store_true", help="Follow --logs until interrupted"
    )
    parser.add_argument(
        "--init", action="store_true", help="Explicitly initialize a new empty account"
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Follow the service in this terminal; Ctrl+C stops it",
    )
    args = parser.parse_args(argv)
    try:
        if args.follow and not args.logs:
            raise ValueError("--follow requires --logs")
        if (args.init or args.foreground) and (args.status or args.stop or args.logs):
            raise ValueError(
                "startup options cannot be used with status, stop, or logs"
            )
        configured_home = os.environ.get(
            "KARKINOS_HOME", str(Path.home() / "Library/Application Support/Karkinos")
        )
        if not configured_home or not Path(configured_home).expanduser().is_absolute():
            raise ValueError("KARKINOS_HOME must be a nonempty absolute path")
        home = Path(configured_home).expanduser().resolve()
        source = source_state.source_directory(home)
        if args.status:
            print(json.dumps(selected_status(home), indent=2))
            return 0
        if args.logs:
            command = ["tail", "-n", "100"]
            if args.follow:
                command.append("-F")
            return subprocess.call([*command, str(home / "logs/main.log")])
        if args.stop:
            if not source.exists():
                return request_stop(source / "run")
            if request_stop(source / "update"):
                raise ValueError("main update cancellation was not confirmed")
            with update_lock(source):
                return request_stop(source / "run")
        env = run_main.runtime_environment(ROOT)
        env.setdefault("KARKINOS_MAIN_PORT", "8000")
        if not 1 <= int(env["KARKINOS_MAIN_PORT"]) <= 65535:
            raise ValueError("KARKINOS_MAIN_PORT must be between 1 and 65535")
        env["KARKINOS_MAIN_PORT"] = str(int(env["KARKINOS_MAIN_PORT"]))
        if args.no_update or args.restart:
            env = restore_bindings(home, env)
        run_main.require_runtime_files(env, initialize=args.init)
        for path in (source, source / "checkouts", source / "prepared", source / "run"):
            source_state.private_directory(path)
        with startup_signals(), update_lock(source) as update:

            def monitor():
                if update.stop_requested():
                    raise InterruptedError("main update was cancelled")

            if args.no_update or args.restart:
                checkout = source_state.selected_checkout(home)
                require_offline_identity(home, checkout, env)
            else:
                log_dir = home / "logs/source-update"
                log_dir.parent.mkdir(mode=0o700, exist_ok=True)
                print(
                    f"Preparing remote main; build log: {log_dir / 'main.log'}",
                    flush=True,
                )
                with MainLogs(log_dir) as logs, redirect_output(logs.stream):

                    def preparing():
                        logs.check_running()
                        monitor()

                    checkout = prepare(ROOT, home, env, preparing)
            result = activate(
                checkout,
                home,
                env,
                restart=args.restart,
                initialize=args.init,
                monitor=monitor,
            )
            foreground_token = None
            if args.foreground and result == 0:
                process = selected_status(home)["process"]
                if process is not None:
                    foreground_token = process["token"]
        if args.foreground and result == 0:
            return (
                follow_service(home, foreground_token)
                if foreground_token is not None
                else 0
            )
        return result
    except (
        OSError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as exc:
        print(f"Main source operation failed: {exc or 'cancelled'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
