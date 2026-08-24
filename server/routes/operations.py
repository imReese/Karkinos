"""Operations center HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.services import operations_projection
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
        from server.dependencies import get_app_state

        return await build_today_operations_payload(get_app_state())

    @router.post("/paper-shadow/run")
    async def run_paper_shadow_daily() -> dict[str, Any]:
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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


async def build_today_operations_payload(state: Any) -> dict[str, Any]:
    """Compatibility wrapper for the canonical Operations projection."""
    return await operations_projection.build_today_operations_payload(state)


async def _current_decision_and_trading_plan(
    state: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return await operations_projection.current_decision_and_trading_plan(state)


async def current_decision_and_trading_plan(
    state: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compatibility wrapper for Decision plus daily-plan composition."""
    return await _current_decision_and_trading_plan(state)


def _build_controlled_per_order_pilot_readiness(
    state: Any,
    *,
    broker_adapter_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the canonical pilot-readiness projection."""
    return operations_projection.build_controlled_per_order_pilot_readiness(
        state,
        broker_adapter_readiness=broker_adapter_readiness,
    )
