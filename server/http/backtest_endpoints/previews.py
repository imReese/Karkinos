"""Backtest previews HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/backtest", tags=["backtest"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    BacktestAttributionPreviewRequest = dependency("BacktestAttributionPreviewRequest")
    BacktestPaperShadowPreviewRequest = dependency("BacktestPaperShadowPreviewRequest")
    BacktestRiskPreviewRequest = dependency("BacktestRiskPreviewRequest")
    _run_backtest_attribution_preview = dependency("_run_backtest_attribution_preview")
    _run_backtest_paper_shadow_preview = dependency(
        "_run_backtest_paper_shadow_preview"
    )
    _run_backtest_risk_preview = dependency("_run_backtest_risk_preview")

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
