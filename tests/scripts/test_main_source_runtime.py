"""Stable source runtime uses the selected branch and shared local workspace."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.service import run_main as runtime


@pytest.fixture
def source(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / ".gitignore").write_text(
        ".run/\n.venv/\n.env\nconfig.json\ndata/store/\nlogs/\nexports/\n"
    )
    (tmp_path / "app.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "fixture")
    return tmp_path, git, git("rev-parse", "HEAD")


def test_clean_selected_branch_needs_no_remote_identity(source, monkeypatch):
    root, git, sha = source
    monkeypatch.setenv("KARKINOS_SOURCE_BRANCH", "main")
    assert git("tag", "--list") == ""
    assert runtime.check_source(root) == sha


def test_clean_local_commit_is_valid_source_code(source, monkeypatch):
    root, git, _sha = source
    (root / "app.py").write_text("value = 2\n")
    git("add", ".")
    git("commit", "-qm", "local commit")
    monkeypatch.setenv("KARKINOS_SOURCE_BRANCH", "main")
    assert runtime.check_source(root) == git("rev-parse", "HEAD")


@pytest.mark.parametrize("change", ["branch", "dirty", "untracked"])
def test_wrong_or_dirty_checkout_is_refused_without_reset(source, change, monkeypatch):
    root, git, _sha = source
    monkeypatch.setenv("KARKINOS_SOURCE_BRANCH", "main")
    if change == "branch":
        git("checkout", "-qb", "dev")
    elif change == "dirty":
        (root / "app.py").write_text("value = 2\n")
    else:
        (root / "extra.py").write_text("value = 2\n")
    before = git("status", "--porcelain")
    with pytest.raises(ValueError):
        runtime.check_source(root)
    assert git("status", "--porcelain") == before


def test_repo_root_is_default_workspace(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("KARKINOS_"):
            monkeypatch.delenv(key)

    env = runtime.runtime_environment(tmp_path)

    assert env["KARKINOS_WORKSPACE"] == str(tmp_path)
    assert env["KARKINOS_HOME"] == str(tmp_path)
    assert env["KARKINOS_DATA_DIR"] == str(tmp_path / "data/store")
    assert env["KARKINOS_CONFIG_PATH"] == str(tmp_path / "config.json")
    assert env["KARKINOS_ENV_FILE"] == str(tmp_path / ".env")
    assert env["KARKINOS_STATIC_DIR"] == str(tmp_path / "web/dist")


def test_explicit_workspace_and_legacy_alias(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("KARKINOS_WORKSPACE", str(workspace))
    env = runtime.runtime_environment(tmp_path)
    assert env["KARKINOS_WORKSPACE"] == str(workspace)
    assert env["KARKINOS_HOME"] == str(workspace)
    assert env["KARKINOS_DATA_DIR"] == str(workspace / "data/store")

    monkeypatch.setenv("KARKINOS_HOME", str(tmp_path / "other"))
    with pytest.raises(ValueError, match="different paths"):
        runtime.runtime_environment(tmp_path)


def test_managed_release_environment_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("KARKINOS_RELEASE_GUARD", "retained")
    with pytest.raises(ValueError, match="managed release"):
        runtime.runtime_environment(tmp_path)


class PortProbe:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def bind(self, address):
        assert address[0] == "127.0.0.1"


@pytest.fixture
def runtime_files(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / "data/store").mkdir(parents=True)
    (workspace / "config.json").write_text("{}\n")
    (workspace / ".env").write_text("\n")
    for name in ("app.db", "meta.db"):
        (workspace / "data/store" / name).write_text("fixture")
    env = {
        "KARKINOS_WORKSPACE": str(workspace),
        "KARKINOS_HOME": str(workspace),
        "KARKINOS_DATA_DIR": str(workspace / "data/store"),
        "KARKINOS_CONFIG_PATH": str(workspace / "config.json"),
        "KARKINOS_ENV_FILE": str(workspace / ".env"),
        "KARKINOS_STATIC_DIR": str(tmp_path / "web/dist"),
    }
    monkeypatch.setattr(runtime, "runtime_environment", lambda root: env)
    monkeypatch.setattr(runtime, "require_runtime_idle", lambda workspace: None)
    return env


def test_locked_preparation_and_state_preflight_before_launch(
    tmp_path, monkeypatch, runtime_files
):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    native_socket = runtime.socket.socket
    monkeypatch.setattr(
        runtime.socket,
        "socket",
        lambda *args: native_socket(*args) if args else PortProbe(),
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert callable(kwargs["monitor"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime, "run_preparation", run)
    monkeypatch.setattr(runtime, "supervise", lambda *args, **kwargs: 0)

    assert runtime.main(["--foreground"]) == 0
    assert commands[:3] == [
        ["uv", "sync", "--locked", "--extra", "server"],
        ["npm", "ci", "--prefix", "web"],
        ["npm", "--prefix", "web", "run", "build"],
    ]
    assert commands[-1][-3:] == ["-m", "server", "--check-state"]


def test_preparation_failure_cannot_launch_partial_service(
    tmp_path, monkeypatch, runtime_files
):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    native_socket = runtime.socket.socket
    monkeypatch.setattr(
        runtime.socket,
        "socket",
        lambda *args: native_socket(*args) if args else PortProbe(),
    )

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runtime, "run_preparation", fail)
    monkeypatch.setattr(
        runtime, "supervise", lambda *args: pytest.fail("must not start")
    )
    assert runtime.main(["--foreground"]) == 1


def test_child_exit_stops_peer_and_binds_both_to_parent_lifetime(tmp_path, monkeypatch):
    class Child:
        def __init__(self, exited):
            self.exited = exited
            self.terminated = False

        def poll(self):
            return 0 if self.exited else None

        def terminate(self):
            self.terminated = True
            self.exited = True

        def wait(self, timeout):
            return 0

    children = [Child(True), Child(False)]
    calls = []

    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return children[len(calls) - 1]

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    control = Mock()
    control.stop_requested.return_value = False
    assert runtime.supervise(tmp_path, {}, 8000, control) == 1
    assert children[1].terminated is True
    assert calls[0][0][-4:] == ["--host", "127.0.0.1", "--port", "8000"]
    assert calls[1][0][-1] == "--research-worker"
    assert "watch_supervisor_lifetime()" in runtime.CHILD_ENTRY
    for _, kwargs in calls:
        assert kwargs["start_new_session"] is True
        fd = kwargs["pass_fds"][0]
        assert kwargs["env"]["KARKINOS_SUPERVISOR_FD"] == str(fd)
        with pytest.raises(OSError):
            os.fstat(fd)
