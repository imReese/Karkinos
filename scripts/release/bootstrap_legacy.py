#!/usr/bin/env python3
"""One-time, journaled handoff from the legacy source service.

The public release manager owns locking and artifact validation.  This module
owns only the exceptional first-install transaction and receives all release
and service operations as narrow callbacks so the transaction can be tested
without touching launchd or a real runtime home.
"""

from __future__ import annotations

import http.client
import json
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_TRANSACTION_ID = re.compile(r"^[0-9a-f]{32}$")
_LABEL = "com.karkinos.daily-candidate"
_JOURNAL_NAME = ".legacy-bootstrap-transaction.json"
_JOURNAL_SCHEMA = "karkinos.legacy_bootstrap_transaction.v1"
_RECEIPT_SCHEMA = "karkinos.legacy_bootstrap_quarantine.v1"
_QUARANTINE_NAME = "legacy-bootstrap-quarantine"
_WORK_PREFIX = ".legacy-bootstrap-work-"
_FINALIZE_CONFIRMATION = "FINALIZE LEGACY BOOTSTRAP"
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_MAX_HEALTH_TIMEOUT_SECONDS = 3600
_PHASES = {
    "preparing",
    "prepared",
    "stopped",
    "snapshotted",
    "state_moved",
    "state_compatible",
    "prod_quarantined",
    "switched",
    "new_started",
    "healthy",
    "readiness",
    "committing",
    "committed",
}
_JOURNAL_PHASES = _PHASES | {"rolled_back"}
_PLIST_KEYS = {
    "Label",
    "ProgramArguments",
    "WorkingDirectory",
    "EnvironmentVariables",
    "RunAtLoad",
    "KeepAlive",
    "ProcessType",
    "ThrottleInterval",
    "StandardOutPath",
    "StandardErrorPath",
}
_LEGACY_ENV_NAMES = {"NO_PROXY", "no_proxy", "UV_CACHE_DIR"}
_PROXY_NAMES = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
    "DEFAULT_PROXY_URL",
)
_SERVICE_HEALTH_FALSE_FIELDS = (
    "financial_readiness_claimed",
    "provider_contacted",
    "database_reads_performed",
    "database_writes_performed",
    "broker_submission_enabled",
    "broker_cancellation_enabled",
    "production_ledger_mutated",
    "capital_authority_changed",
    "authorizes_execution",
)


@dataclass(frozen=True)
class ManagedServiceHooks:
    """Lifecycle for the immutable service selected by ``current``."""

    stop: Callable[[], None]
    start: Callable[[int], None]
    health: Callable[[Path, dict[str, object], int], bool]


@dataclass(frozen=True)
class LegacyServiceHooks:
    """Exact legacy launchd job lifecycle and plist restoration."""

    preflight: Callable[[], None]
    stop: Callable[[], None]
    start: Callable[[], None]
    health: Callable[[int], bool]
    restore_plist: Callable[[Path], None]


@dataclass(frozen=True)
class BootstrapCallbacks:
    """Release-manager primitives used inside the already-held release lock."""

    pointer_state: Callable[[Path], tuple[Path | None, Path | None]]
    validate_candidate: Callable[[Path, str], tuple[Path, dict[str, object]]]
    probe_release: Callable[[Path, Path, dict[str, object], int], None]
    probe_state: Callable[[Path, dict[str, object], Path, int], None]
    clone_tree: Callable[[Path, Path], None]
    clone_file: Callable[[Path, Path], None]
    fsync_tree: Callable[[Path], None]
    remove_private_tree: Callable[[Path], None]
    seal_release: Callable[[Path, str], None]
    replace_pointer: Callable[[Path, str, Path | None], None]
    manifest_for: Callable[[Path], dict[str, object]]
    fsync_directory: Callable[[Path, str], None]
    remove_quarantine: Callable[[Path], None]


def _absolute_without_symlinks(path: Path, error: str) -> Path:
    value = Path(os.path.abspath(os.fspath(path.expanduser())))
    for item in (value, *value.parents):
        if item.is_symlink():
            raise ValueError(error)
        if item.parent == item:
            break
    return value


def _require_sha(value: str) -> str:
    if _FULL_SHA.fullmatch(value) is None:
        raise ValueError("legacy_bootstrap_commit_sha_invalid")
    return value


def _require_timeout(value: object) -> int:
    if type(value) is not int or value < 1 or value > _MAX_HEALTH_TIMEOUT_SECONDS:
        raise ValueError("legacy_bootstrap_health_timeout_invalid")
    return value


def _secure_directory(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("legacy_bootstrap_private_directory_invalid")
    path.chmod(_PRIVATE_DIRECTORY_MODE)


def _validate_regular_private_source(path: Path, error: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(error)
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(error)


def _validate_tree(path: Path, *, require_nonempty: bool) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("legacy_bootstrap_data_invalid")
    entries = sorted(path.rglob("*"))
    if require_nonempty and not entries:
        raise ValueError("legacy_bootstrap_data_empty")
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("legacy_bootstrap_state_link_unsupported")
        metadata = entry.stat(follow_symlinks=False)
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise ValueError("legacy_bootstrap_state_hardlink_unsupported")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("legacy_bootstrap_state_entry_invalid")


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _legacy_paths(home: Path, legacy_workdir: Path) -> dict[str, Path]:
    workdir = _absolute_without_symlinks(
        legacy_workdir, "legacy_bootstrap_workdir_symlink_unsupported"
    )
    if not workdir.is_dir() or _paths_overlap(home, workdir):
        raise ValueError("legacy_bootstrap_workdir_invalid")
    paths = {
        "workdir": workdir,
        "env": workdir / ".env",
        "config": workdir / "config.json",
        "data": workdir / "data" / "store",
    }
    _validate_regular_private_source(
        paths["env"], "legacy_bootstrap_environment_file_invalid"
    )
    _validate_regular_private_source(
        paths["config"], "legacy_bootstrap_config_file_invalid"
    )
    _validate_tree(paths["data"], require_nonempty=True)
    devices = {
        home.stat(follow_symlinks=False).st_dev,
        paths["env"].stat(follow_symlinks=False).st_dev,
        paths["config"].stat(follow_symlinks=False).st_dev,
        paths["data"].stat(follow_symlinks=False).st_dev,
    }
    if len(devices) != 1:
        raise ValueError("legacy_bootstrap_cross_filesystem_unsupported")
    return paths


def _expected_program_arguments() -> list[str]:
    arguments = ["/usr/bin/env"]
    for name in _PROXY_NAMES:
        arguments.extend(("-u", name))
    arguments.extend(
        (
            "/opt/homebrew/bin/uv",
            "run",
            "--frozen",
            "python",
            "-m",
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        )
    )
    return arguments


def validate_legacy_plist(path: Path, legacy_workdir: Path) -> Path:
    """Validate only the exact source-service plist observed in production."""
    plist_path = _absolute_without_symlinks(
        path, "legacy_bootstrap_plist_symlink_unsupported"
    )
    _validate_regular_private_source(plist_path, "legacy_bootstrap_plist_invalid")
    metadata = plist_path.stat(follow_symlinks=False)
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError("legacy_bootstrap_plist_permissions_invalid")
    if metadata.st_size <= 0 or metadata.st_size > 64 * 1024:
        raise ValueError("legacy_bootstrap_plist_invalid")
    try:
        with plist_path.open("rb") as stream:
            payload = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ValueError("legacy_bootstrap_plist_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _PLIST_KEYS:
        raise ValueError("legacy_bootstrap_plist_contract_invalid")
    environment = payload.get("EnvironmentVariables")
    if (
        payload.get("Label") != _LABEL
        or payload.get("ProgramArguments") != _expected_program_arguments()
        or payload.get("WorkingDirectory") != str(legacy_workdir)
        or not isinstance(environment, dict)
        or set(environment) != _LEGACY_ENV_NAMES
        or not all(isinstance(value, str) for value in environment.values())
        or payload.get("RunAtLoad") is not True
        or payload.get("KeepAlive") is not True
        or payload.get("ProcessType") != "Background"
        or payload.get("ThrottleInterval") != 10
    ):
        raise ValueError("legacy_bootstrap_plist_contract_invalid")
    for key in ("StandardOutPath", "StandardErrorPath"):
        value = payload.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("legacy_bootstrap_plist_contract_invalid")
    return plist_path


def legacy_plist_service_port(path: Path, legacy_workdir: Path) -> int:
    """Return the validated legacy listener port without reusing the new port."""
    plist_path = validate_legacy_plist(path, legacy_workdir)
    try:
        with plist_path.open("rb") as stream:
            payload = plistlib.load(stream)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise ValueError("legacy_bootstrap_plist_invalid") from exc
    arguments = payload.get("ProgramArguments")
    if not isinstance(arguments, list) or len(arguments) < 2:
        raise ValueError("legacy_bootstrap_plist_contract_invalid")
    value = arguments[-1]
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]{0,4}", value) is None:
        raise ValueError("legacy_bootstrap_plist_contract_invalid")
    port = int(value)
    if port > 65535:
        raise ValueError("legacy_bootstrap_plist_contract_invalid")
    return port


def _write_json(path: Path, payload: dict[str, object], *, replace: bool) -> None:
    if replace:
        if path.is_symlink() or not path.is_file():
            raise ValueError("legacy_bootstrap_journal_invalid")
    elif os.path.lexists(path):
        raise ValueError("legacy_bootstrap_journal_exists")
    temporary = path.with_name(f".{path.name}.next-{uuid.uuid4().hex}")
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            _PRIVATE_FILE_MODE,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(_PRIVATE_FILE_MODE)
    except OSError as exc:
        raise ValueError("legacy_bootstrap_journal_write_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _journal_path(home: Path) -> Path:
    return home / _JOURNAL_NAME


def _read_journal(home: Path) -> dict[str, object] | None:
    path = _journal_path(home)
    if not path.exists():
        if path.is_symlink():
            raise ValueError("legacy_bootstrap_journal_invalid")
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("legacy_bootstrap_journal_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy_bootstrap_journal_invalid") from exc
    expected = {
        "schema_version",
        "phase",
        "transaction_id",
        "commit_sha",
        "legacy_workdir",
        "legacy_plist",
        "work_name",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("legacy_bootstrap_journal_invalid")
    transaction_id = payload.get("transaction_id")
    commit_sha = payload.get("commit_sha")
    phase = payload.get("phase")
    work_name = payload.get("work_name")
    if (
        payload.get("schema_version") != _JOURNAL_SCHEMA
        or not isinstance(transaction_id, str)
        or _TRANSACTION_ID.fullmatch(transaction_id) is None
        or not isinstance(commit_sha, str)
        or _FULL_SHA.fullmatch(commit_sha) is None
        or phase not in _JOURNAL_PHASES
        or work_name != f"{_WORK_PREFIX}{transaction_id}"
        or not isinstance(payload.get("legacy_workdir"), str)
        or not Path(str(payload["legacy_workdir"])).is_absolute()
        or not isinstance(payload.get("legacy_plist"), str)
        or not Path(str(payload["legacy_plist"])).is_absolute()
    ):
        raise ValueError("legacy_bootstrap_journal_invalid")
    return payload


def _update_phase(home: Path, journal: dict[str, object], phase: str) -> None:
    if phase not in _JOURNAL_PHASES:
        raise ValueError("legacy_bootstrap_phase_invalid")
    journal["phase"] = phase
    _write_json(_journal_path(home), journal, replace=True)
    _fsync_local_directory(home, "legacy_bootstrap_journal_sync_failed")


def _clear_journal(home: Path, callbacks: BootstrapCallbacks) -> None:
    path = _journal_path(home)
    if path.is_symlink():
        raise ValueError("legacy_bootstrap_journal_invalid")
    path.unlink(missing_ok=True)
    callbacks.fsync_directory(home, "legacy_bootstrap_journal_sync_failed")


def _transaction_tree(
    home: Path,
    journal: dict[str, object],
    *,
    required: bool = True,
) -> Path | None:
    work = home / str(journal["work_name"])
    quarantine = home / _QUARANTINE_NAME
    work_exists = work.exists() or work.is_symlink()
    quarantine_exists = quarantine.exists() or quarantine.is_symlink()
    if work_exists and quarantine_exists:
        raise ValueError("legacy_bootstrap_transaction_tree_ambiguous")
    if not work_exists and not quarantine_exists:
        if required:
            raise ValueError("legacy_bootstrap_transaction_tree_missing")
        return None
    selected = quarantine if quarantine_exists else work
    if selected.is_symlink() or not selected.is_dir():
        raise ValueError("legacy_bootstrap_transaction_tree_missing")
    return selected


def _checkpoint(
    home: Path,
    journal: dict[str, object],
    phase: str,
    fault: Callable[[str], None] | None,
) -> None:
    _update_phase(home, journal, phase)
    if fault is not None:
        fault(phase)


def _reset_managed_readiness(
    home: Path,
    journal: dict[str, object],
) -> None:
    if journal.get("phase") == "readiness":
        _update_phase(home, journal, "healthy")


def _quiesce_managed_service(
    home: Path,
    journal: dict[str, object],
    managed_service: ManagedServiceHooks,
) -> None:
    """Close bootstrap readiness and stop managed service without short-circuiting."""
    failures: list[Exception] = []
    try:
        _reset_managed_readiness(home, journal)
    except Exception as exc:
        failures.append(exc)
    try:
        managed_service.stop()
    except Exception as exc:
        failures.append(exc)
    if failures:
        raise ValueError("legacy_bootstrap_managed_quiescence_failed") from failures[0]


def _preflight_inventory(home: Path, candidate: Path) -> Path:
    releases = home / "releases"
    prod = releases / "prod"
    if prod.is_symlink() or not prod.is_dir():
        raise ValueError("legacy_bootstrap_prod_release_missing")
    entries = {entry.name: entry for entry in releases.iterdir()}
    expected = {"prod", candidate.name}
    if set(entries) != expected or any(
        entry.is_symlink() for entry in entries.values()
    ):
        raise ValueError("legacy_bootstrap_release_inventory_invalid")
    if (home / _QUARANTINE_NAME).exists() or (home / _QUARANTINE_NAME).is_symlink():
        raise ValueError("legacy_bootstrap_quarantine_exists")
    if (
        prod.stat(follow_symlinks=False).st_dev
        != home.stat(follow_symlinks=False).st_dev
    ):
        raise ValueError("legacy_bootstrap_cross_filesystem_unsupported")
    return prod


def _require_empty_managed_state(home: Path) -> None:
    for name in ("data", "config"):
        path = home / name
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
            raise ValueError("legacy_bootstrap_destination_not_empty")


def _snapshot_legacy_state(
    tree: Path,
    paths: dict[str, Path],
    callbacks: BootstrapCallbacks,
) -> Path:
    state = tree / "state"
    staging = tree / ".state-staging"
    staging.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
    try:
        config = staging / "config"
        config.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
        callbacks.clone_file(paths["env"], config / ".env")
        callbacks.clone_file(paths["config"], config / "config.json")
        callbacks.clone_tree(paths["data"], staging / "data")
        _secure_directory(staging)
        _secure_directory(config)
        _validate_tree(staging / "data", require_nonempty=True)
        _validate_regular_private_source(
            config / ".env", "legacy_bootstrap_state_snapshot_invalid"
        )
        _validate_regular_private_source(
            config / "config.json", "legacy_bootstrap_state_snapshot_invalid"
        )
        callbacks.fsync_tree(staging)
        os.replace(staging, state)
        callbacks.fsync_directory(tree, "legacy_bootstrap_snapshot_sync_failed")
        return state
    except Exception:
        if staging.exists() and not staging.is_symlink():
            callbacks.remove_private_tree(staging)
        raise


def _move_legacy_state(
    home: Path,
    paths: dict[str, Path],
    callbacks: BootstrapCallbacks,
) -> None:
    managed_data = home / "data"
    managed_config = home / "config"
    managed_data.rmdir()
    os.replace(paths["data"], managed_data)
    os.replace(paths["env"], managed_config / ".env")
    os.replace(paths["config"], managed_config / "config.json")
    _secure_directory(managed_data)
    _secure_directory(managed_config)
    for entry in managed_data.rglob("*"):
        if entry.is_dir():
            entry.chmod(_PRIVATE_DIRECTORY_MODE)
        elif entry.is_file():
            entry.chmod(_PRIVATE_FILE_MODE)
    for entry in managed_config.iterdir():
        entry.chmod(_PRIVATE_FILE_MODE)
    callbacks.fsync_tree(managed_data)
    callbacks.fsync_tree(managed_config)
    callbacks.fsync_directory(
        paths["data"].parent, "legacy_bootstrap_state_move_sync_failed"
    )
    callbacks.fsync_directory(
        paths["workdir"], "legacy_bootstrap_state_move_sync_failed"
    )
    callbacks.fsync_directory(home, "legacy_bootstrap_state_move_sync_failed")


def _clone_config_snapshot(
    snapshot: Path,
    paths: dict[str, Path],
    callbacks: BootstrapCallbacks,
    transaction_id: str,
) -> None:
    for name, destination in ((".env", paths["env"]), ("config.json", paths["config"])):
        temporary = destination.with_name(
            f".{destination.name}.restore-{transaction_id}"
        )
        if os.path.lexists(temporary):
            raise ValueError("legacy_bootstrap_restore_temporary_exists")
        try:
            callbacks.clone_file(snapshot / "config" / name, temporary)
            os.replace(temporary, destination)
        except Exception:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            raise
    callbacks.fsync_directory(
        paths["workdir"], "legacy_bootstrap_state_restore_sync_failed"
    )


def _restore_legacy_state(
    home: Path,
    tree: Path,
    paths: dict[str, Path],
    callbacks: BootstrapCallbacks,
    transaction_id: str,
) -> None:
    snapshot = tree / "state"
    if not snapshot.exists():
        _validate_regular_private_source(
            paths["env"], "legacy_bootstrap_restore_source_missing"
        )
        _validate_regular_private_source(
            paths["config"], "legacy_bootstrap_restore_source_missing"
        )
        _validate_tree(paths["data"], require_nonempty=True)
        return
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("legacy_bootstrap_state_snapshot_invalid")
    _validate_tree(snapshot / "data", require_nonempty=True)
    data_temporary = paths["data"].with_name(
        f".{paths['data'].name}.restore-{transaction_id}"
    )
    if os.path.lexists(data_temporary):
        raise ValueError("legacy_bootstrap_restore_temporary_exists")
    try:
        callbacks.clone_tree(snapshot / "data", data_temporary)
    except Exception:
        if data_temporary.exists() and not data_temporary.is_symlink():
            callbacks.remove_private_tree(data_temporary)
        raise
    if paths["data"].exists() or paths["data"].is_symlink():
        callbacks.remove_private_tree(paths["data"])
    os.replace(data_temporary, paths["data"])
    _clone_config_snapshot(snapshot, paths, callbacks, transaction_id)
    callbacks.fsync_tree(paths["data"])
    callbacks.fsync_directory(
        paths["data"].parent, "legacy_bootstrap_state_restore_sync_failed"
    )

    for name in ("data", "config"):
        managed = home / name
        if managed.exists() or managed.is_symlink():
            callbacks.remove_private_tree(managed)
        managed.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
        _secure_directory(managed)
    callbacks.fsync_directory(home, "legacy_bootstrap_state_restore_sync_failed")


def _restore_release_layout(
    home: Path,
    tree: Path,
    sha: str,
    callbacks: BootstrapCallbacks,
) -> None:
    callbacks.replace_pointer(home, "previous", None)
    callbacks.replace_pointer(home, "current", None)
    releases = home / "releases"
    candidate = releases / f".candidate-{sha}"
    final = releases / f"sha-{sha}"
    if final.exists() and candidate.exists():
        raise ValueError("legacy_bootstrap_candidate_restore_ambiguous")
    if final.is_symlink() or candidate.is_symlink():
        raise ValueError("legacy_bootstrap_candidate_restore_invalid")
    if final.is_dir():
        os.replace(final, candidate)
    elif not candidate.is_dir():
        raise ValueError("legacy_bootstrap_candidate_restore_missing")
    prod = releases / "prod"
    quarantined_prod = tree / "prod"
    if prod.exists() and quarantined_prod.exists():
        raise ValueError("legacy_bootstrap_prod_restore_ambiguous")
    if prod.is_symlink() or quarantined_prod.is_symlink():
        raise ValueError("legacy_bootstrap_prod_restore_invalid")
    if quarantined_prod.is_dir():
        os.replace(quarantined_prod, prod)
    elif not prod.is_dir():
        raise ValueError("legacy_bootstrap_prod_restore_missing")
    callbacks.fsync_directory(releases, "legacy_bootstrap_release_restore_sync_failed")
    callbacks.fsync_directory(tree, "legacy_bootstrap_release_restore_sync_failed")


def _recover_locked(
    home: Path,
    journal: dict[str, object],
    *,
    managed_service: ManagedServiceHooks,
    legacy_service: LegacyServiceHooks,
    callbacks: BootstrapCallbacks,
    health_timeout: int,
) -> None:
    sha = str(journal["commit_sha"])
    workdir = Path(str(journal["legacy_workdir"]))
    paths = _legacy_paths_for_recovery(workdir)
    transaction_id = str(journal["transaction_id"])
    try:
        if journal.get("phase") == "preparing":
            work = home / str(journal["work_name"])
            quarantine = home / _QUARANTINE_NAME
            if quarantine.exists() or quarantine.is_symlink():
                raise ValueError("legacy_bootstrap_transaction_tree_ambiguous")
            if work.exists() or work.is_symlink():
                if work.is_symlink() or not work.is_dir():
                    raise ValueError("legacy_bootstrap_transaction_tree_missing")
                callbacks.remove_private_tree(work)
            _clear_journal(home, callbacks)
            return

        if journal.get("phase") == "rolled_back":
            tree = _transaction_tree(home, journal, required=False)
            legacy_service.stop()
            legacy_service.start()
            if legacy_service.health(health_timeout) is not True:
                raise ValueError("legacy_bootstrap_legacy_health_failed")
            if tree is not None:
                callbacks.remove_private_tree(tree)
            _clear_journal(home, callbacks)
            return

        tree = _transaction_tree(home, journal)
        if tree is None:
            raise ValueError("legacy_bootstrap_transaction_tree_missing")
        _quiesce_managed_service(home, journal, managed_service)
        _restore_release_layout(home, tree, sha, callbacks)
        _restore_legacy_state(home, tree, paths, callbacks, transaction_id)
        backup = tree / "legacy.plist"
        _validate_regular_private_source(
            backup, "legacy_bootstrap_plist_backup_missing"
        )
        legacy_service.restore_plist(backup)
        legacy_service.start()
        if legacy_service.health(health_timeout) is not True:
            raise ValueError("legacy_bootstrap_legacy_health_failed")
        _update_phase(home, journal, "rolled_back")
        callbacks.remove_private_tree(tree)
        _clear_journal(home, callbacks)
    except Exception as exc:
        raise ValueError("legacy_bootstrap_recovery_failed") from exc


def _legacy_paths_for_recovery(workdir: Path) -> dict[str, Path]:
    absolute = Path(os.path.abspath(os.fspath(workdir.expanduser())))
    return {
        "workdir": absolute,
        "env": absolute / ".env",
        "config": absolute / "config.json",
        "data": absolute / "data" / "store",
    }


def _write_receipt(tree: Path, manifest: dict[str, object]) -> None:
    sha = manifest.get("commit_sha")
    fingerprint = manifest.get("payload_fingerprint")
    if not isinstance(sha, str) or _FULL_SHA.fullmatch(sha) is None:
        raise ValueError("legacy_bootstrap_manifest_invalid")
    if (
        not isinstance(fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
    ):
        raise ValueError("legacy_bootstrap_manifest_invalid")
    _write_json(
        tree / "receipt.json",
        {
            "schema_version": _RECEIPT_SCHEMA,
            "commit_sha": sha,
            "payload_fingerprint": fingerprint,
        },
        replace=False,
    )


def preflight_legacy_sources(
    home: Path,
    *,
    legacy_workdir: Path,
    legacy_plist: Path,
) -> None:
    """Validate a clean owner-selected legacy topology before remote download."""

    if home.is_symlink() or not home.is_dir():
        raise ValueError("legacy_bootstrap_home_invalid")
    if _read_journal(home) is not None:
        raise ValueError("legacy_bootstrap_recovery_required")
    if (home / _QUARANTINE_NAME).exists() or (home / _QUARANTINE_NAME).is_symlink():
        raise ValueError("legacy_bootstrap_quarantine_exists")
    if any(home.glob(f"{_WORK_PREFIX}*")):
        raise ValueError("legacy_bootstrap_transaction_tree_exists")

    workdir = _absolute_without_symlinks(
        legacy_workdir, "legacy_bootstrap_workdir_symlink_unsupported"
    )
    validate_legacy_plist(legacy_plist, workdir)
    _legacy_paths(home, workdir)
    _require_empty_managed_state(home)

    releases = home / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise ValueError("legacy_bootstrap_release_inventory_invalid")
    entries = {entry.name: entry for entry in releases.iterdir()}
    if set(entries) != {"prod"} or any(
        entry.is_symlink() for entry in entries.values()
    ):
        raise ValueError("legacy_bootstrap_release_inventory_invalid")
    prod = entries["prod"]
    if (
        not prod.is_dir()
        or prod.stat(follow_symlinks=False).st_dev
        != home.stat(follow_symlinks=False).st_dev
    ):
        raise ValueError("legacy_bootstrap_prod_release_invalid")


def _read_receipt(quarantine: Path) -> dict[str, object]:
    path = quarantine / "receipt.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("legacy_bootstrap_quarantine_receipt_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("legacy_bootstrap_quarantine_receipt_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "commit_sha", "payload_fingerprint"}
        or payload.get("schema_version") != _RECEIPT_SCHEMA
        or not isinstance(payload.get("commit_sha"), str)
        or _FULL_SHA.fullmatch(str(payload["commit_sha"])) is None
        or not isinstance(payload.get("payload_fingerprint"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(payload["payload_fingerprint"])) is None
    ):
        raise ValueError("legacy_bootstrap_quarantine_receipt_invalid")
    return payload


def bootstrap_legacy_locked(
    home: Path,
    *,
    commit_sha: str,
    legacy_workdir: Path,
    legacy_plist: Path,
    confirmation: str,
    health_timeout: int,
    managed_service: ManagedServiceHooks,
    legacy_service: LegacyServiceHooks,
    callbacks: BootstrapCallbacks,
    fault: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Perform the one-time source-service to immutable-release handoff."""
    sha = _require_sha(commit_sha)
    if confirmation != f"BOOTSTRAP {sha}":
        raise ValueError(f"legacy_bootstrap_confirmation_required:BOOTSTRAP {sha}")
    health_timeout = _require_timeout(health_timeout)
    workdir = _absolute_without_symlinks(
        legacy_workdir, "legacy_bootstrap_workdir_symlink_unsupported"
    )
    plist_path = _absolute_without_symlinks(
        legacy_plist, "legacy_bootstrap_plist_symlink_unsupported"
    )

    if recover_legacy_bootstrap_locked(
        home,
        expected_commit_sha=sha,
        legacy_workdir=workdir,
        legacy_plist=plist_path,
        health_timeout=health_timeout,
        managed_service=managed_service,
        legacy_service=legacy_service,
        callbacks=callbacks,
    ):
        raise ValueError("legacy_bootstrap_recovered_retry_required")

    plist_path = validate_legacy_plist(plist_path, workdir)

    current, previous = callbacks.pointer_state(home)
    if current is not None or previous is not None:
        raise ValueError("legacy_bootstrap_requires_unmanaged_runtime")
    paths = _legacy_paths(home, workdir)
    _require_empty_managed_state(home)
    candidate, manifest = callbacks.validate_candidate(home, sha)
    prod = _preflight_inventory(home, candidate)
    callbacks.probe_release(home, candidate, manifest, health_timeout)
    legacy_service.preflight()

    transaction_id = uuid.uuid4().hex
    work = home / f"{_WORK_PREFIX}{transaction_id}"
    journal: dict[str, object] = {
        "schema_version": _JOURNAL_SCHEMA,
        "phase": "preparing",
        "transaction_id": transaction_id,
        "commit_sha": sha,
        "legacy_workdir": str(workdir),
        "legacy_plist": str(plist_path),
        "work_name": work.name,
    }
    _write_json(_journal_path(home), journal, replace=False)

    try:
        callbacks.fsync_directory(home, "legacy_bootstrap_journal_sync_failed")
        if fault is not None:
            fault("preparing")
        work.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
        _secure_directory(work)
        callbacks.clone_file(plist_path, work / "legacy.plist")
        (work / "legacy.plist").chmod(_PRIVATE_FILE_MODE)
        callbacks.fsync_directory(work, "legacy_bootstrap_backup_sync_failed")
        _checkpoint(home, journal, "prepared", fault)
        legacy_service.stop()
        _checkpoint(home, journal, "stopped", fault)
        state_snapshot = _snapshot_legacy_state(work, paths, callbacks)
        callbacks.fsync_directory(work, "legacy_bootstrap_snapshot_sync_failed")
        _checkpoint(home, journal, "snapshotted", fault)
        _move_legacy_state(home, paths, callbacks)
        _checkpoint(home, journal, "state_moved", fault)
        callbacks.probe_state(candidate, manifest, state_snapshot, health_timeout)
        _checkpoint(home, journal, "state_compatible", fault)
        os.replace(prod, work / "prod")
        callbacks.fsync_directory(
            home / "releases", "legacy_bootstrap_prod_sync_failed"
        )
        callbacks.fsync_directory(work, "legacy_bootstrap_prod_sync_failed")
        _checkpoint(home, journal, "prod_quarantined", fault)
        final = home / "releases" / f"sha-{sha}"
        os.replace(candidate, final)
        callbacks.seal_release(final, sha)
        callbacks.replace_pointer(home, "previous", None)
        callbacks.replace_pointer(home, "current", final)
        callbacks.fsync_directory(
            home / "releases", "legacy_bootstrap_switch_sync_failed"
        )
        _checkpoint(home, journal, "switched", fault)
        managed_service.start(health_timeout)
        _checkpoint(home, journal, "new_started", fault)
        if managed_service.health(final, manifest, health_timeout) is not True:
            raise ValueError("legacy_bootstrap_service_identity_mismatch")
        _checkpoint(home, journal, "healthy", fault)
        _checkpoint(home, journal, "readiness", fault)
        if managed_service.health(final, manifest, health_timeout) is not True:
            raise ValueError("legacy_bootstrap_scheduler_readiness_failed")
        _write_receipt(work, manifest)
        callbacks.fsync_directory(work, "legacy_bootstrap_receipt_sync_failed")
        _checkpoint(home, journal, "committing", fault)
        quarantine = home / _QUARANTINE_NAME
        os.replace(work, quarantine)
        callbacks.fsync_directory(home, "legacy_bootstrap_quarantine_sync_failed")
        _checkpoint(home, journal, "committed", fault)
        _clear_journal(home, callbacks)
    except Exception as bootstrap_error:
        try:
            retained = _read_journal(home)
            if retained is None:
                raise ValueError("legacy_bootstrap_journal_missing")
            _recover_locked(
                home,
                retained,
                managed_service=managed_service,
                legacy_service=legacy_service,
                callbacks=callbacks,
                health_timeout=health_timeout,
            )
        except Exception as recovery_error:
            raise ValueError("legacy_bootstrap_recovery_failed") from recovery_error
        raise ValueError("legacy_bootstrap_failed_rolled_back") from bootstrap_error
    return {
        "status": "legacy_bootstrap_complete",
        "current": sha,
        "previous": None,
        "quarantine_retained": True,
    }


def recover_legacy_bootstrap_locked(
    home: Path,
    *,
    legacy_workdir: Path,
    legacy_plist: Path,
    health_timeout: int,
    managed_service: ManagedServiceHooks,
    legacy_service: LegacyServiceHooks,
    callbacks: BootstrapCallbacks,
    expected_commit_sha: str | None = None,
) -> str | None:
    """Recover a retained bootstrap journal without contacting a release source."""

    health_timeout = _require_timeout(health_timeout)
    workdir = _absolute_without_symlinks(
        legacy_workdir, "legacy_bootstrap_workdir_symlink_unsupported"
    )
    plist_path = _absolute_without_symlinks(
        legacy_plist, "legacy_bootstrap_plist_symlink_unsupported"
    )
    expected_sha = (
        _require_sha(expected_commit_sha) if expected_commit_sha is not None else None
    )
    existing = _read_journal(home)
    if existing is None:
        return None
    if (
        (expected_sha is not None and existing.get("commit_sha") != expected_sha)
        or existing.get("legacy_workdir") != str(workdir)
        or existing.get("legacy_plist") != str(plist_path)
    ):
        raise ValueError("legacy_bootstrap_recovery_arguments_mismatch")
    _recover_locked(
        home,
        existing,
        managed_service=managed_service,
        legacy_service=legacy_service,
        callbacks=callbacks,
        health_timeout=health_timeout,
    )
    return str(existing["commit_sha"])


def legacy_bootstrap_recovery_pending(home: Path) -> bool:
    """Return whether a validated legacy bootstrap journal needs recovery."""

    return _read_journal(home) is not None


def finalize_bootstrap_locked(
    home: Path,
    *,
    confirmation: str,
    health_timeout: int,
    managed_service: ManagedServiceHooks,
    callbacks: BootstrapCallbacks,
) -> dict[str, object]:
    """Delete only the exact completed quarantine after current is healthy."""
    if confirmation != _FINALIZE_CONFIRMATION:
        raise ValueError(
            f"legacy_bootstrap_confirmation_required:{_FINALIZE_CONFIRMATION}"
        )
    health_timeout = _require_timeout(health_timeout)
    if _read_journal(home) is not None:
        raise ValueError("legacy_bootstrap_recovery_required")
    quarantine = home / _QUARANTINE_NAME
    if quarantine.is_symlink() or not quarantine.is_dir():
        raise ValueError("legacy_bootstrap_quarantine_missing")
    _read_receipt(quarantine)
    current, _previous = callbacks.pointer_state(home)
    if current is None:
        raise ValueError("legacy_bootstrap_current_missing")
    manifest = callbacks.manifest_for(current)
    managed_service.start(health_timeout)
    if managed_service.health(current, manifest, health_timeout) is not True:
        raise ValueError("legacy_bootstrap_current_health_failed")
    callbacks.remove_quarantine(quarantine)
    callbacks.fsync_directory(home, "legacy_bootstrap_finalize_sync_failed")
    return {
        "status": "legacy_bootstrap_finalized",
        "current": manifest["commit_sha"],
    }


def _fsync_regular_file(path: Path, error: str) -> None:
    """Sync one validated file without following a replaced path."""
    try:
        metadata = path.stat(follow_symlinks=False)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_dev != metadata.st_dev
                or opened.st_ino != metadata.st_ino
            ):
                raise ValueError(error)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(error) from exc


def _fsync_local_directory(path: Path, error: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError(error) from exc


def clone_private_file_apfs(source: Path, destination: Path) -> None:
    """Clone one validated regular file without exposing its contents."""
    _validate_regular_private_source(source, "legacy_bootstrap_clone_source_invalid")
    if os.path.lexists(destination):
        raise ValueError("legacy_bootstrap_clone_destination_exists")
    cloned = False
    try:
        try:
            result = subprocess.run(
                ["/bin/cp", "-c", "--", str(source), str(destination)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            raise ValueError("legacy_bootstrap_apfs_clone_failed") from exc
        if result.returncode != 0:
            raise ValueError("legacy_bootstrap_apfs_clone_failed")
        _validate_regular_private_source(
            destination, "legacy_bootstrap_clone_destination_invalid"
        )
        destination.chmod(_PRIVATE_FILE_MODE)
        _fsync_regular_file(destination, "legacy_bootstrap_clone_sync_failed")
        cloned = True
    finally:
        if not cloned and destination.exists() and not destination.is_symlink():
            destination.unlink()


def remove_legacy_quarantine(path: Path) -> None:
    """Remove one exact quarantine without following legacy symlinks."""
    if path.name != _QUARANTINE_NAME or path.is_symlink() or not path.is_dir():
        raise ValueError("legacy_bootstrap_quarantine_invalid")
    for root, directories, _files in os.walk(path, topdown=False, followlinks=False):
        root_path = Path(root)
        if not root_path.is_symlink():
            root_path.chmod(_PRIVATE_DIRECTORY_MODE)
        for name in directories:
            directory = root_path / name
            if not directory.is_symlink():
                directory.chmod(_PRIVATE_DIRECTORY_MODE)
    try:
        shutil.rmtree(path)
    except OSError as exc:
        raise ValueError("legacy_bootstrap_quarantine_remove_failed") from exc


def _legacy_payload_matches(
    health: object,
    live: object,
    *,
    expected_activation_guarded: bool,
) -> bool:
    return (
        isinstance(health, dict)
        and isinstance(live, dict)
        and _legacy_baseline_payload_matches(health, live)
        and health.get("scope") == "process_liveness_only"
        and all(health.get(field) is False for field in _SERVICE_HEALTH_FALSE_FIELDS)
        and live.get("initialized") is True
        and live.get("activation_guarded") is expected_activation_guarded
    )


def _legacy_baseline_payload_matches(health: object, live: object) -> bool:
    """Recognize the existing source service without requiring new fields."""
    return (
        isinstance(health, dict)
        and health.get("schema_version") == "karkinos.service_health.v1"
        and health.get("service") == "karkinos"
        and health.get("status") == "alive"
        and isinstance(live, dict)
        and live.get("running") is True
    )


def _legacy_health(
    port: int,
    timeout: int,
    *,
    expected_activation_guarded: bool | None,
    identity_probe: Callable[[], bool] = lambda: True,
) -> bool:
    timeout = _require_timeout(timeout)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if identity_probe() is not True:
                time.sleep(0.2)
                continue
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", "/api/health")
                health_response = connection.getresponse()
                health = json.loads(health_response.read())
            finally:
                connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", "/api/settings/live/status")
                live_response = connection.getresponse()
                live = json.loads(live_response.read())
            finally:
                connection.close()
            if (
                health_response.status == 200
                and live_response.status == 200
                and (
                    _legacy_baseline_payload_matches(health, live)
                    if expected_activation_guarded is None
                    else _legacy_payload_matches(
                        health,
                        live,
                        expected_activation_guarded=expected_activation_guarded,
                    )
                )
                and identity_probe() is True
            ):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def legacy_launchd_hooks(
    plist_path: Path,
    *,
    runtime_home: Path,
    legacy_workdir: Path,
    port: int,
    runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
    listener_runner: Callable[
        ..., subprocess.CompletedProcess[object]
    ] = subprocess.run,
    process_runner: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
) -> LegacyServiceHooks:
    """Build the exact launchd lifecycle used only by bootstrap rollback."""
    if platform.system() != "Darwin":
        raise ValueError("legacy_bootstrap_launchd_requires_macos")
    if port < 1 or port > 65535:
        raise ValueError("legacy_bootstrap_service_port_invalid")
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{_LABEL}"
    plist = plist_path.expanduser().absolute()
    home = _absolute_without_symlinks(
        runtime_home, "legacy_bootstrap_home_symlink_unsupported"
    )
    workdir = _absolute_without_symlinks(
        legacy_workdir, "legacy_bootstrap_workdir_symlink_unsupported"
    )

    def launchctl_state() -> subprocess.CompletedProcess[object]:
        return runner(
            ["/bin/launchctl", "print", target],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )

    def loaded() -> bool:
        result = launchctl_state()
        return result.returncode == 0

    def launchctl_identity() -> tuple[int, str, str] | None:
        result = launchctl_state()
        if result.returncode != 0:
            return None
        output = result.stdout
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        if not isinstance(output, str):
            return None
        pid_matches = re.findall(r"(?m)^\s*pid = ([1-9][0-9]*)\s*$", output)
        program_matches = re.findall(r"(?m)^\s*program = (\S+)\s*$", output)
        workdir_matches = re.findall(r"(?m)^\s*working directory = (.+?)\s*$", output)
        if (
            len(pid_matches) != 1
            or program_matches != ["/usr/bin/env"]
            or workdir_matches != [str(workdir)]
        ):
            return None
        return int(pid_matches[0]), program_matches[0], workdir_matches[0]

    def listener_pids() -> list[int] | None:
        result = listener_runner(
            [
                "/usr/sbin/lsof",
                "-nP",
                f"-tiTCP:{port}",
                "-sTCP:LISTEN",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        if not isinstance(output, str):
            return None
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if result.returncode == 1 and not lines:
            return []
        if result.returncode != 0 or any(not line.isdecimal() for line in lines):
            return None
        values = [int(line) for line in lines]
        if any(value <= 0 for value in values) or len(set(values)) != len(values):
            return None
        return values

    def process_identities(
        root_pid: int, listener_pid: int
    ) -> dict[int, tuple[int, int, str, str]] | None:
        requested = {root_pid, listener_pid}
        result = process_runner(
            [
                "/bin/ps",
                "-ww",
                "-o",
                "pid=,ppid=,pgid=,lstart=,command=",
                "-p",
                ",".join(str(pid) for pid in sorted(requested)),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        output = result.stdout
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        if result.returncode != 0 or not isinstance(output, str):
            return None
        identities: dict[int, tuple[int, int, str, str]] = {}
        for line in output.splitlines():
            match = re.fullmatch(
                r"\s*([1-9][0-9]*)\s+([0-9]+)\s+([1-9][0-9]*)\s+"
                r"(\S{3}\s+\S{3}\s+[0-9]{1,2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2}\s+[0-9]{4})\s+"
                r"(.+?)\s*",
                line,
            )
            if match is None:
                return None
            pid, parent, group = (int(match.group(index)) for index in (1, 2, 3))
            if pid not in requested or pid in identities:
                return None
            identities[pid] = (parent, group, match.group(4), match.group(5))
        return identities if set(identities) == requested else None

    expected_wrapper = _expected_program_arguments()
    expected_wrapper = expected_wrapper[
        expected_wrapper.index("/opt/homebrew/bin/uv") :
    ]
    expected_server_arguments = [
        "-m",
        "server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    def wrapper_command_matches(command: str) -> bool:
        return command.split() == expected_wrapper

    def server_command_matches(command: str) -> bool:
        arguments = command.split()
        if len(arguments) != len(expected_server_arguments) + 1:
            return False
        executable = Path(arguments[0])
        return (
            executable.parent == workdir / ".venv" / "bin"
            and re.fullmatch(r"python(?:3(?:\.[0-9]+)?)?", executable.name) is not None
            and arguments[1:] == expected_server_arguments
        )

    def identity_snapshot() -> (
        tuple[
            tuple[int, str, str],
            int,
            dict[int, tuple[int, int, str, str]],
        ]
        | None
    ):
        launchd = launchctl_identity()
        listeners = listener_pids()
        if launchd is None or listeners is None or len(listeners) != 1:
            return None
        root_pid = launchd[0]
        listener_pid = listeners[0]
        processes = process_identities(root_pid, listener_pid)
        if processes is None:
            return None
        return launchd, listener_pid, processes

    def listener_matches_service() -> bool:
        first = identity_snapshot()
        second = identity_snapshot()
        if first is None or first != second:
            return False
        launchd, listener_pid, processes = first
        root_pid = launchd[0]
        listener = processes[listener_pid]
        if listener_pid == root_pid:
            return listener[1] == root_pid and server_command_matches(listener[3])
        root = processes[root_pid]
        return (
            root[1] == root_pid
            and listener[0] == root_pid
            and listener[1] == root[1]
            and wrapper_command_matches(root[3])
            and server_command_matches(listener[3])
        )

    def preflight() -> None:
        if not loaded():
            raise ValueError("legacy_bootstrap_legacy_service_not_loaded")
        if not _legacy_health(
            port,
            5,
            expected_activation_guarded=None,
            identity_probe=listener_matches_service,
        ):
            raise ValueError("legacy_bootstrap_legacy_service_identity_mismatch")

    def stop() -> None:
        if not loaded():
            if listener_pids() == []:
                return
            raise ValueError("legacy_bootstrap_legacy_stop_failed")
        result = runner(
            ["/bin/launchctl", "bootout", target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("legacy_bootstrap_legacy_stop_failed")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not loaded() and listener_pids() == []:
                return
            time.sleep(0.2)
        raise ValueError("legacy_bootstrap_legacy_stop_failed")

    def restore_plist(backup: Path) -> None:
        if loaded():
            raise ValueError("legacy_bootstrap_plist_restore_while_loaded")
        validate_legacy_plist(backup, workdir)
        temporary = plist.with_name(f".{plist.name}.restore-{uuid.uuid4().hex}")
        try:
            clone_private_file_apfs(backup, temporary)
            os.replace(temporary, plist)
            plist.chmod(_PRIVATE_FILE_MODE)
            validate_legacy_plist(plist, workdir)
            _fsync_local_directory(
                plist.parent, "legacy_bootstrap_plist_restore_sync_failed"
            )
        finally:
            temporary.unlink(missing_ok=True)

    def write_guarded_plist(path: Path) -> None:
        official = validate_legacy_plist(plist, workdir)
        try:
            with official.open("rb") as stream:
                payload = plistlib.load(stream)
        except (OSError, plistlib.InvalidFileException) as exc:
            raise ValueError("legacy_bootstrap_plist_invalid") from exc
        environment = payload.get("EnvironmentVariables")
        if not isinstance(environment, dict):
            raise ValueError("legacy_bootstrap_plist_contract_invalid")
        payload["EnvironmentVariables"] = {
            **environment,
            "KARKINOS_HOME": str(home),
            "KARKINOS_DATA_DIR": str(workdir / "data" / "store"),
            "KARKINOS_CONFIG_PATH": str(workdir / "config.json"),
            "KARKINOS_ENV_FILE": str(workdir / ".env"),
        }
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                _PRIVATE_FILE_MODE,
            )
            with os.fdopen(descriptor, "wb") as stream:
                plistlib.dump(payload, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(_PRIVATE_FILE_MODE)
            _fsync_regular_file(path, "legacy_bootstrap_guarded_plist_sync_failed")
            _fsync_local_directory(
                path.parent, "legacy_bootstrap_guarded_plist_sync_failed"
            )
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("legacy_bootstrap_guarded_plist_write_failed") from exc

    def start() -> None:
        if loaded():
            return
        guarded = plist.with_name(f".{plist.name}.guarded-{uuid.uuid4().hex}")
        try:
            write_guarded_plist(guarded)
            result = runner(
                ["/bin/launchctl", "bootstrap", domain, str(guarded)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("legacy_bootstrap_legacy_start_failed")
        finally:
            guarded.unlink(missing_ok=True)
            _fsync_local_directory(
                plist.parent, "legacy_bootstrap_guarded_plist_sync_failed"
            )

    return LegacyServiceHooks(
        preflight=preflight,
        stop=stop,
        start=start,
        health=lambda timeout: _legacy_health(
            port,
            timeout,
            expected_activation_guarded=True,
            identity_probe=listener_matches_service,
        ),
        restore_plist=restore_plist,
    )
