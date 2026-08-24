"""Read-only persistence access for broker adapter readiness evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class BrokerAdapterEvidenceReadError(RuntimeError):
    """Persisted broker adapter evidence could not be read safely."""


class BrokerAdapterEvidenceReader:
    """Query persisted release manifests without creating or mutating schema."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def table_exists(self, table: str) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise BrokerAdapterEvidenceReadError(
                "broker_adapter_evidence_table_check_failed"
            ) from exc
        return row is not None

    def list_release_manifests(self, *, limit: int) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT * FROM broker_adapter_release_manifests
                    ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise BrokerAdapterEvidenceReadError(
                "broker_adapter_release_manifest_read_failed"
            ) from exc
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self._path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.execute("PRAGMA query_only = ON")
        return connection
