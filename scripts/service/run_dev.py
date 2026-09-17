"""Run the current checkout with isolated development state."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEVELOPMENT_HOME = Path("~/.karkinos/development").expanduser().absolute()


def development_environment(home: Path) -> dict[str, str]:
    home = home.expanduser().absolute()
    paths = [home, home / "config", home / "data", home / "logs"]
    paths += [home / "config/config.json", home / "config/.env"]
    paths += [home / "data/app.db", home / "data/meta.db"]
    if any(path.is_symlink() for path in paths):
        raise ValueError("development paths must not be symlinks")
    if any(
        (home / name).exists()
        for name in ("current", "releases", ".release-transaction.json")
    ):
        raise ValueError("development must not use an installed runtime home")
    config = home / "config/config.json"
    data = home / "data"
    legacy_database = ROOT / "data/store/app.db"
    if (
        home == DEFAULT_DEVELOPMENT_HOME
        and not (data / "app.db").exists()
        and legacy_database.is_file()
        and legacy_database.stat().st_size > 0
    ):
        raise ValueError(
            "development state is empty while repository data/store/app.db exists; "
            "clone the legacy state into ~/.karkinos/development before starting dev"
        )
    if not config.exists() and data.exists() and any(data.iterdir()):
        raise ValueError(
            "existing development data requires its original configuration",
        )
    for directory in (home, home / "config", data, home / "logs"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not config.exists():
        with config.open("x", encoding="utf-8") as output:
            json.dump(
                {
                    "server": {"market_calendar_auto_sync": False},
                    "ai": {"enabled": False},
                },
                output,
                indent=2,
            )
            output.write("\n")
    env_file = home / "config/.env"
    if not env_file.exists():
        env_file.touch(mode=0o600)
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("KARKINOS_")
    }
    environment.update(
        KARKINOS_HOME=str(home),
        KARKINOS_WORKSPACE=str(home),
        KARKINOS_DATA_DIR=str(data),
        KARKINOS_WORKSPACE_ROLE="development",
        KARKINOS_CONFIG_PATH=str(config),
        KARKINOS_ENV_FILE=str(env_file),
        KARKINOS_STATIC_DIR=str(ROOT / "web/dist"),
        KARKINOS_BACKTEST_REPORT_DIR=str(data / "reports/backtest"),
    )
    return environment


def _startup_failed(environment: dict[str, str]) -> bool:
    configured = environment.get("KARKINOS_STARTUP_STATUS_FILE")
    token = environment.get("KARKINOS_STARTUP_STATUS_TOKEN")
    if not configured or not token:
        return False
    try:
        record = json.loads(Path(configured).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(record, dict)
        and record.get("token") == token
        and record.get("state") == "failed"
    )


def supervise(
    commands: list[list[str]],
    environment: dict[str, str],
    *,
    health_url: str | None = None,
    startup_timeout: float = 60,
) -> int:
    children: list[subprocess.Popen] = []
    interrupted = 0

    def stop(signum, _frame):
        nonlocal interrupted
        interrupted = signum

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    deadline = time.monotonic() + startup_timeout
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def spawn(command):
        children.append(
            subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                start_new_session=True,
            ),
        )

    deferred = commands[1:] if health_url is not None else []
    initial = commands[:1] if health_url is not None else commands
    try:
        for command in initial:
            if interrupted:
                return 128 + interrupted
            spawn(command)
        while not interrupted:
            for child in children:
                result = child.poll()
                if result is not None:
                    return result if result > 0 else 1
            if _startup_failed(environment):
                print(
                    "Development API startup failed; see the original error above.",
                    file=sys.stderr,
                )
                return 1
            if health_url is not None:
                healthy = False
                try:
                    with http.open(health_url, timeout=0.5) as response:
                        health = json.loads(response.read(8192))
                    healthy = (
                        isinstance(health, dict)
                        and health.get("service") == "karkinos"
                        and health.get("status") == "alive"
                    )
                except (OSError, ValueError):
                    pass
                if healthy:
                    health_url = None
                    # Spawn errors must propagate, not be swallowed as HTTP errors.
                    for command in deferred:
                        if interrupted:
                            return 128 + interrupted
                        spawn(command)
                if health_url is not None and time.monotonic() >= deadline:
                    print("Development API startup timed out.", file=sys.stderr)
                    return 1
            time.sleep(0.1)
        return 128 + interrupted
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        for child in children:
            try:
                child.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def port(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=os.environ.get("KARKINOS_DEV_HOME", "~/.karkinos/development"),
    )
    parser.add_argument(
        "--port",
        type=port,
        default=os.environ.get(
            "KARKINOS_DEV_BACKEND_PORT",
            os.environ.get("KARKINOS_BACKEND_PORT", "8000"),
        ),
    )
    parser.add_argument(
        "--web-port",
        type=port,
        default=os.environ.get("KARKINOS_FRONTEND_PORT", "5173"),
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=os.environ.get("KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS", "60"),
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Prepare development state before the launcher's health timeout starts",
    )
    args = parser.parse_args(argv)
    os.umask(0o077)
    lock = None
    status_path = None
    try:
        npm = shutil.which("npm")
        if npm is None or not (ROOT / "web/node_modules/.bin/vite").is_file():
            raise ValueError("install frontend dependencies with: npm ci --prefix web")
        if args.port == args.web_port:
            raise ValueError("backend and frontend ports must be different")
        if not 0 < args.startup_timeout <= 300:
            raise ValueError("startup timeout must be between 0 and 300 seconds")
        for number in (args.port, args.web_port):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", number))
        environment = development_environment(args.home)
        lock_path = Path(environment["KARKINOS_HOME"]) / ".development.lock"
        lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        opened = os.fstat(lock)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ValueError("development lock must be a regular file")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.prepare_only:
            return subprocess.run(
                [sys.executable, "-m", "server", "--prepare-database"],
                cwd=ROOT,
                env=environment,
                check=False,
            ).returncode
        descriptor, configured = tempfile.mkstemp(
            prefix=".startup-",
            suffix=".json",
            dir=environment["KARKINOS_HOME"],
        )
        os.close(descriptor)
        status_path = Path(configured)
        environment["KARKINOS_STARTUP_STATUS_FILE"] = configured
        environment["KARKINOS_STARTUP_STATUS_TOKEN"] = uuid.uuid4().hex
        environment["KARKINOS_DEV_BACKEND_URL"] = f"http://127.0.0.1:{args.port}"
        environment["KARKINOS_CORS_ALLOWED_ORIGINS"] = (
            f"http://127.0.0.1:{args.web_port},http://localhost:{args.web_port}"
        )
        print(
            f"Development checkout: {ROOT}\nDevelopment state: {environment['KARKINOS_HOME']}\nWeb: http://127.0.0.1:{args.web_port}\nAPI: http://127.0.0.1:{args.port}\nPress Ctrl-C to stop both processes.",
            flush=True,
        )
        return supervise(
            [
                [
                    sys.executable,
                    "-m",
                    "server",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                    "--reload-exclude",
                    "tests/**",
                    "--reload-exclude",
                    "web/**",
                ],
                [
                    npm,
                    "--prefix",
                    str(ROOT / "web"),
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.web_port),
                    "--strictPort",
                ],
            ],
            environment,
            health_url=f"http://127.0.0.1:{args.port}/api/health",
            startup_timeout=args.startup_timeout,
        )
    except (OSError, ValueError) as exc:
        print(f"Development startup refused: {exc}", file=sys.stderr)
        return 1
    finally:
        if status_path is not None:
            status_path.unlink(missing_ok=True)
        if lock is not None:
            os.close(lock)


if __name__ == "__main__":
    raise SystemExit(main())
