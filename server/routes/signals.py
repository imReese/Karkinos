"""Signals routes — /api/signals/*"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.store import IdempotencyConflict
from server.models import (
    ActionCard,
    ActionTaskStatusUpdate,
    SignalJournalEntry,
    SignalResponse,
)
from server.services.decision_outcome_review import (
    DecisionOutcomeReviewRejected,
    DecisionOutcomeReviewRequest,
    DecisionOutcomeReviewService,
    DecisionOutcomeReviewStore,
    DecisionOutcomeReviewTargetDrift,
)
from server.services.recommendation_flow import build_recommendation_cycle

logger = logging.getLogger(__name__)


class SignalJournalReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    reviewed_by: str = Field(min_length=1, max_length=128)
    user_decision: Literal["acted", "ignored", "deferred", "blocked"]
    outcome: Literal[
        "evidence_supported",
        "evidence_not_supported",
        "risk_gate_validated",
        "not_executed",
        "inconclusive",
    ]
    note: str = Field(min_length=1, max_length=4_000)
    expected_target_fingerprint: str = Field(min_length=64, max_length=64)
    confirmation: Literal[
        "record_evidence_bound_decision_review_without_trade_or_capital_authority"
    ]


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

    @r.post("/journal/{signal_id}/review/preview")
    async def preview_signal_journal_review(signal_id: int) -> dict:
        """Build a read-only review target from persisted evidence."""
        from server.app import get_app_state

        try:
            service = _decision_outcome_review_service(get_app_state())
            target = await asyncio.to_thread(service.preview, signal_id)
            return target.to_dict()
        except Exception as exc:
            _raise_decision_outcome_review_http_error(exc)

    @r.post("/journal/{signal_id}/review")
    async def record_signal_journal_review(
        signal_id: int,
        body: SignalJournalReviewRequest,
    ) -> dict:
        """Record an idempotent review bound to the exact previewed evidence."""
        from server.app import get_app_state

        try:
            service = _decision_outcome_review_service(get_app_state())
            result = await asyncio.to_thread(
                service.review,
                signal_id,
                DecisionOutcomeReviewRequest(
                    idempotency_key=body.idempotency_key,
                    reviewed_by=body.reviewed_by,
                    user_decision=body.user_decision,
                    outcome=body.outcome,
                    note=body.note,
                    expected_target_fingerprint=body.expected_target_fingerprint,
                    confirmation=body.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_decision_outcome_review_http_error(exc)

    @r.get("/journal/reviews/{review_id}")
    async def get_signal_journal_review(review_id: str) -> dict:
        """Revalidate one stored review against current persisted evidence."""
        from server.app import get_app_state

        try:
            service = _decision_outcome_review_service(get_app_state())
            result = await asyncio.to_thread(service.get, review_id)
            return result.to_dict()
        except Exception as exc:
            _raise_decision_outcome_review_http_error(exc)

    @r.get("/journal/reviews/{review_id}/replay")
    async def replay_signal_journal_review(review_id: str) -> dict:
        """Replay the append-only decision review audit chain."""
        from server.app import get_app_state

        try:
            service = _decision_outcome_review_service(get_app_state())
            replay = await asyncio.to_thread(service.replay, review_id)
            return replay.to_dict()
        except Exception as exc:
            _raise_decision_outcome_review_http_error(exc)

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


def _decision_outcome_review_service(state) -> DecisionOutcomeReviewService:
    db = getattr(state, "db", None)
    path = getattr(db, "_path", None)
    if db is None or path is None:
        raise DecisionOutcomeReviewRejected("database is not initialized")
    return DecisionOutcomeReviewService(
        db=db,
        store=DecisionOutcomeReviewStore(Path(path)),
        now=lambda: datetime.now(timezone.utc).isoformat(),
    )


def _raise_decision_outcome_review_http_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (IdempotencyConflict, DecisionOutcomeReviewTargetDrift)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (DecisionOutcomeReviewRejected, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc
