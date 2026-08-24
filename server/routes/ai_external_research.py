"""Explicit operator route for evidence-bound external research reports."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.capture import CaptureSelectionError
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.external_research import (
    ExternalBacktestReportRejected,
    HumanExternalBacktestReportRequest,
)
from server.ai_runtime.provider_connectivity import ConnectivityConfigurationError
from server.ai_runtime.store import IdempotencyConflict
from server.composition.ai_application_services import (
    build_external_backtest_report_service,
)


class HumanExternalBacktestReportPayload(BaseModel):
    """One human-authorized external review of one saved backtest."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=128)
    research_question: str = Field(min_length=1, max_length=4_000)
    account_alias: str = Field(min_length=1, max_length=128)
    backtest_result_id: int = Field(gt=0)
    confirmation: Literal[
        "send_selected_saved_backtest_evidence_to_configured_external_model_"
        "without_trade_authority"
    ]


def create_router() -> APIRouter:
    external_router = APIRouter(
        prefix="/api/ai/external-research", tags=["ai-research"]
    )

    @external_router.post("/backtest-reports")
    async def run_external_backtest_report(
        payload: HumanExternalBacktestReportPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        try:
            service = build_external_backtest_report_service(state)
            result = await service.run(
                HumanExternalBacktestReportRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    research_question=payload.research_question,
                    account_alias=payload.account_alias,
                    backtest_result_id=payload.backtest_result_id,
                    confirmation=payload.confirmation,
                )
            )
        except (IdempotencyConflict, EvidenceIdentityMismatch) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ExternalBacktestReportRejected as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ConnectivityConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CaptureSelectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        status_code = {
            "completed": 200,
            "pending": 202,
            "running": 202,
            "partial": 409,
            "blocked": 409,
            "failed": 502,
        }[result.workflow.status.value]
        return JSONResponse(status_code=status_code, content=result.to_dict())

    return external_router
