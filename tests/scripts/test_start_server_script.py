"""Executable contracts for the snapshot-based source launcher."""

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
    (service / "run_main.py").write_text("# fixture launcher\n", encoding="utf-8")

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
        f'printf "source-root=%s\\n" "${{KARKINOS_SOURCE_ROOT:-}}" >>"{python_calls}"\n'
        f'printf "source-sha=%s\\n" "${{KARKINOS_SOURCE_SHA:-}}" >>"{python_calls}"\n'
        f'printf "branch=%s\\n" "${{KARKINOS_SOURCE_BRANCH:-}}" >>"{python_calls}"\n'
        f'printf "data=%s\\n" "${{KARKINOS_DATA_DIR:-}}" >>"{python_calls}"\n'
        f'printf "config=%s\\n" "${{KARKINOS_CONFIG_PATH:-}}" >>"{python_calls}"\n',
    )
    _write_executable(
        bin_dir / "uv",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "uv %s\\n" "$*" >>"{calls}"\n'
        f'printf "workspace=%s\\n" "${{KARKINOS_WORKSPACE:-}}" >>"{calls}"\n'
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
        '  *TCP:8000*) printf "%s\\n" "${KARKINOS_TEST_DEV_LISTENER:-}" ;;\n'
        '  *TCP:5173*) printf "%s\\n" "${KARKINOS_TEST_FRONTEND_LISTENER:-}" ;;\n'
        "esac\n",
    )
    health_exit = 0 if health_ready else 28
    frontend_exit = 0 if frontend_ready else 28
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'if [[ "$*" == *":5173/"* ]]; then\n'
        f"  exit {frontend_exit}\n"
        "fi\n"
        'if [[ "$*" == *"/api/settings/live/status"* ]]; then\n'
        "  printf '{\"running\":true}'\n"
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
        'if [[ "$*" == "-axo command=" ]]; then exit 0; fi\n'
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
    main_sha = _git(repo, "rev-parse", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_sha)
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
    for key in tuple(env):
        if key.startswith("KARKINOS_") and not key.startswith("KARKINOS_TEST_"):
            env.pop(key)
    return repo, env, calls


def _cleanup_source_processes(repo: Path) -> None:
    run_dir = repo / ".run/dev"
    if not run_dir.exists():
        return
    for pid_file in run_dir.glob("*.pid"):
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


def test_default_main_snapshot_does_not_switch_dirty_dev_checkout(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    (repo / "app.py").write_text("value = 'dirty dev'\n", encoding="utf-8")
    before = _git(repo, "status", "--porcelain")

    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "--init"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "branch", "--show-current") == "dev"
    assert _git(repo, "status", "--porcelain") == before
    snapshot = repo / ".run/main/code"
    assert (snapshot / "app.py").read_text() == "value = 1\n"
    assert (snapshot / ".karkinos-source-sha").read_text().strip() == _git(
        repo, "rev-parse", "refs/remotes/origin/main"
    )
    recorded = (tmp_path / "python-calls.log").read_text(encoding="utf-8")
    assert f"workspace={repo}" in recorded
    assert f"source-root={snapshot}" in recorded
    assert "branch=main" in recorded
    assert f"data={repo / 'data/store'}" in recorded
    assert f"config={repo / 'config.json'}" in recorded


def test_arbitrary_branch_snapshot_keeps_current_checkout_untouched(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "feature/research", "--foreground"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "branch", "--show-current") == "dev"
    snapshot = repo / ".run/feature/research/code"
    assert snapshot.is_dir()
    assert (
        snapshot / ".karkinos-source-branch"
    ).read_text().strip() == "feature/research"
    recorded = (tmp_path / "python-calls.log").read_text(encoding="utf-8")
    assert f"source-root={snapshot}" in recorded
    assert "branch=feature/research" in recorded


def test_explicit_branch_option_matches_positional_snapshot(tmp_path: Path):
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
    assert _git(repo, "branch", "--show-current") == "dev"
    assert (repo / ".run/main/code/.karkinos-source-sha").is_file()


def test_dev_uses_current_dirty_working_tree_and_shared_local_state(tmp_path: Path):
    repo, env, calls = _source_repo(tmp_path, current_branch="dev")
    (repo / "app.py").write_text("value = 'work in progress'\n", encoding="utf-8")
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
        assert _git(repo, "branch", "--show-current") == "dev"
        recorded = calls.read_text(encoding="utf-8")
        assert f"workspace={repo}" in recorded
        assert "branch=dev" in recorded
        assert "vite-backend=http://127.0.0.1:8000" in recorded
        assert (repo / ".run/dev/backend.pid").is_file()
        assert (repo / ".run/dev/frontend.pid").is_file()
        assert not (repo / ".run/dev/config").exists()
        assert not (repo / ".run/dev/data").exists()
    finally:
        _cleanup_source_processes(repo)


def test_dev_requires_current_checkout_to_be_dev(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="main")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "dev"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Switch to dev yourself" in result.stderr
    assert _git(repo, "branch", "--show-current") == "main"


def test_missing_snapshot_branch_fails_without_switching(tmp_path: Path):
    repo, env, _calls = _source_repo(tmp_path, current_branch="dev")
    result = subprocess.run(
        ["bash", "scripts/start_server.sh", "missing-branch"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "is not available locally or under origin" in result.stderr
    assert _git(repo, "branch", "--show-current") == "dev"


def test_backend_readiness_timeout_cleans_dev_process(tmp_path: Path):
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
