"""Signals routes — /api/signals/*"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from server.models import SignalResponse

logger = logging.getLogger(__name__)


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/signals", tags=["signals"])

    @r.get("", response_model=list[SignalResponse])
    async def get_signals(limit: int = 50, offset: int = 0) -> list[SignalResponse]:
        """获取信号历史（分页）。"""
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        rows = await db.get_signals(limit=limit, offset=offset)
        return [
            SignalResponse(
                id=row["id"],
                timestamp=row["timestamp"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                direction=row["direction"],
                target_weight=row["target_weight"],
                price=row.get("price"),
                asset_class=row.get("asset_class", "stock"),
            )
            for row in rows
        ]

    @r.get("/latest", response_model=list[SignalResponse])
    async def get_latest_signals(limit: int = 10) -> list[SignalResponse]:
        """获取最新信号。"""
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        rows = await db.get_latest_signals(limit=limit)
        return [
            SignalResponse(
                id=row["id"],
                timestamp=row["timestamp"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                direction=row["direction"],
                target_weight=row["target_weight"],
                price=row.get("price"),
                asset_class=row.get("asset_class", "stock"),
            )
            for row in rows
        ]

    return r
