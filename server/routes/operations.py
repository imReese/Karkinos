"""Operations center HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.services import operations_projection


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

        return await operations_projection.build_today_operations_payload(
            get_app_state()
        )

    @router.post("/paper-shadow/run")
    async def run_paper_shadow_daily() -> dict[str, Any]:
        from server.dependencies import get_app_state
        from server.services.account_paper_shadow import (
            orchestrate_account_paper_shadow,
        )

        return await orchestrate_account_paper_shadow(get_app_state())

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
