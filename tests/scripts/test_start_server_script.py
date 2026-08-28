"""start_server.sh dependency bootstrap behavior."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


def test_start_server_bootstraps_frontend_dependencies_before_build():
    script = Path("scripts/start_server.sh").read_text()

    assert "ensure_frontend_dependencies" in script
    assert "npm install" in script
    assert "It installs missing frontend dependencies before building." in script
    assert script.index("ensure_frontend_dependencies") < script.index("npm run build")


def test_start_server_guides_local_data_source_configuration():
    script = Path("scripts/start_server.sh").read_text()

    assert "guide_data_source_configuration" in script
    assert "scripts/data/configure_data_source.py" in script
    assert script.index("guide_data_source_configuration") < script.index(
        "Starting Karkinos Web service"
    )


def test_start_server_documents_scheduler_as_a_service_invariant():
    script = Path("scripts/start_server.sh").read_text()

    assert "The live scheduler starts with the backend" in script
    assert "cannot be disabled independently" in script
    assert "--no-live" not in script
    assert "live_auto_start" not in script
    assert "KARKINOS_LIVE_AUTO_START" not in script
    assert "ENV_PREFIX" not in script
    assert (
        'env "${NO_PROXY_ENV[@]}" UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"' in script
    )


def test_start_server_limits_reload_scope_and_archives_large_logs():
    script = Path("scripts/start_server.sh").read_text()

    assert "--reload-exclude 'tests/**'" in script
    assert "--reload-exclude 'web/**'" in script
    assert "KARKINOS_LOG_MAX_BYTES:-20971520" in script
    assert "rotate_log_if_needed" in script
    assert 'mv -- "${log_file}" "${archived_log}"' in script
    assert 'rm -f "${log_file}"' not in script


def test_start_server_requires_bounded_service_readiness_before_success():
    script = Path("scripts/start_server.sh").read_text()

    assert "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS:-60" in script
    assert "wait_for_backend_readiness" in script
    assert script.index("wait_for_backend_readiness") < script.index(
        'echo "Karkinos Web service started'
    )
    assert "/api/settings/live/status" in script
    assert '"running":true' in script
    assert "financial_readiness" not in script


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _preflight_repo(
    tmp_path: Path,
    *,
    health_response: str,
    curl_exit: int,
    frontend_curl_exit: int = 0,
    live_response: str = '{"running":true,"market_open":false}',
    listener_pids: str = "4242",
    resident_service_loaded: bool = False,
) -> Path:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    bin_dir = tmp_path / "bin"
    scripts.mkdir(parents=True)
    bin_dir.mkdir()
    (repo / "web").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='test'\n")
    (repo / "web" / "package.json").write_text('{"scripts":{"build":"true"}}')
    (scripts / "start_server.sh").write_text(
        Path("scripts/start_server.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (scripts / "start_server.sh").chmod(0o755)
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"python -c"* ]]; then exit 0; fi\n'
        f"touch '{tmp_path / 'uv-launch-called'}'\n"
        "sleep 5\n",
    )
    _write_executable(
        bin_dir / "npm",
        "#!/usr/bin/env bash\n"
        f"touch '{tmp_path / 'npm-called'}'\n"
        'if [[ "$*" == *"run dev"* ]]; then\n'
        f"  touch '{tmp_path / 'npm-dev-called'}'\n"
        "  sleep 5\n"
        "fi\n",
    )
    _write_executable(
        bin_dir / "lsof",
        f"#!/usr/bin/env bash\nprintf '%s' '{listener_pids}'\n",
    )
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *":5173/"* ]]; then\n'
        f"  exit {frontend_curl_exit}\n"
        "fi\n"
        'if [[ "$*" == *"/api/settings/live/status"* ]]; then\n'
        f"  printf '%s' '{live_response}'\n"
        f"  exit {curl_exit}\n"
        "fi\n"
        f"printf '%s' '{health_response}'\n"
        f"exit {curl_exit}\n",
    )
    _write_executable(bin_dir / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n" f"exit {0 if resident_service_loaded else 1}\n",
    )
    return repo


def _stop_tracked_frontend(repo: Path) -> None:
    pid_file = repo / ".run" / "web.pid"
    if not pid_file.is_file():
        return
    try:
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
    except ProcessLookupError:
        pass


def test_start_server_dev_reuses_healthy_resident_backend(tmp_path: Path):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        curl_exit=0,
        resident_service_loaded=True,
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
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
    try:
        assert result.returncode == 0
        assert "Reusing resident Karkinos Web service" in result.stdout
        assert "resident LaunchAgent remains running" in result.stdout
        assert (tmp_path / "npm-dev-called").is_file()
        assert not (tmp_path / "uv-launch-called").exists()
        assert not (repo / ".run" / "server.pid").exists()
        assert (repo / ".run" / "web.pid").is_file()
    finally:
        _stop_tracked_frontend(repo)


def test_start_server_prod_accepts_healthy_resident_backend(tmp_path: Path):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        curl_exit=0,
        resident_service_loaded=True,
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
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

    assert result.returncode == 0
    assert "Resident service is already running" in result.stdout
    assert not (tmp_path / "npm-called").exists()
    assert not (tmp_path / "uv-launch-called").exists()


def test_start_server_fails_closed_for_unhealthy_resident_backend(tmp_path: Path):
    repo = _preflight_repo(
        tmp_path,
        health_response="",
        curl_exit=28,
        listener_pids="",
        resident_service_loaded=True,
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
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

    assert result.returncode == 1
    assert "resident Karkinos LaunchAgent is loaded" in result.stderr
    assert "No fallback backend was launched" in result.stderr
    assert not (tmp_path / "npm-called").exists()
    assert not (tmp_path / "uv-launch-called").exists()


def test_start_server_fails_closed_when_resident_scheduler_is_stopped(
    tmp_path: Path,
):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        live_response='{"running":false,"market_open":false}',
        curl_exit=0,
        listener_pids="",
        resident_service_loaded=True,
    )

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
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

    assert result.returncode == 1
    assert "service readiness is unavailable" in result.stderr
    assert "No fallback backend was launched" in result.stderr
    assert not (tmp_path / "uv-launch-called").exists()


def test_start_server_cleans_up_when_frontend_readiness_times_out(tmp_path: Path):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        curl_exit=0,
        frontend_curl_exit=28,
        resident_service_loaded=True,
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "frontend did not become ready within 1s" in result.stderr
    assert (tmp_path / "npm-dev-called").is_file()
    assert not (tmp_path / "uv-launch-called").exists()
    assert not (repo / ".run" / "web.pid").exists()


def test_start_server_reports_healthy_existing_service_before_build(tmp_path: Path):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        curl_exit=0,
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
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

    assert result.returncode == 1
    assert "already responding at http://127.0.0.1:8000" in result.stderr
    assert "Listener PID(s): 4242" in result.stderr
    assert "No process was terminated." in result.stderr
    assert not (tmp_path / "npm-called").exists()
    assert not (tmp_path / "uv-launch-called").exists()


def test_start_server_reports_unresponsive_listener_without_killing(tmp_path: Path):
    repo = _preflight_repo(tmp_path, health_response="", curl_exit=28)
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
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

    assert result.returncode == 1
    assert "port 8000 is occupied" in result.stderr
    assert "service readiness did not respond" in result.stderr
    assert "Listener PID(s): 4242" in result.stderr
    assert "No process was terminated." in result.stderr
    assert not (tmp_path / "uv-launch-called").exists()


def test_start_server_prod_without_extra_args_handles_empty_server_args(
    tmp_path: Path,
):
    repo = _preflight_repo(
        tmp_path,
        health_response=(
            '{"schema_version":"karkinos.service_health.v1","status":"alive"}'
        ),
        curl_exit=0,
        listener_pids="",
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
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
    try:
        assert result.returncode == 0
        assert "unbound variable" not in result.stderr
        assert "uv run python -m server" in result.stdout
        assert (tmp_path / "uv-launch-called").is_file()
    finally:
        pid_file = repo / ".run" / "server.pid"
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_start_server_cleans_up_launch_when_service_readiness_times_out(
    tmp_path: Path,
):
    repo = _preflight_repo(
        tmp_path,
        health_response="",
        curl_exit=28,
        listener_pids="",
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "service readiness did not become ready within 1s" in result.stderr
    assert (tmp_path / "uv-launch-called").is_file()
    assert not (repo / ".run" / "server.pid").exists()


def test_start_server_rejects_invalid_service_readiness_timeout_before_launch(
    tmp_path: Path,
):
    repo = _preflight_repo(
        tmp_path,
        health_response="",
        curl_exit=28,
        listener_pids="",
    )
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS": "0",
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "must be an integer within [1, 300]" in result.stderr
    assert not (tmp_path / "uv-launch-called").exists()
