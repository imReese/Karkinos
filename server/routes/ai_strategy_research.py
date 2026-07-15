"""Explicit, human-gated Strategy Lab AI research routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.evidence import CanonicalEvidenceRepository
from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    formula_operator_catalog,
)
from server.ai_runtime.provider_connectivity import (
    ConnectivityConfigurationError,
    load_provider_connectivity_settings,
)
from server.ai_runtime.store import AiAuditStore, IdempotencyConflict
from server.ai_runtime.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    REVIEW_CONFIRMATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    StrategyResearchAuditStore,
    StrategyResearchRejected,
    StrategyResearchSelection,
    StrategyResearchService,
)
from server.bootstrap import resolve_config_path, resolve_data_dir
from server.routes.ai_research import build_human_context_capture_service


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
    frequency: Literal["1d"] = "1d"
    initial_cash: float = Field(gt=0, le=1_000_000_000)
    cost_model_reference: Literal[
        "karkinos.backtest.multi_asset_commission.default.v1"
    ] = CANONICAL_COST_MODEL_REFERENCE
    valuation_snapshot_id: str | None = Field(default=None, max_length=200)
    ledger_cutoff_id: int | None = Field(default=None, ge=0)

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
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        service = _build_read_service(state)
        try:
            return service.get_session(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/hypotheses")
    async def generate_strategy_hypotheses(
        payload: HypothesisGenerationPayload,
    ) -> JSONResponse:
        from server.app import get_app_state

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
        except Exception as exc:
            _raise_http(exc)

    @router.post("/backtests")
    async def run_strategy_formula_backtest(
        payload: FormulaBacktestPayload,
    ) -> JSONResponse:
        from server.app import get_app_state

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
        from server.app import get_app_state

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
        except Exception as exc:
            _raise_http(exc)

    @router.post("/sessions/{session_id}/reviews")
    async def record_strategy_research_review(
        session_id: str,
        payload: HumanReviewPayload,
    ) -> JSONResponse:
        from server.app import get_app_state

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

    return router


def _build_write_service(state: Any, *, external: bool) -> StrategyResearchService:
    if state.db is None:
        raise ConnectivityConfigurationError("database is not initialized")
    db_path = _database_path(state.db)
    evidence_repository = CanonicalEvidenceRepository(db_path)
    ai_store = AiAuditStore(db_path)
    research_store = StrategyResearchAuditStore(db_path)
    evidence_repository.init()
    ai_store.init()
    research_store.init()
    settings = (
        load_provider_connectivity_settings(resolve_config_path()) if external else None
    )
    return StrategyResearchService(
        db=state.db,
        db_path=db_path,
        settings=settings,
        capture_service=build_human_context_capture_service(state),
        evidence_repository=evidence_repository,
        ai_store=ai_store,
        research_store=research_store,
        data_store=DataStore(resolve_data_dir()),
    )


def _build_read_service(state: Any) -> StrategyResearchService:
    """Build without init, DataStore construction, config, provider, or secrets."""
    db_path = _database_path(state.db)
    return StrategyResearchService(
        db=state.db,
        db_path=db_path,
        settings=None,
        capture_service=None,  # type: ignore[arg-type]
        evidence_repository=CanonicalEvidenceRepository(db_path),
        ai_store=AiAuditStore(db_path),
        research_store=StrategyResearchAuditStore(db_path),
        data_store=None,  # type: ignore[arg-type]
    )


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
