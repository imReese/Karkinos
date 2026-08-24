"""Research database compatibility capability."""

from __future__ import annotations

from typing import Any

from server.persistence.facades.base import DatabaseRepositoryAccess


class ResearchDatabaseFacade(DatabaseRepositoryAccess):
    """Delegate the legacy API to cohesive repositories."""

    # ---------- Market Research ----------

    async def add_research_note(
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
        """新增研究记录，供市场研究工作台持久化使用。"""
        return await self._research_notes.add(
            symbol=symbol,
            asset_class=asset_class,
            entry_kind=entry_kind,
            title=title,
            content=content,
            priority=priority,
            event_date=event_date,
        )

    async def get_research_notes(
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
        """异步读取研究记录，按更新时间倒序。"""
        return await self._research_notes.list_notes(
            symbol=symbol,
            entry_kind=entry_kind,
            priority=priority,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            limit=limit,
            offset=offset,
        )

    def get_research_notes_sync(
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
        """同步读取研究记录，供聚合看板快速汇总。"""
        return self._research_notes.list_notes_sync(
            symbol=symbol,
            entry_kind=entry_kind,
            priority=priority,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            limit=limit,
            offset=offset,
        )

    async def delete_research_note(self, note_id: int) -> bool:
        """删除研究记录。"""
        return await self._research_notes.delete(note_id)

    async def update_research_note(
        self,
        *,
        note_id: int,
        entry_kind: str,
        title: str,
        content: str,
        priority: str,
        event_date: str | None = None,
    ) -> bool:
        """更新研究记录。"""
        return await self._research_notes.update(
            note_id=note_id,
            entry_kind=entry_kind,
            title=title,
            content=content,
            priority=priority,
            event_date=event_date,
        )
