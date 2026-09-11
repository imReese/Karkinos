"""Safety contracts for source snapshot and dev shutdown."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/stop_server.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _repo(
    tmp_path: Path,
    *,
    resident_service_loaded: bool = False,
    source_exit: int = 0,
) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    service = scripts / "service"
    bin_dir = tmp_path / "bin"
    process_state = tmp_path / "process-state"
    calls = tmp_path / "calls.log"
    bash_env = tmp_path / "bash-env"
    home = tmp_path / "home"
    installed = tmp_path / "installed"
    state_file = tmp_path / "launchd-loaded"
    plist = home / "Library/LaunchAgents/com.karkinos.daily-candidate.plist"

    service.mkdir(parents=True)
    bin_dir.mkdir()
    process_state.mkdir()
    bash_env.write_text("enable -n kill\n", encoding="utf-8")
    copied = scripts / SCRIPT.name
    copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied.chmod(0o755)
    (service / "run_main.py").write_text("# fixture\n", encoding="utf-8")

    _write_executable(
        bin_dir / "python3",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "python3 %s\\n" "$*" >>"{calls}"\n'
        f'printf "workspace=%s branch=%s\\n" "${{KARKINOS_WORKSPACE:-}}" '
        f'"${{KARKINOS_SOURCE_BRANCH:-}}" >>"{calls}"\n'
        f"exit {source_exit}\n",
    )
    _write_executable(
        bin_dir / "ps",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'state="{process_state}"\n'
        '[[ "${1:-}" == "-p" && "${3:-}" == "-o" ]] || exit 2\n'
        'pid="${2}"\n'
        '[[ -f "${state}/alive-${pid}" ]] || exit 1\n'
        'case "${4:-}" in\n'
        '  command=) cat "${state}/command-${pid}" ;;\n'
        '  lstart=) cat "${state}/start-${pid}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "kill",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'state="{process_state}"\n'
        f'printf "kill %s\\n" "$*" >>"{calls}"\n'
        'case "${1:-}" in\n'
        '  -0) [[ -f "${state}/alive-${2:-}" ]] ;;\n'
        '  -TERM|-KILL) rm -f "${state}/alive-${2:-}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "pgrep",
        "#!/usr/bin/env bash\n"
        f'printf "pgrep %s\\n" "$*" >>"{calls}"\n'
        "exit 1\n",
    )
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "print" ]]; then\n'
        f'  [[ -f "{state_file}" ]]\n'
        "  exit $?\n"
        "fi\n"
        "exit 2\n",
    )

    release = installed / "releases" / f"sha-{'a' * 40}"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        release / "bin/karkinosctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "controller %s\\n" "$*" >>"{calls}"\n'
        f'rm -f "{state_file}" "{plist}"\n',
    )
    (installed / "current").symlink_to(Path("releases") / release.name)

    if resident_service_loaded:
        state_file.touch()
        plist.parent.mkdir(parents=True)
        plist.write_text("fixture\n", encoding="utf-8")

    env = {
        **os.environ,
        "HOME": str(home),
        "KARKINOS_HOME": str(installed),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BASH_ENV": str(bash_env),
        "KARKINOS_TEST_PROCESS_STATE": str(process_state),
    }
    return repo, env, calls


def _register_process(
    env: dict[str, str], pid: int, *, command: str, started_at: str
) -> None:
    state = Path(env["KARKINOS_TEST_PROCESS_STATE"])
    (state / f"alive-{pid}").touch()
    (state / f"command-{pid}").write_text(f"{command}\n", encoding="utf-8")
    (state / f"start-{pid}").write_text(f"{started_at}\n", encoding="utf-8")


def _alive(env: dict[str, str], pid: int) -> bool:
    return (Path(env["KARKINOS_TEST_PROCESS_STATE"]) / f"alive-{pid}").exists()


def _pid(path: Path, pid: int, started_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\t{started_at}\n", encoding="utf-8")


def _stop(
    repo: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/stop_server.sh", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_default_stop_targets_main_snapshot_in_repo_workspace(tmp_path: Path):
    repo, env, calls = _repo(tmp_path)
    result = _stop(repo, env)
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert f"python3 {repo}/scripts/service/run_main.py --stop" in recorded
    assert f"workspace={repo} branch=main" in recorded


def test_arbitrary_snapshot_branch_uses_control_driver_not_dev_pid_files(
    tmp_path: Path,
):
    repo, env, calls = _repo(tmp_path)
    result = _stop(repo, env, "feature/research")
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert f"python3 {repo}/scripts/service/run_main.py --stop" in recorded
    assert f"workspace={repo} branch=feature/research" in recorded


def test_dev_stop_signals_only_owned_pid_records(tmp_path: Path):
    repo, env, calls = _repo(tmp_path)
    started = "Sun Aug 30 22:00:00 2026"
    backend_pid = 4201
    frontend_pid = 4202
    _register_process(
        env,
        backend_pid,
        command=f"python {repo}/scripts/service/run_dev.py --reload",
        started_at=started,
    )
    _register_process(
        env,
        frontend_pid,
        command=f"{repo}/web/node_modules/.bin/vite --host 127.0.0.1",
        started_at=started,
    )
    _pid(repo / ".run/dev/backend.pid", backend_pid, started)
    _pid(repo / ".run/dev/frontend.pid", frontend_pid, started)

    result = _stop(repo, env, "dev")

    assert result.returncode == 0, result.stderr
    assert not _alive(env, backend_pid)
    assert not _alive(env, frontend_pid)
    assert not (repo / ".run/dev/backend.pid").exists()
    assert not (repo / ".run/dev/frontend.pid").exists()
    recorded = calls.read_text(encoding="utf-8")
    assert "kill -TERM 4201" in recorded
    assert "kill -TERM 4202" in recorded
    assert "pgrep -P" in recorded


def test_dev_stop_rejects_reused_pid_identity(tmp_path: Path):
    repo, env, calls = _repo(tmp_path)
    pid = 4203
    _register_process(
        env,
        pid,
        command=f"python {repo}/scripts/service/run_dev.py --reload",
        started_at="Sun Aug 30 22:00:00 2026",
    )
    pid_file = repo / ".run/dev/backend.pid"
    _pid(pid_file, pid, "Mon Jan  1 00:00:00 2001")

    result = _stop(repo, env, "dev")

    assert result.returncode == 1
    assert "start identity changed; no process was signaled" in result.stderr
    assert _alive(env, pid)
    assert pid_file.exists()
    assert "kill -TERM 4203" not in calls.read_text(encoding="utf-8")


def test_snapshot_stop_failure_propagates(tmp_path: Path):
    repo, env, _calls = _repo(tmp_path, source_exit=7)
    result = _stop(repo, env)
    assert result.returncode == 7


def test_prod_uses_installed_release_controller(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_service_loaded=True)
    result = _stop(repo, env, "prod")
    assert result.returncode == 0, result.stderr
    assert "Karkinos production service stopped" in result.stdout
    assert "controller service-stop" in calls.read_text(encoding="utf-8")


def test_prod_rejects_invalid_service_port_before_controller(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_service_loaded=True)
    env["KARKINOS_BACKEND_PORT"] = "65536"
    result = _stop(repo, env, "prod")
    assert result.returncode == 1
    assert "must be an integer from 1 through 65535" in result.stderr
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded


def test_help_never_stops_anything(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_service_loaded=True)
    result = _stop(repo, env, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded
