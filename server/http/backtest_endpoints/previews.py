"""Backtest previews HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from server.contracts.http.backtest import (
    BacktestAttributionPreviewRequest,
    BacktestPaperShadowPreviewRequest,
    BacktestRiskPreviewRequest,
)
from server.http.backtest_endpoints.dependencies import PreviewEndpointDependencies


def create_router(dependencies: PreviewEndpointDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])
    _run_backtest_attribution_preview = dependencies.run_backtest_attribution_preview
    _run_backtest_paper_shadow_preview = dependencies.run_backtest_paper_shadow_preview
    _run_backtest_risk_preview = dependencies.run_backtest_risk_preview

    @r.post("/risk-preview")
    async def preview_backtest_risk(request: BacktestRiskPreviewRequest) -> dict:
        """Preview pre-trade risk without persisting decisions or orders."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return _run_backtest_risk_preview(request, state)

    @r.post("/paper-shadow-preview")
    async def preview_backtest_paper_shadow(
        request: BacktestPaperShadowPreviewRequest,
    ) -> dict:
        """Preview paper/shadow simulation without persisting orders or fills."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return _run_backtest_paper_shadow_preview(request, state)

    @r.post("/attribution-preview")
    async def preview_backtest_attribution(
        request: BacktestAttributionPreviewRequest,
    ) -> dict:
        """Preview attribution evidence without claiming or persisting P/L."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return _run_backtest_attribution_preview(request, state)

    return r
