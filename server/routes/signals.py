"""Signals routes — /api/signals/*"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from server.models import (
    ActionCard,
    ActionTaskStatusUpdate,
    SignalJournalEntry,
    SignalResponse,
)
from server.services.recommendation_flow import build_recommendation_cycle

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

    @r.get("/actions", response_model=list[ActionCard])
    async def get_action_cards(limit: int = 6) -> list[ActionCard]:
        """同步信号到待执行任务，并返回首页动作卡。"""
        from server.app import get_app_state

        state = get_app_state()
        db = state.db
        rows = await db.get_latest_signals(limit=limit)
        scheduler = getattr(state, "scheduler", None)
        portfolio = scheduler.portfolio if scheduler else None
        existing_positions = (
            {}
            if portfolio is None
            else {
                str(symbol): position
                for symbol, position in portfolio.positions.items()
            }
        )
        available_cash = 0.0 if portfolio is None else float(portfolio.cash)
        cycle = build_recommendation_cycle(
            signals=rows,
            available_cash=available_cash,
            existing_positions=existing_positions,
        )

        for task in cycle.tasks:
            db.upsert_action_task_sync(
                source_signal_id=task.source_signal_id,
                symbol=task.symbol,
                title=task.title,
                detail=task.detail,
                direction=task.direction,
                urgency=(
                    "high"
                    if task.direction == "buy" and task.target_weight > 0
                    else "medium"
                ),
                target_weight=task.target_weight,
                price=task.price,
                strategy_id=task.strategy_id,
                timestamp=task.timestamp,
                asset_class=task.asset_class,
            )

        tasks = await db.get_action_tasks(statuses=["pending", "deferred"], limit=limit)
        return [ActionCard(**task) for task in tasks]

    @r.get("/journal", response_model=list[SignalJournalEntry])
    async def get_signal_journal(
        limit: int = 20, offset: int = 0
    ) -> list[SignalJournalEntry]:
        """Return signal → action → risk audit chain entries."""
        from server.app import get_app_state

        state = get_app_state()
        rows = await state.db.list_signal_journal(limit=limit, offset=offset)
        return [SignalJournalEntry(**row) for row in rows]

    @r.patch("/actions/{action_id}", response_model=ActionCard)
    async def update_action_status(
        action_id: int, body: ActionTaskStatusUpdate
    ) -> ActionCard:
        """更新待执行任务状态。"""
        from server.app import get_app_state

        state = get_app_state()
        task = await state.db.update_action_task_status(action_id, body.status)
        if task is None:
            raise HTTPException(status_code=404, detail="Action task not found")
        return ActionCard(**task)

    return r
