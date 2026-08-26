"""Explicit dependency contracts for market HTTP endpoint registration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.types import AssetClass

Operation = Callable[..., Any]
ValueProvider = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class CalendarEndpointDependencies:
    market_calendar_snapshot_response: Operation
    build_market_calendar_provider: Operation


@dataclass(frozen=True, slots=True)
class HealthEndpointDependencies:
    backfill_instrument_metadata: Operation
    backfill_market_bars: Operation
    build_market_data_health_response: Operation
    merged_watchlist_assets: Operation
    quote_fetch_run_response: Operation
    refresh_confirmed_fund_nav: Operation
    run_blocking_fetch: Operation
    shanghai_now: Operation
    with_default_market_indices: Operation


@dataclass(frozen=True, slots=True)
class RefreshEndpointDependencies:
    asset_class_map: Mapping[str, AssetClass]
    create_manual_quote_fetch_run: Operation
    default_refresh_symbols: Operation
    finish_manual_quote_fetch_run: Operation
    merged_watchlist_assets: Operation
    normalize_refresh_symbols: Operation
    publish_committed_runtime_quotes: Operation
    quote_fetch_run_asset_type: Operation
    quote_fetch_run_metadata: Operation
    refresh_one_quote: Operation
    with_default_market_indices: Operation
    asyncio_provider: ValueProvider
    datetime_provider: ValueProvider
    uuid_provider: ValueProvider
    is_cn_trading_session: Operation


@dataclass(frozen=True, slots=True)
class WatchlistEndpointDependencies:
    asset_class_map: Mapping[str, AssetClass]
    default_end_date: str
    extract_runtime_portfolio: Operation
    merged_watchlist_assets: Operation
    position_for_symbol: Operation
    read_market_bars: Operation
    datetime_provider: ValueProvider
    timedelta_provider: ValueProvider
    logger_provider: ValueProvider


@dataclass(frozen=True, slots=True)
class ResearchEndpointDependencies:
    build_market_data_health_response: Operation
    build_research_note_stats: Operation
    with_default_market_indices: Operation


__all__ = [
    "CalendarEndpointDependencies",
    "HealthEndpointDependencies",
    "RefreshEndpointDependencies",
    "ResearchEndpointDependencies",
    "WatchlistEndpointDependencies",
]
