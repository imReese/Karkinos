"""Safety contracts for the user-facing stop command."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/stop_server.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _stop_script_repo(
    tmp_path: Path,
    *,
    resident_service_loaded: bool = False,
    packaged_controller: bool = True,
) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    bin_dir = tmp_path / "bin"
    calls = tmp_path / "calls.log"
    state_file = tmp_path / "launchd-loaded"
    process_state = tmp_path / "process-state"
    bash_env = tmp_path / "bash-env"
    home = tmp_path / "home"
    karkinos_home = tmp_path / "karkinos-home"
    plist = home / "Library" / "LaunchAgents" / "com.karkinos.daily-candidate.plist"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    process_state.mkdir()
    bash_env.write_text("enable -n kill\n", encoding="utf-8")
    copied = scripts / SCRIPT.name
    copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied.chmod(0o755)
    if resident_service_loaded:
        state_file.touch()
        plist.parent.mkdir(parents=True)
        plist.write_text("fixture\n", encoding="utf-8")

    release = karkinos_home / "releases" / f"sha-{'a' * 40}"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    (karkinos_home / "current").symlink_to(Path("releases") / release.name)
    if packaged_controller:
        controller = release / "bin" / "karkinosctl"
        _write_executable(
            controller,
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f'printf "controller %s\\n" "$*" >>"{calls}"\n'
            '[[ "${1:-}" == "service-stop" ]] || exit 2\n'
            f'rm -f "{state_file}" "{plist}"\n',
        )
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "launchctl %s\\n" "$*" >>"{calls}"\n'
        'case "${1:-}" in\n'
        f'  print) [[ -f "{state_file}" ]] ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n",
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
        "set -eu\n"
        f'printf "pgrep %s\\n" "$*" >>"{calls}"\n'
        '[[ "${1:-}" == "-P" ]] || exit 91\n'
        "exit 1\n",
    )
    _write_executable(
        bin_dir / "lsof",
        "#!/usr/bin/env bash\n" f'printf "lsof %s\\n" "$*" >>"{calls}"\n' "exit 92\n",
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "uv %s\\n" "$*" >>"{calls}"\n'
        f'printf "uv-cache=%s dont-write-bytecode=%s\\n" '
        '"${UV_CACHE_DIR:-}" "${PYTHONDONTWRITEBYTECODE:-}" '
        f'>>"{calls}"\n'
        f'rm -f "{state_file}" "{plist}"\n',
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "KARKINOS_HOME": str(karkinos_home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "BASH_ENV": str(bash_env),
        "KARKINOS_TEST_PROCESS_STATE": str(process_state),
    }
    env.pop("UV_CACHE_DIR", None)
    return repo, env, calls


def _register_process(
    env: dict[str, str], pid: int, *, command: str, started_at: str
) -> None:
    state = Path(env["KARKINOS_TEST_PROCESS_STATE"])
    (state / f"alive-{pid}").touch()
    (state / f"command-{pid}").write_text(f"{command}\n", encoding="utf-8")
    (state / f"start-{pid}").write_text(f"{started_at}\n", encoding="utf-8")


def _fake_process_is_alive(env: dict[str, str], pid: int) -> bool:
    state = Path(env["KARKINOS_TEST_PROCESS_STATE"])
    return (state / f"alive-{pid}").exists()


def _write_pid_record(path: Path, pid: int, started_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\t{started_at}\n", encoding="utf-8")


def _run_stop(
    repo: Path, env: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/stop_server.sh", *arguments],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def test_stop_server_has_no_command_or_port_sweep():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "pgrep -f" not in script
    assert "lsof" not in script
    assert "-tiTCP" not in script
    assert 'pgrep -P "${pid}"' in script
    assert "process_start_identity" in script
    assert "process_command" in script
    assert '"${REPO_ROOT}/.run/web.pid"' in script
    assert '"${REPO_ROOT}/.run/dev-server.pid"' in script
    assert (
        'PACKAGED_RELEASE_CONTROL="${KARKINOS_HOME_PATH}/current/bin/karkinosctl"'
        in script
    )
    assert '"${PACKAGED_RELEASE_CONTROL}" "${service_args[@]}"' in script
    assert "RELEASE_MANAGER" not in script
    assert "uv run --frozen" not in script
    assert "explicit release bootstrap workflow" in script
    assert "manage_launch_agent.sh" not in script


def test_stop_server_default_dev_mode_does_not_stop_production(tmp_path: Path) -> None:
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)

    result = _run_stop(repo, env)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "launchd-loaded").is_file()
    recorded_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded_calls
    assert "launchctl print" not in recorded_calls


def test_stop_server_help_and_unknown_mode_never_mutate_services(
    tmp_path: Path,
) -> None:
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)

    help_result = _run_stop(repo, env, "--help")
    invalid_result = _run_stop(repo, env, "unknown")

    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout
    assert invalid_result.returncode == 2
    assert "unknown mode" in invalid_result.stderr
    assert (tmp_path / "launchd-loaded").is_file()
    recorded_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded_calls


def test_stop_server_signals_only_owned_pid_records(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path)
    started_at = "Sun Aug 30 22:00:00 2026"
    backend_pid = 4201
    frontend_pid = 4202
    _register_process(
        env,
        backend_pid,
        command=f"uv run --project {repo} python -m server --reload",
        started_at=started_at,
    )
    _register_process(
        env,
        frontend_pid,
        command=f"{repo}/web/node_modules/.bin/vite --host 127.0.0.1",
        started_at=started_at,
    )
    _write_pid_record(repo / ".run" / "dev-server.pid", backend_pid, started_at)
    _write_pid_record(repo / ".run" / "web.pid", frontend_pid, started_at)

    result = _run_stop(repo, env)

    assert result.returncode == 0, result.stderr
    assert "Stopped Karkinos development backend" in result.stdout
    assert "Stopped Karkinos development frontend" in result.stdout
    assert not (repo / ".run" / "dev-server.pid").exists()
    assert not (repo / ".run" / "web.pid").exists()
    assert not _fake_process_is_alive(env, backend_pid)
    assert not _fake_process_is_alive(env, frontend_pid)
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "kill -TERM 4201" in recorded_calls
    assert "kill -TERM 4202" in recorded_calls
    assert "pgrep -P" in recorded_calls
    assert "pgrep -f" not in recorded_calls
    assert "lsof" not in recorded_calls


def test_stop_server_rejects_reused_pid_with_changed_start_identity(
    tmp_path: Path,
):
    repo, env, calls = _stop_script_repo(tmp_path)
    backend_pid = 4203
    _register_process(
        env,
        backend_pid,
        command=f"uv run --project {repo} python -m server --reload",
        started_at="Sun Aug 30 22:00:00 2026",
    )
    pid_file = repo / ".run" / "dev-server.pid"
    _write_pid_record(pid_file, backend_pid, "Mon Jan  1 00:00:00 2001")

    result = _run_stop(repo, env)

    assert result.returncode == 1
    assert "start identity changed; no process was signaled" in result.stderr
    assert _fake_process_is_alive(env, backend_pid)
    assert pid_file.exists()
    assert "kill -TERM 4203" not in calls.read_text(encoding="utf-8")


def test_stop_server_rejects_pid_whose_command_is_not_owned(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path)
    unrelated_pid = 4204
    started_at = "Sun Aug 30 22:00:00 2026"
    _register_process(
        env,
        unrelated_pid,
        command="/usr/local/bin/unrelated-worker --serve",
        started_at=started_at,
    )
    pid_file = repo / ".run" / "dev-server.pid"
    _write_pid_record(pid_file, unrelated_pid, started_at)

    result = _run_stop(repo, env)

    assert result.returncode == 1
    assert "no longer belongs to Karkinos development backend" in result.stderr
    assert "no process was signaled" in result.stderr
    assert _fake_process_is_alive(env, unrelated_pid)
    assert pid_file.exists()
    assert "kill -TERM 4204" not in calls.read_text(encoding="utf-8")


def test_stop_server_uses_packaged_release_controller(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 0, result.stderr
    assert "Karkinos production service stopped" in result.stdout
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "controller service-stop" in recorded_calls
    assert "--service-port" not in recorded_calls
    assert "uv run" not in recorded_calls
    assert not (tmp_path / "launchd-loaded").exists()


def test_stop_server_prod_removes_persisted_plist_when_launchd_is_unloaded(
    tmp_path: Path,
) -> None:
    repo, env, calls = _stop_script_repo(tmp_path)
    plist = (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )
    plist.parent.mkdir(parents=True)
    plist.write_text("fixture\n", encoding="utf-8")

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 0, result.stderr
    assert "Karkinos production service stopped" in result.stdout
    assert "controller service-stop" in calls.read_text(encoding="utf-8")
    assert not plist.exists()


def test_stop_server_prod_fails_closed_for_unloaded_plist_without_controller(
    tmp_path: Path,
) -> None:
    repo, env, calls = _stop_script_repo(tmp_path, packaged_controller=False)
    plist = (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )
    plist.parent.mkdir(parents=True)
    plist.write_text("fixture\n", encoding="utf-8")

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "failed to stop gui/" in result.stderr
    assert "controller service-stop" not in calls.read_text(encoding="utf-8")
    assert plist.is_file()


def test_stop_server_passes_validated_nondefault_port(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    env["KARKINOS_BACKEND_PORT"] = "8123"

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 0, result.stderr
    assert "controller service-stop --service-port 8123" in calls.read_text(
        encoding="utf-8"
    )


def test_stop_server_rejects_invalid_port_without_calling_controller(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    env["KARKINOS_BACKEND_PORT"] = "not-a-port"

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "must be an integer from 1 through 65535" in result.stderr
    recorded_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "controller service-stop" not in recorded_calls
    assert (tmp_path / "launchd-loaded").exists()


def test_stop_server_fails_closed_without_packaged_release_controller(
    tmp_path: Path,
):
    repo, env, calls = _stop_script_repo(
        tmp_path,
        resident_service_loaded=True,
        packaged_controller=False,
    )

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "explicit release bootstrap workflow" in result.stderr
    assert "failed to stop gui/" in result.stderr
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "uv run" not in recorded_calls
    assert "controller service-stop" not in recorded_calls
    assert (tmp_path / "launchd-loaded").is_file()
    assert (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    ).is_file()


def test_stop_server_rejects_current_resolving_outside_managed_releases(
    tmp_path: Path,
):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    karkinos_home = Path(env["KARKINOS_HOME"])
    external_release = tmp_path / "external" / f"sha-{'b' * 40}"
    (external_release / "bin").mkdir(parents=True)
    (external_release / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        external_release / "bin" / "karkinosctl",
        f"#!/usr/bin/env bash\nprintf 'controller %s\\n' \"$*\" >>'{calls}'\n",
    )
    (karkinos_home / "current").unlink()
    (karkinos_home / "current").symlink_to(external_release)

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "controller service-stop" not in calls.read_text(encoding="utf-8")
    assert (tmp_path / "launchd-loaded").is_file()


def test_stop_server_rejects_mutable_version_named_release(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    karkinos_home = Path(env["KARKINOS_HOME"])
    release = karkinos_home / "releases" / "v0.3.1"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        release / "bin" / "karkinosctl",
        f"#!/usr/bin/env bash\nprintf 'controller %s\\n' \"$*\" >>'{calls}'\n",
    )
    (karkinos_home / "current").unlink()
    (karkinos_home / "current").symlink_to(Path("releases") / release.name)

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "controller service-stop" not in calls.read_text(encoding="utf-8")
    assert (tmp_path / "launchd-loaded").is_file()


def test_stop_server_rejects_symlinked_release_manifest(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    release = (Path(env["KARKINOS_HOME"]) / "current").resolve()
    external_manifest = tmp_path / "external-release.json"
    external_manifest.write_text("{}\n", encoding="utf-8")
    (release / "release.json").unlink()
    (release / "release.json").symlink_to(external_manifest)

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "controller service-stop" not in calls.read_text(encoding="utf-8")
    assert (tmp_path / "launchd-loaded").is_file()


def test_stop_server_rejects_symlinked_release_controller(tmp_path: Path):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    release = (Path(env["KARKINOS_HOME"]) / "current").resolve()
    external_controller = tmp_path / "external-karkinosctl"
    _write_executable(
        external_controller,
        f"#!/usr/bin/env bash\nprintf 'controller %s\\n' \"$*\" >>'{calls}'\n",
    )
    controller = release / "bin" / "karkinosctl"
    controller.unlink()
    controller.symlink_to(external_controller)

    result = _run_stop(repo, env, "prod")

    assert result.returncode == 1
    assert "has no packaged immutable release controller" in result.stderr
    assert "controller service-stop" not in calls.read_text(encoding="utf-8")
    assert (tmp_path / "launchd-loaded").is_file()


def test_stop_server_still_stops_prod_after_pid_record_error(
    tmp_path: Path,
):
    repo, env, calls = _stop_script_repo(tmp_path, resident_service_loaded=True)
    (repo / ".run").mkdir()
    (repo / ".run" / "web.pid").write_text("not-a-pid\n", encoding="utf-8")

    result = _run_stop(repo, env, "all")

    assert result.returncode == 1
    assert "invalid Karkinos development frontend PID record" in result.stderr
    assert "Karkinos production service stopped" in result.stdout
    assert not (tmp_path / "launchd-loaded").exists()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "controller service-stop" in recorded_calls
    assert "uv run" not in recorded_calls
    assert "lsof" not in recorded_calls
