"""HTTP delivery for exact account-qualified paper/shadow approval."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.composition.ai_application_services import (
    build_shadow_research_qualification_service,
    build_shadow_research_write_service,
)


class ShadowResearchQualificationPromotionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "approve_exact_account_qualified_candidate_for_paper_shadow_only_without_"
        "order_trade_or_capital_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/shadow-qualification/run")
    async def run_shadow_research_qualification() -> dict:
        """Replay account qualification locally without provider or trade authority."""
        from server.dependencies import get_app_state

        try:
            return await build_shadow_research_qualification_service(
                get_app_state()
            ).run_once()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/shadow-qualification/runs/{source_run_id}")
    async def replay_shadow_research_qualification(
        source_run_id: Annotated[
            str,
            Path(
                min_length=1,
                max_length=160,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
            ),
        ],
    ) -> dict:
        """Qualify one exact still-current daily artifact source, provider-free."""
        from server.dependencies import get_app_state

        try:
            return await build_shadow_research_qualification_service(
                get_app_state()
            ).run_once(source_run_id=source_run_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post(
        "/shadow-qualification-candidates/{qualification_candidate_id}/"
        "paper-shadow-approvals"
    )
    async def approve_shadow_research_qualification_candidate(
        qualification_candidate_id: str,
        payload: ShadowResearchQualificationPromotionPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        try:
            result = build_shadow_research_write_service(
                get_app_state()
            ).approve_qualification_candidate(
                qualification_candidate_id,
                approved_by=payload.approved_by,
                notes=payload.notes,
                confirmation=payload.confirmation,
            )
            return JSONResponse(status_code=201, content=result)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


__all__ = ["ShadowResearchQualificationPromotionPayload", "create_router"]
