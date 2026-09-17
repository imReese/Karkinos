"""Database path protocol plus durable identity for one Karkinos data root."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

IDENTITY_FILE = ".karkinos-database-identity.json"
IDENTITY_SCHEMA = "karkinos.database_identity.v1"
_ALLOWED_ROLES = {"development", "stable", "local", "candidate"}


@runtime_checkable
class DatabaseIdentity(Protocol):
    """Public database identity required by repository composition."""

    @property
    def path(self) -> Path: ...


@dataclass(frozen=True, slots=True)
class DataRootIdentity:
    """Durable identity for a selected persistent data-root instance."""

    schema_version: str
    database_uuid: str
    workspace_role: str
    created_at: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def optional_database_path(database: object | None) -> Path | None:
    """Return a public database path without inspecting private attributes."""

    if database is None or not isinstance(database, DatabaseIdentity):
        return None
    return Path(database.path)


def require_database_path(database: object | None, missing_error: Exception) -> Path:
    """Resolve a public database path or raise the caller's fail-closed error."""

    path = optional_database_path(database)
    if path is None:
        raise missing_error
    return path


def identity_path(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().absolute() / IDENTITY_FILE


def read_database_identity(data_dir: str | Path) -> DataRootIdentity | None:
    path = identity_path(data_dir)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise RuntimeError("database_identity_path_invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = DataRootIdentity(**payload)
        uuid.UUID(identity.database_uuid)
        datetime.fromisoformat(identity.created_at)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        raise RuntimeError("database_identity_invalid") from exc
    if identity.schema_version != IDENTITY_SCHEMA:
        raise RuntimeError("database_identity_schema_unsupported")
    if identity.workspace_role not in _ALLOWED_ROLES:
        raise RuntimeError("database_identity_role_invalid")
    return identity


def ensure_database_identity(
    data_dir: str | Path,
    *,
    workspace_role: str | None,
) -> DataRootIdentity:
    root = Path(data_dir).expanduser().absolute()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = read_database_identity(root)
    if existing is not None:
        if workspace_role is not None and existing.workspace_role != workspace_role:
            raise RuntimeError(
                "database_identity_role_mismatch: "
                f"recorded={existing.workspace_role} requested={workspace_role}"
            )
        return existing
    role = workspace_role or "local"
    if role not in _ALLOWED_ROLES:
        raise RuntimeError("database_identity_role_invalid")
    identity = DataRootIdentity(
        schema_version=IDENTITY_SCHEMA,
        database_uuid=str(uuid.uuid4()),
        workspace_role=role,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_identity(identity_path(root), identity)
    return identity


def _write_identity(path: Path, identity: DataRootIdentity) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(identity.as_dict(), output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "DatabaseIdentity",
    "DataRootIdentity",
    "IDENTITY_FILE",
    "ensure_database_identity",
    "identity_path",
    "optional_database_path",
    "read_database_identity",
    "require_database_path",
]
