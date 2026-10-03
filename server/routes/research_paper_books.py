"""Explicit independent paper-book commands nested under a research observation."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from server.contracts.http.research_paper_books import (
    PauseResearchPaperBookRequest,
    SettleResearchPaperBookRequest,
    StartResearchPaperBookRequest,
)
from server.services.research_paper_books import ResearchPaperBookService


def _service():
    from server.dependencies import get_app_state

    return ResearchPaperBookService(get_app_state().db)


def _error(exc):
    detail = str(exc)
    return HTTPException(
        status_code=404
        if detail.endswith("not_found")
        else 409
        if "conflict" in detail
        else 422,
        detail=detail,
    )


def create_router():
    router = APIRouter(
        prefix="/api/research-observations/{observation_id}/paper-book",
        tags=["research"],
    )

    @router.get("")
    def get(observation_id: UUID):
        try:
            return _service().get(str(observation_id))
        except ValueError as exc:
            raise _error(exc) from exc

    @router.post("")
    def start(observation_id: UUID, request: StartResearchPaperBookRequest):
        try:
            return _service().start(
                str(observation_id),
                request_id=str(request.request_id),
                initial_cash=request.initial_cash,
                cost_assumptions=request.cost_assumptions,
            )
        except ValueError as exc:
            raise _error(exc) from exc

    @router.post("/settle")
    def settle(observation_id: UUID, request: SettleResearchPaperBookRequest):
        try:
            return _service().settle(
                str(observation_id),
                request_id=str(request.request_id),
                expected_version=request.expected_version,
                dataset_id=request.dataset_id,
            )
        except ValueError as exc:
            raise _error(exc) from exc

    @router.post("/pause")
    def pause(observation_id: UUID, request: PauseResearchPaperBookRequest):
        try:
            return _service().pause(
                str(observation_id),
                request_id=str(request.request_id),
                expected_version=request.expected_version,
            )
        except ValueError as exc:
            raise _error(exc) from exc

    return router
