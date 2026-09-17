"""Contracts for the public source-runtime launcher scripts.

`start_server.sh` and `stop_server.sh` are the public entry points;
`scripts/service/run_dev.py` internals are covered by test_dev_runtime.py.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPO_ROOT / "scripts" / "start_server.sh"
STOP_SCRIPT = REPO_ROOT / "scripts" / "stop_server.sh"

FAKE_COMMIT_SHA = "1" * 40

FAKE_GIT = """#!/bin/sh
# Test double for git: records every invocation and emulates the subset of
# commands the launcher uses. It never touches the real repository.
log="${FAKE_GIT_LOG:?FAKE_GIT_LOG is required}"
printf '%s\\n' "$*" >>"${log}"

if [ "${1:-}" = "-C" ]; then
    shift 2
fi

case "${1:-}" in
    symbolic-ref)
        printf '%s\\n' "${FAKE_GIT_HEAD_BRANCH:-main}"
        ;;
    rev-parse)
        printf '%s\\n' "${FAKE_GIT_COMMIT_SHA:-1111111111111111111111111111111111111111}"
        ;;
    show-ref)
        for last in "$@"; do
            :
        done
        case " ${FAKE_GIT_FAIL_REFS:-} " in
            *" ${last} "*)
                exit 1
                ;;
        esac
        ;;
    worktree)
        if [ "${2:-}" = "add" ]; then
            target=""
            for arg in "$@"; do
                case "${arg}" in
                    worktree|add|--detach|-*) ;;
                    *)
                        if [ -z "${target}" ]; then
                            target="${arg}"
                        fi
                        ;;
                esac
            done
            if [ -n "${target}" ]; then
                mkdir -p "${target}"
                printf 'gitdir: fake\n' >"${target}/.git"
            fi
        fi
        ;;
esac

exit 0
"""

FAKE_PYTHON = """#!PYTHON
# Test double for the Karkinos runtime process: serves the API health
# endpoint (and the web port when requested), records the environment the
# launcher passed, and blocks until terminated.
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _port_from_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return int(value)
    return 0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            body = b'{"service": "karkinos", "status": "alive"}'
        else:
            body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    if sys.argv[1:] == ["-m", "server", "--help"]:
        print("--prepare-database")
        return
    if (
        "--database-status" in sys.argv
        or "--prepare-database" in sys.argv
        or "--prepare-only" in sys.argv
    ):
        print("fake database ready")
        return

    started = os.environ.get("FAKE_RUNTIME_STARTED")
    if started:
        with open(started, "w", encoding="utf-8") as output:
            output.write("started")
    backend = _port_from_env("KARKINOS_BACKEND_PORT", "KARKINOS_DEV_BACKEND_PORT")
    if "--port" in sys.argv:
        backend = int(sys.argv[sys.argv.index("--port") + 1])
    frontend = _port_from_env("KARKINOS_FRONTEND_PORT")
    for port in (backend, frontend):
        if port:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
    dump = os.environ.get("FAKE_RUNTIME_DUMP")
    if dump:
        payload = {
            "argv": list(sys.argv),
            "environment": {
                name: value
                for name, value in os.environ.items()
                if name.startswith("KARKINOS_")
            },
        }
        with open(dump, "w", encoding="utf-8") as output:
            json.dump(payload, output)
    print(f"fake runtime ready pid={os.getpid()}", flush=True)
    threading.Event().wait()


main()
"""


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _git_calls(launcher: SimpleNamespace) -> list[str]:
    return launcher.git_log.read_text(encoding="utf-8").splitlines()


def _meta(launcher: SimpleNamespace) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in (
        (launcher.repo / ".run" / "server.meta")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        key, _, value = line.partition("=")
        meta[key] = value
    return meta


def _start_identity(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _terminate(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@pytest.fixture()
def launcher(tmp_path: Path) -> Iterator[SimpleNamespace]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    (scripts / "service").mkdir(parents=True)
    shutil.copy2(START_SCRIPT, scripts / "start_server.sh")
    shutil.copy2(STOP_SCRIPT, scripts / "stop_server.sh")
    (repo / "config.json").write_text("{}", encoding="utf-8")
    (repo / ".env").write_text("", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    git_log = tmp_path / "git-calls.log"
    uv_log = tmp_path / "uv-calls.log"
    runtime_started = tmp_path / "runtime-started"
    stub_source = FAKE_PYTHON.replace("#!PYTHON", f"#!{sys.executable}")
    python_stub = bin_dir / "python-stub"
    _write_executable(python_stub, stub_source)
    _write_executable(bin_dir / "git", FAKE_GIT)
    _write_executable(
        bin_dir / "uv",
        "#!/bin/sh\n"
        "set -eu\n"
        "# Fake uv: record synchronization and install a runnable Python.\n"
        'printf "%s\\n" "$PWD" "$UV_CACHE_DIR" "$*" >>"${FAKE_UV_LOG:?}"\n'
        'if [ "${FAKE_UV_SYNC_EXIT_CODE:-0}" -ne 0 ]; then\n'
        '    echo "fake uv sync failed" >&2\n'
        '    exit "${FAKE_UV_SYNC_EXIT_CODE}"\n'
        "fi\n"
        'stub="${FAKE_PYTHON_STUB:?FAKE_PYTHON_STUB is required}"\n'
        'if [ "${1:-}" = sync ]; then\n'
        "    mkdir -p .venv/bin\n"
        '    cp "${stub}" .venv/bin/python\n'
        "    chmod 0755 .venv/bin/python\n"
        "fi\n"
        "exit 0\n",
    )
    _write_executable(bin_dir / "npm", "#!/bin/sh\nexit 0\n")

    _write_executable(repo / ".venv" / "bin" / "python", stub_source)
    vite = repo / "web" / "node_modules" / ".bin" / "vite"
    _write_executable(vite, "")

    git = shutil.which("git")
    bash = shutil.which("bash")
    assert git is not None and bash is not None
    subprocess.run([git, "init", "-q", "-b", "main", str(repo)], check=True, timeout=60)

    base_env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "FAKE_GIT_LOG": str(git_log),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_UV_SYNC_EXIT_CODE": "0",
        "FAKE_RUNTIME_STARTED": str(runtime_started),
        "FAKE_GIT_COMMIT_SHA": FAKE_COMMIT_SHA,
        "FAKE_PYTHON_STUB": str(python_stub),
        "KARKINOS_BACKEND_PORT": str(_free_port()),
        "KARKINOS_FRONTEND_PORT": str(_free_port()),
        "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS": "30",
    }

    def run(
        script: str, *args: str, env_extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {**base_env, **(env_extra or {})}
        return subprocess.run(
            [bash, str(scripts / script), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    namespace = SimpleNamespace(
        repo=repo,
        run=run,
        git_log=git_log,
        uv_log=uv_log,
        runtime_started=runtime_started,
        bin_dir=bin_dir,
        git=git,
        bash=bash,
        dump_path=lambda: git_log.parent / "runtime-dump.json",
    )
    try:
        yield namespace
    finally:
        pid_file = repo / ".run" / "server.pid"
        if pid_file.is_file():
            pid_text = pid_file.read_text(encoding="utf-8").strip()
            if pid_text.isdigit():
                _terminate(int(pid_text))


def test_default_start_runs_stable_main(launcher: SimpleNamespace) -> None:
    result = launcher.run(
        "start_server.sh", env_extra={"FAKE_RUNTIME_DUMP": str(launcher.dump_path())}
    )
    assert result.returncode == 0, result.stderr
    assert "Mode:       stable" in result.stdout
    assert "Branch:     main" in result.stdout

    meta = _meta(launcher)
    assert meta["mode"] == "stable"
    assert meta["branch"] == "main"
    assert meta["sha"] == FAKE_COMMIT_SHA
    assert (
        Path(meta["source_root"]).resolve()
        == (launcher.repo / ".run" / "worktrees" / "main").resolve()
    )

    dump = json.loads(launcher.dump_path().read_text(encoding="utf-8"))
    environment = dump["environment"]
    assert Path(environment["KARKINOS_WORKSPACE"]).resolve() == (
        launcher.repo.resolve()
    )
    assert (
        Path(environment["KARKINOS_CONFIG_PATH"]).resolve()
        == (launcher.repo / "config.json").resolve()
    )
    assert (
        Path(environment["KARKINOS_DATA_DIR"]).resolve()
        == (launcher.repo / "data" / "store").resolve()
    )
    assert "server" in dump["argv"]

    calls = _git_calls(launcher)
    assert any(
        "show-ref --verify --quiet refs/remotes/origin/main" in call for call in calls
    ), calls
    assert not any("refs/heads/main" in call for call in calls), calls


def test_dev_start_requires_dev_checkout(launcher: SimpleNamespace) -> None:
    result = launcher.run(
        "start_server.sh", "dev", env_extra={"FAKE_GIT_HEAD_BRANCH": "main"}
    )
    assert result.returncode != 0
    assert "requires the current checkout to be 'dev'" in result.stderr
    assert not (launcher.repo / ".run" / "server.pid").exists()
    assert not launcher.uv_log.exists()
    assert not launcher.runtime_started.exists()


@pytest.mark.parametrize("environment_state", ["ready", "missing", "stale"])
def test_dev_start_runs_current_working_tree(
    launcher: SimpleNamespace, tmp_path: Path, environment_state: str
) -> None:
    if environment_state == "missing":
        shutil.rmtree(launcher.repo / ".venv")
    elif environment_state == "stale":
        # A stale environment cannot run the service until uv repairs it.
        _write_executable(
            launcher.repo / ".venv" / "bin" / "python", "#!/bin/sh\nexit 99\n"
        )
    home = tmp_path / "dev-home"
    result = launcher.run(
        "start_server.sh",
        "dev",
        env_extra={
            "FAKE_GIT_HEAD_BRANCH": "dev",
            "KARKINOS_DEV_HOME": str(home),
        },
    )
    assert result.returncode == 0, result.stderr
    assert "Mode:       development" in result.stdout
    assert "Branch:     dev" in result.stdout
    assert str(home) in result.stdout
    assert launcher.uv_log.read_text(encoding="utf-8").splitlines() == [
        str(launcher.repo),
        str(launcher.repo / ".uv-cache"),
        "sync --locked --extra server --extra dev",
    ]
    assert launcher.runtime_started.is_file()

    meta = _meta(launcher)
    assert meta["mode"] == "development"
    assert meta["branch"] == "dev"
    assert meta["sha"] == "working-tree"
    assert Path(meta["source_root"]).resolve() == launcher.repo.resolve()

    pid = int((launcher.repo / ".run" / "server.pid").read_text(encoding="utf-8"))
    command = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    ).stdout
    assert "run_dev.py" in command


@pytest.mark.parametrize("environment_exists", [True, False])
def test_dev_sync_failure_never_starts_runtime(
    launcher: SimpleNamespace, environment_exists: bool
) -> None:
    if not environment_exists:
        shutil.rmtree(launcher.repo / ".venv")
    result = launcher.run(
        "start_server.sh",
        "dev",
        env_extra={
            "FAKE_GIT_HEAD_BRANCH": "dev",
            "FAKE_UV_SYNC_EXIT_CODE": "42",
        },
    )
    assert result.returncode != 0
    assert "fake uv sync failed" in result.stderr
    assert "dependency sync failed; development server was not started" in result.stderr
    assert launcher.uv_log.is_file()
    assert not launcher.runtime_started.exists()
    assert not (launcher.repo / "logs" / "dev-server.log").exists()
    for name in ("server.pid", "server.start", "server.owner", "server.meta"):
        assert not (launcher.repo / ".run" / name).exists()


def test_dev_start_requires_uv(launcher: SimpleNamespace, tmp_path: Path) -> None:
    # Isolate PATH so an installed uv on the test host cannot mask its absence.
    bin_dir = tmp_path / "no-uv-bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(launcher.bin_dir / "git")
    for name in ("dirname", "mkdir", "rm"):
        executable = shutil.which(name)
        assert executable is not None
        (bin_dir / name).symlink_to(executable)
    result = launcher.run(
        "start_server.sh",
        "dev",
        env_extra={"FAKE_GIT_HEAD_BRANCH": "dev", "PATH": str(bin_dir)},
    )
    assert result.returncode != 0
    assert "'uv' was not found in PATH" in result.stderr
    assert not launcher.uv_log.exists()
    assert not launcher.runtime_started.exists()
    assert not (launcher.repo / ".run" / "server.pid").exists()


def test_launcher_never_fetches_and_never_switches_checkout(
    launcher: SimpleNamespace,
) -> None:
    result = launcher.run(
        "start_server.sh", env_extra={"FAKE_RUNTIME_DUMP": str(launcher.dump_path())}
    )
    assert result.returncode == 0, result.stderr

    forbidden = {"fetch", "pull", "push", "clone", "checkout", "switch"}
    mutating = {"reset", "clean"}
    for call in _git_calls(launcher):
        parts = call.split()
        assert not forbidden & set(parts), call
        if parts[0] == "-C" and parts[2] in mutating:
            assert parts[1] != str(launcher.repo), call

    head = subprocess.run(
        [launcher.git, "-C", str(launcher.repo), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert head.stdout.strip() == "main"


def test_unavailable_branch_fails_closed_without_fetch(
    launcher: SimpleNamespace,
) -> None:
    result = launcher.run(
        "start_server.sh",
        "feature",
        env_extra={
            "FAKE_GIT_FAIL_REFS": "refs/remotes/origin/feature refs/heads/feature"
        },
    )
    assert result.returncode != 0
    assert "is not available locally" in result.stderr
    assert "git fetch origin" in result.stderr
    assert not (launcher.repo / ".run" / "server.pid").exists()

    for call in _git_calls(launcher):
        assert "fetch" not in call.split(), call


@pytest.mark.parametrize("branch", ["main", "dev"])
def test_repeated_start_is_rejected(launcher: SimpleNamespace, branch: str) -> None:
    env = {"FAKE_GIT_HEAD_BRANCH": branch}
    first = launcher.run("start_server.sh", branch, env_extra=env)
    assert first.returncode == 0, first.stderr
    pid = int((launcher.repo / ".run" / "server.pid").read_text(encoding="utf-8"))

    sync_calls = launcher.uv_log.read_text(encoding="utf-8")
    second = launcher.run("start_server.sh", branch, env_extra=env)
    assert second.returncode == 1
    assert "already running" in second.stderr
    assert "stop_server.sh" in second.stderr
    assert launcher.uv_log.read_text(encoding="utf-8") == sync_calls

    os.kill(pid, 0)
    assert (launcher.repo / ".run" / "server.pid").read_text(
        encoding="utf-8"
    ).strip() == str(pid)


def test_stop_rejects_branch_arguments(launcher: SimpleNamespace) -> None:
    started = launcher.run("start_server.sh")
    assert started.returncode == 0, started.stderr
    pid = int((launcher.repo / ".run" / "server.pid").read_text(encoding="utf-8"))

    result = launcher.run("stop_server.sh", "main")
    assert result.returncode == 1
    assert "no arguments" in result.stderr
    os.kill(pid, 0)
    assert (launcher.repo / ".run" / "server.pid").is_file()

    help_result = launcher.run("stop_server.sh", "--help")
    assert help_result.returncode == 0
    assert "stop_server.sh" in help_result.stdout


def test_stop_reports_not_running(launcher: SimpleNamespace) -> None:
    result = launcher.run("stop_server.sh")
    assert result.returncode == 0
    assert "not running" in result.stdout


def test_stop_stops_only_the_managed_runtime(
    launcher: SimpleNamespace,
) -> None:
    started = launcher.run("start_server.sh")
    assert started.returncode == 0, started.stderr
    pid = int((launcher.repo / ".run" / "server.pid").read_text(encoding="utf-8"))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        result = launcher.run("stop_server.sh")
        assert result.returncode == 0, result.stderr
        assert "Karkinos stopped." in result.stdout

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            pytest.fail("managed runtime process survived stop_server.sh")
        assert unrelated.poll() is None
        assert not (launcher.repo / ".run" / "server.pid").exists()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=10)


def test_stop_refuses_unrelated_process_owner(
    launcher: SimpleNamespace,
) -> None:
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        run_dir = launcher.repo / ".run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "server.pid").write_text(str(unrelated.pid), encoding="utf-8")
        (run_dir / "server.start").write_text(
            _start_identity(unrelated.pid), encoding="utf-8"
        )
        (run_dir / "server.owner").write_text(
            "server:/nonexistent/karkinos/python", encoding="utf-8"
        )

        result = launcher.run("stop_server.sh")
        assert result.returncode != 0
        assert "Refusing to stop" in result.stderr
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=10)


def test_stop_refuses_reused_pid(launcher: SimpleNamespace) -> None:
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        run_dir = launcher.repo / ".run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "server.pid").write_text(str(unrelated.pid), encoding="utf-8")
        (run_dir / "server.start").write_text(
            "recorded identity that no longer matches", encoding="utf-8"
        )
        (run_dir / "server.owner").write_text(
            f"server:{sys.executable}", encoding="utf-8"
        )

        result = launcher.run("stop_server.sh")
        assert result.returncode != 0
        assert "process identity changed" in result.stderr
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=10)
