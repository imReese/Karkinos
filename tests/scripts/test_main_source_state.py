"""A source restart must preserve account selection and refuse concurrent writers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.service import run_main as runtime


@pytest.fixture
def account(tmp_path, monkeypatch):
    home = tmp_path / "account"
    for key in tuple(os.environ):
        if key.startswith("KARKINOS_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("KARKINOS_HOME", str(home))
    monkeypatch.setattr(runtime, "ROOT", tmp_path / "source")
    monkeypatch.setattr(runtime, "check_source", lambda root: "a" * 40)
    (home / "config").mkdir(parents=True)
    (home / "data").mkdir()
    for name in ("config/config.json", "config/.env", "data/app.db", "data/meta.db"):
        (home / name).write_bytes(b"original account fixture")
    return home, runtime.runtime_environment(runtime.ROOT)


@pytest.mark.parametrize(
    "key",
    ["KARKINOS_HOME", "KARKINOS_DATA_DIR", "KARKINOS_CONFIG_PATH", "KARKINOS_ENV_FILE"],
)
@pytest.mark.parametrize("value", ["", "relative/path"])
def test_ambiguous_path_overrides_are_refused(account, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="absolute path"):
        runtime.runtime_environment(runtime.ROOT)


def test_original_files_selected_without_copying_or_reinitializing(account):
    home, env = account
    before = {
        path.relative_to(home): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }
    runtime.require_runtime_files(env, initialize=False)
    after = {
        path.relative_to(home): path.read_bytes()
        for path in home.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (runtime.ROOT / ".run/main/data").exists()


@pytest.mark.parametrize(
    "missing", ["config/config.json", "config/.env", "data/app.db", "data/meta.db"]
)
def test_missing_original_files_fail_before_install_or_database_write(
    account, monkeypatch, missing
):
    home, _ = account
    (home / missing).unlink()
    run = Mock(side_effect=AssertionError("must not prepare or initialize"))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.main([]) == 1
    run.assert_not_called()
    assert not (runtime.ROOT / ".run").exists()


def test_new_account_requires_explicit_init_and_never_overwrites_existing(account):
    home, env = account
    with pytest.raises(ValueError, match="empty data"):
        runtime.require_runtime_files(env, initialize=True)
    for name in ("app.db", "meta.db"):
        (home / "data" / name).unlink()
    with pytest.raises(ValueError, match="existing account databases missing"):
        runtime.require_runtime_files(env, initialize=False)
    runtime.require_runtime_files(env, initialize=True)
    assert list((home / "data").iterdir()) == []


@pytest.mark.parametrize(
    "journal", [".release-transaction.json", ".legacy-bootstrap-transaction.json"]
)
@pytest.mark.parametrize("broken_link", [False, True])
def test_pending_recovery_prevents_even_preparation(
    account, monkeypatch, journal, broken_link
):
    home, _ = account
    if broken_link:
        (home / journal).symlink_to(home / "absent-target")
    else:
        (home / journal).write_text("recovery must remain visible")
    monkeypatch.setattr(
        runtime.subprocess, "run", Mock(side_effect=AssertionError("must not prepare"))
    )
    assert runtime.main([]) == 1
    assert (home / journal).is_symlink() or (
        home / journal
    ).read_text() == "recovery must remain visible"


@pytest.mark.parametrize(
    "loaded", ["com.karkinos.daily-candidate", "com.karkinos.research-worker"]
)
def test_each_loaded_managed_service_blocks_even_without_pid(
    account, monkeypatch, loaded
):
    _, env = account
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    commands = []

    def launchctl(command, **kwargs):
        commands.append(command)
        if command[-1].endswith(loaded):
            return subprocess.CompletedProcess(
                command, 0, stdout="state = waiting", stderr=""
            )
        return subprocess.CompletedProcess(
            command, 113, stdout="", stderr="Could not find service"
        )

    monkeypatch.setattr(runtime.subprocess, "run", launchctl)
    with pytest.raises(ValueError, match=loaded):
        runtime.require_runtime_idle(env)
    assert len(commands) == (1 if loaded.endswith("daily-candidate") else 2)


def test_unknown_launchctl_failure_is_not_treated_as_stopped(account, monkeypatch):
    _, env = account
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="permission denied"
        ),
    )
    with pytest.raises(ValueError, match="cannot verify"):
        runtime.require_runtime_idle(env)


@pytest.mark.parametrize("filename", [".release.lock", "data/.source-runtime.lock"])
def test_other_checkout_or_release_owner_prevents_start(account, monkeypatch, filename):
    home, _ = account
    monkeypatch.setattr(runtime, "require_runtime_idle", lambda env: None)
    run = Mock(
        side_effect=AssertionError("must not install or initialize under another owner")
    )
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with runtime.exclusive_lock(home / filename):
        assert runtime.main([]) == 1
    run.assert_not_called()


def test_runtime_lock_refuses_symlink_without_touching_target(tmp_path):
    target = tmp_path / "account-fact"
    target.write_bytes(b"retained")
    link = tmp_path / "lock"
    link.symlink_to(target)
    with pytest.raises(OSError):
        with runtime.exclusive_lock(link):
            pytest.fail("symlink lock must not be acquired")
    assert target.read_bytes() == b"retained"


@pytest.mark.parametrize(
    "marker",
    ["current", ".service-config.json", ".release.lock", *runtime.RECOVERY_JOURNALS],
)
def test_alternate_home_cannot_bypass_account_home_recovery(
    account, monkeypatch, tmp_path, marker
):
    home, _ = account
    (home / marker).write_text("owned runtime marker")
    alternate = tmp_path / "alternate"
    (alternate / "config").mkdir(parents=True)
    for name in ("config.json", ".env"):
        (alternate / "config" / name).write_text("alternate config")
    monkeypatch.setenv("KARKINOS_HOME", str(alternate))
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(home / "data"))
    env = runtime.runtime_environment(runtime.ROOT)
    with pytest.raises(ValueError, match="another runtime home"):
        runtime.require_runtime_files(env, initialize=False)
    assert (home / marker).read_text() == "owned runtime marker"


def test_init_rechecks_empty_account_after_preparation(account, monkeypatch):
    home, _ = account
    for name in ("app.db", "meta.db"):
        (home / "data" / name).unlink()
    monkeypatch.setattr(runtime, "require_runtime_idle", lambda env: None)
    from contextlib import nullcontext

    port = Mock()
    monkeypatch.setattr(runtime.socket, "socket", lambda: nullcontext(port))
    commands = []

    def prepare(command, **kwargs):
        assert (
            "--check-state" not in command
        ), "must not initialize newly discovered account data"
        commands.append(command)
        (home / "data/app.db").write_bytes(b"account appeared during preparation")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime.subprocess, "run", prepare)
    assert runtime.main(["--init"]) == 1
    assert len(commands) == 3
    assert (home / "data/app.db").read_bytes() == b"account appeared during preparation"
    assert not (home / "data/meta.db").exists()


def test_stop_does_not_need_clean_main_or_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(
        runtime,
        "check_source",
        Mock(side_effect=AssertionError("stop must work on dirty checkout")),
    )
    stop = Mock(return_value=0)
    monkeypatch.setattr(runtime, "request_stop", stop)
    assert runtime.main(["--stop"]) == 0
    stop.assert_called_once_with(tmp_path / ".run/main")
