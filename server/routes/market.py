"""Market routes — /api/market/*"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.types import AssetClass, BarFrequency, Symbol
from data.market_calendar import build_market_calendar_provider
from server.contracts.http.market import (
    ConfirmedFundNavRefreshRequest,
    ConfirmedFundNavRefreshResponse,
    InstrumentMetadataBackfillItem,
    InstrumentMetadataBackfillRequest,
    InstrumentMetadataBackfillResponse,
    MarketBarsBackfillItem,
    MarketBarsBackfillRequest,
    MarketBarsBackfillResponse,
    QuoteRefreshRequest,
    QuoteRefreshResponse,
    QuoteRefreshSymbolResult,
)
from server.http.market_endpoints.calendar import (
    create_router as _create_calendar_router,
)
from server.http.market_endpoints.dependencies import (
    CalendarEndpointDependencies,
    HealthEndpointDependencies,
    RefreshEndpointDependencies,
    ResearchEndpointDependencies,
    WatchlistEndpointDependencies,
)
from server.http.market_endpoints.health import create_router as _create_health_router
from server.http.market_endpoints.refresh import create_router as _create_refresh_router
from server.http.market_endpoints.research import (
    create_router as _create_research_router,
)
from server.http.market_endpoints.watchlist import (
    create_router as _create_watchlist_router,
)
from server.models import (
    KlineBar,
    MarketCalendarSnapshotResponse,
    MarketCalendarSyncRequest,
    MarketCalendarVerificationRequest,
    MarketDataHealthResponse,
    MarketHealthQuote,
    MarketQuote,
    QuoteFetchRunResponse,
    ResearchBoardItem,
    ResearchBoardResponse,
    ResearchNoteCreate,
    ResearchNoteListResponse,
    ResearchNoteResponse,
    ResearchNoteUpdate,
    WatchlistCreateRequest,
    WatchlistItem,
)
from server.persistence.market_bars import read_market_bars as _read_market_bars
from server.services.asset_metadata import (
    metadata_configured_count,
    resolve_asset_metadata,
)
from server.services.data_health import build_data_health
from server.services.market_hours import is_cn_trading_session
from server.services.market_indices import (
    default_market_index_assets,
)
from server.services.market_refresh import (
    INDEX_PROVIDER_REFRESH_TIMEOUT_SECONDS as _INDEX_PROVIDER_REFRESH_TIMEOUT_SECONDS,
)
from server.services.market_refresh import (
    MANUAL_REFRESH_TIMEOUT_SECONDS as _MANUAL_REFRESH_TIMEOUT_SECONDS,
)
from server.services.market_refresh import (
    PROVIDER_REFRESH_TIMEOUT_SECONDS as _PROVIDER_REFRESH_TIMEOUT_SECONDS,
)
from server.services.market_refresh import (
    QUOTE_REFRESH_ATTEMPTS as _QUOTE_REFRESH_ATTEMPTS,
)
from server.services.market_refresh import QUOTE_REFRESH_ERRORS as _QUOTE_REFRESH_ERRORS
from server.services.market_refresh import (
    fetch_latest_snapshot as _fetch_latest_snapshot,
)
from server.services.market_refresh import (
    fetch_provider_latest_with_timeout as _fetch_provider_latest_with_timeout,
)
from server.services.market_refresh import (
    is_real_persistent_quote as _is_real_persistent_quote,
)
from server.services.market_refresh import (
    load_latest_snapshot_from_provider as _load_latest_snapshot_from_provider,
)
from server.services.market_refresh import optional_float as _optional_float
from server.services.market_refresh import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.market_refresh import (
    persist_latest_snapshot as _persist_latest_snapshot,
)
from server.services.market_refresh import (
    publish_committed_runtime_quotes as _publish_committed_runtime_quotes,
)
from server.services.market_refresh import quote_metadata as _quote_metadata
from server.services.market_refresh import refresh_one_quote as _refresh_one_quote
from server.services.market_refresh import resolve_quote_status as _resolve_quote_status
from server.services.market_refresh import run_blocking_fetch as _run_blocking_fetch
from server.services.market_refresh import shanghai_now as _shanghai_now
from server.services.market_views.backfill import (
    backfill_instrument_metadata as _backfill_instrument_metadata,
)
from server.services.market_views.backfill import (
    backfill_market_bars as _backfill_market_bars,
)
from server.services.market_views.backfill import bar_frequency as _bar_frequency
from server.services.market_views.backfill import (
    extract_provider_display_name as _extract_provider_display_name,
)
from server.services.market_views.backfill import (
    instrument_metadata_targets as _instrument_metadata_targets,
)
from server.services.market_views.backfill import (
    market_bar_backfill_range as _market_bar_backfill_range,
)
from server.services.market_views.backfill import (
    market_bar_backfill_targets as _market_bar_backfill_targets,
)
from server.services.market_views.backfill import (
    meta_covers_range as _meta_covers_range,
)
from server.services.market_views.backfill import (
    metadata_name_is_useful as _metadata_name_is_useful,
)
from server.services.market_views.backfill import (
    parse_backfill_date as _parse_backfill_date,
)
from server.services.market_views.backfill import (
    provider_asset_class as _provider_asset_class,
)
from server.services.market_views.confirmed_nav import (
    refresh_confirmed_fund_nav as _refresh_confirmed_fund_nav,
)
from server.services.market_views.fetch_runs import (
    create_manual_quote_fetch_run as _create_manual_quote_fetch_run,
)
from server.services.market_views.fetch_runs import (
    finish_manual_quote_fetch_run as _finish_manual_quote_fetch_run,
)
from server.services.market_views.fetch_runs import (
    manual_quote_fetch_provider_status as _manual_quote_fetch_provider_status,
)
from server.services.market_views.fetch_runs import (
    manual_quote_fetch_run_status as _manual_quote_fetch_run_status,
)
from server.services.market_views.fetch_runs import (
    quote_fetch_run_asset_type as _quote_fetch_run_asset_type,
)
from server.services.market_views.fetch_runs import (
    quote_fetch_run_metadata as _quote_fetch_run_metadata,
)
from server.services.market_views.fetch_runs import (
    quote_fetch_run_response as _quote_fetch_run_response,
)
from server.services.market_views.health_inputs import (
    adapt_latest_quote_for_health as _adapt_latest_quote_for_health,
)
from server.services.market_views.health_inputs import (
    aggregate_market_data_health_status as _aggregate_market_data_health_status,
)
from server.services.market_views.health_inputs import (
    configured_provider_name as _configured_provider_name,
)
from server.services.market_views.health_inputs import (
    default_refresh_symbols as _default_refresh_symbols,
)
from server.services.market_views.health_inputs import (
    extract_runtime_portfolio as _extract_runtime_portfolio,
)
from server.services.market_views.health_inputs import (
    find_asset_config as _find_asset_config,
)
from server.services.market_views.health_inputs import (
    has_live_fund_quotes as _has_live_fund_quotes,
)
from server.services.market_views.health_inputs import json_array as _json_array
from server.services.market_views.health_inputs import (
    ledger_position_assets as _ledger_position_assets,
)
from server.services.market_views.health_inputs import (
    market_calendar_snapshot_response as _market_calendar_snapshot_response,
)
from server.services.market_views.health_inputs import (
    merged_watchlist_assets as _merged_watchlist_assets,
)
from server.services.market_views.health_inputs import (
    normalize_asset_class as _normalize_asset_class,
)
from server.services.market_views.health_inputs import (
    normalize_refresh_symbols as _normalize_refresh_symbols,
)
from server.services.market_views.health_inputs import (
    position_for_symbol as _position_for_symbol,
)
from server.services.market_views.health_inputs import (
    provider_configured as _provider_configured,
)
from server.services.market_views.health_inputs import (
    provider_next_action as _provider_next_action,
)
from server.services.market_views.health_inputs import (
    provider_requires_token as _provider_requires_token,
)
from server.services.market_views.health_inputs import (
    provider_supports_funds as _provider_supports_funds,
)
from server.services.market_views.health_inputs import (
    resolve_asset_class as _resolve_asset_class,
)
from server.services.market_views.health_inputs import (
    resolve_asset_display_name as _resolve_asset_display_name,
)
from server.services.market_views.health_inputs import (
    with_default_market_indices as _with_default_market_indices,
)
from server.services.market_views.health_projection import (
    build_market_data_health_response as _build_market_data_health_response,
)
from server.services.market_views.health_projection import (
    build_research_note_stats as _build_research_note_stats,
)
from server.services.market_views.health_projection import (
    maybe_schedule_quote_refresh as _maybe_schedule_quote_refresh,
)
from server.services.market_views.health_projection import (
    quote_refresh_due as _quote_refresh_due,
)
from server.services.market_views.health_projection import (
    refresh_quote_snapshot as _refresh_quote_snapshot,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

logger = logging.getLogger(__name__)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_BAR_BACKFILL_TIMEOUT_SECONDS = 60.0
_BLOCKING_FETCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="market-fetch",
)
_SH_TZ = ZoneInfo("Asia/Shanghai")

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}
_TUSHARE_FUND_NAV_PERMISSION_DENIED = "tushare_fund_nav_permission_denied"


def create_router() -> APIRouter:
    router = APIRouter()
    router.routes.extend(
        _create_calendar_router(
            CalendarEndpointDependencies(
                market_calendar_snapshot_response=(
                    lambda *args, **kwargs: _market_calendar_snapshot_response(
                        *args, **kwargs
                    )
                ),
                build_market_calendar_provider=(
                    lambda *args, **kwargs: build_market_calendar_provider(
                        *args, **kwargs
                    )
                ),
            )
        ).routes
    )
    watchlist_router, get_watchlist = _create_watchlist_router(
        WatchlistEndpointDependencies(
            asset_class_map=_ASSET_CLASS_MAP,
            default_end_date=_DEFAULT_END_DATE,
            extract_runtime_portfolio=lambda *args, **kwargs: (
                _extract_runtime_portfolio(*args, **kwargs)
            ),
            merged_watchlist_assets=lambda *args, **kwargs: _merged_watchlist_assets(
                *args, **kwargs
            ),
            position_for_symbol=lambda *args, **kwargs: _position_for_symbol(
                *args, **kwargs
            ),
            read_market_bars=lambda *args, **kwargs: _read_market_bars(*args, **kwargs),
            datetime_provider=lambda: datetime,
            timedelta_provider=lambda: timedelta,
            logger_provider=lambda: logger,
        )
    )
    router.routes.extend(watchlist_router.routes)
    router.routes.extend(
        _create_health_router(
            HealthEndpointDependencies(
                backfill_instrument_metadata=lambda *args, **kwargs: (
                    _backfill_instrument_metadata(*args, **kwargs)
                ),
                backfill_market_bars=lambda *args, **kwargs: _backfill_market_bars(
                    *args, **kwargs
                ),
                build_market_data_health_response=lambda *args, **kwargs: (
                    _build_market_data_health_response(*args, **kwargs)
                ),
                merged_watchlist_assets=lambda *args, **kwargs: (
                    _merged_watchlist_assets(*args, **kwargs)
                ),
                quote_fetch_run_response=lambda *args, **kwargs: (
                    _quote_fetch_run_response(*args, **kwargs)
                ),
                refresh_confirmed_fund_nav=lambda *args, **kwargs: (
                    _refresh_confirmed_fund_nav(*args, **kwargs)
                ),
                run_blocking_fetch=lambda *args, **kwargs: _run_blocking_fetch(
                    *args, **kwargs
                ),
                shanghai_now=lambda *args, **kwargs: _shanghai_now(*args, **kwargs),
                with_default_market_indices=lambda *args, **kwargs: (
                    _with_default_market_indices(*args, **kwargs)
                ),
            )
        ).routes
    )
    router.routes.extend(
        _create_refresh_router(
            RefreshEndpointDependencies(
                asset_class_map=_ASSET_CLASS_MAP,
                create_manual_quote_fetch_run=lambda *args, **kwargs: (
                    _create_manual_quote_fetch_run(*args, **kwargs)
                ),
                default_refresh_symbols=lambda *args, **kwargs: (
                    _default_refresh_symbols(*args, **kwargs)
                ),
                finish_manual_quote_fetch_run=lambda *args, **kwargs: (
                    _finish_manual_quote_fetch_run(*args, **kwargs)
                ),
                merged_watchlist_assets=lambda *args, **kwargs: (
                    _merged_watchlist_assets(*args, **kwargs)
                ),
                normalize_refresh_symbols=lambda *args, **kwargs: (
                    _normalize_refresh_symbols(*args, **kwargs)
                ),
                publish_committed_runtime_quotes=lambda *args, **kwargs: (
                    _publish_committed_runtime_quotes(*args, **kwargs)
                ),
                quote_fetch_run_asset_type=lambda *args, **kwargs: (
                    _quote_fetch_run_asset_type(*args, **kwargs)
                ),
                quote_fetch_run_metadata=lambda *args, **kwargs: (
                    _quote_fetch_run_metadata(*args, **kwargs)
                ),
                refresh_one_quote=lambda *args, **kwargs: _refresh_one_quote(
                    *args, **kwargs
                ),
                with_default_market_indices=lambda *args, **kwargs: (
                    _with_default_market_indices(*args, **kwargs)
                ),
                asyncio_provider=lambda: asyncio,
                datetime_provider=lambda: datetime,
                uuid_provider=lambda: uuid,
                is_cn_trading_session=lambda: is_cn_trading_session(),
            )
        ).routes
    )
    router.routes.extend(
        _create_research_router(
            ResearchEndpointDependencies(
                build_market_data_health_response=lambda *args, **kwargs: (
                    _build_market_data_health_response(*args, **kwargs)
                ),
                build_research_note_stats=lambda *args, **kwargs: (
                    _build_research_note_stats(*args, **kwargs)
                ),
                with_default_market_indices=lambda *args, **kwargs: (
                    _with_default_market_indices(*args, **kwargs)
                ),
            ),
            get_watchlist,
        ).routes
    )
    return router


def fetch_latest_snapshot(
    state,
    symbol: str,
    asset_class: AssetClass,
) -> dict | None:
    """Compatibility port for non-HTTP composition callers."""

    return _fetch_latest_snapshot(state, symbol, asset_class)


async def refresh_one_quote(
    state,
    symbol: str,
    asset_class: AssetClass,
    timeout_seconds: float | None = None,
    fetch_run_id: str | None = None,
) -> QuoteRefreshSymbolResult:
    """Compatibility port for non-HTTP composition callers."""

    return await _refresh_one_quote(
        state,
        symbol,
        asset_class,
        timeout_seconds=timeout_seconds,
        fetch_run_id=fetch_run_id,
    )
