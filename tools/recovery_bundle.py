"""Create, verify and restore complete local Karkinos recovery bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.persistence.database_identity import (
    ensure_database_identity,
    read_database_identity,
)
from server.persistence.initializer import database_maintenance, initialize_database
from server.persistence.migration_lifecycle import (
    inspect_database,
    migration_definitions,
    source_identity,
    write_record,
    write_registry_snapshot,
)
from tools.state_clone_gate import clone_state, run_state_clone_gate

BUNDLE_SCHEMA = "karkinos.recovery_bundle.v1"
_MANIFEST_DIGEST = "manifest.sha256"
_SECRET_KEY_PARTS = ("password", "secret", "token", "credential", "api_key")
_VOLATILE_NAMES = {".source-runtime.lock"}
_VOLATILE_SUFFIXES = ("-wal", "-shm", "-journal", ".initialize.lock")


def create_recovery_bundle(
    *,
    data_dir: str | Path,
    config_path: str | Path,
    destination_root: str | Path,
    workspace_role: str | None,
) -> Path:
    data = _safe_directory(Path(data_dir), "recovery_source_data_invalid")
    config = _safe_file(Path(config_path), "recovery_config_invalid")
    _load_non_secret_config(config)
    identity = ensure_database_identity(data, workspace_role=workspace_role)
    app = _safe_file(data / "app.db", "recovery_app_database_missing")
    initialize_database(app)

    root = Path(destination_root).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("recovery_destination_invalid")
    bundle_id = uuid.uuid4().hex
    bundle = (
        root
        / f"recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{bundle_id[:12]}"
    )
    bundle.mkdir(mode=0o700)
    try:
        # The database lock is also the managed-writer barrier for the data root.
        # Keep it for the complete snapshot, including immutable-object closure.
        try:
            ownership = database_maintenance(app, timeout_seconds=0)
            with ownership:
                status = inspect_database(app)
                if status.state != "current":
                    raise RuntimeError(f"recovery_database_not_current:{status.state}")
                clone_state(data, bundle / "data")
                _remove_volatile_files(bundle / "data")
                config_dir = bundle / "config"
                config_dir.mkdir(mode=0o700)
                _copy_private_file(config, config_dir / "config.json")
                registry = write_registry_snapshot(
                    bundle, tuple(migration_definitions())
                )
                _fsync_bundle_tree(bundle)
                files = _file_manifest(
                    bundle, exclude={"manifest.json", _MANIFEST_DIGEST}
                )
                source = source_identity()
                manifest = {
                    "schema_version": BUNDLE_SCHEMA,
                    "bundle_id": bundle_id,
                    "state": "complete",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "database_identity": identity.as_dict(),
                    "source": {
                        "commit": source.get("commit"),
                        "persistence_worktree_dirty": source.get(
                            "persistence_worktree_dirty"
                        ),
                    },
                    "database_status": {
                        "state": status.state,
                        "applied": list(status.applied),
                        "expected": list(status.expected),
                        "sqlite_version": sqlite3.sqlite_version,
                    },
                    "migration_registry": registry,
                    "files": files,
                }
                write_record(bundle / "manifest.json", manifest)
                _write_manifest_digest(bundle)
        except TimeoutError as exc:
            raise RuntimeError(
                "recovery_runtime_active: stop Karkinos before creating a recovery bundle"
            ) from exc
        verify_recovery_bundle(bundle)
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        raise
    return bundle


def verify_recovery_bundle(bundle_path: str | Path) -> dict[str, Any]:
    bundle = _safe_directory(Path(bundle_path), "recovery_bundle_invalid")
    manifest_path = _safe_file(bundle / "manifest.json", "recovery_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("recovery_manifest_invalid") from exc
    if (
        manifest.get("schema_version") != BUNDLE_SCHEMA
        or manifest.get("state") != "complete"
    ):
        raise RuntimeError("recovery_manifest_invalid")
    expected = manifest.get("files")
    if not isinstance(expected, list):
        raise RuntimeError("recovery_manifest_invalid")
    actual = _file_manifest(bundle, exclude={"manifest.json", _MANIFEST_DIGEST})
    if actual != expected:
        raise RuntimeError("recovery_bundle_file_manifest_mismatch")
    _verify_manifest_digest(bundle)
    _load_non_secret_config(bundle / "config/config.json")
    identity = read_database_identity(bundle / "data")
    if identity is None or identity.as_dict() != manifest.get("database_identity"):
        raise RuntimeError("recovery_database_identity_mismatch")
    _verify_sqlite_store(bundle / "data/app.db", foreign_keys=True)
    meta = bundle / "data/meta.db"
    if meta.exists():
        _verify_sqlite_store(meta, foreign_keys=False)
    status = inspect_database(bundle / "data/app.db")
    if status.blocked:
        raise RuntimeError(f"recovery_database_history_blocked:{status.state}")
    _verify_registry_and_history(bundle, manifest, status)
    dataset_count = _verify_published_datasets(bundle / "data")
    return {
        "bundle_id": manifest["bundle_id"],
        "database_uuid": identity.database_uuid,
        "workspace_role": identity.workspace_role,
        "database_state": status.state,
        "file_count": len(expected),
        "published_dataset_count": dataset_count,
        "verified": True,
    }


def restore_recovery_bundle(
    *,
    bundle_path: str | Path,
    candidate_dir: str | Path,
    replay: bool = True,
) -> dict[str, Any]:
    verification = verify_recovery_bundle(bundle_path)
    bundle = Path(bundle_path).expanduser().absolute()
    candidate = Path(candidate_dir).expanduser().absolute()
    if candidate.exists() or candidate.is_symlink():
        raise RuntimeError("recovery_candidate_must_not_exist")
    candidate.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate.mkdir(mode=0o700)
    candidate_data = candidate / "data"
    clone_state(bundle / "data", candidate_data)
    _remove_volatile_files(candidate_data)
    candidate_config = candidate / "config"
    candidate_config.mkdir(mode=0o700)
    _copy_private_file(bundle / "config/config.json", candidate_config / "config.json")
    restored_identity = read_database_identity(candidate_data)
    if (
        restored_identity is None
        or restored_identity.database_uuid != verification["database_uuid"]
    ):
        raise RuntimeError("recovery_candidate_identity_mismatch")
    _verify_sqlite_store(candidate_data / "app.db", foreign_keys=True)
    if (candidate_data / "meta.db").exists():
        _verify_sqlite_store(candidate_data / "meta.db", foreign_keys=False)
    replay_report: dict[str, Any] | None = None
    if replay:
        project = Path(__file__).resolve().parents[1]
        replay_report = run_state_clone_gate(
            source_data=candidate_data,
            candidate_command=[sys.executable, "-m", "server"],
            candidate_cwd=project,
            timeout=120,
        )
        if replay_report.get("status") != "passed":
            raise RuntimeError("recovery_candidate_replay_failed")
    receipt = {
        "schema_version": "karkinos.recovery_restore.v1",
        "bundle_id": verification["bundle_id"],
        "database_uuid": verification["database_uuid"],
        "restored_at": datetime.now(timezone.utc).isoformat(),
        "candidate_dir": str(candidate),
        "replay_status": "passed" if replay else "not_checked",
    }
    write_record(candidate / ".recovery-restore.json", receipt)
    return {**verification, "candidate_dir": str(candidate), "replay": replay_report}


def _verify_sqlite_store(path: Path, *, foreign_keys: bool) -> None:
    _safe_file(path, "recovery_sqlite_store_missing")
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=2)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise RuntimeError(f"recovery_integrity_check_failed:{path.name}")
        if (
            foreign_keys
            and conn.execute("PRAGMA foreign_key_check").fetchone() is not None
        ):
            raise RuntimeError(f"recovery_foreign_key_check_failed:{path.name}")


def _verify_published_datasets(data_dir: Path) -> int:
    objects = data_dir / "objects"
    catalog_root = data_dir / "index"
    catalog_path = catalog_root / "catalog/datasets.sqlite3"
    if not objects.exists() and not catalog_path.exists():
        return 0
    if not objects.is_dir() or not catalog_path.is_file():
        raise RuntimeError("recovery_dataset_store_incomplete")
    from data.dataset.catalog import DatasetCatalog
    from data.dataset.reader import read_daily_bar_dataset
    from data.storage.objects import ContentAddressedObjectStore

    store = ContentAddressedObjectStore(objects)
    catalog = DatasetCatalog(catalog_root)
    entries = tuple(catalog.list_daily_bar_datasets())
    for entry in entries:
        read_daily_bar_dataset(store, entry.ref)
    return len(entries)


def _load_non_secret_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            _safe_file(path, "recovery_config_invalid").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError("recovery_config_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("recovery_config_invalid")

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                normalized = str(key).lower()
                if any(
                    part in normalized for part in _SECRET_KEY_PARTS
                ) and not normalized.endswith("_env"):
                    raise RuntimeError(f"recovery_config_contains_secret_key:{key}")
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
    return payload


def _fsync_bundle_tree(root: Path) -> None:
    """Make copied payload durable before publishing a COMPLETE manifest."""
    directories: set[Path] = {root}
    for path in root.rglob("*"):
        if path.is_dir():
            directories.add(path)
            continue
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("recovery_special_file_rejected")
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
        directories.add(path.parent)
    for directory in sorted(
        directories, key=lambda item: len(item.parts), reverse=True
    ):
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_manifest_digest(bundle: Path) -> None:
    manifest = bundle / "manifest.json"
    with manifest.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    target = bundle / _MANIFEST_DIGEST
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=bundle
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(digest + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        directory = os.open(bundle, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _verify_manifest_digest(bundle: Path) -> None:
    digest_file = _safe_file(
        bundle / _MANIFEST_DIGEST, "recovery_manifest_digest_missing"
    )
    recorded = digest_file.read_text(encoding="ascii").strip()
    with (bundle / "manifest.json").open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if recorded != actual:
        raise RuntimeError("recovery_manifest_digest_mismatch")


def _verify_registry_and_history(
    bundle: Path, manifest: dict[str, Any], status: Any
) -> None:
    registry_meta = manifest.get("migration_registry")
    if (
        not isinstance(registry_meta, dict)
        or registry_meta.get("file") != "migration-registry.json"
    ):
        raise RuntimeError("recovery_migration_registry_invalid")
    registry_path = _safe_file(
        bundle / "migration-registry.json", "recovery_migration_registry_missing"
    )
    with registry_path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != registry_meta.get("sha256"):
        raise RuntimeError("recovery_migration_registry_digest_mismatch")
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("recovery_migration_registry_invalid") from exc
    migrations = registry.get("migrations") if isinstance(registry, dict) else None
    if not isinstance(migrations, list):
        raise RuntimeError("recovery_migration_registry_invalid")
    expected_history = [
        {key: row[key] for key in ("version", "name", "checksum")} for row in migrations
    ]
    recorded_status = manifest.get("database_status")
    if not isinstance(recorded_status, dict):
        raise RuntimeError("recovery_database_status_invalid")
    if recorded_status.get("expected") != expected_history:
        raise RuntimeError("recovery_registry_history_mismatch")
    if recorded_status.get("applied") != list(status.applied):
        raise RuntimeError("recovery_applied_history_mismatch")


def _file_manifest(root: Path, *, exclude: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.name in exclude:
            continue
        if path.is_symlink():
            raise RuntimeError("recovery_symlink_rejected")
        if path.is_dir():
            continue
        if not path.is_file():
            raise RuntimeError("recovery_special_file_rejected")
        relative = path.relative_to(root).as_posix()
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        rows.append({"path": relative, "size": path.stat().st_size, "sha256": digest})
    return rows


def _remove_volatile_files(root: Path) -> None:
    for path in list(root.rglob("*")):
        if path.is_file() and (
            path.name in _VOLATILE_NAMES or path.name.endswith(_VOLATILE_SUFFIXES)
        ):
            path.unlink()


def _copy_private_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("recovery_source_file_invalid")
    shutil.copyfile(source, destination)
    destination.chmod(0o600)


def _safe_directory(path: Path, code: str) -> Path:
    resolved = path.expanduser().absolute()
    if resolved.is_symlink() or not resolved.is_dir():
        raise RuntimeError(code)
    return resolved


def _safe_file(path: Path, code: str) -> Path:
    resolved = path.expanduser().absolute()
    if resolved.is_symlink() or not resolved.is_file() or resolved.stat().st_nlink != 1:
        raise RuntimeError(code)
    return resolved


def _default_data_dir() -> Path:
    from server.runtime_paths import resolve_data_dir

    return Path(resolve_data_dir()).expanduser().absolute()


def _default_config_path() -> Path:
    configured = os.environ.get("KARKINOS_CONFIG_PATH")
    return Path(configured or "config.json").expanduser().absolute()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--data-dir", type=Path, default=None)
    create.add_argument("--config", type=Path, default=None)
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--role", default=os.environ.get("KARKINOS_WORKSPACE_ROLE"))
    verify = sub.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("--candidate", type=Path, required=True)
    restore.add_argument("--no-replay", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_recovery_bundle(
            data_dir=args.data_dir or _default_data_dir(),
            config_path=args.config or _default_config_path(),
            destination_root=args.destination,
            workspace_role=args.role,
        )
        print(result)
    elif args.command == "verify":
        print(json.dumps(verify_recovery_bundle(args.bundle), sort_keys=True))
    else:
        print(
            json.dumps(
                restore_recovery_bundle(
                    bundle_path=args.bundle,
                    candidate_dir=args.candidate,
                    replay=not args.no_replay,
                ),
                sort_keys=True,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
