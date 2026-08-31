"""Connection and transaction ownership for AI shadow research persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class ShadowResearchManagedConnection:
    """Commit or roll back one owned SQLite connection, then close it."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self._connection

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self._connection.close()


class ShadowResearchUnitOfWork:
    """Open all read/write transactions for the shadow-research repositories."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def connect(self) -> ShadowResearchManagedConnection:
        return ShadowResearchManagedConnection(self._open())

    def write(self) -> ShadowResearchManagedConnection:
        connection = self._open()
        connection.execute("BEGIN IMMEDIATE")
        return ShadowResearchManagedConnection(connection)

    def read(self) -> ShadowResearchManagedConnection:
        if not self._path.exists():
            raise sqlite3.OperationalError("shadow research store is not initialized")
        connection = sqlite3.connect(
            f"file:{self._path.resolve()}?mode=ro", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        return ShadowResearchManagedConnection(connection)

    def _open(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection
