"""Strategy promotion pipeline routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline


class StrategyPromotionRequest(BaseModel):
    target_stage: str
    readiness: dict[str, Any]
    actor: str = Field(min_length=1, max_length=128)
    review_note: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "approve_evidence_bound_strategy_for_paper_shadow_only_without_"
        "execution_or_capital_authority"
    ]


class StrategyPromotionLifecycleRequest(BaseModel):
    target_stage: str
    reason: str = Field(min_length=1, max_length=8_000)
    actor: str = Field(min_length=1, max_length=128)
    confirmation: Literal[
        "pause_or_retire_strategy_without_execution_or_capital_authority"
    ]


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
                    confirmation=request.confirmation,
                    review_note=request.review_note,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            return service.request_promotion(
                strategy_id,
                target_stage=request.target_stage,
                readiness=request.readiness,
                actor=request.actor,
                confirmation=request.confirmation,
                review_note=request.review_note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/{strategy_id}/lifecycle")
    async def record_strategy_promotion_lifecycle(
        strategy_id: str,
        request: StrategyPromotionLifecycleRequest,
    ) -> dict[str, Any]:
        try:
            return _service().request_lifecycle_transition(
                strategy_id,
                target_stage=request.target_stage,
                reason=request.reason,
                actor=request.actor,
                confirmation=request.confirmation,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.get("/{strategy_id}/events")
    async def list_strategy_promotion_events(
        strategy_id: str,
    ) -> list[dict[str, Any]]:
        return _service().list_events(strategy_id)

    return r


def _service() -> StrategyPromotionPipeline:
    from server.app import get_app_state

    return StrategyPromotionPipeline(db=get_app_state().db)
