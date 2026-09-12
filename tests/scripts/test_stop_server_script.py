"""Safety contracts for source snapshot, dev, and resident shutdown."""

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
    resident_api_loaded: bool = False,
    resident_worker_loaded: bool = False,
    controller_available: bool = True,
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
    installed = home / "Library/Application Support/Karkinos"
    api_state = tmp_path / "launchd-api-loaded"
    worker_state = tmp_path / "launchd-worker-loaded"
    plist_dir = home / "Library/LaunchAgents"
    api_plist = plist_dir / "com.karkinos.daily-candidate.plist"
    worker_plist = plist_dir / "com.karkinos.research-worker.plist"

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
        "#!/usr/bin/env bash\n" f'printf "pgrep %s\\n" "$*" >>"{calls}"\n' "exit 1\n",
    )
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "launchctl %s\\n" "$*" >>"{calls}"\n'
        'target="${2:-}"\n'
        'case "${target}" in\n'
        f'  */com.karkinos.daily-candidate) state="{api_state}" ;;\n'
        f'  */com.karkinos.research-worker) state="{worker_state}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n"
        'case "${1:-}" in\n'
        '  print) [[ -f "${state}" ]] ;;\n'
        '  bootout) rm -f "${state}" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
    )

    if controller_available:
        release = installed / "releases" / f"sha-{'a' * 40}"
        (release / "bin").mkdir(parents=True)
        (release / "release.json").write_text("{}\n", encoding="utf-8")
        _write_executable(
            release / "bin/karkinosctl",
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f'printf "controller %s\\n" "$*" >>"{calls}"\n'
            '[[ "${1:-}" == "service-stop" ]] || exit 2\n'
            f'rm -f "{api_state}" "{worker_state}" "{api_plist}" "{worker_plist}"\n',
        )
        (installed / "current").symlink_to(Path("releases") / release.name)

    if resident_api_loaded or resident_worker_loaded:
        plist_dir.mkdir(parents=True, exist_ok=True)
    if resident_api_loaded:
        api_state.touch()
        api_plist.write_text("fixture\n", encoding="utf-8")
    if resident_worker_loaded:
        worker_state.touch()
        worker_plist.write_text("fixture\n", encoding="utf-8")

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BASH_ENV": str(bash_env),
        "KARKINOS_TEST_PROCESS_STATE": str(process_state),
    }
    env.pop("KARKINOS_HOME", None)
    env.pop("KARKINOS_WORKSPACE", None)
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


def test_default_stop_needs_no_all_and_stops_source_and_resident(tmp_path: Path):
    repo, env, calls = _repo(
        tmp_path,
        resident_api_loaded=True,
        resident_worker_loaded=True,
    )
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

    result = _stop(repo, env)

    assert result.returncode == 0, result.stderr
    assert "Karkinos runtimes stopped" in result.stdout
    assert not _alive(env, backend_pid)
    assert not _alive(env, frontend_pid)
    recorded = calls.read_text(encoding="utf-8")
    assert "kill -TERM 4201" in recorded
    assert "kill -TERM 4202" in recorded
    assert f"python3 {repo}/scripts/service/run_main.py --stop" in recorded
    assert f"workspace={repo} branch=main" in recorded
    assert "controller service-stop" in recorded


def test_all_remains_compatibility_alias_for_default_stop(tmp_path: Path):
    repo, env, calls = _repo(tmp_path)
    result = _stop(repo, env, "all")
    assert result.returncode == 0, result.stderr
    assert f"python3 {repo}/scripts/service/run_main.py --stop" in calls.read_text(
        encoding="utf-8"
    )


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
    assert "controller service-stop" not in recorded


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


def test_targeted_snapshot_stop_failure_propagates(tmp_path: Path):
    repo, env, _calls = _repo(tmp_path, source_exit=7)
    result = _stop(repo, env, "main")
    assert result.returncode == 7


def test_prod_uses_default_installed_home_and_release_controller(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_api_loaded=True)
    result = _stop(repo, env, "prod")
    assert result.returncode == 0, result.stderr
    assert "Karkinos resident service stopped" in result.stdout
    assert "controller service-stop" in calls.read_text(encoding="utf-8")


def test_prod_without_controller_boots_out_both_exact_launch_agents(tmp_path: Path):
    repo, env, calls = _repo(
        tmp_path,
        resident_api_loaded=True,
        resident_worker_loaded=True,
        controller_available=False,
    )
    result = _stop(repo, env, "prod")
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "launchctl bootout gui/" in recorded
    assert "com.karkinos.research-worker" in recorded
    assert "com.karkinos.daily-candidate" in recorded
    plist_dir = Path(env["HOME"]) / "Library/LaunchAgents"
    assert not (plist_dir / "com.karkinos.research-worker.plist").exists()
    assert not (plist_dir / "com.karkinos.daily-candidate.plist").exists()
    assert "controller service-stop" not in recorded


def test_prod_rejects_invalid_service_port_before_controller(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_api_loaded=True)
    env["KARKINOS_BACKEND_PORT"] = "65536"
    result = _stop(repo, env, "prod")
    assert result.returncode == 1
    assert "must be an integer from 1 through 65535" in result.stderr
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded


def test_help_never_stops_anything(tmp_path: Path):
    repo, env, calls = _repo(tmp_path, resident_api_loaded=True)
    result = _stop(repo, env, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    recorded = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded
    assert "launchctl bootout" not in recorded
