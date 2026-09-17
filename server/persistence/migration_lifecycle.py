"""Read-only schema diagnostics and private, recoverable migration records.

The existing migration registry remains authoritative. Records never authorize
an unknown schema, rewrite a checksum, or restore a database automatically.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.persistence.connection import connect_sqlite


@dataclass(frozen=True)
class DatabaseStatus:
    path: Path
    state: str
    applied: tuple[dict[str, Any], ...]
    expected: tuple[dict[str, Any], ...]
    reason: str = ""

    @property
    def needs_preparation(self) -> bool:
        return self.state in {"new", "legacy", "upgrade"}

    @property
    def blocked(self) -> bool:
        return self.state not in {"current", "new", "legacy", "upgrade"}

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        result["sqlite_version"] = sqlite3.sqlite_version
        result["recovery_records"] = recovery_records(self)
        return result

    def explain(self) -> str:
        code_version = self.expected[-1]["version"] if self.expected else 0
        db_version = self.applied[-1]["version"] if self.applied else 0
        lines = [
            f"Database state: {self.state}",
            f"Database: {self.path}",
            f"SQLite: {sqlite3.sqlite_version}",
            f"Code schema: {code_version}; database schema: {db_version}",
        ]
        if self.reason:
            lines.append(self.reason)
        expected = {row["version"]: row for row in self.expected}
        for row in self.applied:
            match = expected.get(row["version"])
            if match is None or any(
                row[key] != match[key] for key in ("name", "checksum")
            ):
                lines.append(
                    f"  {row['version']} {row['name']} "
                    f"checksum={row['checksum']} applied_at={row['applied_at']}"
                )
        if self.blocked:
            for item in recovery_records(self):
                lines.append(
                    f"Recorded source: {item['source']}; "
                    f"ledger comparison: {item['ledger_comparison']}"
                )
                lines.append(f"  Record: {item['path']}")
                registry = item.get("verified_registry_snapshot")
                if registry:
                    lines.append(f"  Verified migration registry: {registry}")
                for backup in item["verified_backups"]:
                    lines.append(f"  Verified backup: {backup}")
            lines.extend(
                [
                    "No schema migration was executed by this check.",
                    "Restore matching migration source or review a compatible backup; "
                    "do not delete migration records or lower their version.",
                    f"Migration records: {history_directory(self.path)}",
                    "Old databases may have no recorded code provenance.",
                ]
            )
        elif self.needs_preparation:
            lines.append("Run the normal Karkinos launcher to prepare this database.")
        return "\n".join(lines)


class DatabasePreparationError(RuntimeError):
    """An actionable startup error; detailed failures may still be logged."""

    def __init__(self, status: DatabaseStatus):
        self.status = status
        super().__init__(status.explain())


def migration_definitions() -> tuple[dict[str, Any], ...]:
    # Resolve dynamically: tests and development can append migrations without
    # stale CURRENT_SCHEMA_VERSION constants becoming the compatibility owner.
    from server.persistence.migrations import migration_registry

    return tuple(
        {
            "version": item.version,
            "name": item.name,
            "checksum": item.checksum,
            "statements": list(item.statements),
            "blockers": [list(blocker) for blocker in item.blockers],
            "schema_contract_checksum": item.schema_contract_checksum,
        }
        for item in migration_registry()
    )


def inspect_database(database_path: str | Path) -> DatabaseStatus:
    """Inspect without creating a database, running migrations or providers."""
    from server.persistence.migrations import (
        assert_migration_table_structure,
        assert_schema_compatible,
    )
    from server.persistence.schema_v1 import initialize_v1_baseline_schema

    path = Path(database_path).expanduser().absolute()
    expected = tuple(
        {key: row[key] for key in ("version", "name", "checksum")}
        for row in migration_definitions()
    )
    applied: tuple[dict[str, Any], ...] = ()
    if not path.exists() and not path.is_symlink():
        return DatabaseStatus(path, "new", applied, expected)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        return DatabaseStatus(
            path, "invalid_database", applied, expected, "Unsafe database path"
        )
    try:
        with closing(connect_sqlite(path, readonly=True)) as conn:
            conn.execute("BEGIN")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "schema_migrations" in tables:
                assert_migration_table_structure(conn)
                applied = tuple(
                    dict(
                        zip(
                            ("version", "name", "checksum", "applied_at"),
                            row,
                            strict=True,
                        ),
                    )
                    for row in conn.execute(
                        "SELECT version, name, checksum, applied_at "
                        "FROM schema_migrations ORDER BY version"
                    )
                )
            assert_schema_compatible(
                conn,
                baseline_initializer=initialize_v1_baseline_schema,
            )
            if "schema_migrations" not in tables:
                state = "legacy" if tables else "new"
            else:
                state = "current" if len(applied) == len(expected) else "upgrade"
            return DatabaseStatus(path, state, applied, expected)
    except (RuntimeError, sqlite3.DatabaseError) as exc:
        reason = str(exc)
        if "database schema is newer" in reason:
            state = "unknown_migration"
        elif "history" in reason or "schema_migrations" in reason:
            state = "history_mismatch"
        elif isinstance(exc, sqlite3.OperationalError) and "locked" in reason:
            state = "database_in_use"
        elif isinstance(exc, sqlite3.DatabaseError):
            state = "invalid_database"
        else:
            state = "schema_drift"
        return DatabaseStatus(path, state, applied, expected, reason)


def require_database_ready(database_path: str | Path) -> DatabaseStatus:
    status = inspect_database(database_path)
    if status.state != "current":
        raise DatabasePreparationError(status)
    return status


def history_directory(path: Path) -> Path:
    return path.parent / "backups" / "schema" / path.name


def recovery_records(status: DatabaseStatus) -> list[dict[str, Any]]:
    """Read advisory recovery records; never authorize or replay their contents.

    An interrupted receipt is compared with the authoritative ledger rather than
    blindly marked successful. Only existing, digest-verified backups are shown.
    """
    root = history_directory(status.path)
    if any(part.is_symlink() for part in (root, *root.parents)):
        return []
    actual = [(row["version"], row["name"], row["checksum"]) for row in status.applied]
    results = []
    for path in sorted(root.glob("*/migration.json")):
        try:
            if (
                path.is_symlink()
                or path.parent.is_symlink()
                or path.stat().st_size > 4_000_000
            ):
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("format") != 1 or record.get("database") != str(status.path):
                continue
            target = [
                (row["version"], row["name"], row["checksum"])
                for row in record.get("target_history", record["target"])
            ]
            before = [
                (row["version"], row["name"], row["checksum"])
                for row in record["before"]
            ]
            if actual == target:
                comparison = "target_present"
            elif actual == before:
                comparison = "before_present"
            else:
                comparison = "different_history"
            registry_snapshot = None
            registry = record.get("registry_snapshot")
            if (
                isinstance(registry, dict)
                and registry.get("file") == "migration-registry.json"
            ):
                saved = path.parent / "migration-registry.json"
                if (
                    not saved.is_symlink()
                    and saved.is_file()
                    and saved.stat().st_nlink == 1
                ):
                    with saved.open("rb") as data:
                        digest = hashlib.file_digest(data, "sha256").hexdigest()
                    if digest == registry.get("sha256"):
                        registry_snapshot = str(saved)
            backups = []
            for item in record.get("backups", []):
                name = item["file"]
                if name not in {status.path.name, "meta.db"}:
                    continue
                saved = path.parent / name
                if (
                    saved.is_symlink()
                    or not saved.is_file()
                    or saved.stat().st_nlink != 1
                ):
                    continue
                with saved.open("rb") as data:
                    digest = hashlib.file_digest(data, "sha256").hexdigest()
                if digest == item["sha256"]:
                    backups.append(str(saved))
            results.append(
                {
                    "path": str(path),
                    "source": record.get("source"),
                    "state": record.get("state"),
                    "started_at": str(record.get("started_at", "")),
                    "ledger_comparison": comparison,
                    "verified_registry_snapshot": registry_snapshot,
                    "verified_backups": backups,
                }
            )
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Diagnostic corruption must not replace the schema's primary error.
            continue
    return sorted(results, key=lambda row: row["started_at"], reverse=True)[:5]


def _private_directory(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("migration_archive_symlink_rejected")
    if not path.exists():
        if not path.parent.exists():
            _private_directory(path.parent)
        path.mkdir(mode=0o700)
    if not path.is_dir():
        raise ValueError("migration_archive_directory_invalid")
    # Never chmod a user's existing data directory here.


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_record(path: Path, record: dict[str, Any]) -> None:
    """Publish a complete durable JSON record; an interrupted write is not success."""
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(record, output, ensure_ascii=False, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_registry_snapshot(
    directory: Path, definitions: tuple[dict[str, Any], ...]
) -> dict[str, str]:
    """Persist the exact evaluated migration registry as recovery material."""

    path = directory / "migration-registry.json"
    write_record(path, {"format": 1, "migrations": list(definitions)})
    with path.open("rb") as saved:
        digest = hashlib.file_digest(saved, "sha256").hexdigest()
    return {"file": path.name, "sha256": digest}


def source_identity() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    # Only code identity is collected. Never archive environment, .env, config,
    # a whole working-tree diff, credentials, or user financial records here.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args],
                env=environment,
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
            )
            return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    sha = git("rev-parse", "HEAD")
    dirty = git(
        "status",
        "--porcelain",
        "--untracked-files=normal",
        "--",
        "server/persistence",
    )
    return {
        "source_root": str(root),
        "commit": sha,
        "persistence_worktree_dirty": None if dirty is None else bool(dirty),
    }


def backup_database(source: Path, destination: Path, *, timeout: float = 30) -> str:
    """Back up committed WAL content; never copy an active .db file directly."""
    if source.is_symlink() or not source.is_file() or source.stat().st_nlink != 1:
        raise ValueError("migration_backup_source_invalid")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    deadline = time.monotonic() + timeout

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("migration_backup_timeout")

    with closing(connect_sqlite(source, readonly=True)) as origin:
        with closing(connect_sqlite(destination)) as target:
            origin.backup(target, pages=256, progress=progress, sleep=0.05)
            if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("migration_backup_integrity_failed")
            target.execute("PRAGMA journal_mode=DELETE")
    with destination.open("rb") as saved:
        os.fsync(saved.fileno())
        checksum = hashlib.file_digest(saved, "sha256").hexdigest()
    return checksum


def begin_preparation(status: DatabaseStatus) -> tuple[Path, dict[str, Any]]:
    """Called under exclusive initialization/maintenance ownership, before DDL."""
    path = status.path
    directory = history_directory(path) / uuid.uuid4().hex
    _private_directory(directory)
    record_path = directory / "migration.json"
    definitions = tuple(copy.deepcopy(migration_definitions()))
    registry_snapshot = write_registry_snapshot(directory, definitions)
    record: dict[str, Any] = {
        "format": 1,
        "state": "preparing",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "database": str(path),
        "before": list(status.applied),
        "target": list(definitions),
        "registry_snapshot": registry_snapshot,
        "source": source_identity(),
        "backups": [],
        "backup_scope": "SQLite stores only; not a complete application restore point",
    }
    prior = {row["version"]: row for row in status.applied}
    record["target_history"] = [
        {
            key: prior.get(row["version"], row)[key]
            for key in ("version", "name", "checksum")
        }
        for row in record["target"]
    ]
    write_record(record_path, record)
    try:
        sources = [path]
        meta = path.parent / "meta.db"
        if meta != path and meta.exists():
            sources.append(meta)
        for source in sources:
            if source.exists():
                checksum = backup_database(source, directory / source.name)
                record["backups"].append({"file": source.name, "sha256": checksum})
        record["state"] = "backed_up"
        write_record(record_path, record)
    except BaseException:
        record["state"] = "backup_failed"
        try:
            write_record(record_path, record)
        except OSError:
            pass
        raise
    return record_path, record


def finish_preparation(
    record_path: Path,
    record: dict[str, Any],
    *,
    succeeded: bool,
) -> None:
    record["state"] = "committed" if succeeded else "failed"
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_record(record_path, record)


class AtomicSchemaConnection(sqlite3.Connection):
    """Keep legacy schema scripts inside the explicit initialization transaction.

    sqlite3.executescript() implicitly commits a pending transaction. Splitting
    only at complete SQLite statements preserves quoted semicolons and trigger
    bodies without rewriting any historical SQL or its checksum.
    """

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        cursor = self.cursor()
        pending = ""
        for character in sql_script:
            pending += character
            if character == ";" and sqlite3.complete_statement(pending):
                cursor.execute(pending)
                pending = ""
        if pending.strip():
            cursor.execute(pending)
        return cursor
