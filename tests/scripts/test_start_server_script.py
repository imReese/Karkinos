"""Executable contracts for the branch-selected source launcher."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/start_server.sh")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_repo(
    tmp_path: Path,
    *,
    current_branch: str = "dev",
    health_ready: bool = True,
    frontend_ready: bool = True,
) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    service = scripts / "service"
    web = repo / "web"
    bin_dir = tmp_path / "bin"
    service.mkdir(parents=True)
    web.mkdir()
    bin_dir.mkdir()

    copied = scripts / SCRIPT.name
    copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied.chmod(0o755)
    (service / "run_dev.py").write_text("# fixture entrypoint\n", encoding="utf-8")
    (service / "run_main.py").write_text("# fixture entrypoint\n", encoding="utf-8")

    (repo / "config.json").write_text("{}\n", encoding="utf-8")
    (repo / ".env").write_text("KARKINOS_DATA_SOURCE=akshare\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8"
    )
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text(
        ".env\nconfig.json\ndata/store/\nlogs/\nexports/\n.run/\n"
        "web/node_modules/\nweb/dist/\n",
        encoding="utf-8",
    )
    (web / "package.json").write_text(
        '{"scripts":{"build":"true","dev":"true"}}\n', encoding="utf-8"
    )
    (web / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (web / ".npmrc").write_text("engine-strict=true\n")

    calls = tmp_path / "calls.log"
    python_calls = tmp_path / "python-calls.log"

    _write_executable(
        bin_dir / "python3",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "python3 %s\\n" "$*" >>"{python_calls}"\n'
        f'printf "workspace=%s\\n" "${{KARKINOS_WORKSPACE:-}}" >>"{python_calls}"\n'
        f'printf "data=%s\\n" "${{KARKINOS_DATA_DIR:-}}" >>"{python_calls}"\n'
        f'printf "config=%s\\n" "${{KARKINOS_CONFIG_PATH:-}}" >>"{python_calls}"\n'
        f'printf "env-file=%s\\n" "${{KARKINOS_ENV_FILE:-}}" >>"{python_calls}"\n'
        f'printf "branch=%s\\n" "${{KARKINOS_SOURCE_BRANCH:-}}" >>"{python_calls}"\n',
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "uv %s\\n" "$*" >>"{calls}"\n'
        f'printf "workspace=%s\\n" "${{KARKINOS_WORKSPACE:-}}" >>"{calls}"\n'
        f'printf "data=%s\\n" "${{KARKINOS_DATA_DIR:-}}" >>"{calls}"\n'
        f'printf "config=%s\\n" "${{KARKINOS_CONFIG_PATH:-}}" >>"{calls}"\n'
        f'printf "env-file=%s\\n" "${{KARKINOS_ENV_FILE:-}}" >>"{calls}"\n'
        f'printf "branch=%s\\n" "${{KARKINOS_SOURCE_BRANCH:-}}" >>"{calls}"\n'
        'if [[ "$*" == *"python -c"* ]]; then exit 0; fi\n'
        f"printf '%s\\n' \"$$\" >'{tmp_path / 'uv-launch-called'}'\n"
        "exec sleep 60\n",
    )
    _write_executable(
        bin_dir / "npm",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "npm %s\\n" "$*" >>"{calls}"\n'
        'if [[ "$*" == "ci" ]]; then\n'
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
        'case "$*" in\n'
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
        bin_dir / "ps",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'if [[ "$*" == "-axo command=" ]]; then\n'
        '  if [[ -n "${KARKINOS_TEST_RUNNING_SOURCE:-}" ]]; then\n'
        f'    printf "%s\\n" "python {repo}/scripts/service/run_dev.py"\n'
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-p" && "${3:-}" == "-o" && "${4:-}" == "lstart=" ]]; then\n'
        "  printf '%s\\n' 'Sun Aug 30 22:00:00 2026'\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
    )
    _write_executable(bin_dir / "pgrep", "#!/usr/bin/env bash\nexit 1\n")

    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    _git(repo, "branch", "dev")
    _git(repo, "branch", "feature/research")
    if current_branch != "main":
        _git(repo, "switch", "-q", current_branch)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS": "2",
        "KARKINOS_FRONTEND_STARTUP_TIMEOUT_SECONDS": "2",
    }
    return repo, env, calls


def _cleanup_source_processes(repo: Path) -> None:
    run_dir = repo / ".run"
    if not run_dir.exists():
        return
    for pid_file in run_dir.rglob("*.pid"):
        raw = pid_file.read_text(encoding="utf-8").split("\t", 1)[0]
        if raw.isdigit():
            try:
                os.kill(int(raw), signal.SIGTERM)
            except ProcessLookupError:
                pass


def _prod_repo(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    copied = scripts / SCRIPT.name
    copied.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    copied.chmod(0o755)

    home = tmp_path / "installed"
    release = home / "releases" / f"sha-{'a' * 40}"
    (release / "bin").mkdir(parents=True)
    (release / "release.json").write_text("{}\n", encoding="utf-8")
    calls = tmp_path / "controller.log"
    _write_executable(
        release / "bin/karkinosctl",
        "#!/usr/bin/env bash\n" "set -eu\n" f'printf "%s\\n" "$*" >>"{calls}"\n',
    )
    (home / "current").symlink_to(Path("releases") / release.name)
    env = {**os.environ, "KARKINOS_HOME": str(home)}
    return repo, env, calls


def test_default_source_branch_is_main_and_uses_repo_local_state(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "--init"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _git(repo, "branch", "--show-current") == "main"
    recorded = (tmp_path / "python-calls.log").read_text(encoding="utf-8")
    assert "scripts/service/run_main.py --init" in recorded
    assert f"workspace={repo}" in recorded
    assert f"data={repo / 'data/store'}" in recorded
    assert f"config={repo / 'config.json'}" in recorded
    assert f"env-file={repo / '.env'}" in recorded
    assert "branch=main" in recorded


def test_branch_switch_refuses_dirty_checkout_without_mutating_it(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    before = _git(repo, "status", "--porcelain")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "checkout has local changes" in result.stderr
    assert _git(repo, "branch", "--show-current") == "dev"
    assert _git(repo, "status", "--porcelain") == before
    assert not (tmp_path / "python-calls.log").exists()


def test_branch_switch_refuses_while_source_runtime_is_running(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    env["KARKINOS_TEST_RUNNING_SOURCE"] = "1"
    result = subprocess.run(
        ["bash", "scripts/start_server.sh"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "source runtime is still using this checkout" in result.stderr
    assert _git(repo, "branch", "--show-current") == "dev"


def test_dev_uses_shared_local_config_and_data_with_branch_only_runtime_state(
    tmp_path: Path,
):
    repo, env, calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    try:
        assert result.returncode == 0, result.stderr
        recorded = calls.read_text(encoding="utf-8")
        assert f"workspace={repo}" in recorded
        assert f"data={repo / 'data/store'}" in recorded
        assert f"config={repo / 'config.json'}" in recorded
        assert f"env-file={repo / '.env'}" in recorded
        assert "branch=dev" in recorded
        assert "vite-backend=http://127.0.0.1:8001" in recorded
        assert (repo / ".run/dev/backend.pid").is_file()
        assert (repo / ".run/dev/frontend.pid").is_file()
        assert not (repo / ".run/dev/config").exists()
        assert not (repo / ".run/dev/data").exists()
        assert (repo / "config.json").is_file()
        assert (repo / ".env").is_file()
    finally:
        _cleanup_source_processes(repo)


def test_arbitrary_development_branch_gets_only_its_own_process_state(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "feature/research"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    try:
        assert result.returncode == 0, result.stderr
        assert _git(repo, "branch", "--show-current") == "feature/research"
        assert (repo / ".run/feature/research/backend.pid").is_file()
        assert (repo / ".run/feature/research/frontend.pid").is_file()
        assert "Workspace: " + str(repo) in result.stdout
    finally:
        _cleanup_source_processes(repo)


def test_explicit_branch_option_matches_positional_branch(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "--branch", "main", "--foreground"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _git(repo, "branch", "--show-current") == "main"
    recorded = (tmp_path / "python-calls.log").read_text(encoding="utf-8")
    assert "scripts/service/run_main.py --foreground" in recorded
    assert "branch=main" in recorded


def test_dev_preserves_existing_listener_without_starting_processes(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
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
    assert not (tmp_path / "uv-launch-called").exists()
    assert not (tmp_path / "npm-dev-called").exists()


def test_backend_readiness_timeout_cleans_tracked_process(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev", health_ready=False)
    env["KARKINOS_STARTUP_HEALTH_TIMEOUT_SECONDS"] = "1"
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 1
    assert "backend readiness timed out after 1s" in result.stderr
    assert not (repo / ".run/dev/backend.pid").exists()
    assert not (tmp_path / "npm-dev-called").exists()


def test_prod_still_delegates_only_to_installed_release_controller(tmp_path: Path):
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


def test_prod_rejects_current_pointer_outside_installed_releases(tmp_path: Path):
    repo, env, calls = _prod_repo(tmp_path)
    home = Path(env["KARKINOS_HOME"])
    external = tmp_path / "external" / f"sha-{'b' * 40}"
    (external / "bin").mkdir(parents=True)
    (external / "release.json").write_text("{}\n", encoding="utf-8")
    _write_executable(
        external / "bin/karkinosctl",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >>'{calls}'\n",
    )
    (home / "current").unlink()
    (home / "current").symlink_to(external)

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "prod"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "installed immutable release controller" in result.stderr
    assert not calls.exists()
