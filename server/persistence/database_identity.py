"""Typed access to the public identity of a SQLite-backed application store."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class DatabaseIdentity(Protocol):
    """Public database identity required by repository composition."""

    @property
    def path(self) -> Path: ...


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


__all__ = ["DatabaseIdentity", "optional_database_path", "require_database_path"]
