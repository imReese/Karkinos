"""Independent target shadow observations; explicit commands, persisted reads."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from server.contracts.http.research_observations import (
    AdvanceResearchObservationRequest,
    PauseResearchObservationRequest,
    StartResearchObservationRequest,
)
from server.services.research_observations import ResearchObservationService


def _service() -> ResearchObservationService:
    from server.dependencies import get_app_state

    return ResearchObservationService(get_app_state().db)


def _error(exc: ValueError) -> HTTPException:
    detail = str(exc)
    status = (
        404 if detail.endswith("not_found") else 409 if "conflict" in detail else 422
    )
    return HTTPException(status_code=status, detail=detail)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/research-observations", tags=["research"])

    @router.get("")
    def list_observations(
        limit: int = Query(default=50, ge=1, le=100),
        source_backtest_result_id: int | None = Query(default=None, gt=0),
    ) -> list[dict[str, Any]]:
        return _service().repository.list(
            limit=limit, source_backtest_result_id=source_backtest_result_id
        )

    @router.get("/{observation_id}")
    def get_observation(observation_id: UUID) -> dict[str, Any]:
        result = _service().repository.get(str(observation_id))
        if result is None:
            raise HTTPException(status_code=404, detail="observation_not_found")
        return result

    @router.post("")
    async def start_observation(
        request: StartResearchObservationRequest,
    ) -> dict[str, Any]:
        try:
            return await _service().start(
                **{**request.model_dump(), "request_id": str(request.request_id)}
            )
        except ValueError as exc:
            raise _error(exc) from exc

    @router.post("/{observation_id}/advance")
    def advance_observation(
        observation_id: UUID, request: AdvanceResearchObservationRequest
    ) -> dict[str, Any]:
        try:
            return _service().advance(
                str(observation_id),
                **{**request.model_dump(), "request_id": str(request.request_id)},
            )
        except ValueError as exc:
            raise _error(exc) from exc

    @router.post("/{observation_id}/pause")
    def pause_observation(
        observation_id: UUID, request: PauseResearchObservationRequest
    ) -> dict[str, Any]:
        try:
            return _service().pause(
                str(observation_id),
                **{**request.model_dump(), "request_id": str(request.request_id)},
            )
        except ValueError as exc:
            raise _error(exc) from exc

    return router
