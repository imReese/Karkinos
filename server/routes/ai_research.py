"""Explicit, read-only AI research context capture routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.capture import (
    CaptureEvidenceType,
    CaptureSelectionError,
    HumanContextCaptureRequest,
    HumanResearchContextCaptureService,
)
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.karkinos_source import CaptureProjectionReaders
from server.ai_runtime.store import IdempotencyConflict
from server.services.ai_context_capture_factory import (
    build_human_context_capture_service as build_capture_service,
)


class HumanResearchContextCaptureRequest(BaseModel):
    """One explicit operator request to freeze canonical persisted evidence."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    requested_by: str = Field(min_length=1, max_length=128)
    research_question: str = Field(min_length=1, max_length=4_000)
    account_alias: str = Field(min_length=1, max_length=128)
    evidence_types: list[CaptureEvidenceType] = Field(min_length=1, max_length=7)
    confirmation: Literal["capture_read_only_research_context"]
    backtest_result_id: int | None = Field(default=None, gt=0)
    paper_shadow_run_id: str | None = Field(default=None, min_length=1, max_length=256)
    strategy_id: str | None = Field(default=None, min_length=1, max_length=256)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/ai/research-contexts", tags=["ai-research"])

    @router.post("/capture")
    async def capture_research_context(
        payload: HumanResearchContextCaptureRequest,
    ) -> dict:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        try:
            request = HumanContextCaptureRequest(
                idempotency_key=payload.idempotency_key,
                requested_by=payload.requested_by,
                research_question=payload.research_question,
                account_alias=payload.account_alias,
                evidence_types=tuple(payload.evidence_types),
                confirmation=payload.confirmation,
                backtest_result_id=payload.backtest_result_id,
                paper_shadow_run_id=payload.paper_shadow_run_id,
                strategy_id=payload.strategy_id,
            )
            result = await build_human_context_capture_service(state).capture(request)
        except IdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EvidenceIdentityMismatch as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CaptureSelectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.to_dict()

    return router


def build_human_context_capture_service(
    state,
) -> HumanResearchContextCaptureService:
    """Build audit-only capture services on the application's SQLite database."""
    return build_capture_service(
        state,
        projection_readers=build_capture_projection_readers(),
    )


def build_capture_projection_readers() -> CaptureProjectionReaders:
    """Bind canonical application projections at the HTTP composition edge."""
    from server.routes.account_strategy import _build_contribution_report
    from server.routes.operations import build_today_operations_payload
    from server.routes.portfolio import (
        _current_valuation_snapshot,
        build_account_state_response,
        build_portfolio_snapshot,
    )

    return CaptureProjectionReaders(
        portfolio_snapshot=build_portfolio_snapshot,
        account_state=build_account_state_response,
        operations_today=build_today_operations_payload,
        current_valuation_snapshot=_current_valuation_snapshot,
        strategy_contribution_report=_build_contribution_report,
    )
