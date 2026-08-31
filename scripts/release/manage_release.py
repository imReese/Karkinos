#!/usr/bin/env python3
"""Verify, test, activate, and roll back immutable Karkinos releases.

The command is deliberately local and fail-closed. It never contacts a broker
or grants trading authority. A tag-free candidate runs only with disposable
state; a published stable artifact enters production only through a journaled,
health-checked activation. Only ``current`` and ``previous`` are active pointers;
candidate directories are never considered active releases.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import math
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlsplit

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

RELEASES_DIRNAME = "releases"
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_TRANSACTION_NAME = ".release-transaction.json"
_LEGACY_BOOTSTRAP_TRANSACTION_NAME = ".legacy-bootstrap-transaction.json"
_TRANSACTION_SCHEMA = "karkinos.release_transaction.v2"
_SERVICE_CONFIG_NAME = ".service-config.json"
_SERVICE_CONFIG_SCHEMA = "karkinos.service_config.v1"
_DEFAULT_SERVICE_PORT = 8000
_DEFAULT_CANDIDATE_PORT = 18000
_FALLBACK_CANDIDATE_PORT = 18001
_DEFAULT_HEALTH_TIMEOUT_SECONDS = 30
_MAX_HEALTH_TIMEOUT_SECONDS = 3600
_SNAPSHOT_DIRNAME = ".release-state-snapshots"
_STAGING_DIRECTORY = re.compile(r"^\.staging-[0-9a-f]{32}$")
_DELETING_DIRECTORY = re.compile(
    r"^\.deleting-(?:sha|candidate)-[0-9a-f]{40}-[0-9a-f]{32}$"
)
_RECOVERY_CONFIRMATION = "RECOVER RELEASE STATE"
_ADOPTION_CONFIRMATION = "ADOPT LEGACY STATE"
_LEGACY_CONFIG_NAMES = ("config.json", ".env")
_ACTIVE_RELEASE_LOCKS: dict[str, tuple[int, str]] = {}


@dataclass(frozen=True)
class ReleaseServiceHooks:
    """Injected resident-service lifecycle used by deploy and recovery transactions."""

    stop: Callable[[], None]
    start: Callable[[int], None]
    health: Callable[[Path, dict[str, object], int], bool]


def _home(value: str | None) -> Path:
    """Resolve the configured root without silently following a root symlink."""
    configured = value or os.environ.get("KARKINOS_HOME")
    return (
        Path(configured or "~/Library/Application Support/Karkinos")
        .expanduser()
        .absolute()
    )


def _architecture() -> str:
    value = platform.machine().lower()
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    raise ValueError("macos_architecture_unsupported")


def _require_sha(value: str) -> str:
    if _FULL_SHA.fullmatch(value) is None:
        raise ValueError("release_commit_sha_invalid")
    return value


def _release_dirs(home: Path) -> tuple[Path, Path, Path]:
    releases = home / RELEASES_DIRNAME
    return releases, home / "current", home / "previous"


def _secure_directory(path: Path, error: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(error)
    try:
        path.chmod(_PRIVATE_DIRECTORY_MODE)
    except OSError as exc:
        raise ValueError(error) from exc


def _secure_private_tree(path: Path) -> None:
    """Restrict a mutable state tree without reading or copying its contents."""
    if path.is_symlink() or not path.is_dir():
        raise ValueError("release_private_tree_invalid")
    entries = [path, *sorted(path.rglob("*"))]
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("release_private_tree_symlink_unsupported")
        try:
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                entry.chmod(_PRIVATE_DIRECTORY_MODE)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                entry.chmod(_PRIVATE_FILE_MODE)
            else:
                raise ValueError("release_private_tree_entry_invalid")
        except OSError as exc:
            raise ValueError("release_private_tree_permission_failed") from exc


def _ensure_layout(home: Path) -> Path:
    releases, _current, _previous = _release_dirs(home)
    if not home.is_absolute():
        raise ValueError("release_runtime_home_not_absolute")
    for ancestor in (home.parent, *home.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("release_runtime_parent_symlink_unsupported")
        if ancestor.parent == ancestor:
            break
    for path in (home, releases, home / "data", home / "config", home / "logs"):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"release_runtime_directory_invalid:{path.name}")
        path.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        _secure_directory(path, f"release_runtime_directory_invalid:{path.name}")
    return releases


@contextlib.contextmanager
def _lock(home: Path) -> Iterator[None]:
    _ensure_layout(home)
    lock_path = home / ".release.lock"
    if lock_path.is_symlink():
        raise ValueError("release_lock_symlink_unsupported")
    flags = (
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(lock_path, flags, _PRIVATE_FILE_MODE)
        _validate_lock_descriptor(lock_path, descriptor)
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ValueError("release_lock_invalid") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as stream:
        locked = False
        capability_published = False
        owner_pid = os.getpid()
        capability = uuid.uuid4().hex
        lock_key = str(home.expanduser().absolute())
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            locked = True
            _validate_lock_descriptor(lock_path, stream.fileno())
            os.fchmod(stream.fileno(), _PRIVATE_FILE_MODE)
            stream.seek(0)
            stream.truncate()
            stream.write(f"{owner_pid} {capability}\n")
            stream.flush()
            os.fsync(stream.fileno())
            _ACTIVE_RELEASE_LOCKS[lock_key] = (owner_pid, capability)
            capability_published = True
            yield
        finally:
            if capability_published:
                _ACTIVE_RELEASE_LOCKS.pop(lock_key, None)
            try:
                if capability_published:
                    _validate_lock_descriptor(lock_path, stream.fileno())
                    stream.seek(0)
                    stream.truncate()
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                if locked:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _validate_lock_descriptor(lock_path: Path, descriptor: int) -> None:
    try:
        opened = os.fstat(descriptor)
        linked = lock_path.lstat()
    except OSError as exc:
        raise ValueError("release_lock_invalid") from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_uid != os.getuid()
        or opened.st_nlink != 1
        or not stat.S_ISREG(linked.st_mode)
        or linked.st_dev != opened.st_dev
        or linked.st_ino != opened.st_ino
    ):
        raise ValueError("release_lock_invalid")


def _fsync_directory(path: Path, error: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ValueError(error) from exc


def _validated_service_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError("release_service_port_invalid")
    return value


def _requested_service_port(args: argparse.Namespace) -> int | None:
    cli_value = getattr(args, "service_port", None)
    cli_port = None if cli_value is None else _validated_service_port(cli_value)
    environment_value = os.environ.get("KARKINOS_BACKEND_PORT")
    environment_port: int | None = None
    if environment_value is not None:
        if re.fullmatch(r"[1-9][0-9]{0,4}", environment_value) is None:
            raise ValueError("release_service_port_invalid")
        environment_port = _validated_service_port(int(environment_value))
    if (
        cli_port is not None
        and environment_port is not None
        and cli_port != environment_port
    ):
        raise ValueError("release_service_port_sources_conflict")
    return cli_port if cli_port is not None else environment_port


def _service_config_path(home: Path) -> Path:
    return home / _SERVICE_CONFIG_NAME


def _read_service_port(home: Path) -> int | None:
    path = _service_config_path(home)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("release_service_config_invalid") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
    ):
        raise ValueError("release_service_config_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_service_config_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "service_port"}
        or payload.get("schema_version") != _SERVICE_CONFIG_SCHEMA
    ):
        raise ValueError("release_service_config_invalid")
    try:
        return _validated_service_port(payload.get("service_port"))
    except ValueError as exc:
        raise ValueError("release_service_config_invalid") from exc


def _write_service_port_locked(home: Path, port: int) -> None:
    port = _validated_service_port(port)
    lock_owner = _ACTIVE_RELEASE_LOCKS.get(str(home.expanduser().absolute()))
    if lock_owner is None or lock_owner[0] != os.getpid():
        raise ValueError("release_service_config_lock_required")
    path = _service_config_path(home)
    if os.path.lexists(path):
        raise ValueError("release_service_config_exists")
    temporary = home / f".{_SERVICE_CONFIG_NAME}.next-{uuid.uuid4().hex}"
    payload = {
        "schema_version": _SERVICE_CONFIG_SCHEMA,
        "service_port": port,
    }
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
        _fsync_directory(home, "release_service_config_sync_failed")
    except OSError as exc:
        raise ValueError("release_service_config_write_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _remove_service_port_locked(home: Path) -> None:
    lock_owner = _ACTIVE_RELEASE_LOCKS.get(str(home.expanduser().absolute()))
    if lock_owner is None or lock_owner[0] != os.getpid():
        raise ValueError("release_service_config_lock_required")
    path = _service_config_path(home)
    if _read_service_port(home) is None:
        return
    try:
        path.unlink()
        _fsync_directory(home, "release_service_config_sync_failed")
    except OSError as exc:
        raise ValueError("release_service_config_remove_failed") from exc


def _initialize_service_port_locked(home: Path, requested: int | None) -> int:
    configured = _read_service_port(home)
    if configured is None:
        configured = requested if requested is not None else _DEFAULT_SERVICE_PORT
        _write_service_port_locked(home, configured)
    elif requested is not None and requested != configured:
        raise ValueError("release_service_port_mismatch")
    return configured


def _configured_or_explicit_service_port_locked(
    home: Path, requested: int | None
) -> int:
    configured = _read_service_port(home)
    if configured is None:
        if requested is None:
            raise ValueError("release_service_config_missing")
        _write_service_port_locked(home, requested)
        return requested
    if requested is not None and requested != configured:
        raise ValueError("release_service_port_mismatch")
    return configured


def _prepare_service_port(home: Path, requested: int | None) -> int:
    with _lock(home):
        _ensure_layout(home)
        return _configured_or_explicit_service_port_locked(home, requested)


def _fsync_private_tree(path: Path) -> None:
    """Make every copied state file and directory durable before publication."""
    _validate_mutable_tree(path)
    try:
        entries = [path, *sorted(path.rglob("*"))]
    except OSError as exc:
        raise ValueError("release_mutable_state_sync_failed") from exc
    directories: list[Path] = []
    for entry in entries:
        try:
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(entry)
                continue
            flags = (
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor = os.open(entry, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or opened.st_dev != metadata.st_dev
                    or opened.st_ino != metadata.st_ino
                ):
                    raise ValueError("release_mutable_state_sync_failed")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("release_mutable_state_sync_failed") from exc
    for directory in reversed(directories):
        _fsync_directory(directory, "release_mutable_state_sync_failed")


def _validate_mutable_tree(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("release_mutable_state_invalid")
    try:
        entries = [path, *sorted(path.rglob("*"))]
    except OSError as exc:
        raise ValueError("release_mutable_state_invalid") from exc
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("release_mutable_state_symlink_unsupported")
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise ValueError("release_mutable_state_invalid") from exc
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise ValueError("release_mutable_state_hardlink_unsupported")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("release_mutable_state_entry_invalid")


def _remove_private_tree(path: Path) -> None:
    if not path.exists():
        if path.is_symlink():
            raise ValueError("release_private_remove_invalid")
        return
    _validate_mutable_tree(path)
    _secure_private_tree(path)
    try:
        shutil.rmtree(path)
        _fsync_directory(path.parent, "release_private_remove_sync_failed")
    except OSError as exc:
        raise ValueError("release_private_remove_failed") from exc


def _snapshot_id(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise ValueError("release_state_snapshot_id_invalid")
    return value


def _snapshot_root(home: Path) -> Path:
    root = home / _SNAPSHOT_DIRNAME
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("release_state_snapshot_root_invalid")
    root.mkdir(mode=_PRIVATE_DIRECTORY_MODE, exist_ok=True)
    _secure_directory(root, "release_state_snapshot_root_invalid")
    return root


def _snapshot_path(home: Path, snapshot_id: str) -> Path:
    return _snapshot_root(home) / _snapshot_id(snapshot_id)


def _copy_mutable_tree(source: Path, destination: Path) -> None:
    _validate_mutable_tree(source)
    if os.path.lexists(destination):
        raise ValueError("release_state_snapshot_destination_exists")
    try:
        if platform.system() == "Darwin":
            result = subprocess.run(
                ["/bin/cp", "-cR", "--", str(source), str(destination)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError("release_state_snapshot_clone_failed")
        else:
            shutil.copytree(source, destination, symlinks=True)
    except OSError as exc:
        raise ValueError("release_state_snapshot_clone_failed") from exc
    _validate_mutable_tree(destination)
    _secure_private_tree(destination)
    _fsync_private_tree(destination)


def _validate_state_snapshot(home: Path, snapshot_id: str) -> Path:
    snapshot = _snapshot_path(home, snapshot_id)
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("release_state_snapshot_missing")
    try:
        entries = {entry.name: entry for entry in snapshot.iterdir()}
    except OSError as exc:
        raise ValueError("release_state_snapshot_invalid") from exc
    if set(entries) != {"config", "data"}:
        raise ValueError("release_state_snapshot_invalid")
    _validate_mutable_tree(entries["config"])
    _validate_mutable_tree(entries["data"])
    return snapshot


def _snapshot_mutable_state(home: Path, snapshot_id: str) -> None:
    root = _snapshot_root(home)
    destination = root / _snapshot_id(snapshot_id)
    if os.path.lexists(destination):
        raise ValueError("release_state_snapshot_exists")
    staging = root / f".staging-{snapshot_id}"
    if os.path.lexists(staging):
        raise ValueError("release_state_snapshot_staging_exists")
    staging.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
    try:
        _copy_mutable_tree(home / "data", staging / "data")
        _copy_mutable_tree(home / "config", staging / "config")
        _secure_private_tree(staging)
        _fsync_directory(staging, "release_state_snapshot_sync_failed")
        os.replace(staging, destination)
        _fsync_directory(root, "release_state_snapshot_sync_failed")
    except Exception:
        if staging.exists() and not staging.is_symlink():
            _remove_private_tree(staging)
        raise


def _restore_mutable_state(home: Path, snapshot_id: str) -> None:
    snapshot = _validate_state_snapshot(home, snapshot_id)
    workspace = home / f".release-restore-{uuid.uuid4().hex}"
    workspace.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
    installed: list[str] = []
    moved_old: list[str] = []
    cleanup_workspace = False
    try:
        new_state = workspace / "new"
        new_state.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
        for name in ("data", "config"):
            _copy_mutable_tree(snapshot / name, new_state / name)
        for name in ("data", "config"):
            current = home / name
            old = workspace / f"old-{name}"
            os.replace(current, old)
            moved_old.append(name)
            os.replace(new_state / name, current)
            installed.append(name)
        _fsync_directory(home, "release_state_restore_sync_failed")
        cleanup_workspace = True
    except Exception as restore_error:
        try:
            for name in reversed(installed):
                _remove_private_tree(home / name)
                os.replace(workspace / f"old-{name}", home / name)
                moved_old.remove(name)
            for name in reversed(moved_old):
                os.replace(workspace / f"old-{name}", home / name)
            _fsync_directory(home, "release_state_restore_sync_failed")
            cleanup_workspace = True
        except Exception as rollback_error:
            raise ValueError(
                "release_state_restore_rollback_failed"
            ) from rollback_error
        raise ValueError("release_state_restore_failed") from restore_error
    finally:
        if cleanup_workspace and workspace.exists() and not workspace.is_symlink():
            _remove_private_tree(workspace)


def _discard_state_snapshot(home: Path, snapshot_id: str) -> None:
    root = _snapshot_root(home)
    snapshot = root / _snapshot_id(snapshot_id)
    _remove_private_tree(snapshot)
    try:
        root.rmdir()
    except OSError:
        pass


def _prune_orphan_state_snapshots_locked(
    home: Path,
    *,
    active_snapshot_id: str | None = None,
) -> int:
    root = home / _SNAPSHOT_DIRNAME
    if not root.exists():
        if root.is_symlink():
            raise ValueError("release_state_snapshot_root_invalid")
        return 0
    if root.is_symlink() or not root.is_dir():
        raise ValueError("release_state_snapshot_root_invalid")
    removed = 0
    for path in sorted(root.iterdir()):
        name = path.name
        snapshot_name = (
            name.removeprefix(".staging-") if name.startswith(".staging-") else name
        )
        _snapshot_id(snapshot_name)
        if not name.startswith(".staging-") and snapshot_name == active_snapshot_id:
            continue
        _remove_private_tree(path)
        removed += 1
    try:
        root.rmdir()
    except OSError:
        pass
    return removed


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_explicit_false(value: object) -> bool:
    return type(value) is bool and not value


def _is_explicit_true(value: object) -> bool:
    return type(value) is bool and value


def _checksum_for_archive(archive: Path, explicit: str | None) -> str:
    value = explicit
    sidecar = archive.with_name(archive.name + ".sha256")
    if value is None:
        if sidecar.is_symlink() or not sidecar.is_file():
            raise ValueError("release_archive_checksum_missing")
        fields = sidecar.read_text(encoding="utf-8").strip().split()
        if len(fields) != 2 or fields[1] != archive.name:
            raise ValueError("release_archive_checksum_file_invalid")
        value = fields[0]
    if _HEX_DIGEST.fullmatch(value or "") is None:
        raise ValueError("release_archive_checksum_invalid")
    if _sha256(archive) != value:
        raise ValueError("release_archive_checksum_mismatch")
    return value


def _safe_member_path(root: Path, member: tarfile.TarInfo) -> Path:
    name = member.name
    relative = Path(name)
    if (
        not name
        or "\x00" in name
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in name
    ):
        raise ValueError("release_archive_path_unsafe")
    destination = (root / relative).resolve()
    if destination != root and root not in destination.parents:
        raise ValueError("release_archive_path_escape")
    if (
        member.issym()
        or member.islnk()
        or member.isdev()
        or not (member.isdir() or member.isreg())
    ):
        raise ValueError("release_archive_member_unsupported")
    return destination


def _extract_archive(archive: Path, destination: Path) -> Path:
    """Extract a native archive without following archive-provided links."""
    from tools.release_artifact import validate_archive

    # Validate the complete archive in an isolated directory before placing
    # anything in the managed release tree. Extraction is repeated below only
    # after the archive has passed identity, payload, and link checks.
    validate_archive(archive)
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        roots = {Path(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise ValueError("release_archive_root_invalid")
        root_name = next(iter(roots))
        seen: set[str] = set()
        for member in members:
            target = _safe_member_path(destination, member)
            relative_name = target.relative_to(destination).as_posix()
            if relative_name in seen:
                raise ValueError("release_archive_duplicate_path")
            seen.add(relative_name)
            if member.isdir():
                if target.exists() and not target.is_dir():
                    raise ValueError("release_archive_path_conflict")
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("release_archive_duplicate_path")
            payload = source.extractfile(member)
            if payload is None:
                raise ValueError("release_archive_payload_missing")
            with target.open("xb") as output:
                shutil.copyfileobj(payload, output)
            target.chmod(member.mode & 0o777 or 0o600)
        extracted = destination / root_name
        if not extracted.is_dir():
            raise ValueError("release_archive_root_missing")
        return extracted


def _manifest_for(path: Path, *, expected_sha: str | None = None) -> dict[str, object]:
    from tools.release_artifact import validate_manifest

    if path.parent.name == RELEASES_DIRNAME and path.name.startswith("sha-"):
        directory_sha = path.name.removeprefix("sha-")
        if _FULL_SHA.fullmatch(directory_sha) is None:
            raise ValueError("release_directory_name_invalid")
        if expected_sha is not None and expected_sha != directory_sha:
            raise ValueError("release_directory_identity_mismatch")
        expected_sha = directory_sha
    return validate_manifest(path, expected_commit_sha=expected_sha)


def _read_pointer(path: Path) -> Path | None:
    if not path.is_symlink():
        if path.exists():
            raise ValueError(f"release_pointer_not_symlink:{path.name}")
        return None
    target = os.readlink(path)
    releases = (path.parent / RELEASES_DIRNAME).resolve()
    target_path = Path(target)
    if (
        target_path.is_absolute()
        or target_path.parts[:1] != (RELEASES_DIRNAME,)
        or len(target_path.parts) != 2
        or ".." in target_path.parts
        or "\\" in target
    ):
        raise ValueError(f"release_pointer_escape:{path.name}")
    target_path = path.parent / target_path
    resolved = target_path.resolve()
    if (
        target_path.is_symlink()
        or resolved.parent != releases
        or not resolved.name.startswith("sha-")
        or _FULL_SHA.fullmatch(resolved.name.removeprefix("sha-")) is None
    ):
        raise ValueError(f"release_pointer_escape:{path.name}")
    if not resolved.is_dir():
        raise ValueError(f"release_pointer_target_missing:{path.name}")
    return resolved


def _relative_release_target(home: Path, release: Path) -> str:
    return os.path.relpath(release, home)


def _replace_pointer(home: Path, name: str, target: Path | None) -> None:
    path = home / name
    if path.exists() and not path.is_symlink():
        raise ValueError(f"release_pointer_not_symlink:{name}")
    if target is None:
        path.unlink(missing_ok=True)
        _fsync_directory(home, "release_pointer_sync_failed")
        return
    releases = (home / RELEASES_DIRNAME).resolve()
    if target.is_symlink():
        raise ValueError(f"release_pointer_target_invalid:{name}")
    target = target.resolve()
    if (
        target.parent != releases
        or not target.name.startswith("sha-")
        or _FULL_SHA.fullmatch(target.name.removeprefix("sha-")) is None
        or not target.is_dir()
    ):
        raise ValueError(f"release_pointer_target_invalid:{name}")
    temporary = home / f".{name}.next-{uuid.uuid4().hex}"
    temporary.symlink_to(_relative_release_target(home, target))
    try:
        os.replace(temporary, path)
        _fsync_directory(home, "release_pointer_sync_failed")
    finally:
        temporary.unlink(missing_ok=True)


def _free_port() -> int:
    try:
        with socket.socket() as stream:
            stream.bind(("127.0.0.1", 0))
            return int(stream.getsockname()[1])
    except OSError as exc:
        raise ValueError("release_probe_port_unavailable") from exc


def _managed_release_sha(path: Path) -> str:
    for prefix in ("sha-", ".candidate-"):
        if path.name.startswith(prefix):
            return _require_sha(path.name.removeprefix(prefix))
    raise ValueError("release_managed_directory_name_invalid")


def _release_tree_entries(path: Path) -> list[Path]:
    if path.is_symlink() or not path.is_dir():
        raise ValueError("release_immutable_directory_invalid")
    try:
        entries = [path, *sorted(path.rglob("*"))]
    except OSError as exc:
        raise ValueError("release_immutable_tree_invalid") from exc
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("release_immutable_tree_symlink_unsupported")
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise ValueError("release_immutable_tree_invalid") from exc
        if stat.S_ISREG(metadata.st_mode):
            if metadata.st_nlink != 1:
                raise ValueError("release_immutable_tree_hardlink_unsupported")
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("release_immutable_tree_entry_invalid")
    return entries


def _fsync_release_tree(path: Path) -> None:
    """Make every immutable payload inode durable before pointer publication."""
    entries = _release_tree_entries(path)
    directories: list[Path] = []
    for entry in entries:
        try:
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(entry)
                continue
            flags = (
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            )
            descriptor = os.open(entry, flags)
            try:
                opened = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_nlink != 1
                    or opened.st_dev != metadata.st_dev
                    or opened.st_ino != metadata.st_ino
                ):
                    raise ValueError("release_immutable_tree_sync_failed")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("release_immutable_tree_sync_failed") from exc
    for directory in reversed(directories):
        _fsync_directory(directory, "release_immutable_tree_sync_failed")


def _seal_release_tree(path: Path, *, expected_sha: str) -> None:
    """Make a validated payload owner-readable/executable but not writable."""
    _manifest_for(path, expected_sha=expected_sha)
    entries = _release_tree_entries(path)
    try:
        for entry in entries:
            if entry.is_file():
                executable = bool(entry.stat(follow_symlinks=False).st_mode & 0o111)
                entry.chmod(0o555 if executable else 0o444)
        for entry in reversed(entries):
            if entry.is_dir():
                entry.chmod(0o555)
    except OSError as exc:
        raise ValueError("release_immutable_tree_seal_failed") from exc
    _manifest_for(path, expected_sha=expected_sha)
    _fsync_release_tree(path)


def _make_release_tree_removable(path: Path) -> None:
    """Re-enable owner writes only after validating one managed release tree."""
    sha = _managed_release_sha(path)
    _manifest_for(path, expected_sha=sha)
    entries = _release_tree_entries(path)
    try:
        for entry in entries:
            if entry.is_file():
                entry.chmod(_PRIVATE_FILE_MODE)
        for entry in reversed(entries):
            if entry.is_dir():
                entry.chmod(_PRIVATE_DIRECTORY_MODE)
    except OSError as exc:
        raise ValueError("release_remove_prepare_failed") from exc


def _remove_transient_tree(path: Path) -> None:
    """Idempotently remove one strictly named private staging/tombstone tree."""
    if not path.exists():
        if path.is_symlink():
            raise ValueError(f"release_remove_symlink_unsupported:{path.name}")
        return
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"release_remove_path_invalid:{path.name}")
    try:
        _secure_private_tree(path)
        shutil.rmtree(path)
        _fsync_directory(path.parent, "release_remove_sync_failed")
    except ValueError:
        raise
    except OSError as exc:
        raise ValueError(f"release_remove_failed:{path.name}") from exc


def _cleanup_release_transients_locked(home: Path) -> None:
    releases = _ensure_layout(home)
    for path in sorted(releases.iterdir()):
        if _STAGING_DIRECTORY.fullmatch(path.name) or _DELETING_DIRECTORY.fullmatch(
            path.name
        ):
            _remove_transient_tree(path)


def _remove_tree(path: Path) -> None:
    """Validate then atomically retire a managed release before recursive removal."""
    if not path.exists():
        if path.is_symlink():
            raise ValueError(f"release_remove_symlink_unsupported:{path.name}")
        return
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"release_remove_path_invalid:{path.name}")
    sha = _managed_release_sha(path)
    _manifest_for(path, expected_sha=sha)
    _release_tree_entries(path)
    kind = "candidate" if path.name.startswith(".candidate-") else "sha"
    tombstone = path.parent / f".deleting-{kind}-{sha}-{uuid.uuid4().hex}"
    try:
        os.replace(path, tombstone)
        _fsync_directory(path.parent, "release_remove_sync_failed")
    except OSError as exc:
        raise ValueError(f"release_remove_failed:{path.name}") from exc
    _remove_transient_tree(tombstone)


def _path_sha(path: Path | None) -> str | None:
    if path is None:
        return None
    name = path.name
    if not name.startswith("sha-"):
        raise ValueError("release_directory_name_invalid")
    return _require_sha(name.removeprefix("sha-"))


def _release_for_sha(home: Path, sha: str | None) -> Path | None:
    if sha is None:
        return None
    release = home / RELEASES_DIRNAME / f"sha-{_require_sha(sha)}"
    if release.is_symlink() or not release.is_dir():
        raise ValueError("release_transaction_target_missing")
    _manifest_for(release, expected_sha=sha)
    return release.resolve()


def _pointer_state(home: Path) -> tuple[Path | None, Path | None]:
    current = _read_pointer(home / "current")
    previous = _read_pointer(home / "previous")
    if current is None and previous is not None:
        raise ValueError("release_pointer_state_inconsistent")
    if current is not None:
        _manifest_for(current)
    if previous is not None:
        _manifest_for(previous)
    if current is not None and current == previous:
        raise ValueError("release_pointer_state_inconsistent")
    return current, previous


def _transaction_path(home: Path) -> Path:
    return home / _TRANSACTION_NAME


def _write_transaction_payload(
    home: Path,
    payload: dict[str, object],
    *,
    replace: bool,
) -> None:
    path = _transaction_path(home)
    if replace:
        if path.is_symlink() or not path.is_file():
            raise ValueError("release_transaction_invalid")
    elif os.path.lexists(path):
        raise ValueError("release_recovery_required")
    temporary = home / f".{_TRANSACTION_NAME}.next-{uuid.uuid4().hex}"
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
        _fsync_directory(home, "release_transaction_sync_failed")
    except OSError as exc:
        raise ValueError("release_transaction_write_failed") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _write_transaction(
    home: Path,
    *,
    operation: str,
    old_current: Path | None,
    old_previous: Path | None,
    target: Path,
) -> str:
    snapshot_id = uuid.uuid4().hex
    payload: dict[str, object] = {
        "schema_version": _TRANSACTION_SCHEMA,
        "operation": operation,
        "old_current": _path_sha(old_current),
        "old_previous": _path_sha(old_previous),
        "target": _path_sha(target),
        "snapshot_id": snapshot_id,
        "phase": "prepared",
    }
    _write_transaction_payload(home, payload, replace=False)
    return snapshot_id


def _read_transaction(home: Path) -> dict[str, object] | None:
    path = _transaction_path(home)
    if not path.exists():
        if path.is_symlink():
            raise ValueError("release_transaction_invalid")
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("release_transaction_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("release_transaction_invalid") from exc
    expected_keys = {
        "schema_version",
        "operation",
        "old_current",
        "old_previous",
        "target",
        "snapshot_id",
        "phase",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ValueError("release_transaction_invalid")
    if payload.get("schema_version") != _TRANSACTION_SCHEMA or payload.get(
        "operation"
    ) not in {"deploy", "rollback", "recover"}:
        raise ValueError("release_transaction_invalid")
    for key in ("old_current", "old_previous"):
        value = payload.get(key)
        if value is not None and (
            not isinstance(value, str) or _FULL_SHA.fullmatch(value) is None
        ):
            raise ValueError("release_transaction_invalid")
    target = payload.get("target")
    if not isinstance(target, str) or _FULL_SHA.fullmatch(target) is None:
        raise ValueError("release_transaction_invalid")
    if payload.get("old_current") is None and payload.get("old_previous") is not None:
        raise ValueError("release_transaction_invalid")
    snapshot_id = payload.get("snapshot_id")
    if not isinstance(snapshot_id, str):
        raise ValueError("release_transaction_invalid")
    _snapshot_id(snapshot_id)
    if payload.get("phase") not in {
        "prepared",
        "snapshotted",
        "switched",
        "readiness",
    }:
        raise ValueError("release_transaction_invalid")
    return payload


def _update_transaction_phase(home: Path, snapshot_id: str, phase: str) -> None:
    transitions = {
        "prepared": "snapshotted",
        "snapshotted": "switched",
        "switched": "readiness",
    }
    payload = _read_transaction(home)
    if payload is None or payload.get("snapshot_id") != snapshot_id:
        raise ValueError("release_transaction_invalid")
    current_phase = payload.get("phase")
    if not isinstance(current_phase, str) or transitions.get(current_phase) != phase:
        raise ValueError("release_transaction_phase_invalid")
    updated = dict(payload)
    updated["phase"] = phase
    _write_transaction_payload(home, updated, replace=True)


def _reset_transaction_readiness(home: Path, snapshot_id: str) -> None:
    """Close the scheduler gate again before restoring the old release."""
    payload = _read_transaction(home)
    if payload is None or payload.get("snapshot_id") != snapshot_id:
        raise ValueError("release_transaction_invalid")
    if payload.get("phase") != "readiness":
        return
    updated = dict(payload)
    updated["phase"] = "switched"
    _write_transaction_payload(home, updated, replace=True)


def _clear_transaction(home: Path) -> None:
    path = _transaction_path(home)
    if path.is_symlink():
        raise ValueError("release_transaction_invalid")
    path.unlink(missing_ok=True)
    _fsync_directory(home, "release_transaction_sync_failed")


def _require_clean_transaction_state_locked(home: Path) -> None:
    _cleanup_release_transients_locked(home)
    if _read_transaction(home) is not None:
        raise ValueError("release_recovery_required")
    _prune_orphan_state_snapshots_locked(home)


def _restore_pointers(home: Path, current: Path | None, previous: Path | None) -> None:
    _replace_pointer(home, "previous", previous)
    _replace_pointer(home, "current", current)


def _validate_release_inventory_locked(home: Path) -> None:
    releases = _ensure_layout(home)
    for path in sorted(releases.iterdir()):
        if path.is_symlink() or not path.is_dir():
            raise ValueError("release_inventory_entry_invalid")
        if path.name.startswith("sha-"):
            sha = _require_sha(path.name.removeprefix("sha-"))
        elif path.name.startswith(".candidate-"):
            sha = _require_sha(path.name.removeprefix(".candidate-"))
        else:
            raise ValueError("release_inventory_entry_invalid")
        _manifest_for(path, expected_sha=sha)
        _release_tree_entries(path)


def _prune_inactive_releases_locked(
    home: Path,
    *,
    include_candidates: bool,
) -> dict[str, int]:
    releases = _ensure_layout(home)
    current, previous = _pointer_state(home)
    keep: set[Path] = set()
    if current is not None:
        _seal_release_tree(current, expected_sha=_managed_release_sha(current))
        keep.add(current.resolve())
    if previous is not None:
        _seal_release_tree(previous, expected_sha=_managed_release_sha(previous))
        keep.add(previous.resolve())
    removable_releases: list[Path] = []
    removable_candidates: list[Path] = []
    for path in sorted(releases.iterdir()):
        if path.is_symlink() or not path.is_dir():
            raise ValueError("release_prune_entry_invalid")
        if path.name.startswith("sha-"):
            sha = path.name.removeprefix("sha-")
            _require_sha(sha)
            _manifest_for(path, expected_sha=sha)
            if path.resolve() not in keep:
                removable_releases.append(path)
            continue
        if path.name.startswith(".candidate-"):
            sha = path.name.removeprefix(".candidate-")
            _require_sha(sha)
            _manifest_for(path, expected_sha=sha)
            if include_candidates:
                removable_candidates.append(path)
            continue
        raise ValueError("release_prune_entry_invalid")
    for path in (*removable_releases, *removable_candidates):
        _remove_tree(path)
    return {
        "releases_removed": len(removable_releases),
        "candidates_removed": len(removable_candidates),
    }


def _require_health_timeout(timeout: object) -> int:
    if type(timeout) is not int or timeout < 1 or timeout > _MAX_HEALTH_TIMEOUT_SECONDS:
        raise ValueError("release_health_timeout_invalid")
    return timeout


def _require_exact_service_health(
    hooks: ReleaseServiceHooks,
    release: Path,
    manifest: dict[str, object],
    timeout: int,
) -> None:
    try:
        healthy = hooks.health(release, manifest, timeout)
    except Exception as exc:
        raise ValueError("release_service_health_failed") from exc
    if healthy is not True:
        raise ValueError("release_service_identity_mismatch")


def _stop_service(hooks: ReleaseServiceHooks) -> None:
    try:
        hooks.stop()
    except Exception as exc:
        raise ValueError("release_service_stop_failed") from exc


def _start_service(hooks: ReleaseServiceHooks, health_timeout: int) -> None:
    health_timeout = _require_health_timeout(health_timeout)
    try:
        hooks.start(health_timeout)
    except Exception as exc:
        raise ValueError("release_service_start_failed") from exc


def _quiesce_readiness_service(
    home: Path,
    *,
    snapshot_id: str,
    hooks: ReleaseServiceHooks,
) -> None:
    """Close the scheduler gate and stop the service without short-circuiting."""
    failures: list[Exception] = []
    try:
        _reset_transaction_readiness(home, snapshot_id)
    except Exception as exc:
        failures.append(exc)
    try:
        _stop_service(hooks)
    except Exception as exc:
        failures.append(exc)
    if failures:
        raise ValueError("release_activation_quiescence_failed") from failures[0]


def _advance_restored_transaction_to_switched(
    home: Path,
    *,
    snapshot_id: str,
) -> None:
    """Prepare the restored service for guarded start and readiness release."""
    payload = _read_transaction(home)
    if payload is None or payload.get("snapshot_id") != snapshot_id:
        raise ValueError("release_transaction_invalid")
    phase = payload.get("phase")
    if phase == "prepared":
        _validate_state_snapshot(home, snapshot_id)
        _update_transaction_phase(home, snapshot_id, "snapshotted")
        phase = "snapshotted"
    if phase == "snapshotted":
        _update_transaction_phase(home, snapshot_id, "switched")
        phase = "switched"
    if phase != "switched":
        raise ValueError("release_transaction_phase_invalid")


def _rollback_activation_locked(
    home: Path,
    *,
    old_current: Path | None,
    old_previous: Path | None,
    snapshot_id: str,
    snapshot_ready: bool,
    service_may_be_running: bool,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> None:
    """Restore the pre-transaction state or leave its journal for recovery."""
    restored_service_may_be_running = False
    try:
        if service_may_be_running:
            _quiesce_readiness_service(
                home,
                snapshot_id=snapshot_id,
                hooks=hooks,
            )
        if not snapshot_ready and old_current is not None:
            _snapshot_mutable_state(home, snapshot_id)
            snapshot_ready = True
        if snapshot_ready:
            snapshot = _validate_state_snapshot(home, snapshot_id)
            if old_current is not None:
                old_manifest = _manifest_for(old_current)
                _probe_state_compatibility(
                    old_current, old_manifest, snapshot, health_timeout
                )
            _restore_mutable_state(home, snapshot_id)
        _restore_pointers(home, old_current, old_previous)
        if old_current is not None:
            _advance_restored_transaction_to_switched(
                home,
                snapshot_id=snapshot_id,
            )
            old_manifest = _manifest_for(old_current)
            restored_service_may_be_running = True
            _start_service(hooks, health_timeout)
            _require_exact_service_health(
                hooks, old_current, old_manifest, health_timeout
            )
            _update_transaction_phase(home, snapshot_id, "readiness")
            _require_exact_service_health(
                hooks, old_current, old_manifest, health_timeout
            )
        _clear_transaction(home)
        try:
            _discard_state_snapshot(home, snapshot_id)
        except ValueError:
            pass
    except Exception as exc:
        if restored_service_may_be_running:
            try:
                _quiesce_readiness_service(
                    home,
                    snapshot_id=snapshot_id,
                    hooks=hooks,
                )
                if snapshot_ready:
                    _restore_mutable_state(home, snapshot_id)
            except Exception as cleanup_error:
                raise ValueError(
                    "release_activation_rollback_failed"
                ) from cleanup_error
        raise ValueError("release_activation_rollback_failed") from exc


def _activate_locked(
    home: Path,
    *,
    operation: str,
    target: Path,
    target_manifest: dict[str, object],
    old_current: Path | None,
    old_previous: Path | None,
    new_previous: Path | None,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> None:
    """Run one journaled stop/switch/start/exact-health transaction."""
    snapshot_id = _write_transaction(
        home,
        operation=operation,
        old_current=old_current,
        old_previous=old_previous,
        target=target,
    )
    try:
        _stop_service(hooks)
    except Exception:
        # A failed stop has unknown process state. Do not change pointers or
        # start a second process; the durable journal makes recovery explicit.
        raise

    service_may_be_running = False
    snapshot_ready = False
    try:
        _snapshot_mutable_state(home, snapshot_id)
        snapshot_ready = True
        _update_transaction_phase(home, snapshot_id, "snapshotted")
        snapshot = _validate_state_snapshot(home, snapshot_id)
        _probe_state_compatibility(target, target_manifest, snapshot, health_timeout)
        _replace_pointer(home, "previous", new_previous)
        _replace_pointer(home, "current", target)
        _update_transaction_phase(home, snapshot_id, "switched")
        service_may_be_running = True
        _start_service(hooks, health_timeout)
        _require_exact_service_health(hooks, target, target_manifest, health_timeout)
        _update_transaction_phase(home, snapshot_id, "readiness")
        _require_exact_service_health(hooks, target, target_manifest, health_timeout)
    except Exception as activation_error:
        try:
            _rollback_activation_locked(
                home,
                old_current=old_current,
                old_previous=old_previous,
                snapshot_id=snapshot_id,
                snapshot_ready=snapshot_ready,
                service_may_be_running=service_may_be_running,
                health_timeout=health_timeout,
                hooks=hooks,
            )
        except ValueError as rollback_error:
            raise rollback_error from activation_error
        raise ValueError("release_activation_failed_rolled_back") from activation_error
    _clear_transaction(home)
    try:
        _discard_state_snapshot(home, snapshot_id)
    except ValueError:
        pass


def _probe_json(path: str, port: int) -> object:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("release_probe_http_status_unexpected")
        return json.loads(response.read())
    finally:
        connection.close()


def _health_payload_matches(
    payload: object,
    live: object,
    manifest: dict[str, object],
    *,
    expected_activation_guarded: bool,
    expected_scheduler_activation_guarded: bool | None = None,
    minimum_completed_iterations: int | None = None,
) -> bool:
    base_matches = (
        isinstance(payload, dict)
        and isinstance(live, dict)
        and payload.get("schema_version") == "karkinos.service_health.v1"
        and payload.get("status") == "alive"
        and payload.get("service") == "karkinos"
        and payload.get("scope") == "process_liveness_only"
        and payload.get("version") == manifest.get("version")
        and payload.get("release_sha") == manifest.get("commit_sha")
        and payload.get("artifact_fingerprint") == manifest.get("payload_fingerprint")
        and _is_explicit_false(payload.get("financial_readiness_claimed"))
        and _is_explicit_false(payload.get("provider_contacted"))
        and _is_explicit_false(payload.get("database_reads_performed"))
        and _is_explicit_false(payload.get("database_writes_performed"))
        and _is_explicit_false(payload.get("broker_submission_enabled"))
        and _is_explicit_false(payload.get("broker_cancellation_enabled"))
        and _is_explicit_false(payload.get("production_ledger_mutated"))
        and _is_explicit_false(payload.get("capital_authority_changed"))
        and _is_explicit_false(payload.get("authorizes_execution"))
        and _is_explicit_true(live.get("running"))
        and _is_explicit_true(live.get("initialized"))
        and live.get("activation_guarded") is expected_activation_guarded
    )
    if not base_matches or not isinstance(live, dict):
        return False
    if (
        expected_scheduler_activation_guarded is not None
        and live.get("scheduler_activation_guarded")
        is not expected_scheduler_activation_guarded
    ):
        return False
    if minimum_completed_iterations is not None:
        completed = live.get("completed_iterations")
        if (
            not isinstance(completed, int)
            or isinstance(completed, bool)
            or completed < minimum_completed_iterations
        ):
            return False
    return True


def _activation_guard_expected(home: Path) -> bool:
    for name in (_TRANSACTION_NAME, _LEGACY_BOOTSTRAP_TRANSACTION_NAME):
        path = home / name
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("release_activation_guard_unreadable") from exc
        return True
    return False


def _service_health_expectations(
    home: Path,
) -> tuple[bool, bool | None, int | None]:
    activation_guarded = _activation_guard_expected(home)
    transaction = _read_transaction(home)
    legacy_phase = _legacy_bootstrap_phase(home)
    if transaction is not None and legacy_phase is not None:
        raise ValueError("release_activation_guard_ambiguous")
    if transaction is not None and transaction.get("phase") == "readiness":
        return True, False, 1
    if transaction is not None:
        return True, True, None
    if legacy_phase == "readiness":
        return True, False, 1
    if legacy_phase is not None:
        return True, True, None
    return activation_guarded, None, None


def _legacy_bootstrap_phase(home: Path) -> str | None:
    path = home / _LEGACY_BOOTSTRAP_TRANSACTION_NAME
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("release_activation_guard_unreadable") from exc
    from scripts.release import bootstrap_legacy

    journal = bootstrap_legacy._read_journal(home)
    if journal is None or not isinstance(journal.get("phase"), str):
        raise ValueError("release_activation_guard_unreadable")
    return str(journal["phase"])


def _wait_for_service_identity(
    _release: Path,
    manifest: dict[str, object],
    timeout: int,
    *,
    port: int,
    expected_activation_guarded: bool,
    expected_scheduler_activation_guarded: bool | None = None,
    minimum_completed_iterations: int | None = None,
) -> bool:
    timeout = _require_health_timeout(timeout)
    if port < 1 or port > 65535:
        raise ValueError("release_service_port_invalid")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _health_payload_matches(
                _probe_json("/api/health", port),
                _probe_json("/api/settings/live/status", port),
                manifest,
                expected_activation_guarded=expected_activation_guarded,
                expected_scheduler_activation_guarded=(
                    expected_scheduler_activation_guarded
                ),
                minimum_completed_iterations=minimum_completed_iterations,
            ):
                return True
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.2)
    return False


def _service_manager_hooks(
    home: Path, path: Path, *, port: int | None
) -> ReleaseServiceHooks:
    managed_home = home.expanduser().absolute()
    manager = path.expanduser().absolute()
    if (
        not manager.is_absolute()
        or manager.is_symlink()
        or not manager.is_file()
        or not os.access(manager, os.X_OK)
    ):
        raise ValueError("release_service_manager_invalid")

    def invoke(command: str, error: str, *, health_timeout: int | None = None) -> None:
        capability = _ACTIVE_RELEASE_LOCKS.get(str(managed_home))
        if capability is None or capability[0] != os.getpid():
            raise ValueError("release_service_lock_capability_missing")
        owner_pid, nonce = capability
        configured_port = _configured_or_explicit_service_port_locked(
            managed_home, port
        )
        environment = os.environ.copy()
        environment.update(
            {
                "KARKINOS_HOME": str(managed_home),
                "KARKINOS_RELEASE_LOCK_OWNER_PID": str(owner_pid),
                "KARKINOS_RELEASE_LOCK_NONCE": nonce,
                "KARKINOS_BACKEND_PORT": str(configured_port),
            }
        )
        if health_timeout is not None:
            environment["KARKINOS_LAUNCH_AGENT_HEALTH_TIMEOUT_SECONDS"] = str(
                _require_health_timeout(health_timeout)
            )
        try:
            result = subprocess.run(
                [str(manager), command],
                check=False,
                env=environment,
            )
        except OSError as exc:
            raise ValueError(error) from exc
        if result.returncode != 0:
            raise ValueError(error)

    def health(
        release: Path,
        manifest: dict[str, object],
        timeout: int,
    ) -> bool:
        configured_port = _configured_or_explicit_service_port_locked(
            managed_home, port
        )
        (
            expected_activation_guarded,
            expected_scheduler_activation_guarded,
            minimum_completed_iterations,
        ) = _service_health_expectations(managed_home)
        return _wait_for_service_identity(
            release,
            manifest,
            timeout,
            port=configured_port,
            expected_activation_guarded=expected_activation_guarded,
            expected_scheduler_activation_guarded=(
                expected_scheduler_activation_guarded
            ),
            minimum_completed_iterations=minimum_completed_iterations,
        )

    return ReleaseServiceHooks(
        stop=lambda: invoke("uninstall", "release_service_stop_failed"),
        start=lambda timeout: invoke(
            "install", "release_service_start_failed", health_timeout=timeout
        ),
        health=health,
    )


def _service_manager_ready(home: Path, path: Path, *, port: int) -> bool:
    manager = path.expanduser().absolute()
    if (
        not manager.is_absolute()
        or manager.is_symlink()
        or not manager.is_file()
        or not os.access(manager, os.X_OK)
    ):
        raise ValueError("release_service_manager_invalid")
    environment = os.environ.copy()
    environment.update(
        {
            "KARKINOS_HOME": str(home.expanduser().absolute()),
            "KARKINOS_BACKEND_PORT": str(_validated_service_port(port)),
        }
    )
    try:
        result = subprocess.run(
            [str(manager), "status"],
            check=False,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _probe_release(
    home: Path, release: Path, manifest: dict[str, object], timeout: int
) -> None:
    """Start the candidate against disposable state and require its identity."""
    timeout = _require_health_timeout(timeout)
    entrypoint = release / "bin" / "karkinos"
    try:
        usable = entrypoint.is_file() and os.access(entrypoint, os.X_OK)
    except OSError as exc:
        raise ValueError("release_entrypoint_unusable") from exc
    if not usable:
        raise ValueError("release_entrypoint_unusable")
    with tempfile.TemporaryDirectory(prefix="karkinos-release-probe-") as temporary:
        runtime = Path(temporary)
        probe_home = runtime / "home"
        config = probe_home / "config" / "config.json"
        env_file = probe_home / "config" / ".env"
        data = probe_home / "data"
        for path in (probe_home, config.parent, data, probe_home / "logs"):
            path.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
            _secure_directory(path, "release_probe_state_invalid")
        _write_private_text(config, "{}\n")
        _write_private_text(env_file, "\n")
        port = _free_port()
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if key in os.environ
        }
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "KARKINOS_HOME": str(probe_home),
                "KARKINOS_DATA_DIR": str(data),
                "KARKINOS_CONFIG_PATH": str(config),
                "KARKINOS_ENV_FILE": str(env_file),
                "KARKINOS_HOST": "127.0.0.1",
                "KARKINOS_PORT": str(port),
                "KARKINOS_AI_ENABLED": "false",
                "KARKINOS_RELEASE_SHA": str(manifest["commit_sha"]),
                "KARKINOS_ARTIFACT_FINGERPRINT": str(manifest["payload_fingerprint"]),
            }
        )
        process = subprocess.Popen(
            [str(entrypoint), "--host", "127.0.0.1", "--port", str(port)],
            cwd=release / "app",
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        healthy = False
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    payload = _probe_json("/api/health", port)
                    live = _probe_json("/api/settings/live/status", port)
                    if not isinstance(payload, dict) or not isinstance(live, dict):
                        raise ValueError("release_probe_payload_invalid")
                    healthy = _health_payload_matches(
                        payload,
                        live,
                        manifest,
                        expected_activation_guarded=False,
                    )
                    if healthy:
                        break
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                time.sleep(0.2)
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not healthy:
            raise ValueError("release_health_probe_failed")


def _probe_state_compatibility(
    release: Path,
    manifest: dict[str, object],
    snapshot: Path,
    timeout: int,
) -> None:
    """Run the target's provider-free state checker on an APFS clone."""
    timeout = _require_health_timeout(timeout)
    entrypoint = release / "bin" / "karkinos"
    if (
        entrypoint.is_symlink()
        or not entrypoint.is_file()
        or not os.access(entrypoint, os.X_OK)
    ):
        raise ValueError("release_state_preflight_runtime_invalid")
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("release_state_snapshot_invalid")
    with tempfile.TemporaryDirectory(prefix="karkinos-state-preflight-") as temporary:
        root = Path(temporary)
        data = root / "data"
        config = root / "config"
        _copy_mutable_tree(snapshot / "data", data)
        _copy_mutable_tree(snapshot / "config", config)
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
            if key in os.environ
        }
        environment.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "KARKINOS_HOME": str(root),
                "KARKINOS_DATA_DIR": str(data),
                "KARKINOS_CONFIG_PATH": str(config / "config.json"),
                "KARKINOS_ENV_FILE": str(config / ".env"),
                "KARKINOS_AI_ENABLED": "false",
                "KARKINOS_RELEASE_SHA": str(manifest["commit_sha"]),
                "KARKINOS_ARTIFACT_FINGERPRINT": str(manifest["payload_fingerprint"]),
            }
        )
        try:
            result = subprocess.run(
                [str(entrypoint), "--check-state"],
                cwd=release / "app",
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("release_state_compatibility_preflight_failed") from exc
        if result.returncode != 0:
            raise ValueError("release_state_compatibility_preflight_failed")


def _stage(home: Path, archive: Path, expected_sha: str, checksum: str | None) -> Path:
    releases = _ensure_layout(home)
    _require_sha(expected_sha)
    archive = archive.expanduser().absolute()
    if archive.is_symlink() or not archive.is_file():
        raise ValueError("release_archive_invalid")
    expected_checksum = _checksum_for_archive(archive, checksum)
    candidate = releases / f".candidate-{expected_sha}"
    if os.path.lexists(candidate) and candidate.is_symlink():
        raise ValueError("release_candidate_symlink_unsupported")
    staging = releases / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        archive_snapshot = staging / ".candidate-input.tar.gz"
        with archive.open("rb") as source, archive_snapshot.open("xb") as target:
            shutil.copyfileobj(source, target)
        if _sha256(archive_snapshot) != expected_checksum:
            raise ValueError("release_archive_checksum_mismatch")
        architecture = _architecture()
        incoming_manifest = _extract_archive_manifest(
            archive_snapshot,
            expected_sha=expected_sha,
            expected_architecture=architecture,
        )
        if candidate.exists():
            existing_manifest = _manifest_for(candidate, expected_sha=expected_sha)
            if incoming_manifest == existing_manifest:
                _seal_release_tree(candidate, expected_sha=expected_sha)
                return candidate
            raise ValueError("release_candidate_conflict")
        extracted = _extract_archive(archive_snapshot, staging)
        manifest = _manifest_for(extracted, expected_sha=expected_sha)
        if manifest != incoming_manifest:
            raise ValueError("release_archive_validation_drift")
        try:
            _fsync_release_tree(extracted)
            os.replace(extracted, candidate)
            _seal_release_tree(candidate, expected_sha=expected_sha)
            _fsync_directory(releases, "release_candidate_sync_failed")
        except Exception:
            _remove_tree(candidate)
            raise
        return candidate
    finally:
        _remove_transient_tree(staging)


def _extract_archive_manifest(
    archive: Path,
    *,
    expected_sha: str,
    expected_architecture: str,
) -> dict[str, object]:
    from tools.release_artifact import validate_archive

    return validate_archive(
        archive,
        expected_commit_sha=expected_sha,
        expected_architecture=expected_architecture,
    )


def _validate_candidate(home: Path, sha: str) -> tuple[Path, dict[str, object]]:
    candidate = _ensure_layout(home) / f".candidate-{_require_sha(sha)}"
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("release_candidate_missing")
    manifest = _manifest_for(candidate, expected_sha=sha)
    _seal_release_tree(candidate, expected_sha=sha)
    return candidate, manifest


def _stage_verified_candidate(home: Path, archive: Path, commit_sha: str) -> Path:
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        return _stage(home, archive, commit_sha, None)


def _discard_inactive_candidate(home: Path, commit_sha: str) -> dict[str, object]:
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        bootstrap_journal = home / ".legacy-bootstrap-transaction.json"
        if bootstrap_journal.exists() or bootstrap_journal.is_symlink():
            raise ValueError("legacy_bootstrap_recovery_required")
        candidate_path = _ensure_layout(home) / f".candidate-{_require_sha(commit_sha)}"
        if not os.path.lexists(candidate_path):
            return {"status": "already_discarded", "commit_sha": commit_sha}
        candidate, _manifest = _validate_candidate(home, commit_sha)
        current = _read_pointer(home / "current")
        previous = _read_pointer(home / "previous")
        if current == candidate or previous == candidate:
            raise ValueError("release_candidate_is_active")
        _remove_tree(candidate)
        return {"status": "discarded", "commit_sha": commit_sha}


def stage(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        candidate = _stage(home, Path(args.archive), args.commit_sha, args.sha256)
    print(json.dumps({"status": "staged", "candidate": str(candidate)}, sort_keys=True))


def discard(home: Path, args: argparse.Namespace) -> None:
    print(
        json.dumps(_discard_inactive_candidate(home, args.commit_sha), sort_keys=True)
    )


def deploy_release(
    home: Path,
    *,
    commit_sha: str,
    confirmation: str,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> dict[str, object]:
    """Activate a staged candidate and retain exactly one rollback release."""
    commit_sha = _require_sha(commit_sha)
    required_confirmation = f"PROMOTE {commit_sha}"
    if confirmation != required_confirmation:
        raise ValueError(f"release_confirmation_required:{required_confirmation}")
    health_timeout = _require_health_timeout(health_timeout)
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        releases = _ensure_layout(home)
        current, previous = _pointer_state(home)
        for installed in (current, previous):
            if installed is not None:
                _seal_release_tree(
                    installed, expected_sha=_managed_release_sha(installed)
                )
        final = releases / f"sha-{commit_sha}"
        if final.is_symlink():
            raise ValueError("release_immutable_directory_symlink_unsupported")
        if current == final:
            manifest = _manifest_for(final, expected_sha=commit_sha)
            pruned = _prune_inactive_releases_locked(home, include_candidates=True)
            return {
                "status": "already_promoted",
                "current": manifest["commit_sha"],
                "previous": _path_sha(previous),
                **pruned,
            }
        candidate, candidate_manifest = _validate_candidate(home, commit_sha)
        final_existed = final.is_dir()
        if final_existed:
            final_manifest = _manifest_for(final, expected_sha=commit_sha)
            if final_manifest != candidate_manifest:
                raise ValueError("release_immutable_directory_conflict")
            _seal_release_tree(final, expected_sha=commit_sha)
        elif final.exists():
            raise ValueError("release_immutable_directory_invalid")

        # Candidate execution and stable activation are distinct boundaries.
        # The disposable probe never points ``current`` at candidate state.
        _probe_release(home, candidate, candidate_manifest, health_timeout)
        if not final_existed:
            os.replace(candidate, final)
            _fsync_directory(releases, "release_final_sync_failed")
        try:
            _validate_release_inventory_locked(home)
            _activate_locked(
                home,
                operation="deploy",
                target=final,
                target_manifest=candidate_manifest,
                old_current=current,
                old_previous=previous,
                new_previous=current,
                health_timeout=health_timeout,
                hooks=hooks,
            )
        except Exception:
            # Only restore the staged name once the rollback transaction was
            # conclusively completed. A retained journal must keep its target.
            # This cleanup is best-effort: its failure must not replace the
            # activation error that explains why promotion failed.
            try:
                pointer_current, pointer_previous = _pointer_state(home)
                if (
                    not final_existed
                    and _read_transaction(home) is None
                    and pointer_current == current
                    and pointer_previous == previous
                    and final.is_dir()
                    and not final.is_symlink()
                ):
                    os.replace(final, candidate)
                    _fsync_directory(releases, "release_candidate_sync_failed")
            except BaseException:
                pass
            raise
        pruned = _prune_inactive_releases_locked(home, include_candidates=True)
        return {
            "status": "promoted",
            "current": commit_sha,
            "previous": _path_sha(current),
            **pruned,
        }


def promote(home: Path, args: argparse.Namespace) -> None:
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    result = deploy_release(
        home,
        commit_sha=args.commit_sha,
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
        hooks=hooks,
    )
    print(json.dumps(result, sort_keys=True))


def rollback_release(
    home: Path,
    *,
    confirmation: str,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> dict[str, object]:
    """Atomically swap stable current/previous through the service manager."""
    health_timeout = _require_health_timeout(health_timeout)
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        current, previous = _pointer_state(home)
        if current is None:
            raise ValueError("release_current_missing")
        if previous is None:
            raise ValueError("release_previous_missing")
        current_manifest = _manifest_for(current)
        previous_manifest = _manifest_for(previous)
        _seal_release_tree(current, expected_sha=str(current_manifest["commit_sha"]))
        _seal_release_tree(previous, expected_sha=str(previous_manifest["commit_sha"]))
        required_confirmation = f"ROLLBACK {previous_manifest['commit_sha']}"
        if confirmation != required_confirmation:
            raise ValueError(f"release_confirmation_required:{required_confirmation}")
        _validate_release_inventory_locked(home)
        _probe_release(home, previous, previous_manifest, health_timeout)
        _activate_locked(
            home,
            operation="rollback",
            target=previous,
            target_manifest=previous_manifest,
            old_current=current,
            old_previous=previous,
            new_previous=current,
            health_timeout=health_timeout,
            hooks=hooks,
        )
        pruned = _prune_inactive_releases_locked(home, include_candidates=True)
        return {
            "status": "rolled_back",
            "current": previous_manifest["commit_sha"],
            "previous": current_manifest["commit_sha"],
            **pruned,
        }


def rollback(home: Path, args: argparse.Namespace) -> None:
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    result = rollback_release(
        home,
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
        hooks=hooks,
    )
    print(json.dumps(result, sort_keys=True))


def recover_release_state(
    home: Path,
    *,
    confirmation: str,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> dict[str, object]:
    """Recover only a journaled or mechanically unambiguous pointer state."""
    if confirmation != _RECOVERY_CONFIRMATION:
        raise ValueError(f"release_confirmation_required:{_RECOVERY_CONFIRMATION}")
    health_timeout = _require_health_timeout(health_timeout)
    with _lock(home):
        _cleanup_release_transients_locked(home)
        journal = _read_transaction(home)
        if journal is not None:
            active_snapshot_id = journal.get("snapshot_id")
            if not isinstance(active_snapshot_id, str):
                raise ValueError("release_transaction_invalid")
            _prune_orphan_state_snapshots_locked(
                home, active_snapshot_id=_snapshot_id(active_snapshot_id)
            )
            _release_for_sha(home, journal.get("target"))  # type: ignore[arg-type]
            desired_current = _release_for_sha(
                home, journal.get("old_current")  # type: ignore[arg-type]
            )
            desired_previous = _release_for_sha(
                home, journal.get("old_previous")  # type: ignore[arg-type]
            )
            recovery_kind = "journal"
        else:
            _prune_orphan_state_snapshots_locked(home)
            current = _read_pointer(home / "current")
            previous = _read_pointer(home / "previous")
            if current is None and previous is not None:
                desired_current, desired_previous = previous, None
                recovery_kind = "missing_current"
            elif current is not None and current == previous:
                desired_current, desired_previous = current, None
                recovery_kind = "duplicate_pointer"
            else:
                desired_current, desired_previous = current, previous
                recovery_kind = "verified"
            if desired_current is not None:
                snapshot_id = _write_transaction(
                    home,
                    operation="recover",
                    old_current=desired_current,
                    old_previous=desired_previous,
                    target=desired_current,
                )
                journal = _read_transaction(home)
                if journal is None:
                    raise ValueError("release_transaction_invalid")
        if desired_current is not None and desired_current == desired_previous:
            raise ValueError("release_recovery_state_invalid")
        for desired_release in (desired_current, desired_previous):
            if desired_release is not None:
                desired_manifest = _manifest_for(desired_release)
                _seal_release_tree(
                    desired_release,
                    expected_sha=str(desired_manifest["commit_sha"]),
                )
        _validate_release_inventory_locked(home)

        raw_snapshot_id: object | None = None
        phase: object | None = None
        if journal is not None:
            raw_snapshot_id = journal.get("snapshot_id")
            phase = journal.get("phase")
            if not isinstance(raw_snapshot_id, str) or not isinstance(phase, str):
                raise ValueError("release_transaction_invalid")
            _quiesce_readiness_service(
                home,
                snapshot_id=_snapshot_id(raw_snapshot_id),
                hooks=hooks,
            )
        else:
            # A successful stop is required even if recovery will leave an
            # empty installation. This prevents moving pointers beneath a live
            # process.
            _stop_service(hooks)
        if journal is None:
            _restore_pointers(home, desired_current, desired_previous)
            pruned = _prune_inactive_releases_locked(home, include_candidates=True)
            return {
                "status": "recovered",
                "recovery_kind": recovery_kind,
                "current": None,
                "previous": None,
                **pruned,
            }

        if not isinstance(raw_snapshot_id, str) or not isinstance(phase, str):
            raise ValueError("release_transaction_invalid")
        snapshot_id = _snapshot_id(raw_snapshot_id)
        snapshot_ready = phase in {"snapshotted", "switched", "readiness"}
        restore_existing_snapshot = snapshot_ready
        if phase == "readiness":
            phase = "switched"
        try:
            if snapshot_ready:
                snapshot = _validate_state_snapshot(home, snapshot_id)
            else:
                snapshot_path = _snapshot_root(home) / snapshot_id
                if snapshot_path.exists():
                    snapshot = _validate_state_snapshot(home, snapshot_id)
                else:
                    _snapshot_mutable_state(home, snapshot_id)
                    snapshot = _validate_state_snapshot(home, snapshot_id)
                snapshot_ready = True
                _update_transaction_phase(home, snapshot_id, "snapshotted")
            if desired_current is not None:
                desired_manifest = _manifest_for(desired_current)
                _probe_state_compatibility(
                    desired_current, desired_manifest, snapshot, health_timeout
                )
            if restore_existing_snapshot:
                _restore_mutable_state(home, snapshot_id)
            _restore_pointers(home, desired_current, desired_previous)
            if phase != "switched":
                _update_transaction_phase(home, snapshot_id, "switched")
        except Exception as exc:
            if snapshot_ready:
                try:
                    _restore_mutable_state(home, snapshot_id)
                except ValueError:
                    pass
            raise ValueError("release_recovery_failed") from exc

        service_may_be_running = False
        try:
            if desired_current is not None:
                desired_manifest = _manifest_for(desired_current)
                service_may_be_running = True
                _start_service(hooks, health_timeout)
                _require_exact_service_health(
                    hooks, desired_current, desired_manifest, health_timeout
                )
                _update_transaction_phase(home, snapshot_id, "readiness")
                _require_exact_service_health(
                    hooks, desired_current, desired_manifest, health_timeout
                )
        except Exception as exc:
            if service_may_be_running:
                try:
                    _quiesce_readiness_service(
                        home,
                        snapshot_id=snapshot_id,
                        hooks=hooks,
                    )
                    _restore_mutable_state(home, snapshot_id)
                except Exception as cleanup_error:
                    raise ValueError("release_recovery_failed") from cleanup_error
            # Keep a journal, when present, until exact recovery is proven.
            raise ValueError("release_recovery_failed") from exc
        _clear_transaction(home)
        try:
            _discard_state_snapshot(home, snapshot_id)
        except ValueError:
            pass
        pruned = _prune_inactive_releases_locked(home, include_candidates=True)
        return {
            "status": "recovered",
            "recovery_kind": recovery_kind,
            "current": _path_sha(desired_current),
            "previous": _path_sha(desired_previous),
            **pruned,
        }


def recover(home: Path, args: argparse.Namespace) -> None:
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    result = recover_release_state(
        home,
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
        hooks=hooks,
    )
    print(json.dumps(result, sort_keys=True))


def prune_releases(
    home: Path,
    *,
    confirmation: str,
) -> dict[str, object]:
    required_confirmation = "PRUNE INACTIVE RELEASES"
    if confirmation != required_confirmation:
        raise ValueError(f"release_confirmation_required:{required_confirmation}")
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        removed = _prune_inactive_releases_locked(home, include_candidates=True)
        current, previous = _pointer_state(home)
        return {
            "status": "pruned",
            "current": _path_sha(current),
            "previous": _path_sha(previous),
            **removed,
        }


def prune(home: Path, args: argparse.Namespace) -> None:
    print(json.dumps(prune_releases(home, confirmation=args.confirm), sort_keys=True))


def _absolute_source(path: Path) -> Path:
    source = Path(os.path.abspath(os.fspath(path.expanduser())))
    for candidate in (source, *source.parents):
        if candidate.is_symlink():
            raise ValueError("release_legacy_source_symlink_unsupported")
        if candidate.parent == candidate:
            break
    return source


def _validate_private_source_tree(source: Path) -> list[Path]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("release_legacy_data_invalid")
    entries = sorted(source.rglob("*"))
    if not entries:
        raise ValueError("release_legacy_data_empty")
    for entry in entries:
        if entry.is_symlink():
            raise ValueError("release_legacy_source_symlink_unsupported")
        if not entry.is_dir() and not entry.is_file():
            raise ValueError("release_legacy_data_entry_invalid")
    return entries


def _require_same_filesystem(source: Path, destination_parent: Path) -> None:
    try:
        if (
            source.stat(follow_symlinks=False).st_dev
            != destination_parent.stat(follow_symlinks=False).st_dev
        ):
            raise ValueError("release_legacy_cross_filesystem_unsupported")
    except OSError as exc:
        raise ValueError("release_legacy_filesystem_check_failed") from exc


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _prepare_legacy_adoption(
    home: Path,
    *,
    legacy_shared: Path,
    legacy_data: Path,
) -> tuple[list[tuple[Path, Path]], tuple[Path, Path]]:
    shared = _absolute_source(legacy_shared)
    data_source = _absolute_source(legacy_data)
    if _paths_overlap(shared, data_source):
        raise ValueError("release_legacy_source_overlap")
    if shared.is_symlink() or not shared.is_dir():
        raise ValueError("release_legacy_shared_invalid")
    shared_entries = sorted(shared.iterdir())
    if not shared_entries or any(
        entry.name not in _LEGACY_CONFIG_NAMES for entry in shared_entries
    ):
        raise ValueError("release_legacy_shared_contents_invalid")
    for entry in shared_entries:
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("release_legacy_shared_contents_invalid")
    _validate_private_source_tree(data_source)

    managed_paths = (
        home / "releases",
        home / "data",
        home / "config",
        home / "logs",
    )
    if any(_paths_overlap(data_source, path) for path in managed_paths) or any(
        _paths_overlap(shared, path) for path in managed_paths
    ):
        raise ValueError("release_legacy_source_overlap")

    config_destination = home / "config"
    data_destination_root = home / "data"
    if any(config_destination.iterdir()) or any(data_destination_root.iterdir()):
        raise ValueError("release_legacy_destination_not_empty")
    config_moves = [
        (entry, config_destination / entry.name) for entry in shared_entries
    ]
    # ``legacy_data`` is the data root itself. In the known source checkout
    # layout callers pass ``data/store`` so app.db/meta.db land directly under
    # ``${KARKINOS_HOME}/data``; the Python package directory is never moved.
    data_move = (data_source, data_destination_root)
    for source, _destination in config_moves:
        _require_same_filesystem(source, config_destination)
    _require_same_filesystem(data_source, home)
    return config_moves, data_move


def _reverse_moves(
    moves: list[tuple[Path, Path]],
    *,
    recreate_data_root: Path | None,
) -> None:
    try:
        for source, destination in reversed(moves):
            if destination.is_symlink() or not destination.exists():
                raise ValueError("release_legacy_move_rollback_failed")
            if os.path.lexists(source):
                raise ValueError("release_legacy_move_rollback_failed")
            os.replace(destination, source)
        if recreate_data_root is not None:
            recreate_data_root.mkdir(mode=_PRIVATE_DIRECTORY_MODE)
            _secure_directory(
                recreate_data_root, "release_runtime_directory_invalid:data"
            )
    except OSError as exc:
        raise ValueError("release_legacy_move_rollback_failed") from exc


def adopt_legacy_state(
    home: Path,
    *,
    legacy_shared: Path,
    legacy_data: Path,
    confirmation: str,
    health_timeout: int,
    hooks: ReleaseServiceHooks,
) -> dict[str, object]:
    """Move explicitly selected private state while the service is stopped."""
    if confirmation != _ADOPTION_CONFIRMATION:
        raise ValueError(f"release_confirmation_required:{_ADOPTION_CONFIRMATION}")
    health_timeout = _require_health_timeout(health_timeout)
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        current, _previous = _pointer_state(home)
        if current is None:
            raise ValueError("release_legacy_adoption_requires_current")
        try:
            config_moves, data_move = _prepare_legacy_adoption(
                home,
                legacy_shared=legacy_shared,
                legacy_data=legacy_data,
            )
        except OSError as exc:
            raise ValueError("release_legacy_source_validation_failed") from exc
        _stop_service(hooks)
        completed: list[tuple[Path, Path]] = []
        recreate_data_root = home / "data"
        try:
            recreate_data_root.rmdir()
            os.replace(*data_move)
            completed.append(data_move)
            for move in config_moves:
                os.replace(*move)
                completed.append(move)
            _secure_private_tree(home / "data")
            _secure_private_tree(home / "config")
        except Exception as adoption_error:
            try:
                _reverse_moves(completed, recreate_data_root=recreate_data_root)
            except ValueError as rollback_error:
                raise rollback_error from adoption_error
            raise ValueError("release_legacy_adoption_failed") from adoption_error

        service_restarted = False
        if current is not None:
            current_manifest = _manifest_for(current)
            _seal_release_tree(
                current, expected_sha=str(current_manifest["commit_sha"])
            )
            preflight_snapshot_id = uuid.uuid4().hex
            try:
                _snapshot_mutable_state(home, preflight_snapshot_id)
                preflight_snapshot = _validate_state_snapshot(
                    home, preflight_snapshot_id
                )
                _probe_state_compatibility(
                    current,
                    current_manifest,
                    preflight_snapshot,
                    health_timeout,
                )
                _start_service(hooks, health_timeout)
                service_restarted = True
                _require_exact_service_health(
                    hooks, current, current_manifest, health_timeout
                )
                try:
                    _discard_state_snapshot(home, preflight_snapshot_id)
                except ValueError:
                    pass
            except Exception as exc:
                # State has already been atomically moved. Make a best effort
                # to leave it closed rather than moving live SQLite files back.
                try:
                    _stop_service(hooks)
                    _restore_mutable_state(home, preflight_snapshot_id)
                    _discard_state_snapshot(home, preflight_snapshot_id)
                except Exception as cleanup_error:
                    raise ValueError(
                        "release_legacy_adoption_health_failed"
                    ) from cleanup_error
                raise ValueError("release_legacy_adoption_health_failed") from exc
        shared = _absolute_source(legacy_shared)
        try:
            shared.rmdir()
        except OSError:
            # The state was adopted successfully; an empty legacy directory is
            # harmless, and an unexpected entry was rejected before the move.
            pass
        return {
            "status": "adopted",
            "config_files_moved": len(config_moves),
            "data_adopted": True,
            "service_restarted": service_restarted,
        }


def adopt_legacy(home: Path, args: argparse.Namespace) -> None:
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    result = adopt_legacy_state(
        home,
        legacy_shared=Path(args.shared),
        legacy_data=Path(args.data),
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
        hooks=hooks,
    )
    print(json.dumps(result, sort_keys=True))


def _legacy_bootstrap_callbacks():
    from scripts.release.bootstrap_legacy import (
        BootstrapCallbacks,
        clone_private_file_apfs,
        remove_legacy_quarantine,
    )

    return BootstrapCallbacks(
        pointer_state=_pointer_state,
        validate_candidate=_validate_candidate,
        probe_release=_probe_release,
        probe_state=_probe_state_compatibility,
        clone_tree=_copy_mutable_tree,
        clone_file=clone_private_file_apfs,
        fsync_tree=_fsync_private_tree,
        remove_private_tree=_remove_private_tree,
        seal_release=lambda path, sha: _seal_release_tree(path, expected_sha=sha),
        replace_pointer=_replace_pointer,
        manifest_for=_manifest_for,
        fsync_directory=_fsync_directory,
        remove_quarantine=remove_legacy_quarantine,
    )


def bootstrap_legacy_release(
    home: Path,
    *,
    commit_sha: str,
    legacy_workdir: Path,
    legacy_plist: Path,
    confirmation: str,
    health_timeout: int,
    service_manager: Path,
    service_port: int,
) -> dict[str, object]:
    from scripts.release.bootstrap_legacy import (
        ManagedServiceHooks,
        bootstrap_legacy_locked,
        legacy_launchd_hooks,
        legacy_plist_service_port,
    )

    health_timeout = _require_health_timeout(health_timeout)
    service_port = _validated_service_port(service_port)
    release_hooks = _service_manager_hooks(home, service_manager, port=service_port)
    managed_hooks = ManagedServiceHooks(
        stop=release_hooks.stop,
        start=release_hooks.start,
        health=release_hooks.health,
    )
    legacy_hooks = legacy_launchd_hooks(
        legacy_plist,
        runtime_home=home,
        legacy_workdir=legacy_workdir,
        port=legacy_plist_service_port(legacy_plist, legacy_workdir),
    )
    with _lock(home):
        _initialize_service_port_locked(home, service_port)
        _require_clean_transaction_state_locked(home)
        result = bootstrap_legacy_locked(
            home,
            commit_sha=commit_sha,
            legacy_workdir=legacy_workdir,
            legacy_plist=legacy_plist,
            confirmation=confirmation,
            health_timeout=health_timeout,
            managed_service=managed_hooks,
            legacy_service=legacy_hooks,
            callbacks=_legacy_bootstrap_callbacks(),
        )
    return result


def recover_legacy_bootstrap_release(
    home: Path,
    *,
    legacy_workdir: Path,
    legacy_plist: Path,
    health_timeout: int,
    service_manager: Path,
    service_port: int,
) -> bool:
    """Recover a retained legacy handoff before any remote bootstrap work."""

    from scripts.release.bootstrap_legacy import (
        ManagedServiceHooks,
        legacy_bootstrap_recovery_pending,
        legacy_launchd_hooks,
        legacy_plist_service_port,
        recover_legacy_bootstrap_locked,
    )

    health_timeout = _require_health_timeout(health_timeout)
    service_port = _validated_service_port(service_port)
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        if not legacy_bootstrap_recovery_pending(home):
            return False
        _initialize_service_port_locked(home, service_port)
        release_hooks = _service_manager_hooks(home, service_manager, port=service_port)
        managed_hooks = ManagedServiceHooks(
            stop=release_hooks.stop,
            start=release_hooks.start,
            health=release_hooks.health,
        )
        legacy_hooks = legacy_launchd_hooks(
            legacy_plist,
            runtime_home=home,
            legacy_workdir=legacy_workdir,
            port=legacy_plist_service_port(legacy_plist, legacy_workdir),
        )
        recovered_sha = recover_legacy_bootstrap_locked(
            home,
            legacy_workdir=legacy_workdir,
            legacy_plist=legacy_plist,
            health_timeout=health_timeout,
            managed_service=managed_hooks,
            legacy_service=legacy_hooks,
            callbacks=_legacy_bootstrap_callbacks(),
        )
        if recovered_sha is None:
            return False
        candidate_path = _ensure_layout(home) / f".candidate-{recovered_sha}"
        if not os.path.lexists(candidate_path):
            return True
        candidate, _manifest = _validate_candidate(home, recovered_sha)
        if candidate != candidate_path:
            raise ValueError("legacy_bootstrap_candidate_restore_invalid")
        current, previous = _pointer_state(home)
        if candidate in {current, previous}:
            raise ValueError("release_candidate_is_active")
        _remove_tree(candidate)
        return True


def bootstrap_legacy(home: Path, args: argparse.Namespace) -> None:
    health_timeout = _require_health_timeout(args.health_timeout)
    requested_port = _requested_service_port(args)
    service_port = (
        requested_port if requested_port is not None else _DEFAULT_SERVICE_PORT
    )
    result = bootstrap_legacy_release(
        home,
        commit_sha=args.commit_sha,
        legacy_workdir=Path(args.legacy_workdir),
        legacy_plist=Path(args.legacy_plist),
        confirmation=args.confirm,
        health_timeout=health_timeout,
        service_manager=Path(args.service_manager),
        service_port=service_port,
    )
    print(json.dumps(result, sort_keys=True))


def finalize_legacy_bootstrap(home: Path, args: argparse.Namespace) -> None:
    from scripts.release.bootstrap_legacy import (
        ManagedServiceHooks,
        finalize_bootstrap_locked,
    )

    health_timeout = _require_health_timeout(args.health_timeout)
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    release_hooks = _service_manager_hooks(
        home, Path(args.service_manager), port=service_port
    )
    managed_hooks = ManagedServiceHooks(
        stop=release_hooks.stop,
        start=release_hooks.start,
        health=release_hooks.health,
    )
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        result = finalize_bootstrap_locked(
            home,
            confirmation=args.confirm,
            health_timeout=health_timeout,
            managed_service=managed_hooks,
            callbacks=_legacy_bootstrap_callbacks(),
        )
    print(json.dumps(result, sort_keys=True))


def _write_private_text(path: Path, value: str) -> None:
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
        _PRIVATE_FILE_MODE,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)


def _candidate_port(home: Path, requested: int | None) -> int:
    configured = _read_service_port(home)
    production_port = configured if configured is not None else _DEFAULT_SERVICE_PORT
    if requested is None:
        port = (
            _FALLBACK_CANDIDATE_PORT
            if production_port == _DEFAULT_CANDIDATE_PORT
            else _DEFAULT_CANDIDATE_PORT
        )
    else:
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise ValueError("release_candidate_port_invalid")
        port = requested
    if port < 1 or port > 65535:
        raise ValueError("release_candidate_port_invalid")
    if port == production_port:
        raise ValueError("release_candidate_port_conflicts_with_production")
    return port


def run_candidate(
    home: Path,
    *,
    commit_sha: str,
    port: int | None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Run a staged candidate in the foreground with disposable mutable state."""
    port = _candidate_port(home, port)

    with tempfile.TemporaryDirectory(prefix="karkinos-candidate-run-") as temporary:
        runtime = Path(temporary)
        execution_release = runtime / f".candidate-{_require_sha(commit_sha)}"
        with _lock(home):
            _require_clean_transaction_state_locked(home)
            candidate, manifest = _validate_candidate(home, commit_sha)
            try:
                if platform.system() == "Darwin":
                    copy_result = subprocess.run(
                        [
                            "/bin/cp",
                            "-cR",
                            "--",
                            str(candidate),
                            str(execution_release),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    if copy_result.returncode != 0:
                        raise ValueError("release_candidate_execution_clone_failed")
                else:
                    shutil.copytree(candidate, execution_release)
                _seal_release_tree(execution_release, expected_sha=commit_sha)
            except OSError as exc:
                raise ValueError("release_candidate_execution_clone_failed") from exc

        entrypoint = execution_release / "bin" / "karkinos"
        if (
            entrypoint.is_symlink()
            or not entrypoint.is_file()
            or not os.access(entrypoint, os.X_OK)
        ):
            raise ValueError("release_entrypoint_unusable")
        try:
            isolated_home = runtime / "home"
            for path in (
                isolated_home,
                isolated_home / "data",
                isolated_home / "config",
                isolated_home / "logs",
            ):
                path.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
                _secure_directory(path, "release_candidate_state_invalid")
            config = isolated_home / "config" / "config.json"
            env_file = isolated_home / "config" / ".env"
            _write_private_text(config, "{}\n")
            _write_private_text(env_file, "\n")
            environment = {
                key: os.environ[key]
                for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
                if key in os.environ
            }
            environment.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "KARKINOS_HOME": str(isolated_home),
                    "KARKINOS_DATA_DIR": str(isolated_home / "data"),
                    "KARKINOS_CONFIG_PATH": str(config),
                    "KARKINOS_ENV_FILE": str(env_file),
                    "KARKINOS_HOST": "127.0.0.1",
                    "KARKINOS_PORT": str(port),
                    "KARKINOS_AI_ENABLED": "false",
                    "KARKINOS_RELEASE_SHA": str(manifest["commit_sha"]),
                    "KARKINOS_ARTIFACT_FINGERPRINT": str(
                        manifest["payload_fingerprint"]
                    ),
                }
            )
            result = runner(
                [
                    str(entrypoint),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=execution_release / "app",
                env=environment,
                check=False,
            )
        finally:
            _make_release_tree_removable(execution_release)
        return {
            "status": "candidate_exited",
            "commit_sha": commit_sha,
            "port": port,
            "returncode": int(result.returncode),
        }


def run_candidate_command(home: Path, args: argparse.Namespace) -> None:
    result = run_candidate(home, commit_sha=args.commit_sha, port=args.port)
    print(json.dumps(result, sort_keys=True))
    if result["returncode"] != 0:
        raise SystemExit(result["returncode"])


def candidate(home: Path, args: argparse.Namespace) -> None:
    """Fetch and run an exact CI candidate without changing stable pointers."""

    from scripts.release.update_workflow import (
        ReleaseWorkflowCallbacks,
        run_candidate_workflow,
    )

    def unavailable_deploy(_sha: str, _confirmation: str, _timeout: int) -> object:
        raise AssertionError("candidate workflow cannot deploy a release")

    callbacks = ReleaseWorkflowCallbacks(
        preflight=lambda: None,
        stage=lambda archive, sha: _stage_verified_candidate(home, archive, sha),
        run_candidate=lambda sha, port: run_candidate(home, commit_sha=sha, port=port),
        discard=lambda sha: _discard_inactive_candidate(home, sha),
        deploy=unavailable_deploy,
    )
    port = _candidate_port(home, args.port)
    result = run_candidate_workflow(
        callbacks,
        commit_sha=args.commit_sha,
        port=port,
    )
    if not isinstance(result, dict):
        raise ValueError("release_candidate_result_invalid")
    print(json.dumps(result, sort_keys=True))
    returncode = result.get("returncode")
    if not isinstance(returncode, int):
        raise ValueError("release_candidate_result_invalid")
    if returncode != 0:
        raise SystemExit(returncode)


def _require_update_ready(home: Path, requested_port: int | None) -> int:
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        current, _previous = _pointer_state(home)
        if current is None:
            raise ValueError("release_update_requires_current")
        service_port = _configured_or_explicit_service_port_locked(home, requested_port)
        manifest = _manifest_for(current)
        _seal_release_tree(current, expected_sha=str(manifest["commit_sha"]))
        return service_port


def update(home: Path, args: argparse.Namespace) -> None:
    """Fetch and transactionally activate one attested stable tag."""

    from scripts.release.update_workflow import (
        ReleaseWorkflowCallbacks,
        run_stable_update_workflow,
    )

    hooks: ReleaseServiceHooks | None = None
    requested_port = _requested_service_port(args)

    def preflight() -> None:
        nonlocal hooks
        # Avoid a remote download when this runtime still needs one-time
        # bootstrap, but only after tag and confirmation validation.
        service_port = _require_update_ready(home, requested_port)
        hooks = _service_manager_hooks(
            home, Path(args.service_manager), port=service_port
        )

    def deploy_verified(sha: str, confirmation: str, timeout: int) -> dict[str, object]:
        if hooks is None:
            raise ValueError("release_update_preflight_missing")
        return deploy_release(
            home,
            commit_sha=sha,
            confirmation=confirmation,
            health_timeout=timeout,
            hooks=hooks,
        )

    callbacks = ReleaseWorkflowCallbacks(
        preflight=preflight,
        stage=lambda archive, sha: _stage_verified_candidate(home, archive, sha),
        run_candidate=lambda sha, port: run_candidate(home, commit_sha=sha, port=port),
        discard=lambda sha: _discard_inactive_candidate(home, sha),
        deploy=deploy_verified,
    )
    result = run_stable_update_workflow(
        callbacks,
        tag=args.tag,
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
    )
    if not isinstance(result, dict):
        raise ValueError("release_update_result_invalid")
    print(json.dumps(result, sort_keys=True))


def bootstrap(home: Path, args: argparse.Namespace) -> None:
    """Fetch stable bytes and perform the one-time legacy source handoff."""

    from scripts.release.bootstrap_legacy import preflight_legacy_sources
    from scripts.release.update_workflow import (
        LegacyBootstrapWorkflowCallbacks,
        run_stable_bootstrap_workflow,
    )

    legacy_workdir = Path(args.legacy_workdir)
    legacy_plist = Path(args.legacy_plist)
    service_manager = Path(args.service_manager)
    requested_port = _requested_service_port(args)
    service_port: int | None = None
    service_config_created = False

    def preflight() -> None:
        nonlocal service_port
        with _lock(home):
            _ensure_layout(home)
            configured_port = _read_service_port(home)
            if configured_port is not None:
                if requested_port is not None and requested_port != configured_port:
                    raise ValueError("release_service_port_mismatch")
                service_port = configured_port
            else:
                service_port = (
                    requested_port
                    if requested_port is not None
                    else _DEFAULT_SERVICE_PORT
                )
        if service_port is None:
            raise ValueError("release_service_config_missing")
        if recover_legacy_bootstrap_release(
            home,
            legacy_workdir=legacy_workdir,
            legacy_plist=legacy_plist,
            health_timeout=args.health_timeout,
            service_manager=service_manager,
            service_port=service_port,
        ):
            raise ValueError("legacy_bootstrap_recovered_retry_required")
        with _lock(home):
            _require_clean_transaction_state_locked(home)
            current, previous = _pointer_state(home)
            if current is not None or previous is not None:
                raise ValueError("legacy_bootstrap_requires_unmanaged_runtime")
            preflight_legacy_sources(
                home,
                legacy_workdir=legacy_workdir,
                legacy_plist=legacy_plist,
            )

    def bootstrap_verified(
        sha: str, confirmation: str, timeout: int
    ) -> dict[str, object]:
        nonlocal service_config_created
        if service_port is None:
            raise ValueError("release_service_config_missing")
        with _lock(home):
            service_config_created = _read_service_port(home) is None
            _initialize_service_port_locked(home, service_port)
        try:
            return bootstrap_legacy_release(
                home,
                commit_sha=sha,
                legacy_workdir=legacy_workdir,
                legacy_plist=legacy_plist,
                confirmation=confirmation,
                health_timeout=timeout,
                service_manager=service_manager,
                service_port=service_port,
            )
        except BaseException:
            if service_config_created:
                with _lock(home):
                    current, previous = _pointer_state(home)
                    if (
                        current is None
                        and previous is None
                        and _legacy_bootstrap_phase(home) is None
                    ):
                        _remove_service_port_locked(home)
            raise

    callbacks = LegacyBootstrapWorkflowCallbacks(
        preflight=preflight,
        stage=lambda archive, sha: _stage_verified_candidate(home, archive, sha),
        bootstrap=bootstrap_verified,
        discard=lambda sha: _discard_inactive_candidate(home, sha),
    )
    result = run_stable_bootstrap_workflow(
        callbacks,
        tag=args.tag,
        confirmation=args.confirm,
        health_timeout=args.health_timeout,
    )
    if not isinstance(result, dict):
        raise ValueError("legacy_bootstrap_result_invalid")
    print(json.dumps(result, sort_keys=True))


def download(_home_path: Path, args: argparse.Namespace) -> None:
    url = args.url
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "\x00" in url
    ):
        raise ValueError("release_download_url_must_use_https")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("release_download_url_must_use_https") from exc
    if port < 1 or port > 65535:
        raise ValueError("release_download_url_must_use_https")
    if _HEX_DIGEST.fullmatch(args.sha256) is None:
        raise ValueError("release_download_checksum_invalid")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("release_download_timeout_invalid")
    output = Path(args.output).expanduser().absolute()
    for ancestor in (output.parent, *output.parent.parents):
        if ancestor.is_symlink():
            raise ValueError("release_download_output_symlink_unsupported")
        if ancestor.parent == ancestor:
            break
    if os.path.lexists(output):
        raise ValueError("release_download_output_already_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.download-{uuid.uuid4().hex}")
    request_path = parsed.path or "/"
    if parsed.query:
        request_path += f"?{parsed.query}"
    connection = http.client.HTTPSConnection(
        parsed.hostname, port, timeout=args.timeout
    )
    try:
        connection.request(
            "GET", request_path, headers={"User-Agent": "karkinos-release-manager/1"}
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("release_download_http_status_unexpected")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError as exc:
                raise ValueError("release_download_content_length_invalid") from exc
            if declared_size < 0 or declared_size > _MAX_DOWNLOAD_BYTES:
                raise ValueError("release_download_too_large")
        else:
            declared_size = None
        total = 0
        with temporary.open("xb") as stream:
            while total <= _MAX_DOWNLOAD_BYTES:
                chunk = response.read(min(1024 * 1024, _MAX_DOWNLOAD_BYTES + 1 - total))
                if not chunk:
                    break
                stream.write(chunk)
                total += len(chunk)
        if total > _MAX_DOWNLOAD_BYTES:
            raise ValueError("release_download_too_large")
        if declared_size is not None and total != declared_size:
            raise ValueError("release_download_content_length_mismatch")
        if _sha256(temporary) != args.sha256:
            raise ValueError("release_download_checksum_mismatch")
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    print(
        json.dumps(
            {"status": "downloaded", "path": str(output), "sha256": args.sha256},
            sort_keys=True,
        )
    )


def _status_locked(home: Path, _args: argparse.Namespace) -> None:
    _ensure_layout(home)
    current = _read_pointer(home / "current")
    previous = _read_pointer(home / "previous")
    service_port = _read_service_port(home)
    if (current is not None or previous is not None) and service_port is None:
        raise ValueError("release_service_config_missing")
    payload: dict[str, object] = {
        "schema_version": "karkinos.release_runtime_status.v1",
        "home": str(home),
        "current": None,
        "previous": None,
        "candidates": [],
        "data": str(home / "data"),
        "config": str(home / "config"),
        "logs": str(home / "logs"),
        "service_port": service_port,
        "recovery": {
            "required": False,
            "kind": None,
            "phase": None,
        },
        "service": {
            "scope": "loopback_process_identity",
            "supervisor": "launchd",
            "supervisor_ready": None,
            "reachable": False,
            "identity_ready": False,
            "scheduler_running": False,
            "scheduler_initialized": False,
            "scheduler_activation_guarded": None,
            "scheduler_completed_iterations": None,
            "financial_readiness_claimed": False,
        },
    }
    transaction = _read_transaction(home)
    legacy_phase = _legacy_bootstrap_phase(home)
    if transaction is not None and legacy_phase is not None:
        raise ValueError("release_activation_guard_ambiguous")
    if transaction is not None:
        payload["recovery"] = {
            "required": True,
            "kind": "release",
            "phase": transaction.get("phase"),
        }
    elif legacy_phase is not None:
        payload["recovery"] = {
            "required": True,
            "kind": "legacy_bootstrap",
            "phase": legacy_phase,
        }
    for key, path in (("current", current), ("previous", previous)):
        if path is not None:
            manifest = _manifest_for(path)
            payload[key] = {
                "path": str(path),
                "commit_sha": manifest["commit_sha"],
                "version": manifest["version"],
            }
    if current is not None and service_port is not None:
        manifest = _manifest_for(current)
        service = payload["service"]
        if not isinstance(service, dict):
            raise ValueError("release_status_internal_invalid")
        try:
            health_payload = _probe_json("/api/health", service_port)
            live_payload = _probe_json("/api/settings/live/status", service_port)
            service["reachable"] = True
            (
                expected_activation_guarded,
                expected_scheduler_activation_guarded,
                minimum_completed_iterations,
            ) = _service_health_expectations(home)
            service["identity_ready"] = _health_payload_matches(
                health_payload,
                live_payload,
                manifest,
                expected_activation_guarded=expected_activation_guarded,
                expected_scheduler_activation_guarded=(
                    expected_scheduler_activation_guarded
                ),
                minimum_completed_iterations=minimum_completed_iterations,
            )
            if isinstance(live_payload, dict):
                service["scheduler_running"] = _is_explicit_true(
                    live_payload.get("running")
                )
                service["scheduler_initialized"] = _is_explicit_true(
                    live_payload.get("initialized")
                )
                guarded = live_payload.get("scheduler_activation_guarded")
                service["scheduler_activation_guarded"] = (
                    guarded if type(guarded) is bool else None
                )
                iterations = live_payload.get("completed_iterations")
                service["scheduler_completed_iterations"] = (
                    iterations
                    if isinstance(iterations, int) and not isinstance(iterations, bool)
                    else None
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        service_manager = getattr(_args, "service_manager", None)
        if isinstance(service_manager, str):
            service["supervisor_ready"] = _service_manager_ready(
                home,
                Path(service_manager),
                port=service_port,
            )
    candidates: list[str] = []
    for path in (home / RELEASES_DIRNAME).glob(".candidate-*"):
        if path.is_symlink():
            raise ValueError("release_candidate_symlink_unsupported")
        if path.is_dir():
            candidate_sha = path.name.removeprefix(".candidate-")
            if _FULL_SHA.fullmatch(candidate_sha) is None:
                raise ValueError("release_candidate_name_invalid")
            candidates.append(candidate_sha)
    payload["candidates"] = sorted(candidates)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def status(home: Path, args: argparse.Namespace) -> None:
    with _lock(home):
        _status_locked(home, args)


def service_start(home: Path, args: argparse.Namespace) -> None:
    health_timeout = _require_health_timeout(args.health_timeout)
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    with _lock(home):
        _require_clean_transaction_state_locked(home)
        current, _previous = _pointer_state(home)
        if current is None:
            raise ValueError("release_current_missing")
        current_manifest = _manifest_for(current)
        _seal_release_tree(current, expected_sha=str(current_manifest["commit_sha"]))
        try:
            _start_service(hooks, health_timeout)
            _require_exact_service_health(
                hooks, current, current_manifest, health_timeout
            )
        except Exception as exc:
            try:
                _stop_service(hooks)
            except ValueError:
                pass
            raise ValueError("release_service_start_verification_failed") from exc
    print(
        json.dumps(
            {
                "status": "service_started",
                "current": current_manifest["commit_sha"],
            },
            sort_keys=True,
        )
    )


def service_stop(home: Path, args: argparse.Namespace) -> None:
    requested_port = _requested_service_port(args)
    service_port = _prepare_service_port(home, requested_port)
    hooks = _service_manager_hooks(home, Path(args.service_manager), port=service_port)
    with _lock(home):
        # Stopping is allowed with a retained journal so recovery can begin
        # from a known quiescent process state.
        _stop_service(hooks)
    print(json.dumps({"status": "service_stopped"}, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        default=None,
        help="Runtime root (default: ~/Library/Application Support/Karkinos)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    default_service_manager = str(
        _REPOSITORY_ROOT / "scripts" / "service" / "manage_launch_agent.sh"
    )
    candidate_parser = sub.add_parser(
        "candidate", help="fetch and run an exact CI candidate in isolation"
    )
    candidate_parser.add_argument("--commit-sha", required=True)
    candidate_parser.add_argument("--port", type=int)
    update_parser = sub.add_parser(
        "update", help="fetch and atomically activate one stable release tag"
    )
    update_parser.add_argument("--tag", required=True)
    update_parser.add_argument("--confirm", required=True)
    update_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    update_parser.add_argument("--service-manager", default=default_service_manager)
    update_parser.add_argument("--service-port", type=int)
    bootstrap_parser = sub.add_parser(
        "bootstrap", help="one-time migration from the validated legacy service"
    )
    bootstrap_parser.add_argument("--tag", required=True)
    bootstrap_parser.add_argument("--legacy-workdir", required=True)
    bootstrap_parser.add_argument("--legacy-plist", required=True)
    bootstrap_parser.add_argument("--confirm", required=True)
    bootstrap_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    bootstrap_parser.add_argument("--service-manager", default=default_service_manager)
    bootstrap_parser.add_argument("--service-port", type=int)

    rollback_parser = sub.add_parser(
        "rollback", help="health-check and atomically swap current/previous"
    )
    rollback_parser.add_argument("--confirm", required=True)
    rollback_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    rollback_parser.add_argument("--service-manager", default=default_service_manager)
    rollback_parser.add_argument("--service-port", type=int)
    recover_parser = sub.add_parser(
        "recover", help="recover a journaled or unambiguous pointer state"
    )
    recover_parser.add_argument("--confirm", required=True)
    recover_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    recover_parser.add_argument("--service-manager", default=default_service_manager)
    recover_parser.add_argument("--service-port", type=int)
    finalize_bootstrap_parser = sub.add_parser(
        "finalize-bootstrap",
        help="delete the retained legacy quarantine after exact health",
    )
    finalize_bootstrap_parser.add_argument("--confirm", required=True)
    finalize_bootstrap_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    finalize_bootstrap_parser.add_argument(
        "--service-manager", default=default_service_manager
    )
    finalize_bootstrap_parser.add_argument("--service-port", type=int)
    status_parser = sub.add_parser(
        "status", help="show pointers, recovery state, and exact service identity"
    )
    status_parser.add_argument("--service-manager", default=default_service_manager)
    service_start_parser = sub.add_parser(
        "service-start", help="start current through the resident service manager"
    )
    service_start_parser.add_argument(
        "--health-timeout", type=int, default=_DEFAULT_HEALTH_TIMEOUT_SECONDS
    )
    service_start_parser.add_argument(
        "--service-manager", default=default_service_manager
    )
    service_start_parser.add_argument("--service-port", type=int)
    service_stop_parser = sub.add_parser(
        "service-stop", help="stop the resident service under the release lock"
    )
    service_stop_parser.add_argument(
        "--service-manager", default=default_service_manager
    )
    service_stop_parser.add_argument("--service-port", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    home = _home(args.home)
    try:
        if args.command == "candidate":
            candidate(home, args)
        elif args.command == "update":
            update(home, args)
        elif args.command == "bootstrap":
            bootstrap(home, args)
        elif args.command == "rollback":
            rollback(home, args)
        elif args.command == "recover":
            recover(home, args)
        elif args.command == "finalize-bootstrap":
            finalize_legacy_bootstrap(home, args)
        elif args.command == "status":
            status(home, args)
        elif args.command == "service-start":
            service_start(home, args)
        elif args.command == "service-stop":
            service_stop(home, args)
        return 0
    except (OSError, tarfile.TarError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
