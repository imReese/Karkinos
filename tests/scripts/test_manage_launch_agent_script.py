"""macOS LaunchAgent contracts for immutable production releases."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import release_artifact

SCRIPT = Path("scripts/service/manage_launch_agent.sh")
SHA = "a" * 40
VERSION = "0.3.2"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _native_current(home: Path) -> dict[str, object]:
    release = home / "releases" / f"sha-{SHA}"
    (release / "bin").mkdir(parents=True)
    _write_executable(release / "bin" / "karkinos", "#!/bin/sh\nexit 0\n")
    (release / "app" / "server").mkdir(parents=True)
    (release / "app" / "server" / "__init__.py").write_text(
        f'__version__ = "{VERSION}"\n', encoding="utf-8"
    )
    (release / "app" / "web" / "dist").mkdir(parents=True)
    (release / "app" / "web" / "dist" / "index.html").write_text(
        "<!doctype html>\n", encoding="utf-8"
    )
    (release / "runtime" / "bin").mkdir(parents=True)
    _write_executable(release / "runtime" / "bin" / "python3.12", "#!/bin/sh\nexit 0\n")
    manifest: dict[str, object] = {
        "schema_version": release_artifact.NATIVE_ARTIFACT_SCHEMA,
        "artifact_kind": "macos-native",
        "release_control_protocol": release_artifact.RELEASE_CONTROL_PROTOCOL,
        "version": VERSION,
        "commit_sha": SHA,
        "architecture": "arm64",
        "entrypoint": "bin/karkinos",
        "runtime": "python3.12",
        "mutable_state": "~/Library/Application Support/Karkinos",
    }
    manifest["file_checksums"] = release_artifact.payload_checksums(release)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(release)
    (release / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    home.mkdir(parents=True, exist_ok=True)
    (home / "current").symlink_to(Path("releases") / release.name)
    for directory in ("data", "config", "logs"):
        (home / directory).mkdir()
    return manifest


def _fake_launch_agent_repo(
    tmp_path: Path,
    *,
    with_current: bool = True,
    loaded: bool = False,
    karkinos_home: Path | None = None,
) -> tuple[Path, dict[str, str], Path, dict[str, object] | None]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts" / "service"
    fake_bin = tmp_path / "bin"
    state_file = tmp_path / "launchd-loaded"
    calls = tmp_path / "calls.log"
    user_home = tmp_path / "home"
    native_home = (
        karkinos_home
        if karkinos_home is not None
        else user_home / "Library" / "Application Support" / "Karkinos"
    )
    plist = (
        user_home / "Library" / "LaunchAgents" / "com.karkinos.daily-candidate.plist"
    )
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    manifest = _native_current(native_home) if with_current else None
    native_home.mkdir(parents=True, exist_ok=True)
    lock_nonce = "d" * 32
    (native_home / ".release.lock").write_text(
        f"{os.getpid()} {lock_nonce}\n", encoding="utf-8"
    )
    if loaded:
        state_file.touch()
        plist.parent.mkdir(parents=True)
        plist.write_text("fixture\n", encoding="utf-8")

    _write_executable(fake_bin / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(fake_bin / "plutil", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "uv",
        "#!/usr/bin/env bash\n" f"touch '{tmp_path / 'unexpected-uv'}'\n" "exit 97\n",
    )
    _write_executable(
        fake_bin / "lsof",
        "#!/usr/bin/env bash\n"
        f'printf "lsof %s\\n" "$*" >>"{calls}"\n'
        'if [[ -n "${KARKINOS_TEST_LSOF_EXIT:-}" ]]; then\n'
        '  exit "${KARKINOS_TEST_LSOF_EXIT}"\n'
        "fi\n"
        f'state="{state_file}"\n'
        'if [[ -n "${KARKINOS_TEST_LISTENER_PIDS:-}" ]]; then\n'
        '  printf "%s" "${KARKINOS_TEST_LISTENER_PIDS}"\n'
        'elif [[ -f "${state}" ]]; then\n'
        '  printf "%s" "${KARKINOS_TEST_SERVICE_LISTENER_PIDS:-4242}"\n'
        "fi\n",
    )
    _write_executable(
        fake_bin / "curl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "curl %s\\n" "$*" >>"{calls}"\n'
        'if [[ "$*" == *"/api/settings/live/status"* ]]; then\n'
        '  printf \'{"running":%s,"initialized":%s,"activation_guarded":%s,'
        '"market_open":false}\' '
        '"${KARKINOS_TEST_LIVE_RUNNING:-true}" '
        '"${KARKINOS_TEST_LIVE_INITIALIZED:-true}" '
        '"${KARKINOS_TEST_ACTIVATION_GUARDED:-false}"\n'
        "  exit 0\n"
        "fi\n"
        "printf "
        '\'{"schema_version":"karkinos.service_health.v1",\''
        '\'"service":"karkinos","status":"alive",\''
        '\'"version":"%s","release_sha":"%s",\''
        '\'"artifact_fingerprint":"%s",\''
        "'\"financial_readiness_claimed\":false,'"
        "'\"broker_submission_enabled\":false,'"
        "'\"production_ledger_mutated\":false,'"
        "'\"authorizes_execution\":false,'"
        "'\"capital_authority_changed\":false}' "
        '"${KARKINOS_TEST_HEALTH_VERSION:?}" '
        '"${KARKINOS_TEST_HEALTH_SHA:?}" '
        '"${KARKINOS_TEST_HEALTH_FINGERPRINT:?}"\n',
    )
    _write_executable(
        fake_bin / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        f'printf "launchctl %s\\n" "$*" >>"{calls}"\n'
        f'state="{state_file}"\n'
        'case "${1:-}" in\n'
        "  print)\n"
        '    [[ -f "${state}" ]] || exit 113\n'
        "    printf '%s\\n' 'state = running' 'runs = 1' "
        '"pid = ${KARKINOS_TEST_LAUNCHD_PID:-4242}"\n'
        "    ;;\n"
        "  bootstrap)\n"
        '    touch "${state}"\n'
        "    ;;\n"
        "  bootout)\n"
        '    if [[ "${KARKINOS_TEST_BOOTOUT_PRESERVES_LABEL:-0}" != "1" ]]; then\n'
        '      rm -f "${state}"\n'
        "    fi\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    fingerprint = str(manifest["payload_fingerprint"]) if manifest else "f" * 64
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(user_home),
        "KARKINOS_HOME": str(native_home),
        "KARKINOS_TEST_HEALTH_VERSION": VERSION,
        "KARKINOS_TEST_HEALTH_SHA": SHA,
        "KARKINOS_TEST_HEALTH_FINGERPRINT": fingerprint,
        "KARKINOS_RELEASE_LOCK_OWNER_PID": str(os.getpid()),
        "KARKINOS_RELEASE_LOCK_NONCE": lock_nonce,
        "KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS": "1",
        "KARKINOS_LAUNCH_AGENT_UNLOAD_TIMEOUT_SECONDS": "2",
    }
    return repo, env, calls, manifest


def _run(
    repo: Path, env: dict[str, str], command: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/service/manage_launch_agent.sh", command],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _plist(env: dict[str, str]) -> Path:
    return (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )


def test_launch_agent_is_native_only_and_checks_exact_runtime_identity():
    script = SCRIPT.read_text(encoding="utf-8")

    assert (
        'HEALTH_TIMEOUT_SECONDS="${KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS:-120}"'
        in script
    )
    assert 'NATIVE_ENTRYPOINT="${KARKINOS_HOME_PATH}/current/bin/karkinos"' in script
    assert "REPO_ROOT" not in script
    assert "resolve_uv" not in script
    assert "UV_CACHE_DIR" not in script
    assert '"release_sha":"' in script
    assert '"artifact_fingerprint":"' in script
    assert '"running":true' in script
    assert '"initialized":true' in script
    assert '"activation_guarded":' in script
    assert "launchd_service_pid" in script
    assert '[[ "${pids}" == "${launchd_pid}" ]]' in script
    assert '"production_ledger_mutated":false' in script
    assert '"authorizes_execution":false' in script
    assert "PYTHONDONTWRITEBYTECODE" in script
    assert "source fallback is forbidden" in script


def test_launch_agent_is_user_scoped_reversible_and_restart_is_explicit():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'DOMAIN="gui/${USER_ID}"' in script
    assert 'PLIST_DIR="${HOME}/Library/LaunchAgents"' in script
    assert 'LABEL="com.karkinos.daily-candidate"' in script
    assert 'launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"' in script
    assert 'launchctl bootout "${SERVICE_TARGET}"' in script
    assert "<key>RunAtLoad</key>" in script
    assert "<key>KeepAlive</key>\n  <true/>" in script
    assert "restart_agent" in script
    assert "restart)" in script
    assert "require_release_controller" in script
    assert "${KARKINOS_RELEASE_LOCK_OWNER_PID:-}" in script
    assert "${KARKINOS_RELEASE_LOCK_NONCE:-}" in script
    assert "No command submits broker orders or changes capital authority" in script


def test_print_plist_uses_exact_current_and_is_write_free(tmp_path: Path):
    native_home = tmp_path / "Karkinos & evidence"
    repo, env, _, manifest = _fake_launch_agent_repo(
        tmp_path, karkinos_home=native_home
    )
    assert manifest is not None
    env.pop("KARKINOS_RELEASE_LOCK_OWNER_PID")
    env.pop("KARKINOS_RELEASE_LOCK_NONCE")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = _run(repo, env, "print-plist")

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert result.returncode == 0, result.stderr
    assert before == after
    assert "Karkinos &amp; evidence/current/bin/karkinos" in result.stdout
    assert "Karkinos & evidence/current/bin/karkinos" not in result.stdout
    assert "<key>KARKINOS_DATA_DIR</key>" in result.stdout
    assert "<key>KARKINOS_CONFIG_PATH</key>" in result.stdout
    assert "<key>KARKINOS_ENV_FILE</key>" not in result.stdout
    assert "<key>PYTHONDONTWRITEBYTECODE</key><string>1</string>" in result.stdout
    assert not _plist(env).exists()
    assert not (tmp_path / "unexpected-uv").exists()


def test_install_fails_closed_without_immutable_current(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path, with_current=False)

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert "requires an executable immutable current release" in result.stderr
    assert "Stage and promote a CI-built candidate" in result.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    assert not (tmp_path / "unexpected-uv").exists()
    if calls.exists():
        assert "bootstrap" not in calls.read_text(encoding="utf-8")


@pytest.mark.parametrize("command", ["install", "restart", "uninstall"])
def test_service_mutation_rejects_direct_lock_bypass(tmp_path: Path, command: str):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path, loaded=True)
    env.pop("KARKINOS_RELEASE_LOCK_OWNER_PID")
    env.pop("KARKINOS_RELEASE_LOCK_NONCE")

    result = _run(repo, env, command)

    assert result.returncode == 1
    assert "must run through the locked Karkinos release controller" in result.stderr
    assert (
        "Use ./scripts/start_server.sh prod or ./scripts/stop_server.sh"
        in result.stderr
    )
    assert _plist(env).is_file()
    assert (tmp_path / "launchd-loaded").is_file()
    assert not calls.exists()


def test_install_rejects_manifest_sha_that_does_not_match_release_directory(
    tmp_path: Path,
):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    mismatched_sha = "b" * 40
    release = Path(env["KARKINOS_HOME"]) / "releases" / f"sha-{SHA}"
    manifest_path = release / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["commit_sha"] = mismatched_sha
    manifest_path.write_bytes(release_artifact.canonical_json(manifest))
    env["KARKINOS_TEST_HEALTH_SHA"] = mismatched_sha

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert "current native release identity is invalid" in result.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    if calls.exists():
        assert "bootstrap" not in calls.read_text(encoding="utf-8")


def test_install_and_uninstall_use_exact_current_release(tmp_path: Path):
    repo, env, calls, manifest = _fake_launch_agent_repo(tmp_path)
    assert manifest is not None
    env["KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS"] = "3600"

    installed = _run(repo, env, "install")

    assert installed.returncode == 0, installed.stderr
    assert _plist(env).is_file()
    assert (tmp_path / "launchd-loaded").is_file()
    assert f"exact current release {SHA}" in installed.stdout
    assert "launchd owns the listener, live scheduler initialized" in installed.stdout
    assert "Financial readiness: not claimed" in installed.stdout
    plist_source = _plist(env).read_text(encoding="utf-8")
    assert f"current/bin/karkinos</string>" in plist_source
    assert "uv</string>" not in plist_source

    uninstalled = _run(repo, env, "uninstall")

    assert uninstalled.returncode == 0, uninstalled.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    assert "Runtime data and logs were not deleted" in uninstalled.stdout
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootstrap gui/" in recorded_calls
    assert "launchctl bootout gui/" in recorded_calls


@pytest.mark.parametrize("health_timeout", ("0", "3601", "1.5"))
def test_install_rejects_health_timeout_outside_shared_contract(
    tmp_path: Path, health_timeout: str
) -> None:
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS"] = health_timeout

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert (
        "KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS must be an integer within [1, 3600]"
        in result.stderr
    )
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    if calls.exists():
        assert "bootstrap" not in calls.read_text(encoding="utf-8")


def test_uninstall_fails_closed_for_listener_without_loaded_label(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_TEST_LISTENER_PIDS"] = "9898"
    plist = _plist(env)
    plist.parent.mkdir(parents=True)
    plist.write_text("fixture\n", encoding="utf-8")

    result = _run(repo, env, "uninstall")

    assert result.returncode == 1
    assert "is not loaded, but port 8000 still has a listener" in result.stderr
    assert "Listener PID(s): 9898" in result.stderr
    assert "no process was signaled" in result.stderr
    assert "Uninstalled" not in result.stdout
    assert plist.is_file()
    assert not (tmp_path / "launchd-loaded").exists()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootout" not in recorded_calls
    assert "kill " not in recorded_calls


def test_uninstall_fails_closed_when_listener_absence_cannot_be_proven(
    tmp_path: Path,
):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_TEST_LSOF_EXIT"] = "2"
    plist = _plist(env)
    plist.parent.mkdir(parents=True)
    plist.write_text("fixture\n", encoding="utf-8")

    result = _run(repo, env, "uninstall")

    assert result.returncode == 1
    assert "could not determine whether port 8000 has a listener" in result.stderr
    assert "no process was signaled" in result.stderr
    assert "Uninstalled" not in result.stdout
    assert plist.is_file()
    assert "launchctl" not in calls.read_text(encoding="utf-8")


def test_uninstall_waits_for_listener_and_fails_without_killing_it(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path, loaded=True)
    env["KARKINOS_TEST_LISTENER_PIDS"] = "9898"

    result = _run(repo, env, "uninstall")

    assert result.returncode == 1
    assert "did not fully stop within 2s" in result.stderr
    assert "Port 8000 listener PID(s): 9898" in result.stderr
    assert "no process was signaled" in result.stderr
    assert "Uninstalled" not in result.stdout
    assert _plist(env).is_file()
    assert not (tmp_path / "launchd-loaded").exists()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootout gui/" in recorded_calls
    assert recorded_calls.count("lsof -tiTCP:8000 -sTCP:LISTEN") >= 2
    assert "kill " not in recorded_calls


def test_uninstall_waits_for_label_and_preserves_plist_on_timeout(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path, loaded=True)
    env["KARKINOS_TEST_BOOTOUT_PRESERVES_LABEL"] = "1"

    result = _run(repo, env, "uninstall")

    assert result.returncode == 1
    assert "did not fully stop within 2s" in result.stderr
    assert "launchd label remains loaded" in result.stderr
    assert "no process was signaled" in result.stderr
    assert "Uninstalled" not in result.stdout
    assert _plist(env).is_file()
    assert (tmp_path / "launchd-loaded").is_file()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootout gui/" in recorded_calls
    assert "kill " not in recorded_calls


@pytest.mark.parametrize(
    ("environment_key", "bad_value"),
    [
        ("KARKINOS_TEST_HEALTH_SHA", "b" * 40),
        ("KARKINOS_TEST_HEALTH_FINGERPRINT", "e" * 64),
        ("KARKINOS_TEST_LIVE_RUNNING", "false"),
        ("KARKINOS_TEST_LIVE_INITIALIZED", "false"),
        ("KARKINOS_TEST_ACTIVATION_GUARDED", "true"),
    ],
)
def test_install_fails_closed_for_wrong_identity_or_scheduler(
    tmp_path: Path, environment_key: str, bad_value: str
):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env[environment_key] = bad_value

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert "service readiness did not become ready" in result.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootstrap gui/" in recorded_calls
    assert "launchctl bootout gui/" in recorded_calls


def test_install_fails_closed_when_listener_is_not_the_launchd_process(
    tmp_path: Path,
):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_TEST_SERVICE_LISTENER_PIDS"] = "9898"

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert "service readiness did not become ready" in result.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    recorded_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootstrap gui/" in recorded_calls
    assert "launchctl bootout gui/" in recorded_calls


def test_install_requires_and_accepts_guarded_readiness_during_transaction(
    tmp_path: Path,
):
    repo, env, _calls, _ = _fake_launch_agent_repo(tmp_path)
    (Path(env["KARKINOS_HOME"]) / ".release-transaction.json").write_text(
        "{}\n", encoding="utf-8"
    )
    env["KARKINOS_TEST_ACTIVATION_GUARDED"] = "true"

    result = _run(repo, env, "install")

    assert result.returncode == 0, result.stderr
    assert "live scheduler initialized" in result.stdout


def test_install_does_not_replace_loaded_service_but_restart_does(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path, loaded=True)

    installed = _run(repo, env, "install")

    assert installed.returncode == 0, installed.stderr
    assert "already loaded; no process was replaced" in installed.stdout
    install_calls = calls.read_text(encoding="utf-8")
    assert "bootout" not in install_calls
    assert "bootstrap" not in install_calls

    calls.unlink()
    restarted = _run(repo, env, "restart")

    assert restarted.returncode == 0, restarted.stderr
    restart_calls = calls.read_text(encoding="utf-8")
    assert "launchctl bootout gui/" in restart_calls
    assert "launchctl bootstrap gui/" in restart_calls
    assert restart_calls.index("bootout") < restart_calls.index("bootstrap")
    assert _plist(env).is_file()
    assert (tmp_path / "launchd-loaded").is_file()


def test_install_preserves_existing_listener_without_bootstrap(tmp_path: Path):
    repo, env, calls, _ = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_TEST_LISTENER_PIDS"] = "4242"

    result = _run(repo, env, "install")

    assert result.returncode == 1
    assert "another Karkinos process already owns port 8000" in result.stderr
    assert "No process was terminated" in result.stderr
    assert not _plist(env).exists()
    assert not (tmp_path / "launchd-loaded").exists()
    assert "bootstrap" not in calls.read_text(encoding="utf-8")


def test_help_exposes_restart_and_safety_boundary():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "restart" in result.stdout
    assert "source fallback is forbidden" in result.stdout
    assert "does not edit config.json or .env" in result.stdout
