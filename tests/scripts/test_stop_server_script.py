"""stop_server.sh resident-service lifecycle behavior."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _stop_script_repo(tmp_path: Path, *, resident_service_loaded: bool) -> Path:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    bin_dir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    (scripts / "stop_server.sh").write_text(
        Path("scripts/stop_server.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (scripts / "stop_server.sh").chmod(0o755)

    calls = tmp_path / "calls.log"
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n" f"exit {0 if resident_service_loaded else 1}\n",
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


def _run_stop_script(repo: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/stop_server.sh"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_stop_server_preserves_loaded_resident_service(tmp_path: Path):
    repo = _stop_script_repo(tmp_path, resident_service_loaded=True)

    result = _run_stop_script(repo, tmp_path)

    assert result.returncode == 0
    assert "resident Web service remains running" in result.stdout
    assert "resident service preserved" in result.stdout
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8")
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
    assert "resident service preserved" in helper.stdout


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
