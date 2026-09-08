"""Managed source preparation leaves developer and daily runtime state separate."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.service import run_main, source_main, source_state

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("KARKINOS_"):
            monkeypatch.delenv(name)
    remote = tmp_path / "remote"
    remote.mkdir()
    git = lambda *args: source_state.git(remote, *args)
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    for name in ("pyproject.toml", "uv.lock", "web/package-lock.json"):
        path = remote / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("fixture\n")
    (remote / ".gitignore").write_text(".venv/\nweb/dist/\nweb/node_modules/\n")
    shutil.copytree(
        REPO / "scripts/service",
        remote / "scripts/service",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    git("add", ".")
    git("commit", "-qm", "fixture main")
    sha = git("rev-parse", "HEAD")
    developer = tmp_path / "developer"
    subprocess.run(["git", "clone", "-q", str(remote), str(developer)], check=True)
    source_state.git(developer, "checkout", "-qb", "dev")
    (developer / "uv.lock").write_text("uncommitted development\n")
    (developer / "private.txt").write_text("untracked development\n")
    home = tmp_path / "account"
    for name in ("config/config.json", "config/.env", "data/app.db", "data/meta.db"):
        path = home / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original account fixture")
    monkeypatch.setenv("KARKINOS_HOME", str(home))
    env = run_main.runtime_environment(developer)
    env["KARKINOS_MAIN_PORT"] = "8000"
    for path in (
        home / "source",
        home / "source/checkouts",
        home / "source/prepared",
        home / "source/run",
    ):
        source_state.private_directory(path)
    monkeypatch.setattr(source_main, "ROOT", developer)
    return developer, remote, home, env, sha


@pytest.fixture
def builds(monkeypatch):
    commands = []
    original = source_main.run_preparation

    def run(command, *, cwd, env, monitor):
        commands.append((command, cwd, env))
        if command[0] == "git":
            return original(command, cwd=cwd, env=env, monitor=monitor)
        monitor()
        assert not any(name.startswith("KARKINOS_") for name in env)
        assert env["UV_PROJECT_ENVIRONMENT"] == str(cwd / ".venv")
        (cwd / ".venv/bin").mkdir(parents=True, exist_ok=True)
        (cwd / ".venv/bin/python").symlink_to(sys.executable)
        (cwd / ".venv/pyvenv.cfg").write_text("fixture python")
        (cwd / "web/dist/assets").mkdir(parents=True, exist_ok=True)
        (cwd / "web/dist/index.html").write_text("fixture frontend")
        (cwd / "web/dist/assets/app.js").write_text("fixture javascript")

    def preparation(command, **kwargs):
        # Build outputs are emitted by the final build command only.
        if command[0] != "git" and command[-1] != "build":
            commands.append((command, kwargs["cwd"], kwargs["env"]))
            kwargs["monitor"]()
            return None
        return run(command, **kwargs)

    monkeypatch.setattr(source_main, "run_preparation", preparation)
    return commands


def test_dirty_dev_prepares_exact_remote_main_without_touching_developer_or_account(
    project, builds
):
    developer, _, home, env, sha = project
    before = source_state.git(developer, "status", "--porcelain")
    account = {path: path.read_bytes() for path in home.rglob("*") if path.is_file()}
    checkout = source_main.prepare(developer, home, env, lambda: None)
    assert checkout == home / "source/checkouts" / sha
    assert source_state.check_prepared(checkout, home) == sha
    assert source_state.git(developer, "branch", "--show-current") == "dev"
    assert source_state.git(developer, "status", "--porcelain") == before
    assert all(path.read_bytes() == content for path, content in account.items())
    assert not (developer / ".venv").exists()
    assert not (developer / "web/dist").exists()
    assert not (home / "current").exists()
    assert not (home / "releases").exists()
    assert [command[0][0] for command in builds][-3:] == ["uv", "npm", "npm"]


def test_prepared_same_sha_is_reused_without_rebuilding(project, builds):
    developer, _, home, env, _ = project
    first = source_main.prepare(developer, home, env, lambda: None)
    builds.clear()
    second = source_main.prepare(developer, home, env, lambda: None)
    assert first == second
    assert len(builds) == 1
    assert builds[0][0][:2] == ["git", "fetch"]


@pytest.mark.parametrize(
    "name", ["uv.lock", "web/dist/assets/app.js", ".venv/pyvenv.cfg"]
)
def test_prepared_code_or_build_tampering_fails_closed(project, builds, name):
    developer, _, home, env, _ = project
    checkout = source_main.prepare(developer, home, env, lambda: None)
    (checkout / name).write_text("changed after preparation")
    with pytest.raises(ValueError, match="modified|build changed"):
        source_state.check_prepared(checkout, home)


def test_failed_build_never_stops_existing_service_or_selects_candidate(
    project, monkeypatch
):
    _, _, home, _, _ = project

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(7, ["fixture-build"])

    monkeypatch.setattr(source_main, "prepare", fail)
    monkeypatch.setattr(
        source_main,
        "request_stop",
        lambda *args: pytest.fail("must preserve running main"),
    )
    assert source_main.main([]) == 1
    assert not (home / "source/selected.json").exists()


def test_candidate_protocol_checked_before_stopping_old_service(
    project, builds, monkeypatch
):
    developer, _, home, env, _ = project
    checkout = source_main.prepare(developer, home, env, lambda: None)
    commands = []

    def reject(command, **kwargs):
        commands.append(command)
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(source_main, "run_preparation", reject)
    monkeypatch.setattr(
        source_main,
        "request_stop",
        lambda *args: pytest.fail("old service must survive incompatible protocol"),
    )
    with pytest.raises(subprocess.CalledProcessError):
        source_main.activate(checkout, home, env, restart=False, initialize=False)
    assert commands[0][-2:] == ["--prepared", "--check"]


def test_offline_restart_uses_selected_checkout_and_saved_account_without_git_or_build(
    project, builds, monkeypatch
):
    developer, _, home, env, sha = project
    checkout = source_main.prepare(developer, home, env, lambda: None)
    env["KARKINOS_MAIN_PORT"] = "8123"
    source_state.write_record(
        home / "source/selected.json",
        {"sha": sha, "bindings": source_main.runtime_bindings(env)},
    )
    monkeypatch.setattr(source_main, "ROOT", home / "not-a-git-repository")
    monkeypatch.setattr(
        source_main,
        "prepare",
        lambda *args: pytest.fail("offline must not fetch or build"),
    )
    seen = []
    monkeypatch.setattr(
        source_main,
        "activate",
        lambda root, selected_home, selected_env, **kwargs: seen.append(
            (root, selected_home, selected_env, kwargs)
        )
        or 0,
    )
    assert source_main.main(["--restart"]) == 0
    assert seen[0][0] == checkout
    assert seen[0][2]["KARKINOS_MAIN_PORT"] == "8123"
    assert seen[0][3]["restart"] is True
    assert seen[0][3]["initialize"] is False
    assert callable(seen[0][3]["monitor"])


def test_offline_conflicting_account_override_refused(project, builds, monkeypatch):
    developer, _, home, env, sha = project
    source_main.prepare(developer, home, env, lambda: None)
    source_state.write_record(
        home / "source/selected.json",
        {"sha": sha, "bindings": source_main.runtime_bindings(env)},
    )
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(home / "different-data"))
    monkeypatch.setattr(
        source_main,
        "activate",
        lambda *args, **kwargs: pytest.fail("must not start another account"),
    )
    assert source_main.main(["--no-update"]) == 1


def test_status_does_not_claim_stale_process_record_is_running(project):
    _, _, home, _, sha = project
    source_state.write_record(
        home / "source/run/running.json", {"sha": sha, "pid": 123}
    )
    status = source_main.selected_status(home)
    assert status["running"] is False
    assert status["process"] is None


def test_environment_cannot_redirect_managed_imports_or_installation(tmp_path):
    env = source_main.isolated_environment(
        tmp_path,
        {
            "PYTHONPATH": "/developer",
            "PYTHONHOME": "/developer",
            "VIRTUAL_ENV": "/developer/.venv",
            "UV_PROJECT": "/developer",
            "UV_PROJECT_ENVIRONMENT": "/developer/.venv",
            "GIT_WORK_TREE": "/developer",
            "NODE_PATH": "/developer/node_modules",
            "NODE_OPTIONS": "--require /developer/hook.js",
            "npm_config_prefix": "/developer",
            "NPM_CONFIG_USERCONFIG": "/developer/npmrc",
            "BASH_ENV": "/developer/bashrc",
            "ENV": "/developer/shellrc",
        },
    )
    assert set(env) == {
        "UV_PROJECT_ENVIRONMENT",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "KARKINOS_STATIC_DIR",
    }
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / ".venv")


def test_managed_supervisor_checks_candidate_identity_and_skips_dependency_preparation(
    project, builds, monkeypatch
):
    developer, _, home, env, sha = project
    checkout = source_main.prepare(developer, home, env, lambda: None)
    monkeypatch.setattr(run_main, "ROOT", checkout)
    monkeypatch.setattr(run_main, "require_runtime_idle", lambda env: None)
    monkeypatch.setattr(run_main, "require_port_available", lambda port: None)
    monkeypatch.setattr(
        run_main, "check_source", lambda root: pytest.fail("managed source is detached")
    )
    commands = []
    monkeypatch.setattr(
        run_main,
        "run_preparation",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )

    def supervise(root, runtime_env, port, control, **kwargs):
        assert root == checkout
        assert control.runtime_dir == home / "source/run"
        assert runtime_env["KARKINOS_STATIC_DIR"] == str(checkout / "web/dist")
        assert source_main.selected_status(home)["process"]["sha"] == sha
        return 0

    monkeypatch.setattr(run_main, "supervise", supervise)
    assert run_main.main(["--prepared", "--foreground"]) == 0
    assert len(commands) == 1
    assert commands[0][0] == [
        str(checkout / ".venv/bin/python"),
        "-m",
        "server",
        "--check-state",
    ]
    assert not (home / "source/run/running.json").exists()


@pytest.mark.parametrize("action", ["--status", "--stop", "--logs"])
def test_management_only_needs_home_not_credentials_branch_or_port(
    project, monkeypatch, action
):
    _, _, home, _, _ = project
    monkeypatch.setenv("KARKINOS_RELEASE_GUARD", "unrelated")
    monkeypatch.setenv("KARKINOS_DATA_DIR", "relative-and-invalid")
    monkeypatch.setenv("KARKINOS_MAIN_PORT", "invalid")
    monkeypatch.setattr(source_main, "ROOT", home / "no-checkout")
    monkeypatch.setattr(source_main.subprocess, "call", lambda *args, **kwargs: 0)
    assert source_main.main([action]) == 0


def test_incomplete_activation_blocks_offline_even_after_new_process_exits(
    project, builds, monkeypatch
):
    developer, _, home, env, sha = project
    source_main.prepare(developer, home, env, lambda: None)
    source_state.write_record(
        home / "source/selected.json",
        {"sha": sha, "bindings": source_main.runtime_bindings(env)},
    )
    source_state.write_record(
        home / "source/activation.json",
        {"sha": "b" * 40, "bindings": source_main.runtime_bindings(env)},
    )
    monkeypatch.setattr(
        source_main,
        "activate",
        lambda *args, **kwargs: pytest.fail(
            "must not roll back after interrupted activation"
        ),
    )
    assert source_main.main(["--restart"]) == 1
    status = source_main.selected_status(home)
    assert status["running"] is False
    assert status["activation"]["sha"] == "b" * 40


def test_selection_write_failure_retains_activation_and_does_not_stop_new_service(
    project, builds, monkeypatch
):
    developer, _, home, env, sha = project
    checkout = source_main.prepare(developer, home, env, lambda: None)
    native_write = source_state.write_record

    def write(path, record):
        if path.name == "selected.json":
            raise OSError("fixture disk failure")
        native_write(path, record)

    monkeypatch.setattr(source_state, "write_record", write)
    calls = []
    monkeypatch.setattr(
        source_main, "run_preparation", lambda command, **kwargs: calls.append(command)
    )
    stops = []
    monkeypatch.setattr(
        source_main, "request_stop", lambda path: stops.append(path) or 0
    )
    with pytest.raises(RuntimeError, match="selection could not be saved"):
        source_main.activate(checkout, home, env, restart=False, initialize=False)
    assert len(stops) == 1
    assert len(calls) == 2
    assert source_state.read_record(home / "source/activation.json")["sha"] == sha
    assert not (home / "source/selected.json").exists()


def test_stop_cancels_real_update_process_and_releases_control_before_return(
    project, tmp_path
):
    developer, _, home, env, _ = project
    marker = tmp_path / "preparing.pid"
    child = (
        "import os,time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); time.sleep(60)"
        % str(marker)
    )
    driver = tmp_path / "update_driver.py"
    driver.write_text(
        "import sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from scripts.service import source_main\n"
        f"source_main.ROOT = Path({str(developer)!r})\n"
        "def prepare(root, home, env, monitor):\n"
        f"    source_main.run_preparation([sys.executable, '-c', {child!r}], cwd=root, env=env, monitor=monitor)\n"
        "    raise AssertionError('cancelled preparation must not finish')\n"
        "source_main.prepare = prepare\n"
        "raise SystemExit(source_main.main())\n"
    )
    updater = subprocess.Popen(
        [sys.executable, str(driver)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        pid = int(marker.read_text())
        stopped = subprocess.run(
            [sys.executable, str(driver), "--stop"],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert stopped.returncode == 0, stopped.stderr
        updater.communicate(timeout=5)
        assert updater.returncode == 1
        assert not source_main._lock_held(home / "source/update")
        assert not (home / "source/update/control.sock").exists()
        assert not (home / "source/selected.json").exists()
        # Preparation is a real process owned by the cancellation wrapper.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if updater.poll() is None:
            updater.kill()
            updater.communicate(timeout=5)


def test_foreground_does_not_stop_replacement_instance(project, monkeypatch):
    _, _, home, _, _ = project
    records = iter(
        [
            {"process": {"token": "old"}},
            {"process": {"token": "new"}},
            {"process": {"token": "new"}},
        ]
    )
    monkeypatch.setattr(source_main, "selected_status", lambda home: next(records))

    class Tail:
        stopped = False
        returncode = 0

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(source_main.subprocess, "Popen", lambda *args, **kwargs: Tail())
    monkeypatch.setattr(
        source_main,
        "request_stop",
        lambda *args: pytest.fail("must leave replacement instance running"),
    )
    assert source_main.follow_service(home, "old") == 0


def test_foreground_identity_is_captured_before_releasing_update_lock(
    project, monkeypatch
):
    _, _, home, _, _ = project
    monkeypatch.setattr(
        source_main, "selected_status", lambda home: {"process": {"token": "new"}}
    )
    monkeypatch.setattr(
        source_main.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("must not attach to replacement service"),
    )
    monkeypatch.setattr(
        source_main,
        "request_stop",
        lambda *args: pytest.fail("must not stop replacement service"),
    )
    assert source_main.follow_service(home, "old") == 0


@pytest.mark.parametrize("mismatch", ["sha", "account"])
def test_offline_restart_refuses_live_identity_drift_even_without_activation_marker(
    project, builds, monkeypatch, mismatch
):
    developer, _, home, env, sha = project
    source_main.prepare(developer, home, env, lambda: None)
    bindings = source_main.runtime_bindings(env)
    source_state.write_record(
        home / "source/selected.json", {"sha": sha, "bindings": bindings}
    )
    process = {"sha": sha, "bindings": dict(bindings)}
    if mismatch == "sha":
        process["sha"] = "b" * 40
    else:
        process["bindings"]["KARKINOS_DATA_DIR"] = str(home / "another-account")
    monkeypatch.setattr(
        source_main,
        "selected_status",
        lambda home: {"running": True, "process": process},
    )
    monkeypatch.setattr(
        source_main,
        "activate",
        lambda *args, **kwargs: pytest.fail("must preserve the running identity"),
    )
    assert source_main.main(["--restart"]) == 1


@pytest.mark.parametrize(
    "name,value",
    [("KARKINOS_DATA_DIR", "relative-data"), ("KARKINOS_MAIN_PORT", "65536")],
)
def test_offline_selection_rejects_invalid_saved_runtime_paths_and_port(
    project, builds, monkeypatch, name, value
):
    developer, _, home, env, sha = project
    source_main.prepare(developer, home, env, lambda: None)
    bindings = source_main.runtime_bindings(env)
    bindings[name] = value
    source_state.write_record(
        home / "source/selected.json", {"sha": sha, "bindings": bindings}
    )
    monkeypatch.setattr(
        source_main,
        "activate",
        lambda *args, **kwargs: pytest.fail(
            "invalid configuration must not reach activation"
        ),
    )
    assert source_main.main(["--no-update"]) == 1
