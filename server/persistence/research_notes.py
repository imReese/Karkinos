"""SQLite repository for persisted market research notes."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from server.persistence.event_log import insert_event_sync


class ResearchNotesRepository:
    """Own research note persistence without research workflow behavior."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    async def add(
        self,
        *,
        symbol: str,
        asset_class: str,
        entry_kind: str,
        title: str,
        content: str,
        priority: str = "normal",
        event_date: str | None = None,
    ) -> int:
        now = datetime.now().isoformat()
        with sqlite3.connect(self._database_path) as conn:
            cursor = conn.execute(
                """INSERT INTO market_research_notes
                   (symbol, asset_class, entry_kind, title, content, priority, event_date, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    asset_class,
                    entry_kind,
                    title,
                    content,
                    priority,
                    event_date,
                    now,
                    now,
                ),
            )
            note_id = cursor.lastrowid or 0
            insert_event_sync(
                conn,
                event_type="research.note.created",
                timestamp=now,
                entity_type="instrument",
                entity_id=symbol,
                source="market_research_notes",
                source_ref=str(note_id),
                payload={
                    "note_id": note_id,
                    "symbol": symbol,
                    "asset_class": asset_class,
                    "entry_kind": entry_kind,
                    "title": title,
                    "content": content,
                    "priority": priority,
                    "event_date": event_date,
                },
            )
            conn.commit()
            return note_id

    async def list_notes(
        self,
        *,
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        import aiosqlite

        query = "SELECT * FROM market_research_notes"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if entry_kind:
            clauses.append("entry_kind = ?")
            params.append(entry_kind)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if event_date_from:
            clauses.append("COALESCE(event_date, '') >= ?")
            params.append(event_date_from)
        if event_date_to:
            clauses.append("COALESCE(event_date, '') <= ?")
            params.append(event_date_to)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with aiosqlite.connect(self._database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    def list_notes_sync(
        self,
        *,
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM market_research_notes"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if entry_kind:
            clauses.append("entry_kind = ?")
            params.append(entry_kind)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if event_date_from:
            clauses.append("COALESCE(event_date, '') >= ?")
            params.append(event_date_from)
        if event_date_to:
            clauses.append("COALESCE(event_date, '') <= ?")
            params.append(event_date_to)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self._database_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    async def delete(self, note_id: int) -> bool:
        import aiosqlite

        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                "DELETE FROM market_research_notes WHERE id = ?",
                (note_id,),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update(
        self,
        *,
        note_id: int,
        entry_kind: str,
        title: str,
        content: str,
        priority: str,
        event_date: str | None = None,
    ) -> bool:
        import aiosqlite

        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                """UPDATE market_research_notes
                   SET entry_kind = ?, title = ?, content = ?, priority = ?, event_date = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    entry_kind,
                    title,
                    content,
                    priority,
                    event_date,
                    datetime.now().isoformat(),
                    note_id,
                ),
            )
            await db.commit()
            return cursor.rowcount > 0
