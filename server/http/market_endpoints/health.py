"""Market health HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.contracts.http.market import (
    ConfirmedFundNavRefreshRequest,
    ConfirmedFundNavRefreshResponse,
    InstrumentMetadataBackfillRequest,
    InstrumentMetadataBackfillResponse,
    MarketBarsBackfillRequest,
    MarketBarsBackfillResponse,
)
from server.contracts.http.market_models import (
    MarketDataHealthResponse,
    QuoteFetchRunResponse,
)
from server.http.market_endpoints.dependencies import HealthEndpointDependencies


def create_router(dependencies: HealthEndpointDependencies) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])
    _backfill_instrument_metadata = dependencies.backfill_instrument_metadata
    _backfill_market_bars = dependencies.backfill_market_bars
    _build_market_data_health_response = dependencies.build_market_data_health_response
    _merged_watchlist_assets = dependencies.merged_watchlist_assets
    _quote_fetch_run_response = dependencies.quote_fetch_run_response
    _refresh_confirmed_fund_nav = dependencies.refresh_confirmed_fund_nav
    _run_blocking_fetch = dependencies.run_blocking_fetch
    _shanghai_now = dependencies.shanghai_now
    _with_default_market_indices = dependencies.with_default_market_indices

    @r.get("/data-health")
    async def get_data_health() -> MarketDataHealthResponse:
        """获取数据缓存与快照健康度概览。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        market_health_assets = _with_default_market_indices(
            _merged_watchlist_assets(state)
        )
        return _build_market_data_health_response(state, market_health_assets)

    @r.get("/quote-fetch-runs", response_model=list[QuoteFetchRunResponse])
    async def get_quote_fetch_runs(
        limit: int = 20,
        trigger: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[QuoteFetchRunResponse]:
        """List recent quote fetch audit runs for backend diagnostics."""
        from server.dependencies import get_app_state

        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be at least 1")
        if limit > 100:
            raise HTTPException(status_code=422, detail="limit must be at most 100")

        state = get_app_state()
        db = getattr(state, "db", None)
        if db is None or not hasattr(db, "list_quote_fetch_runs"):
            return []
        rows = db.list_quote_fetch_runs(
            limit=limit,
            trigger=trigger,
            status=status,
            provider=provider,
        )
        return [_quote_fetch_run_response(row) for row in rows]

    @r.post(
        "/instrument-metadata/backfill",
        response_model=InstrumentMetadataBackfillResponse,
    )
    async def backfill_instrument_metadata(
        request: InstrumentMetadataBackfillRequest,
    ) -> InstrumentMetadataBackfillResponse:
        """Backfill local instrument names from AKShare into the database."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return await _backfill_instrument_metadata(state, request)

    @r.post("/bars/backfill", response_model=MarketBarsBackfillResponse)
    async def backfill_market_bars(
        request: MarketBarsBackfillRequest,
    ) -> MarketBarsBackfillResponse:
        """Backfill historical OHLCV bars into the authoritative local store."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return await _backfill_market_bars(state, request)

    @r.post(
        "/fund-nav/confirmed/refresh",
        response_model=ConfirmedFundNavRefreshResponse,
    )
    async def refresh_confirmed_fund_nav(
        request: ConfirmedFundNavRefreshRequest,
    ) -> ConfirmedFundNavRefreshResponse:
        """Ingest confirmed fund NAV evidence without changing account authority."""
        from server.dependencies import get_app_state

        state = get_app_state()
        return await _refresh_confirmed_fund_nav(
            state,
            request,
            run_blocking_fetch=_run_blocking_fetch,
            shanghai_now=_shanghai_now,
        )

    return r
