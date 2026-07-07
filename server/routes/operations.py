"""Operations center API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.routes.decision import _today_decision_payload, _trading_plan_positions
from server.services.daily_operations import build_daily_operations_summary
from server.services.daily_trading_plan import build_daily_trading_plan
from server.services.operations_today import build_operations_today_summary
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan


class PaperShadowRunReviewRequest(BaseModel):
    reviewed_at: str
    review_status: str = Field(..., min_length=1)
    review_notes: str = Field(..., min_length=1)
    reviewer: str | None = None


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/operations", tags=["operations"])

    @router.get("/today")
    async def today_operations() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")

        decision_payload, trading_plan = await _current_decision_and_trading_plan(state)
        pending_manual_orders = _call_list(
            state.db,
            "list_manual_orders_sync",
            status="pending_confirm",
            limit=50,
            offset=0,
        )
        order_facts = _call_list(
            state.db,
            "list_orders_sync",
            limit=100,
            offset=0,
        )
        fill_facts = _call_list(
            state.db,
            "list_fills_sync",
            limit=100,
            offset=0,
        )
        automation_runs = _call_list(
            state.db,
            "list_automation_runs_sync",
            limit=20,
            offset=0,
        )
        ledger_review_count = len(
            _call_list(
                state.db,
                "get_ledger_entries_sync",
                limit=50,
                offset=0,
            )
        )
        daily_operations = build_daily_operations_summary(
            decision_summary=decision_payload.get("summary"),
            candidates=decision_payload.get("candidates", []),
            pending_manual_orders=pending_manual_orders,
            order_facts=order_facts,
            fill_facts=fill_facts,
            ledger_review_count=ledger_review_count,
        )
        paper_shadow_run = _latest_paper_shadow_run(
            state.db,
            plan_date=str(
                trading_plan.get("plan_date")
                or decision_payload.get("decision_date")
                or ""
            ),
        )
        return build_operations_today_summary(
            decision_payload=decision_payload,
            trading_plan=trading_plan,
            daily_operations=daily_operations,
            order_facts=order_facts,
            fill_facts=fill_facts,
            paper_shadow_run=paper_shadow_run,
            automation_runs=automation_runs,
        )

    @router.post("/paper-shadow/run")
    async def run_paper_shadow_daily() -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")

        decision_payload, trading_plan = await _current_decision_and_trading_plan(state)
        return run_paper_shadow_from_trading_plan(
            db=state.db,
            trading_plan=trading_plan,
            generated_at=trading_plan.get("generated_at")
            or decision_payload.get("generated_at"),
        )

    @router.post("/paper-shadow/runs/{run_id}/review")
    async def record_paper_shadow_run_review(
        run_id: str,
        payload: PaperShadowRunReviewRequest,
    ) -> dict[str, Any]:
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        review_status = payload.review_status.strip().lower()
        writer = getattr(state.db, "record_paper_shadow_run_review_sync", None)
        if not callable(writer):
            raise HTTPException(
                status_code=501,
                detail="paper shadow run reviews are not supported by this database",
            )
        try:
            reviewed = writer(
                run_id=run_id,
                reviewed_at=payload.reviewed_at,
                review_status=review_status,
                review_notes=payload.review_notes,
                reviewer=payload.reviewer,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if reviewed is None:
            raise HTTPException(status_code=404, detail="paper shadow run not found")
        return reviewed

    return router


async def _current_decision_and_trading_plan(
    state: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    decision_payload = await _today_decision_payload(state)
    trading_plan = build_daily_trading_plan(
        decision_payload=decision_payload,
        config=state.config,
        positions=_trading_plan_positions(state),
    )
    return decision_payload, trading_plan


def _call_list(db: Any, name: str, **kwargs: Any) -> list[dict[str, Any]]:
    reader = getattr(db, name, None)
    if not callable(reader):
        return []
    try:
        rows = reader(**kwargs)
    except TypeError:
        rows = reader()
    return list(rows or [])


def _latest_paper_shadow_run(
    db: Any,
    *,
    plan_date: str,
) -> dict[str, Any] | None:
    reader = getattr(db, "latest_paper_shadow_run_sync", None)
    if not callable(reader):
        return None
    try:
        return reader(plan_date=plan_date) if plan_date else reader()
    except TypeError:
        return reader()
