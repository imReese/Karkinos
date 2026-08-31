"""Read-only persistence queries for signed broker adapter release reviews."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SignedBrokerAdapterReviewReader:
    """Read persisted manifest and review rows without schema side effects."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def table_exists(self, table: str) -> bool:
        if not self._path.exists():
            return False
        with self._connect() as connection:
            return self._table_exists(connection, table)

    def list_release_manifests(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM broker_adapter_release_manifests
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_review(self, *, release_evidence_ref: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE release_evidence_ref = ? ORDER BY id DESC LIMIT 1
                """,
                (release_evidence_ref,),
            ).fetchone()
        return dict(row) if row is not None else None

    def review_by_id(self, *, review_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM broker_adapter_release_review_events
                WHERE review_id = ? LIMIT 1
                """,
                (review_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def counts(self) -> tuple[int, int]:
        if not self._path.exists():
            return 0, 0
        with self._connect() as connection:
            manifests = self._table_count(
                connection,
                table="broker_adapter_release_manifests",
            )
            reviews = self._table_count(
                connection,
                table="broker_adapter_release_review_events",
            )
        return manifests, reviews

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"{self._path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @classmethod
    def _table_count(cls, connection: sqlite3.Connection, *, table: str) -> int:
        if not cls._table_exists(connection, table):
            return 0
        if table == "broker_adapter_release_manifests":
            query = "SELECT COUNT(*) FROM broker_adapter_release_manifests"
        elif table == "broker_adapter_release_review_events":
            query = "SELECT COUNT(*) FROM broker_adapter_release_review_events"
        else:  # pragma: no cover - callers use the two fixed evidence tables.
            raise ValueError("unsupported signed broker adapter review table")
        row = connection.execute(query).fetchone()
        return int(row[0]) if row is not None else 0
