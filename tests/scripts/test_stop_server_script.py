"""stop_server.sh resident-service lifecycle behavior."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _stop_script_repo(tmp_path: Path, *, resident_service_loaded: bool) -> Path:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    service_scripts = scripts / "service"
    bin_dir = tmp_path / "bin"
    service_scripts.mkdir(parents=True)
    bin_dir.mkdir()
    (scripts / "stop_server.sh").write_text(
        Path("scripts/stop_server.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (scripts / "stop_server.sh").chmod(0o755)
    shutil.copy2(
        Path("scripts/service/manage_launch_agent.sh"),
        service_scripts / "manage_launch_agent.sh",
    )

    calls = tmp_path / "calls.log"
    state_file = tmp_path / "launchd-loaded"
    plist = (
        tmp_path
        / "home"
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )
    if resident_service_loaded:
        state_file.touch()
        plist.parent.mkdir(parents=True)
        plist.write_text("fixture\n", encoding="utf-8")
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "launchctl %s\\n" "$*" >>"{calls}"\n'
        'case "${1:-}" in\n'
        f'  print) [[ -f "{state_file}" ]] ;;\n'
        "  bootout)\n"
        '    if [[ "${KARKINOS_TEST_STICKY_LAUNCH_AGENT:-0}" != "1" ]]; then\n'
        f'      rm -f "{state_file}"\n'
        "    fi\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    _write_executable(
        bin_dir / "pgrep",
        f'#!/usr/bin/env bash\nprintf "pgrep %s\\n" "$*" >>"{calls}"\n',
    )
    _write_executable(
        bin_dir / "lsof",
        f'#!/usr/bin/env bash\nprintf "lsof %s\\n" "$*" >>"{calls}"\n',
    )
    return repo


def _run_stop_script(
    repo: Path,
    tmp_path: Path,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/stop_server.sh"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS": "1",
            **(env_overrides or {}),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_stop_server_uninstalls_loaded_resident_service(tmp_path: Path):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=True)

    result = _run_stop_script(repo, tmp_path)

    assert result.returncode == 0
    assert "Karkinos resident Web service stopped" in result.stdout
    assert "Karkinos Web processes stopped" in result.stdout
    assert not (tmp_path / "launchd-loaded").exists()
    assert not (
        tmp_path
        / "home"
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    ).exists()
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "launchctl bootout gui/" in calls
    assert "5173" in calls
    assert "8000" not in calls
    assert "python.* -m server" not in calls
    assert "uv run python -m server" not in calls


def test_stop_server_does_not_signal_callers_process_group(tmp_path: Path):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=True)
    helper = subprocess.run(
        [
            "bash",
            "-c",
            "sleep 60 & child=$!; mkdir -p .run; "
            'printf "%s\\n" "$child" >.run/web.pid; '
            "bash scripts/stop_server.sh",
        ],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
        start_new_session=True,
        timeout=15,
    )

    assert helper.returncode == 0
    assert "Stopped Karkinos Web frontend" in helper.stdout
    assert "Karkinos resident Web service stopped" in helper.stdout


def test_stop_server_keeps_manual_backend_cleanup_without_resident_service(
    tmp_path: Path,
):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=False)

    result = _run_stop_script(repo, tmp_path)

    assert result.returncode == 0
    assert "Karkinos Web processes stopped" in result.stdout
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
    assert "5173" in calls
    assert "8000" in calls
    assert "python.* -m server" in calls
    assert "uv run python -m server" in calls


def test_stop_server_fails_when_resident_remains_loaded(tmp_path: Path):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=True)

    result = _run_stop_script(
        repo,
        tmp_path,
        env_overrides={"KARKINOS_TEST_STICKY_LAUNCH_AGENT": "1"},
    )

    assert result.returncode != 0
    assert (tmp_path / "launchd-loaded").exists()
    assert (
        tmp_path
        / "home"
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    ).exists()
    assert "Karkinos Web processes stopped" not in result.stdout


def test_stop_server_attempts_resident_uninstall_after_frontend_error(
    tmp_path: Path,
):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=True)
    (repo / ".run").mkdir()
    (repo / ".run" / "web.pid").write_text("invalid\n", encoding="utf-8")

    result = _run_stop_script(repo, tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / "launchd-loaded").exists()
    assert "Karkinos resident Web service stopped" in result.stdout
    assert "Karkinos Web processes stopped" not in result.stdout
