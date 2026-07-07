"""Strategy promotion pipeline routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline


class StrategyPromotionRequest(BaseModel):
    target_stage: str
    readiness: dict[str, Any]
    actor: str | None = None


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/strategy-promotion", tags=["strategy-promotion"])

    @r.get("/states")
    async def list_strategy_promotion_states() -> list[dict[str, Any]]:
        return _service().list_states()

    @r.post("/{strategy_id}/promote")
    async def promote_strategy(
        strategy_id: str,
        request: StrategyPromotionRequest,
    ) -> dict[str, Any]:
        service = _service()
        if request.target_stage == "paper_shadow":
            try:
                service.evaluate_readiness(request.readiness, actor=request.actor)
                return service.request_promotion(
                    strategy_id,
                    target_stage=request.target_stage,
                    readiness=request.readiness,
                    actor=request.actor,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            return service.request_promotion(
                strategy_id,
                target_stage=request.target_stage,
                readiness=request.readiness,
                actor=request.actor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return r


def _service() -> StrategyPromotionPipeline:
    from server.app import get_app_state

    return StrategyPromotionPipeline(db=get_app_state().db)
