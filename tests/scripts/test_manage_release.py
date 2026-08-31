from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.release import bootstrap_legacy, manage_release, update_workflow
from tools import release_artifact

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40
_SHA_D = "d" * 40


def _native_release(root: Path, commit_sha: str) -> Path:
    root.mkdir(parents=True)
    (root / "bin").mkdir()
    launcher = root / "bin" / "karkinos"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    (root / "app" / "server").mkdir(parents=True)
    (root / "app" / "server" / "__init__.py").write_text(
        '__version__ = "0.3.1"\n', encoding="utf-8"
    )
    (root / "app" / "server" / "__main__.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )
    (root / "app" / "server" / "app.py").write_text(
        "def create_app():\n    return None\n", encoding="utf-8"
    )
    (root / "app" / "web" / "dist").mkdir(parents=True)
    (root / "app" / "web" / "dist" / "index.html").write_text(
        "<!doctype html>\n", encoding="utf-8"
    )
    (root / "runtime" / "bin").mkdir(parents=True)
    runtime_python = root / "runtime" / "bin" / "python3.12"
    runtime_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime_python.chmod(0o755)
    for relative_name in release_artifact.REQUIRED_RELEASE_CONTROL_FILES:
        control_file = root / relative_name
        control_file.parent.mkdir(parents=True, exist_ok=True)
        control_file.write_text(f"fixture:{relative_name}\n", encoding="utf-8")
    for relative_name in release_artifact.REQUIRED_RELEASE_CONTROL_EXECUTABLES:
        (root / relative_name).chmod(0o755)
    manifest: dict[str, object] = {
        "schema_version": release_artifact.NATIVE_ARTIFACT_SCHEMA,
        "artifact_kind": "macos-native",
        "release_control_protocol": release_artifact.RELEASE_CONTROL_PROTOCOL,
        "version": "0.3.1",
        "commit_sha": commit_sha,
        "architecture": "arm64",
        "entrypoint": "bin/karkinos",
        "runtime": "python3.12",
        "mutable_state": "~/Library/Application Support/Karkinos",
    }
    manifest["file_checksums"] = release_artifact.payload_checksums(root)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(root)
    (root / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    return root


def _release(home: Path, commit_sha: str) -> Path:
    manage_release._ensure_layout(home)
    return _native_release(home / "releases" / f"sha-{commit_sha}", commit_sha)


def _candidate(home: Path, commit_sha: str) -> Path:
    manage_release._ensure_layout(home)
    return _native_release(home / "releases" / f".candidate-{commit_sha}", commit_sha)


def _refresh_manifest(release: Path) -> dict[str, object]:
    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
    manifest["file_checksums"] = release_artifact.payload_checksums(release)
    manifest["payload_fingerprint"] = release_artifact.payload_fingerprint(release)
    (release / "release.json").write_bytes(release_artifact.canonical_json(manifest))
    return release_artifact.validate_manifest(release)


def _point(home: Path, name: str, release: Path | None) -> None:
    pointer = home / name
    pointer.unlink(missing_ok=True)
    if release is not None:
        pointer.symlink_to(Path("releases") / release.name)


def _pointer_sha(home: Path, name: str) -> str | None:
    pointer = manage_release._read_pointer(home / name)
    if pointer is None:
        return None
    return pointer.name.removeprefix("sha-")


class _ServiceRecorder:
    def __init__(self, health_results: Iterator[bool] | None = None) -> None:
        self.events: list[object] = []
        self.start_timeouts: list[int] = []
        self.health_results = health_results

    def stop(self) -> None:
        self.events.append("stop")

    def start(self, health_timeout: int) -> None:
        self.start_timeouts.append(health_timeout)
        self.events.append("start")

    def health(
        self, release: Path, manifest: dict[str, object], timeout: float
    ) -> bool:
        self.events.append(("health", manifest["commit_sha"], release.name, timeout))
        if self.health_results is None:
            return True
        return next(self.health_results)

    def hooks(self) -> manage_release.ReleaseServiceHooks:
        return manage_release.ReleaseServiceHooks(
            stop=self.stop,
            start=self.start,
            health=self.health,
        )


def _write_interrupted_deploy(
    home: Path,
    *,
    old_current: str,
    old_previous: str,
    target: str,
    phase: str = "switched",
) -> None:
    snapshot_id = "e" * 32
    manage_release._snapshot_mutable_state(home, snapshot_id)
    journal = home / ".release-transaction.json"
    journal.write_text(
        json.dumps(
            {
                "schema_version": "karkinos.release_transaction.v2",
                "operation": "deploy",
                "old_current": old_current,
                "old_previous": old_previous,
                "target": target,
                "snapshot_id": snapshot_id,
                "phase": phase,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    journal.chmod(0o600)


def test_layout_and_lock_are_private(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    for path in (
        home,
        home / "releases",
        home / "data",
        home / "config",
        home / "logs",
    ):
        path.chmod(0o755)

    with manage_release._lock(home):
        assert stat.S_IMODE((home / ".release.lock").stat().st_mode) == 0o600

    assert (home / ".release.lock").read_text(encoding="utf-8") == ""
    assert (home / ".release.lock").stat().st_nlink == 1

    with manage_release._lock(home):
        assert (home / ".release.lock").read_text(encoding="utf-8")

    for path in (
        home,
        home / "releases",
        home / "data",
        home / "config",
        home / "logs",
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_release_lock_rejects_hardlink_without_modifying_victim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"do-not-truncate")
    victim.chmod(0o644)
    os.link(victim, home / ".release.lock")

    with pytest.raises(ValueError, match="release_lock_invalid"):
        with manage_release._lock(home):
            raise AssertionError("hardlinked lock must not be acquired")

    assert victim.read_bytes() == b"do-not-truncate"
    assert stat.S_IMODE(victim.stat().st_mode) == 0o644
    assert manage_release._ACTIVE_RELEASE_LOCKS == {}


def test_release_lock_rechecks_path_identity_after_flock_without_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    lock_path = home / ".release.lock"
    detached = tmp_path / "detached-lock"
    lock_path.write_bytes(b"original-lock-content")
    lock_path.chmod(0o644)
    real_flock = manage_release.fcntl.flock
    swapped = False

    def swap_after_lock(descriptor: int, operation: int) -> None:
        nonlocal swapped
        real_flock(descriptor, operation)
        if operation == manage_release.fcntl.LOCK_EX and not swapped:
            swapped = True
            os.replace(lock_path, detached)
            lock_path.write_bytes(b"replacement-lock-content")
            lock_path.chmod(0o644)

    monkeypatch.setattr(manage_release.fcntl, "flock", swap_after_lock)

    with pytest.raises(ValueError, match="release_lock_invalid"):
        with manage_release._lock(home):
            raise AssertionError("replaced lock path must not be acquired")

    assert detached.read_bytes() == b"original-lock-content"
    assert stat.S_IMODE(detached.stat().st_mode) == 0o644
    assert lock_path.read_bytes() == b"replacement-lock-content"
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o644
    assert manage_release._ACTIVE_RELEASE_LOCKS == {}


def test_state_snapshot_recursively_syncs_files_and_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    (home / "data" / "nested").mkdir()
    (home / "data" / "nested" / "app.db").write_bytes(b"authoritative")
    (home / "config" / "config.json").write_text("{}\n", encoding="utf-8")
    synced_modes: list[int] = []
    original_fsync = manage_release.os.fsync

    def record_fsync(descriptor: int) -> None:
        synced_modes.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
        original_fsync(descriptor)

    monkeypatch.setattr(manage_release.os, "fsync", record_fsync)

    manage_release._snapshot_mutable_state(home, "3" * 32)

    assert synced_modes.count(stat.S_IFREG) == 2
    assert synced_modes.count(stat.S_IFDIR) >= 5


def test_state_snapshot_uses_portable_copy_outside_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    (home / "data" / "app.db").write_bytes(b"authoritative")
    monkeypatch.setattr(manage_release.platform, "system", lambda: "Linux")
    original_copytree = manage_release.shutil.copytree
    copy_symlink_modes: list[bool] = []

    def reject_subprocess(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("non-Darwin snapshots must not call macOS cp")

    def record_copytree(
        source: Path, destination: Path, *, symlinks: bool = False
    ) -> Path:
        copy_symlink_modes.append(symlinks)
        return original_copytree(source, destination, symlinks=symlinks)

    monkeypatch.setattr(manage_release.subprocess, "run", reject_subprocess)
    monkeypatch.setattr(manage_release.shutil, "copytree", record_copytree)

    snapshot_id = "5" * 32
    manage_release._snapshot_mutable_state(home, snapshot_id)

    snapshot = manage_release._validate_state_snapshot(home, snapshot_id)
    assert (snapshot / "data" / "app.db").read_bytes() == b"authoritative"
    assert copy_symlink_modes == [True, True]


def test_portable_state_snapshot_copy_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    monkeypatch.setattr(manage_release.platform, "system", lambda: "Linux")

    def fail_copy(_source: Path, _destination: Path, *, symlinks: bool = False) -> None:
        assert symlinks is True
        raise OSError("injected portable copy failure")

    monkeypatch.setattr(manage_release.shutil, "copytree", fail_copy)

    snapshot_id = "6" * 32
    with pytest.raises(ValueError, match="release_state_snapshot_clone_failed"):
        manage_release._snapshot_mutable_state(home, snapshot_id)

    root = home / ".release-state-snapshots"
    assert not (root / snapshot_id).exists()
    assert not (root / f".staging-{snapshot_id}").exists()


def test_macos_state_snapshot_clone_failure_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    monkeypatch.setattr(manage_release.platform, "system", lambda: "Darwin")

    def fail_clone(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert command[:3] == ["/bin/cp", "-cR", "--"]
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(manage_release.subprocess, "run", fail_clone)

    snapshot_id = "8" * 32
    with pytest.raises(ValueError, match="release_state_snapshot_clone_failed"):
        manage_release._snapshot_mutable_state(home, snapshot_id)

    root = home / ".release-state-snapshots"
    assert not (root / snapshot_id).exists()
    assert not (root / f".staging-{snapshot_id}").exists()


def test_state_snapshot_sync_failure_never_publishes_partial_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    (home / "data" / "app.db").write_bytes(b"authoritative")
    snapshot_id = "4" * 32

    def fail_sync(_path: Path) -> None:
        raise ValueError("release_mutable_state_sync_failed")

    monkeypatch.setattr(manage_release, "_fsync_private_tree", fail_sync)

    with pytest.raises(ValueError, match="release_mutable_state_sync_failed"):
        manage_release._snapshot_mutable_state(home, snapshot_id)

    root = home / ".release-state-snapshots"
    assert not (root / snapshot_id).exists()
    assert not (root / f".staging-{snapshot_id}").exists()


def test_staged_release_recursively_syncs_payload_files_and_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _native_release(tmp_path / "Karkinos-native", _SHA_D)
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname=source.name)
    home = tmp_path / "runtime"
    monkeypatch.setattr(manage_release, "_architecture", lambda: "arm64")
    synced_modes: list[int] = []
    original_fsync = manage_release.os.fsync

    def record_fsync(descriptor: int) -> None:
        synced_modes.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
        original_fsync(descriptor)

    monkeypatch.setattr(manage_release.os, "fsync", record_fsync)

    manage_release._stage(home, archive, _SHA_D, manage_release._sha256(archive))

    source_files = sum(path.is_file() for path in source.rglob("*"))
    source_directories = 1 + sum(path.is_dir() for path in source.rglob("*"))
    assert synced_modes.count(stat.S_IFREG) >= source_files
    assert synced_modes.count(stat.S_IFDIR) >= source_directories + 1


def test_release_tree_sync_failure_never_publishes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _native_release(tmp_path / "Karkinos-native", _SHA_D)
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname=source.name)
    home = tmp_path / "runtime"
    monkeypatch.setattr(manage_release, "_architecture", lambda: "arm64")

    def fail_sync(_path: Path) -> None:
        raise ValueError("release_immutable_tree_sync_failed")

    monkeypatch.setattr(manage_release, "_fsync_release_tree", fail_sync)

    with pytest.raises(ValueError, match="release_immutable_tree_sync_failed"):
        manage_release._stage(
            home,
            archive,
            _SHA_D,
            manage_release._sha256(archive),
        )

    releases = home / "releases"
    assert not (releases / f".candidate-{_SHA_D}").exists()
    assert not list(releases.glob(".staging-*"))


def test_staged_release_is_sealed_and_validated_removal_can_delete_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _native_release(tmp_path / "Karkinos-native", _SHA_D)
    archive = tmp_path / "candidate.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(source, arcname=source.name)
    home = tmp_path / "runtime"
    monkeypatch.setattr(manage_release, "_architecture", lambda: "arm64")

    candidate = manage_release._stage(
        home, archive, _SHA_D, manage_release._sha256(archive)
    )

    release_artifact.validate_manifest(candidate, expected_commit_sha=_SHA_D)
    assert stat.S_IMODE(candidate.stat().st_mode) == 0o555
    assert stat.S_IMODE((candidate / "release.json").stat().st_mode) == 0o444
    assert stat.S_IMODE((candidate / "bin" / "karkinos").stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o555
        for path in candidate.rglob("*")
        if path.is_dir()
    )

    manage_release._remove_tree(candidate)

    assert not candidate.exists()


def test_strict_orphan_staging_tree_is_cleaned_before_next_operation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    releases = manage_release._ensure_layout(home)
    staging = releases / f".staging-{'1' * 32}"
    staging.mkdir()
    (staging / "partial-archive.tar.gz").write_bytes(b"partial")

    with manage_release._lock(home):
        manage_release._require_clean_transaction_state_locked(home)

    assert not staging.exists()


def test_interrupted_release_delete_leaves_recoverable_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "runtime"
    inactive = _release(home, _SHA_C)
    original_rmtree = manage_release.shutil.rmtree
    interrupted = False

    def interrupt_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal interrupted
        if not interrupted and path.name.startswith(".deleting-sha-"):
            interrupted = True
            (path / "release.json").unlink()
            raise OSError("injected partial deletion")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(manage_release.shutil, "rmtree", interrupt_once)
    with pytest.raises(ValueError, match="release_remove_failed"):
        manage_release._remove_tree(inactive)

    tombstones = list((home / "releases").glob(".deleting-sha-*"))
    assert not inactive.exists()
    assert len(tombstones) == 1

    monkeypatch.setattr(manage_release.shutil, "rmtree", original_rmtree)
    with manage_release._lock(home):
        manage_release._require_clean_transaction_state_locked(home)

    assert not tombstones[0].exists()


def test_state_compatibility_probe_runs_target_checker_only_on_snapshot_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    release = _release(home, _SHA_A)
    launcher = release / "bin" / "karkinos"
    launcher.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "--check-state" ] || exit 2\n'
        'printf migrated > "$KARKINOS_DATA_DIR/app.db"\n'
        "printf 'Karkinos persisted state compatible\\n'\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    manifest = _refresh_manifest(release)
    (home / "data" / "app.db").write_bytes(b"authoritative-original")
    (home / "config" / "config.json").write_text("{}\n", encoding="utf-8")
    snapshot_id = "f" * 32
    manage_release._snapshot_mutable_state(home, snapshot_id)
    snapshot = manage_release._validate_state_snapshot(home, snapshot_id)
    original_run = manage_release.subprocess.run
    checker_stdio: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command == [str(launcher), "--check-state"]:
            checker_stdio.update(
                {"stdout": kwargs.get("stdout"), "stderr": kwargs.get("stderr")}
            )
        return original_run(command, **kwargs)

    monkeypatch.setattr(manage_release.subprocess, "run", run)

    manage_release._probe_state_compatibility(release, manifest, snapshot, 5)

    assert checker_stdio == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    assert (snapshot / "data" / "app.db").read_bytes() == b"authoritative-original"
    assert (home / "data" / "app.db").read_bytes() == b"authoritative-original"
    manage_release._discard_state_snapshot(home, snapshot_id)


def test_deploy_switches_service_then_prunes_to_current_and_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    obsolete_previous = _release(home, _SHA_B)
    inactive = _release(home, _SHA_C)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", obsolete_previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder()

    result = manage_release.deploy_release(
        home,
        commit_sha=_SHA_D,
        confirmation=f"PROMOTE {_SHA_D}",
        health_timeout=4,
        hooks=service.hooks(),
    )

    assert _pointer_sha(home, "current") == _SHA_D
    assert _pointer_sha(home, "previous") == _SHA_A
    assert {path.name for path in (home / "releases").iterdir()} == {
        f"sha-{_SHA_A}",
        f"sha-{_SHA_D}",
    }
    assert not obsolete_previous.exists()
    assert not inactive.exists()
    assert not (home / ".release-transaction.json").exists()
    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_D, f"sha-{_SHA_D}", 4),
        ("health", _SHA_D, f"sha-{_SHA_D}", 4),
    ]
    assert service.start_timeouts == [4]
    assert result["current"] == _SHA_D
    assert result["previous"] == _SHA_A


def test_failed_deploy_restores_and_rechecks_previous_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder(iter((False, True, True)))

    with pytest.raises(ValueError):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=service.hooks(),
        )

    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") == _SHA_B
    assert not (home / ".release-transaction.json").exists()
    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_D, f"sha-{_SHA_D}", 5),
        "stop",
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 5),
        ("health", _SHA_A, f"sha-{_SHA_A}", 5),
    ]


def test_post_guard_iteration_failure_rolls_back_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    events: list[object] = []
    observed_phases: list[str] = []

    def health(release: Path, manifest: dict[str, object], timeout: float) -> bool:
        journal = manage_release._read_transaction(home)
        assert journal is not None
        phase = str(journal["phase"])
        observed_phases.append(phase)
        events.append(("health", manifest["commit_sha"], release.name, timeout))
        # The process is healthy while the scheduler is guarded.  Once the
        # readiness phase releases only that scheduler gate, its first loop
        # iteration fails and reports initialized=false/completed=0.
        return not (manifest["commit_sha"] == _SHA_D and phase == "readiness")

    hooks = manage_release.ReleaseServiceHooks(
        stop=lambda: events.append("stop"),
        start=lambda _timeout: events.append("start"),
        health=health,
    )

    with pytest.raises(ValueError, match="release_activation_failed_rolled_back"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=hooks,
        )

    assert observed_phases == [
        "switched",
        "readiness",
        "switched",
        "readiness",
    ]
    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") == _SHA_B
    assert not (home / ".release-transaction.json").exists()
    assert events == [
        "stop",
        "start",
        ("health", _SHA_D, f"sha-{_SHA_D}", 5),
        ("health", _SHA_D, f"sha-{_SHA_D}", 5),
        "stop",
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 5),
        ("health", _SHA_A, f"sha-{_SHA_A}", 5),
    ]


def test_readiness_reset_failure_still_attempts_target_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder(iter((True, False)))

    def fail_reset(_home: Path, _snapshot_id: str) -> None:
        raise ValueError("injected readiness reset failure")

    monkeypatch.setattr(manage_release, "_reset_transaction_readiness", fail_reset)

    with pytest.raises(ValueError, match="release_activation_rollback_failed"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=service.hooks(),
        )

    assert service.events[-1] == "stop"
    journal = manage_release._read_transaction(home)
    assert journal is not None
    assert journal["phase"] == "readiness"
    assert _pointer_sha(home, "current") == _SHA_D


def test_target_stop_failure_still_closes_scheduler_readiness_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    stops = 0

    def stop() -> None:
        nonlocal stops
        stops += 1
        if stops == 2:
            raise RuntimeError("injected target stop failure")

    health_results = iter((True, False))
    hooks = manage_release.ReleaseServiceHooks(
        stop=stop,
        start=lambda _timeout: None,
        health=lambda *_args: next(health_results),
    )

    with pytest.raises(ValueError, match="release_activation_rollback_failed"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=hooks,
        )

    assert stops == 2
    journal = manage_release._read_transaction(home)
    assert journal is not None
    assert journal["phase"] == "switched"
    assert _pointer_sha(home, "current") == _SHA_D


def test_deploy_cleanup_failure_does_not_mask_activation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    _candidate(home, _SHA_D)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *_args: None)

    def fail_activation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("activation failed")

    original_fsync = manage_release._fsync_directory

    def fail_cleanup_sync(path: Path, error: str) -> None:
        if error == "release_candidate_sync_failed":
            raise KeyboardInterrupt("cleanup interrupted")
        original_fsync(path, error)

    monkeypatch.setattr(manage_release, "_activate_locked", fail_activation)
    monkeypatch.setattr(manage_release, "_fsync_directory", fail_cleanup_sync)

    with pytest.raises(RuntimeError, match="activation failed"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=_ServiceRecorder().hooks(),
        )

    assert (home / "releases" / f".candidate-{_SHA_D}").is_dir()
    assert not (home / "releases" / f"sha-{_SHA_D}").exists()


def test_journal_unlink_sync_failure_never_renames_active_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    candidate = _candidate(home, _SHA_D)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *_args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *_args: None
    )
    original_fsync = manage_release._fsync_directory

    def fail_after_journal_unlink(path: Path, error: str) -> None:
        if (
            error == "release_transaction_sync_failed"
            and not (home / ".release-transaction.json").exists()
        ):
            raise ValueError("injected journal directory sync failure")
        original_fsync(path, error)

    monkeypatch.setattr(manage_release, "_fsync_directory", fail_after_journal_unlink)

    with pytest.raises(ValueError, match="journal directory sync failure"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=_ServiceRecorder().hooks(),
        )

    final = home / "releases" / f"sha-{_SHA_D}"
    assert not candidate.exists()
    assert final.is_dir()
    assert (home / "current").resolve() == final.resolve()


def test_failed_deploy_restores_mutable_state_before_restarting_old_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    (home / "data" / "app.db").write_bytes(b"old-schema")
    (home / "config" / "config.json").write_text('{"schema":"old"}\n', encoding="utf-8")
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    compatibility_checks: list[str] = []

    def check_compatibility(
        _release_path: Path,
        manifest: dict[str, object],
        snapshot: Path,
        _timeout: float,
    ) -> None:
        assert (snapshot / "data" / "app.db").read_bytes() == b"old-schema"
        compatibility_checks.append(str(manifest["commit_sha"]))

    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", check_compatibility
    )
    events: list[str] = []
    starts = 0

    def stop() -> None:
        events.append("stop")

    def start(_timeout: int) -> None:
        nonlocal starts
        starts += 1
        events.append("start")
        if starts == 1:
            (home / "data" / "app.db").write_bytes(b"target-migrated-schema")
            (home / "config" / "config.json").write_text(
                '{"schema":"target"}\n', encoding="utf-8"
            )
        else:
            assert (home / "data" / "app.db").read_bytes() == b"old-schema"
            assert (home / "config" / "config.json").read_text(
                encoding="utf-8"
            ) == '{"schema":"old"}\n'

    health_results = iter((False, True, True))
    hooks = manage_release.ReleaseServiceHooks(
        stop=stop,
        start=start,
        health=lambda *_args: next(health_results),
    )

    with pytest.raises(ValueError, match="release_activation_failed_rolled_back"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=hooks,
        )

    assert events == ["stop", "start", "stop", "start"]
    assert compatibility_checks == [_SHA_D, _SHA_A]
    assert (home / "data" / "app.db").read_bytes() == b"old-schema"
    assert (home / "config" / "config.json").read_text(
        encoding="utf-8"
    ) == '{"schema":"old"}\n'
    assert not (home / ".release-transaction.json").exists()
    assert not (home / ".release-state-snapshots").exists()


def test_failed_deploy_keeps_recovery_journal_if_restored_service_is_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder(iter((False, False)))

    with pytest.raises(ValueError):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=service.hooks(),
        )

    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") == _SHA_B
    assert (home / ".release-transaction.json").is_file()


def test_failed_deploy_retains_journal_when_restored_scheduler_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder(iter((False, True, False)))

    with pytest.raises(ValueError, match="release_activation_rollback_failed"):
        manage_release.deploy_release(
            home,
            commit_sha=_SHA_D,
            confirmation=f"PROMOTE {_SHA_D}",
            health_timeout=5,
            hooks=service.hooks(),
        )

    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") == _SHA_B
    journal = manage_release._read_transaction(home)
    assert journal is not None
    assert journal["phase"] == "switched"
    assert service.events[-1] == "stop"


def test_rollback_is_a_checked_service_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    _point(home, "current", current)
    _point(home, "previous", previous)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder()

    result = manage_release.rollback_release(
        home,
        confirmation=f"ROLLBACK {_SHA_B}",
        health_timeout=6,
        hooks=service.hooks(),
    )

    assert _pointer_sha(home, "current") == _SHA_B
    assert _pointer_sha(home, "previous") == _SHA_A
    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_B, f"sha-{_SHA_B}", 6),
        ("health", _SHA_B, f"sha-{_SHA_B}", 6),
    ]
    assert result["current"] == _SHA_B
    assert result["previous"] == _SHA_A


@pytest.mark.parametrize("interrupted_phase", ("switched", "readiness"))
def test_recovery_restores_journaled_pointers_and_prunes_interrupted_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_phase: str,
) -> None:
    home = tmp_path / "runtime"
    old_current = _release(home, _SHA_A)
    _release(home, _SHA_B)
    interrupted_target = _release(home, _SHA_D)
    _point(home, "current", interrupted_target)
    _point(home, "previous", old_current)
    (home / "data" / "app.db").write_bytes(b"before-target-start")
    (home / "config" / "config.json").write_text(
        '{"schema":"before"}\n', encoding="utf-8"
    )
    _write_interrupted_deploy(
        home,
        old_current=_SHA_A,
        old_previous=_SHA_B,
        target=_SHA_D,
        phase=interrupted_phase,
    )
    (home / "data" / "app.db").write_bytes(b"target-migrated-before-crash")
    (home / "config" / "config.json").write_text(
        '{"schema":"target"}\n', encoding="utf-8"
    )

    def check_recovery_snapshot(
        _release_path: Path,
        _manifest: dict[str, object],
        snapshot: Path,
        _timeout: float,
    ) -> None:
        assert (snapshot / "data" / "app.db").read_bytes() == b"before-target-start"

    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", check_recovery_snapshot
    )
    service = _ServiceRecorder()

    result = manage_release.recover_release_state(
        home,
        confirmation="RECOVER RELEASE STATE",
        health_timeout=7,
        hooks=service.hooks(),
    )

    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") == _SHA_B
    assert not interrupted_target.exists()
    assert not (home / ".release-transaction.json").exists()
    assert (home / "data" / "app.db").read_bytes() == b"before-target-start"
    assert (home / "config" / "config.json").read_text(
        encoding="utf-8"
    ) == '{"schema":"before"}\n'
    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 7),
        ("health", _SHA_A, f"sha-{_SHA_A}", 7),
    ]
    assert service.start_timeouts == [7]
    assert result["current"] == _SHA_A
    assert result["previous"] == _SHA_B


def test_recovery_promotes_a_valid_orphaned_previous_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    previous = _release(home, _SHA_B)
    _point(home, "current", None)
    _point(home, "previous", previous)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder()

    result = manage_release.recover_release_state(
        home,
        confirmation="RECOVER RELEASE STATE",
        health_timeout=7,
        hooks=service.hooks(),
    )

    assert _pointer_sha(home, "current") == _SHA_B
    assert _pointer_sha(home, "previous") is None
    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_B, f"sha-{_SHA_B}", 7),
        ("health", _SHA_B, f"sha-{_SHA_B}", 7),
    ]
    assert result["current"] == _SHA_B
    assert result["previous"] is None


def test_recovery_accepts_complete_snapshot_left_before_phase_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    previous = _release(home, _SHA_B)
    target = _release(home, _SHA_D)
    _point(home, "current", current)
    _point(home, "previous", previous)
    (home / "data" / "app.db").write_bytes(b"snapshot-before-phase-update")
    snapshot_id = manage_release._write_transaction(
        home,
        operation="deploy",
        old_current=current,
        old_previous=previous,
        target=target,
    )
    manage_release._snapshot_mutable_state(home, snapshot_id)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder()

    result = manage_release.recover_release_state(
        home,
        confirmation="RECOVER RELEASE STATE",
        health_timeout=7,
        hooks=service.hooks(),
    )

    assert result["current"] == _SHA_A
    assert result["previous"] == _SHA_B
    assert not (home / ".release-transaction.json").exists()
    assert not (home / ".release-state-snapshots").exists()


def test_no_journal_cleanup_removes_complete_and_partial_orphan_snapshots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)
    complete_id = "1" * 32
    partial_id = "2" * 32
    manage_release._snapshot_mutable_state(home, complete_id)
    partial = home / ".release-state-snapshots" / f".staging-{partial_id}"
    partial.mkdir(mode=0o700)
    (partial / "partial.db").write_bytes(b"private-partial")

    with manage_release._lock(home):
        manage_release._require_clean_transaction_state_locked(home)

    assert not (home / ".release-state-snapshots").exists()


def test_service_start_and_stop_are_locked_service_manager_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    service = _ServiceRecorder()
    monkeypatch.setattr(
        manage_release,
        "_service_manager_hooks",
        lambda *_args, **_kwargs: service.hooks(),
    )
    start_args = SimpleNamespace(
        service_manager="/unused",
        service_port=8000,
        health_timeout=4,
    )
    stop_args = SimpleNamespace(service_manager="/unused", service_port=None)

    manage_release.service_start(home, start_args)
    manage_release._write_transaction(
        home,
        operation="recover",
        old_current=current,
        old_previous=None,
        target=current,
    )
    manage_release.service_stop(home, stop_args)

    assert service.events == [
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 4),
        "stop",
    ]
    assert service.start_timeouts == [4]
    assert (home / ".release-transaction.json").is_file()


@pytest.mark.parametrize("health_timeout", (1, 3600))
def test_service_manager_receives_explicit_home_and_release_lock_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, health_timeout: int
) -> None:
    home = tmp_path / "custom-runtime"
    manager = tmp_path / "manage-service"
    manager.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    manager.chmod(0o755)
    invocations: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        invocations.append((command, environment))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(manage_release.subprocess, "run", run)
    monkeypatch.setenv("KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS", "60")
    hooks = manage_release._service_manager_hooks(home, manager, port=8123)

    with manage_release._lock(home):
        hooks.stop()
        hooks.start(health_timeout)

    assert [command[-1] for command, _environment in invocations] == [
        "uninstall",
        "install",
    ]
    for _command, environment in invocations:
        assert environment["KARKINOS_HOME"] == str(home.absolute())
        assert environment["KARKINOS_RELEASE_LOCK_OWNER_PID"] == str(os.getpid())
        assert re.fullmatch(r"[0-9a-f]{32}", environment["KARKINOS_RELEASE_LOCK_NONCE"])
        assert environment["KARKINOS_BACKEND_PORT"] == "8123"
    assert invocations[1][1]["KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS"] == str(
        health_timeout
    )

    service_config = home / ".service-config.json"
    assert stat.S_IMODE(service_config.stat().st_mode) == 0o600
    assert json.loads(service_config.read_text(encoding="utf-8")) == {
        "schema_version": "karkinos.service_config.v1",
        "service_port": 8123,
    }
    assert (home / ".release.lock").read_text(encoding="utf-8") == ""


def test_persisted_service_port_is_reused_and_mismatches_fail_closed(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"

    assert manage_release._prepare_service_port(home, 8123) == 8123
    assert manage_release._prepare_service_port(home, None) == 8123
    with pytest.raises(ValueError, match="release_service_port_mismatch"):
        manage_release._prepare_service_port(home, 8000)

    config = home / ".service-config.json"
    assert json.loads(config.read_text(encoding="utf-8"))["service_port"] == 8123


def test_service_port_sources_conflict_and_status_reports_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    manage_release._prepare_service_port(home, 8123)

    manage_release.status(home, SimpleNamespace())
    assert json.loads(capsys.readouterr().out)["service_port"] == 8123

    monkeypatch.setenv("KARKINOS_BACKEND_PORT", "8123")
    assert (
        manage_release._requested_service_port(SimpleNamespace(service_port=None))
        == 8123
    )
    with pytest.raises(ValueError, match="release_service_port_sources_conflict"):
        manage_release._requested_service_port(SimpleNamespace(service_port=8000))

    (home / ".service-config.json").unlink()
    with pytest.raises(ValueError, match="release_service_config_missing"):
        manage_release.status(home, SimpleNamespace())


def test_status_reuses_receipt_and_reports_exact_scheduler_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    manage_release._prepare_service_port(home, 8123)
    manifest = manage_release._manifest_for(current)
    requests: list[tuple[str, int]] = []

    def probe(path: str, port: int) -> object:
        requests.append((path, port))
        if path == "/api/health":
            return _service_health_payload(manifest)
        return {
            "running": True,
            "initialized": True,
            "activation_guarded": False,
            "scheduler_activation_guarded": False,
            "completed_iterations": 3,
        }

    monkeypatch.setattr(manage_release, "_probe_json", probe)

    manage_release.status(home, SimpleNamespace())

    payload = json.loads(capsys.readouterr().out)
    assert requests == [
        ("/api/health", 8123),
        ("/api/settings/live/status", 8123),
    ]
    assert payload["service"] == {
        "scope": "loopback_process_identity",
        "supervisor": "launchd",
        "supervisor_ready": None,
        "reachable": True,
        "identity_ready": True,
        "scheduler_running": True,
        "scheduler_initialized": True,
        "scheduler_activation_guarded": False,
        "scheduler_completed_iterations": 3,
        "financial_readiness_claimed": False,
    }
    assert payload["recovery"] == {
        "required": False,
        "kind": None,
        "phase": None,
    }


def test_status_reports_retained_release_recovery_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "runtime"
    old_current = _release(home, _SHA_A)
    _release(home, _SHA_B)
    target = _release(home, _SHA_D)
    _point(home, "current", target)
    _point(home, "previous", old_current)
    manage_release._prepare_service_port(home, 8123)
    _write_interrupted_deploy(
        home,
        old_current=_SHA_A,
        old_previous=_SHA_B,
        target=_SHA_D,
        phase="readiness",
    )
    monkeypatch.setattr(
        manage_release,
        "_probe_json",
        lambda *_args: (_ for _ in ()).throw(OSError("service unavailable")),
    )

    manage_release.status(home, SimpleNamespace())

    payload = json.loads(capsys.readouterr().out)
    assert payload["recovery"] == {
        "required": True,
        "kind": "release",
        "phase": "readiness",
    }
    assert payload["service"]["identity_ready"] is False


def test_status_checks_launchd_with_the_persisted_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    manage_release._prepare_service_port(home, 8123)
    manager = tmp_path / "service-manager"
    manager.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    manager.chmod(0o755)
    observed: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(manage_release.subprocess, "run", run)
    monkeypatch.setattr(
        manage_release,
        "_probe_json",
        lambda *_args: (_ for _ in ()).throw(OSError("service unavailable")),
    )

    manage_release.status(home, SimpleNamespace(service_manager=str(manager)))

    payload = json.loads(capsys.readouterr().out)
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert observed["command"] == [str(manager), "status"]
    assert environment["KARKINOS_HOME"] == str(home)
    assert environment["KARKINOS_BACKEND_PORT"] == "8123"
    assert payload["service"]["supervisor_ready"] is True


def test_service_port_receipt_rejects_loose_permissions(tmp_path: Path) -> None:
    home = tmp_path / "runtime"
    manage_release._prepare_service_port(home, 8000)
    (home / ".service-config.json").chmod(0o644)

    with pytest.raises(ValueError, match="release_service_config_invalid"):
        manage_release._prepare_service_port(home, None)


def test_service_manager_rejects_invocation_without_active_release_lock(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    manager = tmp_path / "manage-service"
    manager.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    manager.chmod(0o755)
    hooks = manage_release._service_manager_hooks(home, manager, port=8000)

    with pytest.raises(ValueError, match="release_service_lock_capability_missing"):
        hooks.start(30)


def _service_health_payload(manifest: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "karkinos.service_health.v1",
        "status": "alive",
        "service": "karkinos",
        "scope": "process_liveness_only",
        "version": manifest["version"],
        "release_sha": manifest["commit_sha"],
        "artifact_fingerprint": manifest["payload_fingerprint"],
        "financial_readiness_claimed": False,
        "provider_contacted": False,
        "database_reads_performed": False,
        "database_writes_performed": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "production_ledger_mutated": False,
        "capital_authority_changed": False,
        "authorizes_execution": False,
    }


@pytest.mark.parametrize("expected_activation_guarded", [False, True])
def test_release_health_requires_initialized_and_exact_activation_guard(
    expected_activation_guarded: bool,
) -> None:
    manifest = {
        "version": "0.3.1",
        "commit_sha": _SHA_A,
        "payload_fingerprint": "f" * 64,
    }
    health = _service_health_payload(manifest)
    live = {
        "running": True,
        "initialized": True,
        "activation_guarded": expected_activation_guarded,
    }

    assert (
        manage_release._health_payload_matches(
            health,
            live,
            manifest,
            expected_activation_guarded=expected_activation_guarded,
        )
        is True
    )
    assert (
        manage_release._health_payload_matches(
            health,
            {**live, "initialized": False},
            manifest,
            expected_activation_guarded=expected_activation_guarded,
        )
        is False
    )
    assert (
        manage_release._health_payload_matches(
            health,
            {**live, "activation_guarded": not expected_activation_guarded},
            manifest,
            expected_activation_guarded=expected_activation_guarded,
        )
        is False
    )


def test_release_readiness_requires_scheduler_gate_open_and_completed_iteration() -> (
    None
):
    manifest = {
        "version": "0.3.1",
        "commit_sha": _SHA_A,
        "payload_fingerprint": "f" * 64,
    }
    health = _service_health_payload(manifest)
    live = {
        "running": True,
        "initialized": True,
        "activation_guarded": True,
        "scheduler_activation_guarded": False,
        "completed_iterations": 1,
    }

    assert manage_release._health_payload_matches(
        health,
        live,
        manifest,
        expected_activation_guarded=True,
        expected_scheduler_activation_guarded=False,
        minimum_completed_iterations=1,
    )
    for unsafe_live in (
        {**live, "initialized": False},
        {**live, "scheduler_activation_guarded": True},
        {**live, "completed_iterations": 0},
        {**live, "completed_iterations": True},
    ):
        assert not manage_release._health_payload_matches(
            health,
            unsafe_live,
            manifest,
            expected_activation_guarded=True,
            expected_scheduler_activation_guarded=False,
            minimum_completed_iterations=1,
        )


def test_service_health_expectations_track_explicit_readiness_phase(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    target = _release(home, _SHA_D)
    _point(home, "current", current)
    snapshot_id = manage_release._write_transaction(
        home,
        operation="deploy",
        old_current=current,
        old_previous=None,
        target=target,
    )

    assert manage_release._service_health_expectations(home) == (True, True, None)
    manage_release._update_transaction_phase(home, snapshot_id, "snapshotted")
    manage_release._update_transaction_phase(home, snapshot_id, "switched")
    assert manage_release._service_health_expectations(home) == (True, True, None)
    manage_release._update_transaction_phase(home, snapshot_id, "readiness")
    assert manage_release._service_health_expectations(home) == (True, False, 1)

    manage_release._clear_transaction(home)
    transaction_id = "1" * 32
    legacy_journal = {
        "schema_version": "karkinos.legacy_bootstrap_transaction.v1",
        "phase": "healthy",
        "transaction_id": transaction_id,
        "commit_sha": _SHA_D,
        "legacy_workdir": str(tmp_path / "legacy"),
        "legacy_plist": str(tmp_path / "legacy.plist"),
        "work_name": f".legacy-bootstrap-work-{transaction_id}",
    }
    bootstrap_legacy._write_json(
        home / ".legacy-bootstrap-transaction.json",
        legacy_journal,
        replace=False,
    )
    assert manage_release._service_health_expectations(home) == (True, True, None)
    bootstrap_legacy._update_phase(home, legacy_journal, "readiness")
    assert manage_release._service_health_expectations(home) == (True, False, 1)


@pytest.mark.parametrize(
    "journal_name",
    [".release-transaction.json", ".legacy-bootstrap-transaction.json"],
)
def test_service_health_expected_guard_tracks_transaction_journals(
    tmp_path: Path,
    journal_name: str,
) -> None:
    home = tmp_path / "runtime"
    home.mkdir()
    journal = home / journal_name

    assert manage_release._activation_guard_expected(home) is False
    journal.write_text("{}\n", encoding="utf-8")
    assert manage_release._activation_guard_expected(home) is True
    journal.unlink()
    assert manage_release._activation_guard_expected(home) is False


def test_candidate_run_uses_disposable_state_without_switching_pointers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _candidate(home, _SHA_D)
    _point(home, "current", current)
    monkeypatch.setattr(manage_release, "_probe_release", lambda *args: None)
    observed: dict[str, object] = {}

    def runner(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        isolated_home = Path(environment["KARKINOS_HOME"])
        isolated_data = Path(environment["KARKINOS_DATA_DIR"])
        isolated_config = Path(environment["KARKINOS_CONFIG_PATH"])
        isolated_env = Path(environment["KARKINOS_ENV_FILE"])
        observed.update(
            {
                "command": command,
                "cwd": kwargs["cwd"],
                "home": isolated_home,
                "data": isolated_data,
                "config": isolated_config,
                "env": isolated_env,
                "port": environment["KARKINOS_PORT"],
                "release_lock_held": bool(manage_release._ACTIVE_RELEASE_LOCKS),
                "exists_during_run": all(
                    path.exists()
                    for path in (
                        isolated_home,
                        isolated_data,
                        isolated_config,
                        isolated_env,
                    )
                ),
            }
        )
        return subprocess.CompletedProcess(command, 0)

    result = manage_release.run_candidate(
        home,
        commit_sha=_SHA_D,
        port=18000,
        runner=runner,
    )

    assert observed["exists_during_run"] is True
    assert observed["release_lock_held"] is False
    assert observed["home"] != home
    candidate_cwd = Path(observed["cwd"])
    assert candidate_cwd.parent.name == f".candidate-{_SHA_D}"
    assert candidate_cwd.name == "app"
    assert candidate_cwd.parent != home / "releases" / f".candidate-{_SHA_D}"
    assert observed["port"] == "18000"
    assert not Path(observed["home"]).exists()
    assert not candidate_cwd.exists()
    assert (home / "releases" / f".candidate-{_SHA_D}").is_dir()
    assert _pointer_sha(home, "current") == _SHA_A
    assert _pointer_sha(home, "previous") is None
    assert result["commit_sha"] == _SHA_D
    assert result["port"] == 18000
    assert result["returncode"] == 0


def test_candidate_port_avoids_the_persisted_production_listener(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    manage_release._prepare_service_port(home, 18000)

    assert manage_release._candidate_port(home, None) == 18001
    assert manage_release._candidate_port(home, 8000) == 8000
    with pytest.raises(
        ValueError, match="release_candidate_port_conflicts_with_production"
    ):
        manage_release._candidate_port(home, 18000)


def test_candidate_without_a_receipt_reserves_the_legacy_default_port(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"

    assert manage_release._candidate_port(home, None) == 18000
    with pytest.raises(
        ValueError, match="release_candidate_port_conflicts_with_production"
    ):
        manage_release._candidate_port(home, 8000)


def test_candidate_discard_is_idempotent_after_concurrent_release_pruning(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    manage_release._ensure_layout(home)

    result = manage_release._discard_inactive_candidate(home, _SHA_D)

    assert result == {"status": "already_discarded", "commit_sha": _SHA_D}


def test_public_workflow_parsers_expose_candidate_update_and_bootstrap() -> None:
    parser = manage_release._parser()
    expected_service_manager = str(
        manage_release._REPOSITORY_ROOT
        / "scripts"
        / "service"
        / "manage_launch_agent.sh"
    )
    candidate_args = parser.parse_args(
        ["candidate", "--commit-sha", _SHA_D, "--port", "19000"]
    )
    default_candidate_args = parser.parse_args(["candidate", "--commit-sha", _SHA_D])
    update_args = parser.parse_args(
        ["update", "--tag", "v0.3.2", "--confirm", "UPDATE v0.3.2"]
    )
    bootstrap_args = parser.parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            "/legacy/workdir",
            "--legacy-plist",
            "/legacy/service.plist",
            "--confirm",
            "BOOTSTRAP v0.3.2",
        ]
    )

    assert (candidate_args.command, candidate_args.commit_sha, candidate_args.port) == (
        "candidate",
        _SHA_D,
        19000,
    )
    assert default_candidate_args.port is None
    assert (update_args.command, update_args.tag, update_args.health_timeout) == (
        "update",
        "v0.3.2",
        30,
    )
    assert update_args.service_port is None
    assert update_args.service_manager == expected_service_manager
    assert (
        bootstrap_args.command,
        bootstrap_args.tag,
        bootstrap_args.legacy_workdir,
        bootstrap_args.legacy_plist,
    ) == (
        "bootstrap",
        "v0.3.2",
        "/legacy/workdir",
        "/legacy/service.plist",
    )
    assert bootstrap_args.service_port is None
    assert bootstrap_args.service_manager == expected_service_manager


@pytest.mark.parametrize("health_timeout", (True, 0, 3601, 1.5))
def test_release_health_timeout_contract_rejects_invalid_values(
    health_timeout: object,
) -> None:
    with pytest.raises(ValueError, match="release_health_timeout_invalid"):
        manage_release._require_health_timeout(health_timeout)


@pytest.mark.parametrize("health_timeout", (1, 3600))
def test_release_health_timeout_contract_accepts_inclusive_boundaries(
    health_timeout: int,
) -> None:
    assert manage_release._require_health_timeout(health_timeout) == health_timeout


def test_service_start_rejects_invalid_timeout_before_runtime_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    args = SimpleNamespace(
        service_manager="/unused",
        service_port=8000,
        health_timeout=3601,
    )

    with pytest.raises(ValueError, match="release_health_timeout_invalid"):
        manage_release.service_start(home, args)

    assert not home.exists()


def test_public_candidate_wires_fetch_workflow_to_local_candidate_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "runtime"
    archive = tmp_path / "verified.tar.gz"
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        manage_release,
        "_stage_verified_candidate",
        lambda actual_home, actual_archive, sha: events.append(
            ("stage", actual_home, actual_archive, sha)
        ),
    )
    monkeypatch.setattr(
        manage_release,
        "run_candidate",
        lambda actual_home, *, commit_sha, port: events.append(
            ("run", actual_home, commit_sha, port)
        )
        or {"status": "candidate_exited", "commit_sha": commit_sha, "returncode": 0},
    )
    monkeypatch.setattr(
        manage_release,
        "_discard_inactive_candidate",
        lambda actual_home, sha: events.append(("discard", actual_home, sha)),
    )

    def workflow(
        callbacks: update_workflow.ReleaseWorkflowCallbacks,
        *,
        commit_sha: str,
        port: int,
    ) -> object:
        events.append(("workflow", commit_sha, port))
        callbacks.stage(archive, commit_sha)
        result = callbacks.run_candidate(commit_sha, port)
        callbacks.discard(commit_sha)
        return result

    monkeypatch.setattr(update_workflow, "run_candidate_workflow", workflow)
    args = manage_release._parser().parse_args(
        ["candidate", "--commit-sha", _SHA_D, "--port", "19000"]
    )

    manage_release.candidate(home, args)

    assert events == [
        ("workflow", _SHA_D, 19000),
        ("stage", home, archive, _SHA_D),
        ("run", home, _SHA_D, 19000),
        ("discard", home, _SHA_D),
    ]
    assert json.loads(capsys.readouterr().out) == {
        "status": "candidate_exited",
        "commit_sha": _SHA_D,
        "returncode": 0,
    }


def test_public_update_wires_verified_sha_to_transactional_deploy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    archive = tmp_path / "verified.tar.gz"
    service_hooks = _ServiceRecorder().hooks()
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        manage_release,
        "_service_manager_hooks",
        lambda actual_home, manager, *, port: events.append(
            ("service", actual_home, manager, port)
        )
        or service_hooks,
    )
    monkeypatch.setattr(
        manage_release,
        "_stage_verified_candidate",
        lambda actual_home, actual_archive, sha: events.append(
            ("stage", actual_home, actual_archive, sha)
        ),
    )

    def deploy(
        actual_home: Path,
        *,
        commit_sha: str,
        confirmation: str,
        health_timeout: float,
        hooks: manage_release.ReleaseServiceHooks,
    ) -> dict[str, object]:
        events.append(
            (
                "deploy",
                actual_home,
                commit_sha,
                confirmation,
                health_timeout,
                hooks,
            )
        )
        return {"status": "promoted", "current": commit_sha}

    monkeypatch.setattr(manage_release, "deploy_release", deploy)

    def workflow(
        callbacks: update_workflow.ReleaseWorkflowCallbacks,
        *,
        tag: str,
        confirmation: str,
        health_timeout: float,
    ) -> object:
        events.append(("workflow", tag, confirmation, health_timeout))
        callbacks.preflight()
        callbacks.stage(archive, _SHA_D)
        return callbacks.deploy(_SHA_D, f"PROMOTE {_SHA_D}", health_timeout)

    monkeypatch.setattr(update_workflow, "run_stable_update_workflow", workflow)
    args = manage_release._parser().parse_args(
        [
            "update",
            "--tag",
            "v0.3.2",
            "--confirm",
            "UPDATE v0.3.2",
            "--health-timeout",
            "17",
            "--service-manager",
            "/service-manager",
            "--service-port",
            "8123",
        ]
    )

    manage_release.update(home, args)

    assert events == [
        ("workflow", "v0.3.2", "UPDATE v0.3.2", 17),
        ("service", home, Path("/service-manager"), 8123),
        ("stage", home, archive, _SHA_D),
        ("deploy", home, _SHA_D, f"PROMOTE {_SHA_D}", 17, service_hooks),
    ]
    assert json.loads(capsys.readouterr().out) == {
        "status": "promoted",
        "current": _SHA_D,
    }


def test_public_update_without_current_stops_before_remote_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setattr(
        update_workflow.release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("remote fetch must not run")
        ),
    )
    args = manage_release._parser().parse_args(
        ["update", "--tag", "v0.3.2", "--confirm", "UPDATE v0.3.2"]
    )

    with pytest.raises(ValueError, match="release_update_requires_current"):
        manage_release.update(home, args)


@pytest.mark.parametrize(
    ("tag", "confirmation"),
    [
        ("v0.3.2-rc.1", "UPDATE v0.3.2-rc.1"),
        ("v0.3.2", "UPDATE v0.3.1"),
    ],
)
def test_public_update_validates_command_before_local_preflight_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tag: str,
    confirmation: str,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        manage_release,
        "_require_update_ready",
        lambda _home: events.append("preflight"),
    )
    monkeypatch.setattr(
        manage_release,
        "_service_manager_hooks",
        lambda *_args, **_kwargs: events.append("service"),
    )
    monkeypatch.setattr(
        update_workflow.release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: events.append("network"),
    )
    args = manage_release._parser().parse_args(
        ["update", "--tag", tag, "--confirm", confirmation]
    )

    with pytest.raises(ValueError):
        manage_release.update(tmp_path / "runtime", args)

    assert events == []


def test_public_bootstrap_preflights_before_stage_and_wires_exact_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "runtime"
    legacy_workdir = tmp_path / "legacy-workdir"
    legacy_plist = tmp_path / "legacy.plist"
    archive = tmp_path / "verified.tar.gz"
    events: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        bootstrap_legacy,
        "preflight_legacy_sources",
        lambda actual_home, *, legacy_workdir, legacy_plist: events.append(
            ("preflight", actual_home, legacy_workdir, legacy_plist)
        ),
    )
    monkeypatch.setattr(
        manage_release,
        "recover_legacy_bootstrap_release",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        manage_release,
        "_stage_verified_candidate",
        lambda actual_home, actual_archive, sha: events.append(
            ("stage", actual_home, actual_archive, sha)
        ),
    )

    def bootstrap_release(
        actual_home: Path,
        *,
        commit_sha: str,
        legacy_workdir: Path,
        legacy_plist: Path,
        confirmation: str,
        health_timeout: float,
        service_manager: Path,
        service_port: int,
    ) -> dict[str, object]:
        events.append(
            (
                "bootstrap",
                actual_home,
                commit_sha,
                legacy_workdir,
                legacy_plist,
                confirmation,
                health_timeout,
                service_manager,
                service_port,
            )
        )
        return {"status": "legacy_bootstrap_complete", "current": commit_sha}

    monkeypatch.setattr(manage_release, "bootstrap_legacy_release", bootstrap_release)

    def workflow(
        callbacks: update_workflow.LegacyBootstrapWorkflowCallbacks,
        *,
        tag: str,
        confirmation: str,
        health_timeout: float,
    ) -> object:
        events.append(("workflow", tag, confirmation, health_timeout))
        callbacks.preflight()
        callbacks.stage(archive, _SHA_D)
        return callbacks.bootstrap(_SHA_D, f"BOOTSTRAP {_SHA_D}", health_timeout)

    monkeypatch.setattr(update_workflow, "run_stable_bootstrap_workflow", workflow)
    args = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            str(legacy_workdir),
            "--legacy-plist",
            str(legacy_plist),
            "--confirm",
            "BOOTSTRAP v0.3.2",
            "--health-timeout",
            "19",
            "--service-manager",
            "/service-manager",
            "--service-port",
            "8124",
        ]
    )

    manage_release.bootstrap(home, args)

    assert events == [
        ("workflow", "v0.3.2", "BOOTSTRAP v0.3.2", 19),
        ("preflight", home, legacy_workdir, legacy_plist),
        ("stage", home, archive, _SHA_D),
        (
            "bootstrap",
            home,
            _SHA_D,
            legacy_workdir,
            legacy_plist,
            f"BOOTSTRAP {_SHA_D}",
            19,
            Path("/service-manager"),
            8124,
        ),
    ]
    assert json.loads(capsys.readouterr().out) == {
        "status": "legacy_bootstrap_complete",
        "current": _SHA_D,
    }
    assert (
        json.loads((home / ".service-config.json").read_text(encoding="utf-8"))[
            "service_port"
        ]
        == 8124
    )


def test_public_bootstrap_recovers_before_preflight_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        manage_release,
        "recover_legacy_bootstrap_release",
        lambda *_args, **_kwargs: events.append("recover") or True,
    )
    monkeypatch.setattr(
        bootstrap_legacy,
        "preflight_legacy_sources",
        lambda *_args, **_kwargs: events.append("preflight"),
    )
    monkeypatch.setattr(
        update_workflow.release_fetch,
        "fetch_stable_native",
        lambda **_kwargs: events.append("network"),
    )
    args = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            str(tmp_path / "legacy-workdir"),
            "--legacy-plist",
            str(tmp_path / "legacy.plist"),
            "--confirm",
            "BOOTSTRAP v0.3.2",
        ]
    )

    with pytest.raises(ValueError, match="legacy_bootstrap_recovered_retry_required"):
        manage_release.bootstrap(tmp_path / "runtime", args)

    assert events == ["recover"]


def test_failed_legacy_preflight_does_not_pin_a_service_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setattr(
        manage_release,
        "recover_legacy_bootstrap_release",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        bootstrap_legacy,
        "preflight_legacy_sources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("legacy_preflight_fixture_failed")
        ),
    )
    monkeypatch.setattr(
        update_workflow,
        "run_stable_bootstrap_workflow",
        lambda callbacks, **_kwargs: callbacks.preflight(),
    )
    args = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            str(tmp_path / "legacy-workdir"),
            "--legacy-plist",
            str(tmp_path / "legacy.plist"),
            "--confirm",
            "BOOTSTRAP v0.3.2",
            "--service-port",
            "8123",
        ]
    )

    with pytest.raises(ValueError, match="legacy_preflight_fixture_failed"):
        manage_release.bootstrap(home, args)

    assert not (home / ".service-config.json").exists()


def test_failed_remote_bootstrap_fetch_does_not_pin_a_service_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setattr(
        manage_release,
        "recover_legacy_bootstrap_release",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        bootstrap_legacy,
        "preflight_legacy_sources",
        lambda *_args, **_kwargs: None,
    )

    def workflow(
        callbacks: update_workflow.LegacyBootstrapWorkflowCallbacks, **_kwargs: object
    ) -> object:
        callbacks.preflight()
        raise ValueError("release_fetch_fixture_failed")

    monkeypatch.setattr(update_workflow, "run_stable_bootstrap_workflow", workflow)
    args = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            str(tmp_path / "legacy-workdir"),
            "--legacy-plist",
            str(tmp_path / "legacy.plist"),
            "--confirm",
            "BOOTSTRAP v0.3.2",
            "--service-port",
            "8123",
        ]
    )

    with pytest.raises(ValueError, match="release_fetch_fixture_failed"):
        manage_release.bootstrap(home, args)

    assert not (home / ".service-config.json").exists()


def test_rolled_back_bootstrap_removes_new_service_port_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    monkeypatch.setattr(
        manage_release,
        "recover_legacy_bootstrap_release",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        bootstrap_legacy,
        "preflight_legacy_sources",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        manage_release, "_stage_verified_candidate", lambda *_args: None
    )
    monkeypatch.setattr(
        manage_release,
        "bootstrap_legacy_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("legacy_bootstrap_fixture_rolled_back")
        ),
    )

    def workflow(
        callbacks: update_workflow.LegacyBootstrapWorkflowCallbacks,
        *,
        health_timeout: float,
        **_kwargs: object,
    ) -> object:
        callbacks.preflight()
        callbacks.stage(tmp_path / "verified.tar.gz", _SHA_D)
        return callbacks.bootstrap(_SHA_D, f"BOOTSTRAP {_SHA_D}", health_timeout)

    monkeypatch.setattr(update_workflow, "run_stable_bootstrap_workflow", workflow)
    args = manage_release._parser().parse_args(
        [
            "bootstrap",
            "--tag",
            "v0.3.2",
            "--legacy-workdir",
            str(tmp_path / "legacy-workdir"),
            "--legacy-plist",
            str(tmp_path / "legacy.plist"),
            "--confirm",
            "BOOTSTRAP v0.3.2",
            "--service-port",
            "8123",
        ]
    )

    with pytest.raises(ValueError, match="legacy_bootstrap_fixture_rolled_back"):
        manage_release.bootstrap(home, args)

    assert not (home / ".service-config.json").exists()


def test_adopt_legacy_moves_private_state_without_copying_or_disclosing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    secret = "private-config-sentinel"
    database = b"private-sqlite-sentinel"
    (shared / "config.json").write_text(secret, encoding="utf-8")
    (shared / ".env").write_text("TOKEN=private-token-sentinel\n", encoding="utf-8")
    legacy_data = tmp_path / "legacy-store"
    legacy_data.mkdir()
    (legacy_data / "app.db").write_bytes(database)
    (legacy_data / "app.db-wal").write_bytes(b"private-wal-sentinel")
    service = _ServiceRecorder()

    result = manage_release.adopt_legacy_state(
        home,
        legacy_shared=shared,
        legacy_data=legacy_data,
        confirmation="ADOPT LEGACY STATE",
        health_timeout=8,
        hooks=service.hooks(),
    )

    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 8),
    ]
    assert not (shared / "config.json").exists()
    assert not (shared / ".env").exists()
    assert not legacy_data.exists()
    assert (home / "config" / "config.json").read_text(encoding="utf-8") == secret
    assert (home / "data" / "app.db").read_bytes() == database
    assert stat.S_IMODE((home / "config" / "config.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((home / "data").stat().st_mode) == 0o700
    assert stat.S_IMODE((home / "data" / "app.db").stat().st_mode) == 0o600
    serialized = json.dumps(result, sort_keys=True)
    assert secret not in serialized
    assert "private-token-sentinel" not in serialized
    assert str(shared) not in serialized
    assert str(legacy_data) not in serialized


def test_adopt_legacy_requires_a_managed_current_before_stopping_service(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    legacy_data = tmp_path / "legacy-store"
    legacy_data.mkdir()
    (legacy_data / "app.db").write_bytes(b"sqlite")
    service = _ServiceRecorder()

    with pytest.raises(ValueError, match="release_legacy_adoption_requires_current"):
        manage_release.adopt_legacy_state(
            home,
            legacy_shared=shared,
            legacy_data=legacy_data,
            confirmation="ADOPT LEGACY STATE",
            health_timeout=8,
            hooks=service.hooks(),
        )

    assert service.events == []
    assert (shared / "config.json").is_file()
    assert (legacy_data / "app.db").is_file()


def test_adopt_legacy_restarts_only_the_exact_managed_current_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    (shared / ".env").write_text("\n", encoding="utf-8")
    legacy_store = tmp_path / "legacy-store"
    legacy_store.mkdir()
    (legacy_store / "app.db").write_bytes(b"sqlite")
    monkeypatch.setattr(
        manage_release, "_probe_state_compatibility", lambda *args: None
    )
    service = _ServiceRecorder()

    manage_release.adopt_legacy_state(
        home,
        legacy_shared=shared,
        legacy_data=legacy_store,
        confirmation="ADOPT LEGACY STATE",
        health_timeout=9,
        hooks=service.hooks(),
    )

    assert service.events == [
        "stop",
        "start",
        ("health", _SHA_A, f"sha-{_SHA_A}", 9),
    ]


def test_adopt_legacy_rejects_symlinks_before_stopping_service(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    (shared / ".env").write_text("\n", encoding="utf-8")
    legacy_store = tmp_path / "legacy-store"
    legacy_store.mkdir()
    outside = tmp_path / "outside.db"
    outside.write_bytes(b"must-not-be-adopted")
    (legacy_store / "app.db").symlink_to(outside)
    service = _ServiceRecorder()

    with pytest.raises(ValueError):
        manage_release.adopt_legacy_state(
            home,
            legacy_shared=shared,
            legacy_data=legacy_store,
            confirmation="ADOPT LEGACY STATE",
            health_timeout=8,
            hooks=service.hooks(),
        )

    assert service.events == []
    assert (shared / "config.json").is_file()
    assert (legacy_store / "app.db").is_symlink()
    assert outside.read_bytes() == b"must-not-be-adopted"


def test_adopt_legacy_rejects_cross_filesystem_before_stopping_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    legacy_data = tmp_path / "legacy-store"
    legacy_data.mkdir()
    (legacy_data / "app.db").write_bytes(b"sqlite")
    service = _ServiceRecorder()
    monkeypatch.setattr(
        manage_release,
        "_require_same_filesystem",
        lambda *_args: (_ for _ in ()).throw(
            ValueError("release_legacy_cross_filesystem_unsupported")
        ),
    )

    with pytest.raises(ValueError, match="release_legacy_cross_filesystem_unsupported"):
        manage_release.adopt_legacy_state(
            home,
            legacy_shared=shared,
            legacy_data=legacy_data,
            confirmation="ADOPT LEGACY STATE",
            health_timeout=8,
            hooks=service.hooks(),
        )

    assert service.events == []
    assert (shared / "config.json").is_file()
    assert (legacy_data / "app.db").is_file()


def test_adopt_legacy_rejects_destination_collision_before_stopping_service(
    tmp_path: Path,
) -> None:
    home = tmp_path / "runtime"
    current = _release(home, _SHA_A)
    _point(home, "current", current)
    manage_release._ensure_layout(home)
    (home / "config" / "existing.json").write_text("{}\n", encoding="utf-8")
    shared = tmp_path / "legacy-shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    legacy_data = tmp_path / "legacy-store"
    legacy_data.mkdir()
    (legacy_data / "app.db").write_bytes(b"sqlite")
    service = _ServiceRecorder()

    with pytest.raises(ValueError, match="release_legacy_destination_not_empty"):
        manage_release.adopt_legacy_state(
            home,
            legacy_shared=shared,
            legacy_data=legacy_data,
            confirmation="ADOPT LEGACY STATE",
            health_timeout=8,
            hooks=service.hooks(),
        )

    assert service.events == []
    assert (shared / "config.json").is_file()
    assert (legacy_data / "app.db").is_file()


@pytest.mark.parametrize(
    "arguments",
    (
        ["rollback", "--confirm", f"ROLLBACK {_SHA_A}"],
        ["recover", "--confirm", "RECOVER RELEASE STATE"],
    ),
)
def test_service_mutating_commands_default_to_repository_service_manager(
    arguments: list[str],
) -> None:
    parsed = manage_release._parser().parse_args(arguments)

    assert parsed.service_manager == str(
        manage_release._REPOSITORY_ROOT
        / "scripts"
        / "service"
        / "manage_launch_agent.sh"
    )


@pytest.mark.parametrize(
    "command",
    (
        "stage",
        "discard",
        "promote",
        "prune",
        "adopt-legacy",
        "bootstrap-legacy",
        "run-candidate",
        "download",
    ),
)
def test_unsafe_low_level_release_primitives_are_not_cli_commands(
    command: str,
) -> None:
    with pytest.raises(SystemExit):
        manage_release._parser().parse_args([command])
