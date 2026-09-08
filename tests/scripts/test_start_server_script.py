"""Executable contracts for the user-facing start command."""

from __future__ import annotations

import os
import select
import shlex
import signal
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/start_server.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _copy_start_script(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    service_scripts = scripts / "service"
    bin_dir = tmp_path / "bin"
    service_scripts.mkdir(parents=True)
    bin_dir.mkdir()
    copied = scripts / SCRIPT.name
    copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied.chmod(0o755)
    return repo, bin_dir


def _prod_repo(
    tmp_path: Path, *, with_controller: bool = True
) -> tuple[Path, dict[str, str], Path]:
    repo, bin_dir = _copy_start_script(tmp_path)
    calls = tmp_path / "release-controller-calls.log"
    karkinos_home = tmp_path / "karkinos-home"
    release = karkinos_home / "releases" / f"sha-{'a' * 40}"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    (karkinos_home / "current").symlink_to(Path("releases") / release.name)
    if with_controller:
        controller = release / "bin" / "karkinosctl"
        _write_executable(
            controller,
            "#!/usr/bin/env bash\n" "set -eu\n" f'printf "%s\\n" "$*" >>"{calls}"\n',
        )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n" f"touch '{tmp_path / 'unexpected-uv'}'\n" "exit 97\n",
    )
    _write_executable(
        bin_dir / "npm",
        "#!/usr/bin/env bash\n" f"touch '{tmp_path / 'unexpected-npm'}'\n" "exit 97\n",
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "KARKINOS_HOME": str(karkinos_home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    return repo, env, calls


def _dev_repo(
    tmp_path: Path,
    *,
    health_ready: bool = True,
    frontend_ready: bool = True,
    backend_child: bool = False,
) -> tuple[Path, dict[str, str], Path]:
    repo, bin_dir = _copy_start_script(tmp_path)
    calls = tmp_path / "calls.log"
    (repo / "web").mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    (repo / "web" / "package.json").write_text(
        '{"scripts":{"build":"true","dev":"true"}}\n', encoding="utf-8"
    )
    (repo / "web" / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (repo / "web" / ".npmrc").write_text("engine-strict=true\n")
    spawn_child = (
        'bash -c \'trap "" TERM; '
        f'echo $$ > "{tmp_path / "backend-child.pid"}"; exec sleep 60'
        "' &\n"
        if backend_child
        else ""
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "uv %s\\n" "$*" >>"{calls}"\n'
        'if [[ "$*" == *"python -c"* ]]; then exit 0; fi\n'
        f"printf '%s\\n' \"$$\" >'{tmp_path / 'uv-launch-called'}'\n"
        + spawn_child
        + "exec sleep 60\n",
    )
    _write_executable(
        bin_dir / "npm",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "npm %s\\n" "$*" >>"{calls}"\n'
        'if [[ "$*" == "ci" ]]; then\n'
        '  if [[ "${KARKINOS_TEST_NPM_CI_EXIT:-0}" != "0" ]]; then\n'
        '    exit "${KARKINOS_TEST_NPM_CI_EXIT}"\n'
        "  fi\n"
        "  mkdir -p node_modules/.bin node_modules/vitest\n"
        "  touch node_modules/.bin/vite node_modules/vitest/globals.d.ts\n"
        "  chmod +x node_modules/.bin/vite\n"
        "fi\n"
        'if [[ "$*" == *"run dev"* ]]; then\n'
        f'  printf "vite-backend=%s\\n" "${{KARKINOS_DEV_BACKEND_URL:-}}" >>"{calls}"\n'
        f"  printf '%s\\n' \"$$\" >'{tmp_path / 'npm-dev-called'}'\n"
        "  exec sleep 60\n"
        "fi\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "lsof",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "lsof %s\\n" "$*" >>"{calls}"\n'
        'case "$*" in\n'
        '  *TCP:8000*) printf "%s\\n" "${KARKINOS_TEST_PROD_LISTENER:-4242}" ;;\n'
        '  *TCP:8001*) printf "%s\\n" "${KARKINOS_TEST_DEV_LISTENER:-}" ;;\n'
        '  *TCP:5173*) printf "%s\\n" "${KARKINOS_TEST_FRONTEND_LISTENER:-}" ;;\n'
        "esac\n",
    )
    health_exit = 0 if health_ready else 28
    frontend_exit = 0 if frontend_ready else 28
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "curl %s\\n" "$*" >>"{calls}"\n'
        'if [[ "$*" == *":5173/"* ]]; then\n'
        f"  exit {frontend_exit}\n"
        "fi\n"
        'if [[ "$*" == *"/api/settings/live/status"* ]]; then\n'
        '  printf \'{"running":true,"market_open":false}\'\n'
        f"  exit {health_exit}\n"
        "fi\n"
        "printf '%s' "
        "'{'"
        '\'"schema_version":"karkinos.service_health.v1",\''
        '\'"service":"karkinos","status":"alive"\''
        "'}'\n"
        f"exit {health_exit}\n",
    )
    _write_executable(
        bin_dir / "launchctl",
        "#!/usr/bin/env bash\n"
        f"touch '{tmp_path / 'unexpected-launchctl'}'\n"
        "exit 0\n",
    )
    _write_executable(
        bin_dir / "ps",
        "#!/usr/bin/env bash\n"
        '[[ "${1:-}" == "-p" && "${3:-}" == "-o" '
        '&& "${4:-}" == "lstart=" ]] || exit 2\n'
        "printf '%s\\n' 'Sun Aug 30 22:00:00 2026'\n",
    )
    _write_executable(bin_dir / "pgrep", "#!/usr/bin/env bash\nexit 1\n")
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS": "2",
        "KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS": "2",
    }
    return repo, env, calls


def _terminate_pid_record(path: Path) -> None:
    if not path.is_file():
        return
    raw_pid = path.read_text(encoding="utf-8").split("\t", 1)[0]
    if not raw_pid.isdigit():
        return
    try:
        os.kill(int(raw_pid), signal.SIGTERM)
    except ProcessLookupError:
        pass


def _cleanup_dev_processes(repo: Path) -> None:
    _terminate_pid_record(repo / ".run" / "web.pid")
    _terminate_pid_record(repo / ".run" / "dev-server.pid")


def test_start_server_separates_strict_prod_from_source_dev():
    script = SCRIPT.read_text(encoding="utf-8")

    assert (
        'PRODUCTION_CONTROL="${KARKINOS_HOME_PATH}/current/bin/karkinosctl"' in script
    )
    production_exec = 'exec "${PRODUCTION_CONTROL}" "${service_args[@]}"'
    assert production_exec in script
    assert script.index(production_exec) < script.index('cd "${REPO_ROOT}"')
    assert 'BACKEND_PORT="${KARKINOS_DEV_BACKEND_PORT:-8001}"' in script
    assert 'PID_FILE="${RUN_DIR}/dev-server.pid"' in script
    assert 'KARKINOS_DEV_BACKEND_URL="http://$(probe_host ' in script
    assert "REUSE_RESIDENT_BACKEND" not in script
    assert "resident_service_is_loaded" not in script
    assert "launchctl" not in script
    assert "manage_launch_agent.sh" not in script


def test_start_server_keeps_scheduler_and_bounded_readiness_invariants():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "The live scheduler always starts with the backend" in script
    assert "has no independent off" in script
    assert "--no-live" not in script
    assert "KARKINOS_LIVE_AUTO_START" not in script
    assert "wait_for_backend" in script
    assert "/api/settings/live/status" in script
    assert '"running":true' in script
    assert "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS:-60" in script
    assert "--reload-exclude 'tests/**'" in script
    assert "--reload-exclude 'web/**'" in script


def test_start_server_prod_only_delegates_to_packaged_release_controller(
    tmp_path: Path,
):
    repo, env, calls = _prod_repo(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8") == "service-start\n"
    assert not (tmp_path / "unexpected-uv").exists()
    assert not (tmp_path / "unexpected-npm").exists()
    assert not (repo / ".run").exists()


def test_start_server_prod_does_not_source_user_local_environment(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    local_env = Path(env["HOME"]) / ".local" / "bin" / "env"
    sourced_marker = tmp_path / "unexpected-local-env-source"
    local_env.parent.mkdir(parents=True)
    local_env.write_text(
        f"touch '{sourced_marker}'\nexit 86\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8") == "service-start\n"
    assert not sourced_marker.exists()


def test_start_server_prod_passes_validated_nondefault_port(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    env["KARKINOS_BACKEND_PORT"] = "8123"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8") == "service-start --service-port 8123\n"


def test_start_server_prod_rejects_invalid_port_before_controller(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    env["KARKINOS_BACKEND_PORT"] = "65536"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be an integer from 1 through 65535" in result.stderr
    assert not calls.exists()


def test_start_server_prod_fails_closed_without_packaged_controller(
    tmp_path: Path,
):
    repo, env, calls = _prod_repo(tmp_path, with_controller=False)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires the packaged immutable release controller" in result.stderr
    assert "verified CI release" in result.stderr
    assert not calls.exists()
    assert not (tmp_path / "unexpected-uv").exists()
    assert not (tmp_path / "unexpected-npm").exists()


def test_start_server_prod_rejects_current_resolving_outside_managed_releases(
    tmp_path: Path,
):
    repo, env, calls = _prod_repo(tmp_path)
    karkinos_home = Path(env["KARKINOS_HOME"])
    external_release = tmp_path / "external" / f"sha-{'b' * 40}"
    (external_release / "bin").mkdir(parents=True)
    (external_release / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        external_release / "bin" / "karkinosctl",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>'{calls}'\n",
    )
    (karkinos_home / "current").unlink()
    (karkinos_home / "current").symlink_to(external_release)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires the packaged immutable release controller" in result.stderr
    assert not calls.exists()


def test_start_server_prod_rejects_mutable_version_named_release(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    karkinos_home = Path(env["KARKINOS_HOME"])
    release = karkinos_home / "releases" / "v0.3.1"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        release / "bin" / "karkinosctl",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>'{calls}'\n",
    )
    (karkinos_home / "current").unlink()
    (karkinos_home / "current").symlink_to(Path("releases") / release.name)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires the packaged immutable release controller" in result.stderr
    assert not calls.exists()


def test_start_server_prod_rejects_symlinked_release_manifest(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    release = (Path(env["KARKINOS_HOME"]) / "current").resolve()
    external_manifest = tmp_path / "external-release.json"
    external_manifest.write_text("{}\n", encoding="utf-8")
    (release / "release.json").unlink()
    (release / "release.json").symlink_to(external_manifest)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires the packaged immutable release controller" in result.stderr
    assert not calls.exists()


def test_start_server_prod_rejects_symlinked_release_controller(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    release = (Path(env["KARKINOS_HOME"]) / "current").resolve()
    external_controller = tmp_path / "external-karkinosctl"
    _write_executable(
        external_controller,
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>'{calls}'\n",
    )
    controller = release / "bin" / "karkinosctl"
    controller.unlink()
    controller.symlink_to(external_controller)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "requires the packaged immutable release controller" in result.stderr
    assert not calls.exists()


def test_start_server_prod_rejects_ad_hoc_source_arguments(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod", "--reload"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "prod does not accept ad-hoc server arguments" in result.stderr
    assert not calls.exists()


def test_start_server_fresh_dev_is_source_only_on_8001_even_when_prod_is_resident(
    tmp_path: Path,
):
    repo, env, calls = _dev_repo(tmp_path)
    assert not (repo / "logs").exists()

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert "Backend:  http://127.0.0.1:8001" in result.stdout
        assert (repo / "logs").is_dir()
        assert (tmp_path / "uv-launch-called").is_file()
        assert (tmp_path / "npm-dev-called").is_file()
        assert not (tmp_path / "unexpected-launchctl").exists()
        recorded_calls = calls.read_text(encoding="utf-8")
        assert "lsof -tiTCP:8001 -sTCP:LISTEN" in recorded_calls
        assert "lsof -tiTCP:5173 -sTCP:LISTEN" in recorded_calls
        assert "TCP:8000" not in recorded_calls
        backend_command = next(
            shlex.split(line)
            for line in recorded_calls.splitlines()
            if "python -m server" in line
        )
        assert backend_command == [
            "uv",
            "run",
            "--locked",
            "--extra",
            "server",
            "python",
            "-m",
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            "8001",
            "--reload",
            "--reload-exclude",
            "tests/**",
            "--reload-exclude",
            "web/**",
        ]
        assert "uv run --locked --extra server python -c" in recorded_calls
        assert "npm ci\n" in recorded_calls
        assert "--strictPort" in recorded_calls
        assert "vite-backend=http://127.0.0.1:8001" in recorded_calls
        assert "\t" in (repo / ".run" / "dev-server.pid").read_text()
        assert "\t" in (repo / ".run" / "web.pid").read_text()
    finally:
        _cleanup_dev_processes(repo)


def test_start_server_dev_loads_user_local_environment(tmp_path: Path):
    repo, env, _calls = _dev_repo(tmp_path)
    local_env = Path(env["HOME"]) / ".local" / "bin" / "env"
    sourced_marker = tmp_path / "local-env-sourced"
    local_env.parent.mkdir(parents=True)
    local_env.write_text(f"touch '{sourced_marker}'\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert sourced_marker.is_file()
    finally:
        _cleanup_dev_processes(repo)


def test_start_server_dev_works_when_lsof_is_unavailable(tmp_path: Path):
    repo, env, calls = _dev_repo(tmp_path)
    (tmp_path / "bin" / "lsof").unlink()
    env["PATH"] = f"{tmp_path / 'bin'}:/usr/bin:/bin"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert "Backend:  http://127.0.0.1:8001" in result.stdout
        assert "lsof " not in calls.read_text(encoding="utf-8")
    finally:
        _cleanup_dev_processes(repo)


def test_start_server_dev_preserves_an_existing_dev_listener(tmp_path: Path):
    repo, env, calls = _dev_repo(tmp_path)
    env["KARKINOS_TEST_DEV_LISTENER"] = "31337"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "development port is already occupied" in result.stderr
    assert "Backend listener PID(s): 31337" in result.stderr
    assert "no process was terminated" in result.stderr
    assert not (tmp_path / "uv-launch-called").exists()
    assert not (tmp_path / "npm-dev-called").exists()
    assert "npm " not in calls.read_text(encoding="utf-8")


def test_start_server_dev_cleans_up_backend_after_readiness_timeout(
    tmp_path: Path,
):
    repo, env, _ = _dev_repo(tmp_path, health_ready=False)
    env["KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS"] = "1"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "backend readiness timed out after 1s" in result.stderr
    assert (tmp_path / "uv-launch-called").is_file()
    assert not (repo / ".run" / "dev-server.pid").exists()
    assert not (tmp_path / "npm-dev-called").exists()


@pytest.mark.parametrize(
    ("arguments", "expected_host", "expected_port"),
    [
        ([], "127.0.0.1", "8123"),
        (["--host", "0.0.0.0", "--port", "8124"], "0.0.0.0", "8124"),
        (["--host=0.0.0.0", "--port=8125"], "0.0.0.0", "8125"),
    ],
)
def test_start_server_dev_forwards_effective_bind_with_cli_precedence(
    tmp_path: Path, arguments: list[str], expected_host: str, expected_port: str
):
    repo, env, calls = _dev_repo(tmp_path)
    env["KARKINOS_DEV_BACKEND_PORT"] = "8123"
    env["KARKINOS_PORT"] = "8000"
    env["KARKINOS_HOST"] = "192.0.2.1"

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev", *arguments],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode == 0, result.stderr
        recorded_calls = calls.read_text()
        backend_command = next(
            shlex.split(line)
            for line in recorded_calls.splitlines()
            if "python -m server" in line
        )
        assert backend_command[8:12] == [
            "--host",
            expected_host,
            "--port",
            expected_port,
        ]
        assert backend_command[17:] == arguments
        assert f"vite-backend=http://127.0.0.1:{expected_port}" in recorded_calls
        assert f"http://127.0.0.1:{expected_port}/api/health" in recorded_calls
    finally:
        _cleanup_dev_processes(repo)


@pytest.mark.parametrize(
    "changed_input", [None, "package.json", "package-lock.json", ".npmrc"]
)
def test_start_server_dev_syncs_frontend_when_dependency_inputs_change(
    tmp_path: Path, changed_input: str | None
):
    repo, env, calls = _dev_repo(tmp_path)
    web = repo / "web"
    (web / "node_modules" / ".bin").mkdir(parents=True)
    (web / "node_modules" / "vitest").mkdir()
    _write_executable(web / "node_modules" / ".bin" / "vite", "#!/bin/sh\n")
    (web / "node_modules" / "vitest" / "globals.d.ts").touch()
    stamp = web / "node_modules" / ".karkinos-dependencies"
    inputs = [
        str(web / name) for name in ("package.json", "package-lock.json", ".npmrc")
    ]
    stamp.write_bytes(subprocess.check_output(["cksum", *inputs]))
    if changed_input:
        target = web / changed_input
        target.write_text(target.read_text() + "\n")

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert ("npm ci\n" in calls.read_text()) is (changed_input is not None)
        assert "npm install" not in calls.read_text()
        assert stamp.read_bytes() == subprocess.check_output(["cksum", *inputs])
    finally:
        _cleanup_dev_processes(repo)


def test_start_server_dev_does_not_record_failed_frontend_install(tmp_path: Path):
    repo, env, calls = _dev_repo(tmp_path)
    env["KARKINOS_TEST_NPM_CI_EXIT"] = "17"
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 17
    assert "npm ci\n" in calls.read_text()
    assert not (repo / "web/node_modules/.karkinos-dependencies").exists()
    assert not (tmp_path / "uv-launch-called").exists()


@pytest.mark.parametrize("backend_child", [False, True])
def test_start_server_dev_rolls_back_both_processes_after_frontend_timeout(
    tmp_path: Path, backend_child: bool
):
    repo, env, _calls = _dev_repo(
        tmp_path, frontend_ready=False, backend_child=backend_child
    )
    if backend_child:
        _write_executable(
            tmp_path / "bin/pgrep",
            "#!/usr/bin/env bash\n"
            f'if [[ "$2" == "$(cat "{tmp_path / "uv-launch-called"}")" ]]; then\n'
            f'  cat "{tmp_path / "backend-child.pid"}"\n'
            "fi\n",
        )
    env["KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS"] = "1"
    read_fd, write_fd = os.pipe()
    try:
        result = subprocess.run(
            ["bash", "scripts/start_server.sh", "dev"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            pass_fds=(write_fd,),
        )
    finally:
        os.close(write_fd)
    try:
        assert result.returncode == 1, result.stderr
        assert "frontend readiness timed out" in result.stderr
        for launch_file in ("uv-launch-called", "npm-dev-called"):
            pid = int((tmp_path / launch_file).read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        assert not (repo / ".run/dev-server.pid").exists()
        assert not (repo / ".run/web.pid").exists()
        assert select.select([read_fd], [], [], 1)[
            0
        ], "a startup child survived rollback"
        assert os.read(read_fd, 1) == b""
    finally:
        os.close(read_fd)
        _cleanup_dev_processes(repo)
        if backend_child and (tmp_path / "backend-child.pid").is_file():
            try:
                os.kill(
                    int((tmp_path / "backend-child.pid").read_text()), signal.SIGKILL
                )
            except ProcessLookupError:
                pass
