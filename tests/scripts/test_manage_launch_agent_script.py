"""macOS LaunchAgent operations entry-point contract."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/manage_launch_agent.sh")
HEALTH_RESPONSE = (
    '{"schema_version":"karkinos.service_health.v1","status":"alive",'
    '"financial_readiness_claimed":false,"broker_submission_enabled":false,'
    '"capital_authority_changed":false}'
)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_launch_agent_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    state_file = tmp_path / "launchd-loaded"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    (repo / "web" / "dist").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    (repo / "web" / "dist" / "index.html").write_text("ok\n")
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    _write_executable(fake_bin / "uv", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "uname", "#!/usr/bin/env bash\necho Darwin\n")
    _write_executable(fake_bin / "plutil", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(
        fake_bin / "lsof",
        "#!/usr/bin/env bash\nprintf '%s' \"${KARKINOS_TEST_LISTENER_PIDS:-}\"\n",
    )
    _write_executable(
        fake_bin / "curl",
        f"#!/usr/bin/env bash\nprintf '%s' '{HEALTH_RESPONSE}'\n",
    )
    _write_executable(
        fake_bin / "launchctl",
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        'state="${KARKINOS_TEST_LAUNCHD_STATE:?}"\n'
        'case "${1:-}" in\n'
        "  print)\n"
        '    [[ -f "${state}" ]] || exit 113\n'
        "    printf '%s\\n' 'state = running' 'runs = 1' 'pid = 4242'\n"
        "    ;;\n"
        "  bootstrap)\n"
        '    touch "${state}"\n'
        "    ;;\n"
        "  bootout)\n"
        '    delay="${KARKINOS_TEST_BOOTOUT_DELAY_SECONDS:-0}"\n'
        '    if [[ "${delay}" == "0" ]]; then\n'
        '      rm -f "${state}"\n'
        "    else\n"
        '      (sleep "${delay}"; rm -f "${state}") >/dev/null 2>&1 &\n'
        "    fi\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path / "home"),
        "KARKINOS_TEST_LAUNCHD_STATE": str(state_file),
        "KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS": "1",
    }
    return repo, env


def test_launch_agent_script_keeps_financial_and_authority_boundaries_explicit():
    script = SCRIPT.read_text(encoding="utf-8")

    assert "does not enable live monitoring" in script
    assert "Financial readiness: not claimed" in script
    assert "Broker submission: disabled" in script
    assert "No command submits broker orders or changes capital authority" in script
    assert "KARKINOS_LIVE_AUTO_START=true" not in script
    assert "config.json" in script
    assert ".env" in script


def test_launch_agent_script_is_user_scoped_reversible_and_direct_exec():
    script = SCRIPT.read_text(encoding="utf-8")

    assert 'DOMAIN="gui/${USER_ID}"' in script
    assert 'PLIST_DIR="${HOME}/Library/LaunchAgents"' in script
    assert 'LABEL="com.karkinos.daily-candidate"' in script
    assert 'launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"' in script
    assert 'launchctl bootout "${SERVICE_TARGET}"' in script
    assert "<key>RunAtLoad</key>" in script
    assert "<key>KeepAlive</key>" in script
    assert "<key>KeepAlive</key>\n  <true/>" in script
    assert "<key>SuccessfulExit</key>" not in script
    assert "<string>/usr/bin/env</string>" in script
    assert "<string>server</string>" in script
    assert "<string>--frozen</string>" in script
    assert 'BACKEND_HOST="127.0.0.1"' in script
    assert "<string>${BACKEND_HOST}</string>" in script
    assert "/bin/zsh" not in script
    assert "launchctl submit" not in script


def test_print_plist_is_write_free_and_escapes_local_paths(tmp_path: Path):
    repo = tmp_path / "repo & evidence"
    scripts = repo / "scripts"
    fake_bin = tmp_path / "bin"
    scripts.mkdir(parents=True)
    fake_bin.mkdir()
    copied_script = scripts / SCRIPT.name
    shutil.copy2(SCRIPT, copied_script)
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(0o755)

    result = subprocess.run(
        ["bash", str(copied_script), "print-plist"],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(tmp_path / "home"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "repo &amp; evidence" in result.stdout
    assert "repo & evidence" not in result.stdout
    assert str(fake_uv) in result.stdout
    assert not (tmp_path / "home" / "Library" / "LaunchAgents").exists()
    assert "<key>UV_CACHE_DIR</key>" in result.stdout
    assert "<string>127.0.0.1,localhost</string>" in result.stdout


def test_help_requires_explicit_install_or_uninstall():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "print-plist" in result.stdout
    assert "install" in result.stdout
    assert "status" in result.stdout
    assert "uninstall" in result.stdout
    assert "does not edit config.json or .env" in result.stdout


def test_install_and_uninstall_are_explicit_user_scoped_and_reversible(
    tmp_path: Path,
):
    repo, env = _fake_launch_agent_repo(tmp_path)
    command = ["bash", "scripts/manage_launch_agent.sh"]

    installed = subprocess.run(
        [*command, "install"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    plist = (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )
    assert installed.returncode == 0, installed.stderr
    assert plist.is_file()
    assert Path(env["KARKINOS_TEST_LAUNCHD_STATE"]).is_file()
    assert "Process liveness: alive" in installed.stdout
    assert "Financial readiness: not claimed" in installed.stdout

    env["KARKINOS_TEST_BOOTOUT_DELAY_SECONDS"] = "1"
    uninstalled = subprocess.run(
        [*command, "uninstall"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert uninstalled.returncode == 0, uninstalled.stderr
    assert not plist.exists()
    assert not Path(env["KARKINOS_TEST_LAUNCHD_STATE"]).exists()
    assert "Runtime data and logs were not deleted" in uninstalled.stdout


def test_install_preserves_an_existing_listener_without_bootstrap(tmp_path: Path):
    repo, env = _fake_launch_agent_repo(tmp_path)
    env["KARKINOS_TEST_LISTENER_PIDS"] = "4242"

    result = subprocess.run(
        ["bash", "scripts/manage_launch_agent.sh", "install"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    plist = (
        Path(env["HOME"])
        / "Library"
        / "LaunchAgents"
        / "com.karkinos.daily-candidate.plist"
    )
    assert result.returncode == 1
    assert "another Karkinos process already owns port 8000" in result.stderr
    assert "No process was terminated" in result.stderr
    assert not plist.exists()
    assert not Path(env["KARKINOS_TEST_LAUNCHD_STATE"]).exists()
