"""Market health HTTP endpoints."""

from __future__ import annotations

from typing import Any

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


def create_router(facade: Any) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _backfill_instrument_metadata = dependency("_backfill_instrument_metadata")
    _backfill_market_bars = dependency("_backfill_market_bars")
    _build_market_data_health_response = dependency(
        "_build_market_data_health_response"
    )
    _merged_watchlist_assets = dependency("_merged_watchlist_assets")
    _quote_fetch_run_response = dependency("_quote_fetch_run_response")
    _refresh_confirmed_fund_nav = dependency("_refresh_confirmed_fund_nav")
    _run_blocking_fetch = dependency("_run_blocking_fetch")
    _shanghai_now = dependency("_shanghai_now")
    _with_default_market_indices = dependency("_with_default_market_indices")

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
