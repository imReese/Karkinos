"""Explicit, human-gated Strategy Lab AI research routes."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    formula_operator_catalog,
)
from server.ai_runtime.provider_call_window import (
    ProviderCallDeferred,
    provider_call_deferred_payload,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
)
from server.ai_runtime.store import IdempotencyConflict
from server.ai_runtime.strategy_research import (
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    SealedTestRequest,
    StrategyResearchAuditStore,
    StrategyResearchRejected,
    StrategyResearchSelection,
    StrategyResearchService,
)
from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL,
)
from server.composition.ai_application_services import (
    build_shadow_research_read_service,
    build_shadow_research_write_service,
    build_strategy_research_read_service,
    build_strategy_research_write_service,
)
from server.http.ai_shadow_research_automation import (
    ShadowResearchCitationCallExtensionPayload,
    ShadowResearchCorrectedPanelCitationResumePayload,
    ShadowResearchCorrectedPanelRearmPayload,
    ShadowResearchOutputTruncationCallExtensionPayload,
    ShadowResearchPolicyPayload,
    ShadowResearchPromotionPayload,
    ShadowResearchRetryPayload,
    ShadowResearchTimeoutResumeCallExtensionPayload,
)
from server.http.ai_shadow_research_automation import (
    create_router as create_shadow_research_automation_router,
)
from server.http.ai_shadow_research_qualification import (
    create_router as create_shadow_research_qualification_router,
)
from server.services.strategy_research_factory import (
    strategy_research_model_timeout_seconds as _model_timeout_seconds,
)


class StrategyResearchSelectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved_backtest_result_id: int = Field(gt=0)
    universe: list[str] = Field(min_length=1, max_length=50)
    asset_classes: list[Literal["stock", "etf", "fund", "gold", "bond"]] = Field(
        min_length=1,
        max_length=50,
    )
    dataset_snapshot_id: str = Field(min_length=8, max_length=200)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    sealed_end_date: str | None = Field(default=None, min_length=10, max_length=10)
    frequency: Literal["1d"] = "1d"
    initial_cash: float = Field(gt=0, le=1_000_000_000)
    cost_model_reference: str = Field(
        min_length=1,
        max_length=300,
        pattern=(
            r"^(?:karkinos\.backtest\.multi_asset_commission\.default\.v1|"
            r"karkinos\.backtest\.reviewed_account_fee_schedule\.v1:"
            r"fee_review_[0-9a-f]{32}:[0-9a-f]{64})$"
        ),
    )
    valuation_snapshot_id: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    ledger_cutoff_id: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_research_capital_binding(self) -> "StrategyResearchSelectionPayload":
        if (self.valuation_snapshot_id is None) != (self.ledger_cutoff_id is None):
            raise ValueError("account fact binding must be complete or omitted")
        if self.valuation_snapshot_id is None:
            if self.cost_model_reference != CANONICAL_COST_MODEL_REFERENCE:
                raise ValueError(
                    "strategy-only research requires the canonical estimated cost model"
                )
            if self.initial_cash != NORMALIZED_RESEARCH_NOTIONAL:
                raise ValueError(
                    "strategy-only research requires the versioned normalized notional"
                )
        elif self.cost_model_reference == CANONICAL_COST_MODEL_REFERENCE:
            raise ValueError(
                "account-bound research requires a reviewed account cost model"
            )
        return self

    def to_domain(self) -> StrategyResearchSelection:
        return StrategyResearchSelection(
            saved_backtest_result_id=self.saved_backtest_result_id,
            universe=tuple(self.universe),
            asset_classes=tuple(self.asset_classes),
            dataset_snapshot_id=self.dataset_snapshot_id,
            start_date=self.start_date,
            end_date=self.end_date,
            frequency=self.frequency,
            initial_cash=self.initial_cash,
            sealed_end_date=self.sealed_end_date,
            cost_model_reference=self.cost_model_reference,
            valuation_snapshot_id=self.valuation_snapshot_id,
            ledger_cutoff_id=self.ledger_cutoff_id,
        )


class HypothesisGenerationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=128)
    account_alias: str = Field(min_length=1, max_length=128)
    research_question: str = Field(min_length=1, max_length=4_000)
    selection: StrategyResearchSelectionPayload
    confirmation: Literal[
        "send_selected_sanitized_strategy_research_evidence_to_configured_"
        "external_model_without_trade_authority"
    ]


class FormulaBacktestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=200)
    draft_id: str = Field(min_length=1, max_length=200)
    confirmation: Literal[
        "run_selected_validated_formula_with_canonical_backtest_without_trade_authority"
    ]


class CritiquePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=200)
    draft_id: str = Field(min_length=1, max_length=200)
    backtest_run_id: str = Field(min_length=1, max_length=200)
    confirmation: Literal[
        "send_selected_formula_and_canonical_backtest_evidence_to_configured_"
        "external_model_without_trade_authority"
    ]


class SealedTestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=200)
    draft_id: str = Field(min_length=1, max_length=200)
    backtest_run_id: str = Field(min_length=1, max_length=200)
    benchmark_return: float | None = None
    confirmation: Literal[
        "run_frozen_champion_sealed_holdout_evaluation_without_trade_authority"
    ]


class HumanReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)
    critique_id: str = Field(min_length=1, max_length=200)
    reviewer: str = Field(min_length=1, max_length=128)
    disposition: Literal["accepted_for_more_research", "rejected", "needs_revision"]
    notes: str = Field(min_length=1, max_length=8_000)
    confirmation: Literal[
        "record_human_strategy_research_review_without_trade_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/ai/strategy-research", tags=["ai-research"])

    @router.get("/formula-catalog")
    async def get_formula_catalog() -> dict[str, Any]:
        """Pure local catalog read; no DB, provider, secret, or refresh."""
        return formula_operator_catalog()

    @router.get("/sessions/{session_id}")
    async def get_strategy_research_session(session_id: str) -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        service = _build_read_service(state)
        try:
            return service.get_session(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    # These two provider-capable routes are explicit human research commands.
    # Lifespan, daily qualification, and the automatic enqueue loop never call
    # them; automatic provider work crosses only the durable worker boundary.
    @router.post("/hypotheses")
    async def generate_strategy_hypotheses(
        payload: HypothesisGenerationPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            service = _build_write_service(state, external=True)
            result = await service.generate_hypotheses(
                HypothesisGenerationRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    account_alias=payload.account_alias,
                    research_question=payload.research_question,
                    selection=payload.selection.to_domain(),
                    confirmation=payload.confirmation,
                )
            )
            return _status_response(result)
        except ProviderCallDeferred as exc:
            return _provider_call_deferred_response(exc)
        except Exception as exc:
            _raise_http(exc)

    @router.post("/backtests")
    async def run_strategy_formula_backtest(
        payload: FormulaBacktestPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            service = _build_write_service(state, external=False)
            result = await service.run_formula_backtest(
                FormulaBacktestRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    session_id=payload.session_id,
                    draft_id=payload.draft_id,
                    confirmation=payload.confirmation,
                )
            )
            return _status_response(result)
        except Exception as exc:
            _raise_http(exc)

    @router.post("/critiques")
    async def critique_strategy_backtest(payload: CritiquePayload) -> JSONResponse:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            service = _build_write_service(state, external=True)
            result = await service.critique(
                CritiqueRequest(
                    idempotency_key=payload.idempotency_key,
                    requested_by=payload.requested_by,
                    session_id=payload.session_id,
                    draft_id=payload.draft_id,
                    backtest_run_id=payload.backtest_run_id,
                    confirmation=payload.confirmation,
                )
            )
            return _status_response(result)
        except ProviderCallDeferred as exc:
            return _provider_call_deferred_response(exc)
        except Exception as exc:
            _raise_http(exc)

    @router.post("/sealed-tests")
    async def run_sealed_holdout_test(payload: SealedTestPayload) -> JSONResponse:
        return await _run_sealed_holdout_test(payload)

    @router.post("/sessions/{session_id}/reviews")
    async def record_strategy_research_review(
        session_id: str,
        payload: HumanReviewPayload,
    ) -> JSONResponse:
        from server.dependencies import get_app_state

        state = get_app_state()
        try:
            db_path = _database_path(state.db)
            store = StrategyResearchAuditStore(db_path)
            store.init()
            session = _build_read_service(state).get_session(session_id)
            if (
                session["status"] != "completed"
                or session["binding_validity"] != "valid"
            ):
                raise StrategyResearchRejected(
                    "human final review requires a current completed session"
                )
            critique = store.get_critique(payload.critique_id)
            if (
                critique["session_id"] != session_id
                or critique["status"] != "completed"
                or not isinstance(critique.get("artifact"), dict)
                or content_fingerprint(critique["artifact"])
                != critique.get("artifact_fingerprint")
            ):
                raise StrategyResearchRejected(
                    "human final review requires the exact completed critique"
                )
            critique_replay_valid, _ = store.verify_events(payload.critique_id)
            if not critique_replay_valid:
                raise StrategyResearchRejected("strategy critique audit drift")
            review = store.save_review(
                idempotency_key=payload.idempotency_key,
                session_id=session_id,
                critique_id=payload.critique_id,
                critique_artifact_fingerprint=str(critique["artifact_fingerprint"]),
                reviewer=payload.reviewer,
                disposition=payload.disposition,
                notes=payload.notes,
                confirmation=payload.confirmation,
                created_at=_utc_now(),
            )
            return JSONResponse(
                status_code=201,
                content={
                    **review,
                    "non_authoritative": True,
                    "non_executable": True,
                    "requires_human_review": False,
                    "decision_input_created": False,
                    "trade_plan_created": False,
                    "authority_effect": "none",
                },
            )
        except Exception as exc:
            _raise_http(exc)

    shadow_automation_router = create_shadow_research_automation_router(
        build_write_service=lambda state: _build_shadow_write_service(state),
        build_job_scheduler=lambda state: _build_shadow_job_scheduler(state),
        build_read_service=lambda state: _build_shadow_read_service(state),
        raise_http=lambda exc: _raise_http(exc),
    )
    router.routes.extend(shadow_automation_router.routes)
    router.include_router(create_shadow_research_qualification_router())
    return router


def _build_write_service(state: Any, *, external: bool) -> StrategyResearchService:
    return build_strategy_research_write_service(
        state,
        external=external,
    )


def _build_read_service(state: Any) -> StrategyResearchService:
    return build_strategy_research_read_service(state)


def _build_shadow_write_service(state: Any) -> Any:
    return build_shadow_research_write_service(state)


def _build_shadow_job_scheduler(state: Any) -> Any:
    from server.composition.ai_shadow_research_automation import (
        compose_ai_shadow_research_job_scheduler,
    )
    from server.services.ai_shadow_research_job_scheduler import (
        AiShadowResearchJobScheduler,
    )

    return compose_ai_shadow_research_job_scheduler(
        state,
        service_type=AiShadowResearchJobScheduler,
    )


def _build_shadow_read_service(state: Any) -> Any:
    return build_shadow_research_read_service(state)


def _read_shadow_research_readiness() -> dict[str, Any]:
    """Bounded provider-free policy projection for loopback readiness checks."""
    from server.dependencies import get_app_state

    state = get_app_state()
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return _build_shadow_read_service(state).readiness_status()


async def _run_sealed_holdout_test(payload: SealedTestPayload) -> JSONResponse:
    from server.dependencies import get_app_state

    state = get_app_state()
    try:
        service = _build_write_service(state, external=False)
        result = await service.sealed_test(
            SealedTestRequest(
                idempotency_key=payload.idempotency_key,
                requested_by=payload.requested_by,
                session_id=payload.session_id,
                draft_id=payload.draft_id,
                backtest_run_id=payload.backtest_run_id,
                confirmation=payload.confirmation,
                benchmark_return=(
                    Decimal(str(payload.benchmark_return))
                    if payload.benchmark_return is not None
                    else None
                ),
            )
        )
        return _status_response(result)
    except Exception as exc:
        _raise_http(exc)


def _strategy_research_model_timeout_seconds(settings: Any | None) -> float:
    """Compatibility export for the former route-level timeout helper."""
    return _model_timeout_seconds(settings)


def _database_path(db: Any) -> Path:
    path = getattr(db, "_path", None)
    if path is None:
        raise ConnectivityConfigurationError("database path is unavailable")
    return Path(path)


def _status_response(result: dict[str, Any]) -> JSONResponse:
    status = str(result.get("status") or "failed")
    status_code = {
        "completed": 200,
        "pending": 202,
        "running": 202,
        "partial": 409,
        "blocked": 409,
        "failed": 502,
    }.get(status, 500)
    return JSONResponse(status_code=status_code, content=result)


def _provider_call_deferred_response(exc: ProviderCallDeferred) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content=provider_call_deferred_payload(exc.decision),
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, IdempotencyConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ConnectivityConfigurationError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (StrategyResearchRejected, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
