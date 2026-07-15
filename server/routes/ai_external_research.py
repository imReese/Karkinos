"""Explicit operator route for evidence-bound external research reports."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.capture import CaptureSelectionError
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from server.ai_runtime.external_research import (
    ExternalBacktestReportAuditStore,
    ExternalBacktestReportRejected,
    HumanExternalBacktestReportRequest,
    HumanExternalBacktestReportService,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.bootstrap import resolve_config_path
from server.routes.ai_research import build_human_context_capture_service


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
    router = APIRouter()
    external_router = APIRouter(
        prefix="/api/ai/external-research", tags=["ai-research"]
    )

    @external_router.post("/backtest-reports")
    async def run_external_backtest_report(
        payload: HumanExternalBacktestReportPayload,
    ) -> JSONResponse:
        from server.app import get_app_state

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

    from server.routes.ai_strategy_research import (
        create_router as create_strategy_router,
    )

    router.include_router(external_router)
    router.include_router(create_strategy_router())
    return router


def build_external_backtest_report_service(
    state,
) -> HumanExternalBacktestReportService:
    """Build the explicit external boundary on AI-only audit storage."""
    db_path = _database_path(state.db)
    evidence_repository = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    report_store = ExternalBacktestReportAuditStore(db_path)
    evidence_repository.init()
    ai_store.init()
    report_store.init()
    return HumanExternalBacktestReportService(
        settings=load_provider_connectivity_settings(resolve_config_path()),
        capture_service=build_human_context_capture_service(state),
        evidence_repository=evidence_repository,
        ai_store=ai_store,
        report_store=report_store,
    )


def _database_path(db) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ConnectivityConfigurationError("database path is unavailable")
    return Path(path)
