"""SQLite repository and transaction helper for the shared event log."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class EventLogRepository:
    """Own normalized event persistence without interpreting event payloads."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    def append(
        self,
        *,
        event_type: str,
        timestamp: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str = "app",
        source_ref: str | None = None,
        payload: dict[str, Any] | str | None = None,
    ) -> int:
        with sqlite3.connect(self._database_path) as conn:
            cursor = insert_event_sync(
                conn,
                event_type=event_type,
                timestamp=timestamp,
                entity_type=entity_type,
                entity_id=entity_id,
                source=source,
                source_ref=source_ref,
                payload=payload,
            )
            conn.commit()
            return cursor.lastrowid or 0

    def list_events(
        self,
        *,
        event_type: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if entity_type is not None:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if entity_id is not None:
            conditions.append("entity_id = ?")
            params.append(entity_id)
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM event_log
                {where_clause}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(row) for row in rows]


def insert_event_sync(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    timestamp: str,
    entity_type: str | None,
    entity_id: str | None,
    source: str,
    source_ref: str | None,
    payload: dict[str, Any] | str | None,
) -> sqlite3.Cursor:
    """Insert one event on the caller-owned transaction connection."""
    now = datetime.now().isoformat()
    return conn.execute(
        """
        INSERT INTO event_log (
            event_type, timestamp, entity_type, entity_id, source,
            source_ref, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            timestamp,
            entity_type,
            entity_id,
            source,
            source_ref,
            serialize_event_payload_json(payload),
            now,
        ),
    )


def serialize_event_payload_json(value: dict[str, Any] | str | None) -> str:
    """Serialize event payloads with Decimal-safe stable JSON bytes."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
