"""Backtest strategy catalog HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from server.config import BacktestConfig
from server.contracts.http.backtest import (
    StrategyInfoResponse,
    StrategyPromotionReadinessResponse,
    StrategySignalPreviewRequest,
    StrategySignalPreviewResponse,
    StrategyValidationMatrixResponse,
)


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _run_strategy_signal_preview = dependency("_run_strategy_signal_preview")
    _validate_signal_preview_strategy_params = dependency(
        "_validate_signal_preview_strategy_params"
    )
    asyncio = dependency("asyncio")

    @r.get("/strategies", response_model=list[StrategyInfoResponse])
    async def list_strategies() -> list[StrategyInfoResponse]:
        """获取所有已注册策略及参数信息。"""
        import strategy.builtins  # noqa: F401
        from strategy.registry import StrategyRegistry

        return [StrategyInfoResponse(**s) for s in StrategyRegistry.get_info()]

    @r.get(
        "/strategy-validation",
        response_model=StrategyValidationMatrixResponse,
    )
    async def get_strategy_validation() -> StrategyValidationMatrixResponse:
        """获取 v0.2 基准策略 after-cost / OOS 证据矩阵。"""
        import strategy.builtins  # noqa: F401
        from analytics.strategy_validation_matrix import (
            build_strategy_validation_matrix,
        )
        from server.dependencies import get_app_state
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        rows = await state.db.get_backtest_results()
        matrix = build_strategy_validation_matrix(StrategyRegistry.get_info(), rows)
        return StrategyValidationMatrixResponse(**matrix.to_json_dict())

    @r.get(
        "/strategy-promotion-readiness",
        response_model=StrategyPromotionReadinessResponse,
    )
    async def get_strategy_promotion_readiness() -> StrategyPromotionReadinessResponse:
        """获取 v0.2 策略晋级证据闸门，不自动晋级或执行。"""
        import strategy.builtins  # noqa: F401
        from analytics.strategy_promotion_readiness import (
            build_strategy_promotion_readiness,
        )
        from server.account_truth_gate import build_latest_account_truth_score_payload
        from server.dependencies import get_app_state
        from server.services.account_strategy_assignment import (
            account_strategy_assignment_from_payload,
        )
        from server.services.account_strategy_projections import (
            build_attribution_summary,
            build_contribution_report,
        )
        from strategy.registry import StrategyRegistry

        state = get_app_state()
        rows = await state.db.get_backtest_results()
        risk_decisions = state.db.get_risk_decisions_sync(limit=500)
        order_facts = state.db.list_orders_sync(limit=500)
        runtime_reader = getattr(state.db, "get_runtime_control_sync", None)
        assignment_payload = (
            runtime_reader("account_strategy_assignment")
            if callable(runtime_reader)
            else None
        )
        account_strategy_assignments: list[dict[str, Any]] = []
        account_strategy_attributions: list[dict[str, Any]] = []
        if isinstance(assignment_payload, dict):
            assignment = account_strategy_assignment_from_payload(
                assignment_payload,
                fallback_config=state.config,
            )
            account_strategy_assignments.append(assignment.model_dump())
            attribution_payload = build_attribution_summary(
                state.db,
                assignment,
            ).model_dump()
            contribution_payload = build_contribution_report(
                state.db,
                assignment,
            ).model_dump()
            account_strategy_attributions.append(
                {**attribution_payload, **contribution_payload}
            )
        account_truth_payload = build_latest_account_truth_score_payload(state)
        account_truth_scores = (
            [account_truth_payload]
            if account_truth_payload.get("status") == "available"
            else None
        )
        readiness = build_strategy_promotion_readiness(
            StrategyRegistry.get_info(),
            rows,
            risk_decisions,
            order_facts,
            account_truth_scores=account_truth_scores,
            account_strategy_assignments=account_strategy_assignments,
            account_strategy_attributions=account_strategy_attributions,
        )
        return StrategyPromotionReadinessResponse(**readiness.to_json_dict())

    @r.post("/signal-preview", response_model=StrategySignalPreviewResponse)
    async def preview_strategy_signal(
        request: StrategySignalPreviewRequest,
    ) -> StrategySignalPreviewResponse:
        """Preview strategy outputs as research evidence without persistence."""
        from server.dependencies import get_app_state

        state = get_app_state()
        config = state.config or BacktestConfig()
        request = _validate_signal_preview_strategy_params(request)
        preview = await asyncio.to_thread(_run_strategy_signal_preview, request, config)
        return StrategySignalPreviewResponse(**preview)

    return r
