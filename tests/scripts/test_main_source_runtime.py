"""Tag-free source startup must not mutate branches or take over production."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

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
    (tmp_path / ".gitignore").write_text(".run/\n.venv/\n")
    (tmp_path / "app.py").write_text("value = 1\n")
    git("add", ".")
    git("commit", "-qm", "fixture")
    sha = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", sha)
    return tmp_path, git, sha


def test_clean_main_needs_no_tag(source):
    root, git, sha = source
    assert git("tag", "--list") == ""
    assert runtime.check_source(root) == sha


@pytest.mark.parametrize("change", ["branch", "dirty", "untracked", "ahead"])
def test_unverified_checkout_is_refused_without_reset(source, change):
    root, git, sha = source
    if change == "branch":
        git("checkout", "-qb", "dev")
    elif change == "dirty":
        (root / "app.py").write_text("value = 2\n")
    elif change == "untracked":
        (root / "extra.py").write_text("value = 2\n")
    else:
        (root / "app.py").write_text("value = 2\n")
        git("add", ".")
        git("commit", "-qm", "local only")
    before = git("status", "--porcelain")
    with pytest.raises(ValueError):
        runtime.check_source(root)
    assert git("status", "--porcelain") == before


def test_data_is_separate_by_default_and_explicit_selection_is_respected(
    tmp_path, monkeypatch
):
    for key in tuple(os.environ):
        if key.startswith("KARKINOS_RELEASE_") or key in {
            "KARKINOS_ARTIFACT_FINGERPRINT",
            "KARKINOS_DATA_DIR",
        }:
            monkeypatch.delenv(key)
    env = runtime.runtime_environment(tmp_path)
    assert env["KARKINOS_DATA_DIR"] == str(tmp_path / ".run/main/data")
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path / "explicit-data"))
    assert runtime.runtime_environment(tmp_path)["KARKINOS_DATA_DIR"].endswith(
        "explicit-data"
    )
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


def test_locked_preparation_and_state_preflight_before_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    monkeypatch.setattr(runtime.socket, "socket", PortProbe)
    monkeypatch.setattr(
        runtime,
        "runtime_environment",
        lambda root: {"KARKINOS_DATA_DIR": str(tmp_path / "data")},
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", run)

    def supervise(*args):
        assert len(commands) == 4
        return 0

    monkeypatch.setattr(runtime, "supervise", supervise)
    assert runtime.main([]) == 0
    assert commands[:3] == [
        ["uv", "sync", "--locked", "--extra", "server"],
        ["npm", "ci", "--prefix", "web"],
        ["npm", "--prefix", "web", "run", "build"],
    ]
    assert commands[-1][-3:] == ["-m", "server", "--check-state"]


def test_preparation_failure_cannot_launch_partial_service(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    monkeypatch.setattr(runtime.socket, "socket", PortProbe)
    monkeypatch.setattr(
        runtime,
        "runtime_environment",
        lambda root: {"KARKINOS_DATA_DIR": str(tmp_path / "data")},
    )

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runtime.subprocess, "run", fail)
    monkeypatch.setattr(
        runtime, "supervise", lambda *args: pytest.fail("must not start")
    )
    assert runtime.main([]) == 1


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
    assert runtime.supervise(tmp_path, {}, 8000) == 1
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
