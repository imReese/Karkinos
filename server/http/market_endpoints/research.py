"""Market research HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    HTTPException = dependency("HTTPException")
    ResearchBoardItem = dependency("ResearchBoardItem")
    ResearchBoardResponse = dependency("ResearchBoardResponse")
    ResearchNoteCreate = dependency("ResearchNoteCreate")
    ResearchNoteListResponse = dependency("ResearchNoteListResponse")
    ResearchNoteResponse = dependency("ResearchNoteResponse")
    ResearchNoteUpdate = dependency("ResearchNoteUpdate")
    _build_market_data_health_response = dependency(
        "_build_market_data_health_response"
    )
    _build_research_note_stats = dependency("_build_research_note_stats")
    _with_default_market_indices = dependency("_with_default_market_indices")

    def get_watchlist(*args, **kwargs):
        return endpoints["get_watchlist"](*args, **kwargs)

    @r.get("/research-board", response_model=ResearchBoardResponse)
    async def get_research_board() -> ResearchBoardResponse:
        """聚合 watchlist、最新报价与数据健康，供研究工作台消费。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        watchlist = await get_watchlist()
        market_health_assets = _with_default_market_indices(
            [
                {
                    "symbol": item.symbol,
                    "asset_class": item.asset_class,
                    "display_name": item.name,
                }
                for item in watchlist
            ]
        )
        health = _build_market_data_health_response(state, market_health_assets)
        note_stats = (
            _build_research_note_stats(
                state.db.get_research_notes_sync(limit=500, offset=0)
            )
            if state.db is not None and hasattr(state.db, "get_research_notes_sync")
            else {}
        )

        latest_quotes = {item.symbol: item for item in health.quotes}

        items = [
            ResearchBoardItem(
                symbol=item.symbol,
                asset_class=item.asset_class,
                name=item.name,
                is_holding=item.is_holding,
                quantity=item.quantity,
                avg_cost=item.avg_cost,
                market_value=item.market_value,
                unrealized_pnl=item.unrealized_pnl,
                realized_pnl=item.realized_pnl,
                last_snapshot_at=item.last_snapshot_at,
                price=(
                    latest_quotes.get(item.symbol).price
                    if latest_quotes.get(item.symbol)
                    else None
                ),
                volume=None,
                research_count=int(note_stats.get(item.symbol, {}).get("count", 0)),
                last_research_at=str(note_stats.get(item.symbol, {}).get("latest", ""))
                or None,
            )
            for item in watchlist
        ]

        return ResearchBoardResponse(items=items, health=health)

    @r.get("/research-notes", response_model=ResearchNoteListResponse)
    async def get_research_notes(
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
    ) -> ResearchNoteListResponse:
        """列出研究记录，支持按 symbol 过滤。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "get_research_notes"):
            return ResearchNoteListResponse(items=[])

        rows = await state.db.get_research_notes(
            symbol=symbol,
            entry_kind=entry_kind,
            priority=priority,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            limit=limit,
            offset=0,
        )
        return ResearchNoteListResponse(
            items=[ResearchNoteResponse(**row) for row in rows]
        )

    @r.post("/research-notes", response_model=ResearchNoteResponse)
    async def create_research_note(body: ResearchNoteCreate) -> ResearchNoteResponse:
        """新增研究记录，支持 note / thesis / catalyst。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "add_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        symbol = body.symbol.strip()
        title = body.title.strip()
        content = body.content.strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        if not content:
            raise HTTPException(status_code=400, detail="content is required")

        note_id = await state.db.add_research_note(
            symbol=symbol,
            asset_class=body.asset_class,
            entry_kind=body.entry_kind,
            title=title,
            content=content,
            priority=body.priority,
            event_date=body.event_date,
        )
        rows = await state.db.get_research_notes(limit=1, offset=0)
        note = next((row for row in rows if row["id"] == note_id), None)
        if note is None:
            raise HTTPException(status_code=500, detail="failed to fetch created note")
        return ResearchNoteResponse(**note)

    @r.put("/research-notes/{note_id}", response_model=ResearchNoteResponse)
    async def update_research_note(
        note_id: int, body: ResearchNoteUpdate
    ) -> ResearchNoteResponse:
        """更新研究记录内容与分类。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "update_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        title = body.title.strip()
        content = body.content.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        if not content:
            raise HTTPException(status_code=400, detail="content is required")

        updated = await state.db.update_research_note(
            note_id=note_id,
            entry_kind=body.entry_kind,
            title=title,
            content=content,
            priority=body.priority,
            event_date=body.event_date,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="note not found")

        rows = await state.db.get_research_notes(limit=200, offset=0)
        note = next((row for row in rows if row["id"] == note_id), None)
        if note is None:
            raise HTTPException(status_code=500, detail="failed to fetch updated note")
        return ResearchNoteResponse(**note)

    @r.delete("/research-notes/{note_id}")
    async def delete_research_note(note_id: int) -> dict[str, str]:
        """删除研究记录。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "delete_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        deleted = await state.db.delete_research_note(note_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="note not found")
        return {"status": "ok"}

    return r
