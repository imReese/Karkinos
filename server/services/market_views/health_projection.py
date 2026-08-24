"""Canonical market health projection projections."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import BackgroundTasks

from core.types import AssetClass
from server.models import (
    MarketDataHealthResponse,
    MarketHealthQuote,
)
from server.services.asset_metadata import (
    metadata_configured_count,
)
from server.services.data_health import build_data_health
from server.services.market_hours import is_cn_trading_session
from server.services.market_refresh import (
    MANUAL_REFRESH_TIMEOUT_SECONDS as _MANUAL_REFRESH_TIMEOUT_SECONDS,
)
from server.services.market_refresh import (
    QUOTE_REFRESH_ATTEMPTS as _QUOTE_REFRESH_ATTEMPTS,
)
from server.services.market_refresh import (
    is_real_persistent_quote as _is_real_persistent_quote,
)
from server.services.market_refresh import (
    load_latest_snapshot_from_provider as _load_latest_snapshot_from_provider,
)
from server.services.market_refresh import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.market_refresh import (
    persist_latest_snapshot as _persist_latest_snapshot,
)
from server.services.market_refresh import quote_metadata as _quote_metadata
from server.services.market_refresh import run_blocking_fetch as _run_blocking_fetch
from server.services.market_refresh import shanghai_now as _shanghai_now
from server.services.market_views.health_inputs import (
    adapt_latest_quote_for_health,
    aggregate_market_data_health_status,
    configured_provider_name,
    has_live_fund_quotes,
    provider_configured,
    provider_next_action,
    provider_requires_token,
    provider_supports_funds,
)

logger = logging.getLogger(__name__)


def build_research_note_stats(rows: list[dict]) -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    for row in rows:
        symbol = row["symbol"]
        current = stats.setdefault(symbol, {"count": 0, "latest": ""})
        current["count"] = int(current["count"]) + 1
        updated_at = row.get("updated_at") or ""
        if updated_at and updated_at > str(current["latest"]):
            current["latest"] = updated_at
    return stats


async def refresh_quote_snapshot(state, symbol: str, asset_class: AssetClass) -> None:
    try:
        snapshot = await _run_blocking_fetch(
            _load_latest_snapshot_from_provider,
            state,
            symbol,
            asset_class,
        )
        if snapshot:
            _persist_latest_snapshot(state, symbol, snapshot)
    except Exception:
        logger.warning("Async quote refresh failed for %s", symbol, exc_info=True)


def quote_refresh_due(state, symbol: str, asset_class: AssetClass) -> bool:
    if not is_cn_trading_session():
        return False

    ttl = max(int(getattr(state.config, "live_poll_interval", 60) or 60), 15)
    key = (symbol, asset_class.value)
    now = datetime.now()
    last_attempt = _QUOTE_REFRESH_ATTEMPTS.get(key)
    if last_attempt is not None and (now - last_attempt).total_seconds() < ttl:
        return False
    _QUOTE_REFRESH_ATTEMPTS[key] = now
    return True


def maybe_schedule_quote_refresh(
    state,
    background_tasks: BackgroundTasks,
    symbol: str,
    asset_class: AssetClass,
) -> None:
    if quote_refresh_due(state, symbol, asset_class):
        background_tasks.add_task(refresh_quote_snapshot, state, symbol, asset_class)


def build_market_data_health_response(
    state,
    market_health_assets: list[dict[str, str]],
) -> MarketDataHealthResponse:
    """Build health from an already-resolved persisted asset projection."""
    watchlist = [
        (asset_cfg["symbol"], asset_cfg["asset_class"])
        for asset_cfg in market_health_assets
    ]

    latest_quotes: dict[str, dict] = {}
    persistent_quotes: dict[str, dict] = {}
    persistent_reader_available = state.db is not None and (
        hasattr(state.db, "list_latest_quotes_sync")
        or hasattr(state.db, "get_latest_quotes_sync")
    )
    scheduler = state.scheduler
    if (
        not persistent_reader_available
        and scheduler
        and getattr(scheduler, "latest_quotes", None)
    ):
        latest_quotes.update(
            {str(symbol): quote for symbol, quote in scheduler.latest_quotes.items()}
        )
    if state.db is not None:
        if hasattr(state.db, "list_latest_quotes_sync"):
            for row in state.db.list_latest_quotes_sync():
                quote = adapt_latest_quote_for_health(row)
                if _is_real_persistent_quote(quote):
                    persistent_quotes[quote["symbol"]] = quote
                latest_quotes[quote["symbol"]] = quote
        if hasattr(state.db, "get_latest_quotes_sync"):
            for row in state.db.get_latest_quotes_sync():
                quote = adapt_latest_quote_for_health(row)
                if _is_real_persistent_quote(quote):
                    persistent_quotes.setdefault(quote["symbol"], quote)
                latest_quotes.setdefault(quote["symbol"], quote)

    payload = build_data_health(
        watchlist=watchlist,
        latest_quotes=latest_quotes,
        bar_coverage={},
    )
    market_open = is_cn_trading_session()
    refresh_policy = "live" if market_open else "cache_only"
    now = _shanghai_now()
    health_quotes: list[MarketHealthQuote] = []
    for item in payload["quotes"]:
        symbol = item["symbol"]
        asset_class = item["asset_class"]
        quote = latest_quotes.get(symbol)
        metadata = _quote_metadata(
            state,
            symbol,
            asset_class,
            quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
            now=now,
        )
        health_quotes.append(
            MarketHealthQuote(
                symbol=symbol,
                asset_class=asset_class,
                timestamp=item["timestamp"],
                price=item["price"],
                **metadata,
            )
        )

    quote_timestamps = [
        _parse_quote_timestamp(item.timestamp) for item in health_quotes
    ]
    quote_timestamps = [item for item in quote_timestamps if item is not None]
    latest_quote_timestamp = (
        max(quote_timestamps).isoformat() if quote_timestamps else None
    )
    persistent_timestamps = [
        _parse_quote_timestamp(item.get("timestamp"))
        for item in persistent_quotes.values()
    ]
    persistent_timestamps = [item for item in persistent_timestamps if item is not None]
    latest_persistent_quote_timestamp = (
        max(persistent_timestamps).isoformat() if persistent_timestamps else None
    )
    cache_age_seconds = None
    if quote_timestamps:
        cache_age_seconds = max(int((now - max(quote_timestamps)).total_seconds()), 0)
    account_health_quotes = [
        item for item in health_quotes if item.asset_class != AssetClass.INDEX.value
    ]
    status_health_quotes = account_health_quotes or health_quotes
    stale_symbols = [
        item.symbol for item in status_health_quotes if item.quote_status != "live"
    ]
    latest_attempts = [
        _parse_quote_timestamp(item.last_refresh_attempt)
        for item in health_quotes
        if item.last_refresh_attempt
    ]
    latest_attempts = [item for item in latest_attempts if item is not None]
    latest_refresh_attempt = (
        max(latest_attempts).isoformat() if latest_attempts else None
    )
    latest_refresh_error = next(
        (item.last_refresh_error for item in health_quotes if item.last_refresh_error),
        None,
    )
    provider_name = configured_provider_name(state)
    requires_provider_token = provider_requires_token(provider_name)
    is_provider_configured = provider_configured(state, provider_name)
    supports_fund_quotes = provider_supports_funds(provider_name)
    source_health = aggregate_market_data_health_status(status_health_quotes)
    provider_status = (
        "error"
        if latest_refresh_error
        and not any(item.quote_status == "live" for item in status_health_quotes)
        else source_health
    )
    has_funds = any(asset_class in {"fund", "etf"} for _, asset_class in watchlist)
    effective_provider_supports_funds = (
        True
        if has_funds and has_live_fund_quotes(health_quotes)
        else supports_fund_quotes
    )
    has_persistent_cache = bool(persistent_quotes)
    real_data_available = has_persistent_cache
    persistent_cache_status = "available" if has_persistent_cache else "missing"
    next_action = provider_next_action(
        provider_configured=is_provider_configured,
        provider_supports_funds=effective_provider_supports_funds,
        has_funds=has_funds,
        latest_refresh_error=latest_refresh_error,
        source_health=source_health,
    )
    if latest_refresh_error and has_persistent_cache:
        next_action = "use_cached_data"
    elif latest_refresh_error and not has_persistent_cache:
        next_action = "run_first_sync"
    return MarketDataHealthResponse(
        quotes=health_quotes,
        market_open=market_open,
        refresh_policy=refresh_policy,
        provider_status=provider_status,
        provider_name=provider_name,
        provider_configured=is_provider_configured,
        provider_requires_token=requires_provider_token,
        provider_supports_funds=effective_provider_supports_funds,
        provider_last_error=latest_refresh_error,
        provider_timeout_seconds=_MANUAL_REFRESH_TIMEOUT_SECONDS,
        next_action=next_action,
        metadata_configured_count=metadata_configured_count(state),
        source_health=source_health,
        cache_age_seconds=cache_age_seconds,
        latest_quote_timestamp=latest_quote_timestamp,
        last_refresh_attempt=latest_refresh_attempt,
        last_refresh_error=latest_refresh_error,
        stale_symbols_count=len(stale_symbols),
        stale_symbols_sample=stale_symbols[:5],
        real_data_available=real_data_available,
        has_persistent_cache=has_persistent_cache,
        latest_persistent_quote_timestamp=latest_persistent_quote_timestamp,
        persistent_cache_status=persistent_cache_status,
    )


__all__ = (
    "build_market_data_health_response",
    "build_research_note_stats",
    "maybe_schedule_quote_refresh",
    "quote_refresh_due",
    "refresh_quote_snapshot",
)
