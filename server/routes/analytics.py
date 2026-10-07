"""Analytics & factor evaluation routes — /api/analytics/* and /api/universes/*."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.services.factor_analytics import (
    get_curated_universe,
    list_curated_universes,
    run_factor_evaluation,
)


class FactorEvaluationRequest(BaseModel):
    universe_id: str = Field(
        default="core_etf_universe", description="Curated universe identifier"
    )
    factor_type: str = Field(
        default="momentum",
        description="Factor type: momentum, risk_adjusted_momentum, reversal, volatility, rsi",
    )
    lookback_period: int = Field(
        default=20, ge=2, le=250, description="Factor lookback rolling window"
    )
    forward_period: int = Field(
        default=5,
        ge=1,
        le=60,
        description="Forward return horizon for IC and performance",
    )
    n_quantiles: int = Field(
        default=5, ge=2, le=10, description="Number of quantile buckets"
    )


def create_router() -> APIRouter:
    router = APIRouter(tags=["analytics"])

    @router.get("/api/universes")
    def get_universes() -> list[dict[str, Any]]:
        """List all curated ETF & asset universes."""
        return list_curated_universes()

    @router.get("/api/universes/{universe_id}")
    def get_universe(universe_id: str) -> dict[str, Any]:
        """Get universe metadata and constituent members."""
        data = get_curated_universe(universe_id)
        if data is None:
            raise HTTPException(status_code=404, detail="universe_not_found")
        return data

    @router.post("/api/analytics/factor-evaluation")
    def evaluate_factor(request: FactorEvaluationRequest) -> dict[str, Any]:
        """Compute cross-sectional IC, ICIR, and quantile distribution for a factor."""
        try:
            return run_factor_evaluation(
                universe_id=request.universe_id,
                factor_type=request.factor_type,
                lookback_period=request.lookback_period,
                forward_period=request.forward_period,
                n_quantiles=request.n_quantiles,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return router
