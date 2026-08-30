"""Decision platform HTTP routes — /api/decision/*."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.ai_runtime.store import IdempotencyConflict
from server.services import decision_application
from server.services.decision_quality import (
    DecisionQualityCaptureRejected,
    DecisionQualityCaptureRequest,
    DecisionQualityService,
    DecisionQualityStore,
    DecisionQualityTargetDrift,
)


class DecisionQualityCaptureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=256)
    captured_by: str = Field(min_length=1, max_length=128)
    expected_target_fingerprint: str = Field(min_length=64, max_length=64)
    confirmation: Literal[
        "capture_decision_quality_evidence_without_financial_or_trading_authority"
    ]


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/decision", tags=["decision"])

    @router.get("/today")
    async def get_today_decision() -> dict[str, Any]:
        from server.dependencies import get_app_state

        return await _today_decision_payload(get_app_state())

    @router.get("/quality")
    async def get_decision_quality() -> dict[str, Any]:
        """Project the current target and captured North Star history."""
        from server.dependencies import get_app_state

        try:
            state = get_app_state()
            payload = await _today_decision_payload(state)
            service = _decision_quality_service(state)
            view = await asyncio.to_thread(service.view, payload)
            return view.to_dict()
        except Exception as exc:
            _raise_decision_quality_http_error(exc)

    @router.post("/quality/capture")
    async def capture_decision_quality(
        body: DecisionQualityCaptureBody,
    ) -> dict[str, Any]:
        """Append one evidence-bound daily quality snapshot."""
        from server.dependencies import get_app_state

        try:
            state = get_app_state()
            payload = await _today_decision_payload(state)
            service = _decision_quality_service(state)
            result = await asyncio.to_thread(
                service.capture,
                payload,
                DecisionQualityCaptureRequest(
                    idempotency_key=body.idempotency_key,
                    captured_by=body.captured_by,
                    expected_target_fingerprint=body.expected_target_fingerprint,
                    confirmation=body.confirmation,
                ),
            )
            return result.to_dict()
        except Exception as exc:
            _raise_decision_quality_http_error(exc)

    @router.get("/quality/snapshots/{snapshot_id}")
    async def get_decision_quality_snapshot(snapshot_id: str) -> dict[str, Any]:
        """Read one immutable capture together with its audit replay."""
        from server.dependencies import get_app_state

        try:
            service = _decision_quality_service(get_app_state())
            return await asyncio.to_thread(service.get, snapshot_id)
        except Exception as exc:
            _raise_decision_quality_http_error(exc)

    @router.get("/quality/snapshots/{snapshot_id}/replay")
    async def replay_decision_quality_snapshot(snapshot_id: str) -> dict[str, Any]:
        """Verify the append-only capture event chain."""
        from server.dependencies import get_app_state

        try:
            service = _decision_quality_service(get_app_state())
            replay = await asyncio.to_thread(service.replay, snapshot_id)
            return replay.to_dict()
        except Exception as exc:
            _raise_decision_quality_http_error(exc)

    @router.get("/trading-plan")
    async def get_daily_trading_plan() -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        portfolio_context = await asyncio.to_thread(
            _decision_portfolio_context,
            state,
        )
        decision_payload = await _today_decision_payload(
            state,
            portfolio_context=portfolio_context,
        )
        return await asyncio.to_thread(
            _build_daily_trading_plan_for_state,
            state,
            decision_payload,
            portfolio_context,
        )

    @router.post("/pre-trade-risk/batch")
    async def run_batch_pre_trade_risk() -> dict[str, Any]:
        from server.dependencies import get_app_state

        return await run_batch_pre_trade_risk_for_state(get_app_state())

    @router.get("/intraday")
    async def get_intraday_decision() -> dict[str, Any]:
        from server.dependencies import get_app_state

        return await decision_application.intraday_decision_payload(get_app_state())

    return router


def _decision_quality_service(state: Any) -> DecisionQualityService:
    db = getattr(state, "db", None)
    path = getattr(db, "_path", None)
    if db is None or path is None:
        raise DecisionQualityCaptureRejected("database is not initialized")
    return DecisionQualityService(
        store=DecisionQualityStore(Path(path)),
        now=lambda: datetime.now(timezone.utc).isoformat(),
    )


def _build_daily_trading_plan_for_state(
    state: Any,
    decision_payload: dict[str, Any],
    portfolio_context: dict[str, Any],
) -> dict[str, Any]:
    from server.services.daily_research_operation_preview import (
        resolve_latest_verified_research_operation_preview,
    )
    from server.services.daily_trading_plan import build_daily_trading_plan
    from server.services.research_operation_instruments import (
        build_research_operation_instruments,
    )

    research_operation_preview = resolve_latest_verified_research_operation_preview(
        getattr(state, "db", None),
        plan_date=str(decision_payload.get("decision_date") or "") or None,
    )
    plan = build_daily_trading_plan(
        decision_payload=decision_payload,
        config=getattr(state, "config", None),
        positions=_trading_plan_positions(
            state,
            portfolio_context=portfolio_context,
        ),
        research_operation_preview=research_operation_preview,
    )
    plan["research_operation_instruments"] = build_research_operation_instruments(
        getattr(state, "db", None),
        plan.get("research_operation_preview"),
    )
    return plan


def _raise_decision_quality_http_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (IdempotencyConflict, DecisionQualityTargetDrift)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (DecisionQualityCaptureRejected, ValueError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


async def run_batch_pre_trade_risk_for_state(state: Any) -> dict[str, Any]:
    """Compatibility wrapper for the former route-owned application flow."""
    return await decision_application.run_batch_pre_trade_risk_for_state(state)


async def _today_decision_payload(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await decision_application.today_decision_payload(
        state,
        portfolio_context=portfolio_context,
    )


def _trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return decision_application.trading_plan_positions(
        state,
        portfolio_context=portfolio_context,
    )


def _decision_portfolio_context(state: Any) -> dict[str, Any]:
    return decision_application.decision_portfolio_context(state)


def _account_truth_gate_evidence(state: Any) -> dict[str, Any]:
    return decision_application.account_truth_gate_evidence(state)


def _action_trade_date(action: dict[str, Any]) -> str | None:
    return decision_application.action_trade_date(action)


def _data_freshness_evidence(
    action: dict[str, Any],
    db: Any,
    *,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    return decision_application.data_freshness_evidence(
        action,
        db,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
    )


def _paper_shadow_evidence(
    action: dict[str, Any],
    manual_confirmation_status: str,
    *,
    db: Any,
) -> dict[str, Any]:
    return decision_application.paper_shadow_evidence(
        action,
        manual_confirmation_status,
        db=db,
    )


def _paper_shadow_allows_manual_ticket(evidence: dict[str, Any]) -> bool:
    return decision_application.paper_shadow_allows_manual_ticket(evidence)


def _latest_quote_timestamp(quotes: Any) -> str | None:
    return decision_application.latest_quote_timestamp(quotes)


def _strategy_attribution_gate_evidence(
    state: Any,
    db: Any,
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    return decision_application.strategy_attribution_gate_evidence(
        state,
        db,
        actions,
    )


def resolve_strategy_order_generation_gate(
    db: Any,
    strategy_id: str,
    *,
    as_of_date: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Compatibility wrapper for legacy tests and integrations."""
    return decision_application.resolve_strategy_order_generation_gate(
        db,
        strategy_id,
        as_of_date=as_of_date,
    )


async def today_decision_payload(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the canonical Decision projection."""
    return await _today_decision_payload(
        state,
        portfolio_context=portfolio_context,
    )


def trading_plan_positions(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper for the canonical plan-position projection."""
    return _trading_plan_positions(state, portfolio_context=portfolio_context)


def decision_portfolio_context(state: Any) -> dict[str, Any]:
    """Compatibility wrapper for canonical portfolio evidence resolution."""
    return _decision_portfolio_context(state)


def account_truth_gate_evidence(state: Any) -> dict[str, Any]:
    """Compatibility wrapper for canonical Account Truth gate evidence."""
    return _account_truth_gate_evidence(state)


def action_trade_date(action: dict[str, Any]) -> str | None:
    """Compatibility wrapper for canonical action-date parsing."""
    return _action_trade_date(action)


def data_freshness_evidence(
    action: dict[str, Any],
    db: Any,
    *,
    quotes: dict[str, dict[str, Any]],
    allow_direct_quote_fallback: bool,
) -> dict[str, Any]:
    """Compatibility wrapper for canonical market-data evidence."""
    return _data_freshness_evidence(
        action,
        db,
        quotes=quotes,
        allow_direct_quote_fallback=allow_direct_quote_fallback,
    )


def paper_shadow_evidence(
    action: dict[str, Any],
    manual_confirmation_status: str,
    *,
    db: Any,
) -> dict[str, Any]:
    """Compatibility wrapper for canonical paper/shadow evidence."""
    return _paper_shadow_evidence(
        action,
        manual_confirmation_status,
        db=db,
    )


def paper_shadow_allows_manual_ticket(evidence: dict[str, Any]) -> bool:
    """Compatibility wrapper for canonical manual-ticket admission."""
    return _paper_shadow_allows_manual_ticket(evidence)
