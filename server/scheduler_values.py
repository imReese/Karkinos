"""Pure configuration and quote-run projections for the scheduler."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from core.events import MarketEvent
from data.market_data import (
    MarketDataStatus,
    is_fund_estimate_quote_source,
    normalize_market_data_status,
)
from server.projections.quote_status import (
    expected_quote_date,
    parse_quote_timestamp,
    quote_live_ttl_seconds,
)
from server.services.market_hours import get_shanghai_now


@dataclass(frozen=True, slots=True)
class SchedulerQuoteEvidence:
    """Normalized evidence required before a polled quote may be published."""

    quote_timestamp: str
    quote_source: str
    provider_name: str
    quote_status: str
    provider_status: str
    stale_reason: str | None
    strategy_eligible: bool


_HEALTHY_PROVIDER_STATUSES = frozenset(
    {"confirmed", "fresh", "healthy", "live", "ok", "success"}
)
_STRATEGY_QUOTE_STATUSES = frozenset(
    {MarketDataStatus.CONFIRMED, MarketDataStatus.LIVE}
)


def configured_symbol_set(
    config: Any,
    *attribute_names: str,
) -> Callable[[], set[str]]:
    """Build a late-bound getter for optional symbol collections."""

    def getter() -> set[str]:
        values: set[str] = set()
        for name in attribute_names:
            raw = getattr(config, name, None)
            if raw is None:
                continue
            if isinstance(raw, dict):
                raw = raw.keys()
            if isinstance(raw, str):
                values.add(raw)
                continue
            try:
                values.update(str(item) for item in raw)
            except TypeError:
                values.add(str(raw))
        return values

    return getter


def quote_fetch_asset_type(watchlist: list[tuple[Any, Any]]) -> str | None:
    asset_types = {asset_class.value for _, asset_class in watchlist}
    if not asset_types:
        return None
    if len(asset_types) == 1:
        return next(iter(asset_types))
    return "mixed"


def quote_fetch_metadata(
    config: Any,
    watchlist: list[tuple[Any, Any]],
    *,
    provider_status: str,
    success_symbols: list[str],
    failed_symbols: list[str],
    error_message: str | None = None,
    quote_statuses: list[str] | None = None,
) -> dict[str, Any]:
    success_count = len(success_symbols)
    status_counts = Counter(quote_statuses or (["live"] * success_count))
    return {
        "trigger": "scheduler_poll",
        "provider": config.data_source,
        "provider_status": provider_status,
        "market_open": True,
        "poll_interval_seconds": config.live_poll_interval,
        "symbols": [str(symbol) for symbol, _ in watchlist],
        "asset_types": [asset_class.value for _, asset_class in watchlist],
        "success_symbols": success_symbols,
        "failed_symbols": failed_symbols,
        "symbol_count": len(watchlist),
        "success_count": success_count,
        "failure_count": len(failed_symbols),
        "cache_hit_count": 0,
        "quote_status_counts": dict(status_counts),
        "stale_reason_counts": {},
        "error_message": error_message,
    }


def quote_fetch_started_metadata(
    config: Any,
    watchlist: list[tuple[Any, Any]],
) -> dict[str, Any]:
    return {
        "trigger": "scheduler_poll",
        "provider": config.data_source,
        "market_open": True,
        "poll_interval_seconds": config.live_poll_interval,
        "symbols": [str(symbol) for symbol, _ in watchlist],
        "asset_types": [asset_class.value for _, asset_class in watchlist],
    }


def quote_fetch_status(
    watchlist_size: int,
    *,
    success_count: int,
    failure_count: int,
) -> str:
    if success_count == watchlist_size and failure_count == 0:
        return "success"
    if success_count > 0:
        return "partial_success"
    return "failed"


def provider_status_for_quote_run(
    watchlist_size: int,
    *,
    success_count: int,
    failure_count: int,
) -> str:
    if success_count == watchlist_size and failure_count == 0:
        return "live"
    if success_count > 0:
        return "partial"
    return "failed"


def is_complete_quote_batch(
    watchlist: list[tuple[Any, Any]],
    events: list[Any],
) -> bool:
    expected = {(str(symbol), asset_class) for symbol, asset_class in watchlist}
    received = {(str(event.symbol), event.asset_class) for event in events}
    return len(events) == len(expected) and received == expected


def optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def scheduler_quote_evidence(
    event: MarketEvent,
    snapshot: dict[str, Any],
    *,
    now: datetime,
    live_poll_interval: int,
) -> SchedulerQuoteEvidence:
    """Validate provenance, provider health, and active-session freshness."""

    raw_timestamp = snapshot.get("timestamp")
    if raw_timestamp in {None, ""}:
        raise RuntimeError(f"scheduler quote timestamp missing: {event.symbol}")
    timestamp = parse_quote_timestamp(event.timestamp)
    if timestamp is None:
        raise RuntimeError(f"scheduler quote timestamp invalid: {event.symbol}")

    current = get_shanghai_now(now)
    future_tolerance = timedelta(seconds=max(int(live_poll_interval or 0), 15))
    if timestamp > current + future_tolerance:
        raise RuntimeError(
            f"scheduler quote timestamp is in the future: {event.symbol}"
        )

    quote_source = str(
        snapshot.get("quote_source")
        or snapshot.get("source")
        or snapshot.get("provider_name")
        or snapshot.get("provider")
        or ""
    ).strip()
    provider_name = str(
        snapshot.get("provider_name")
        or snapshot.get("provider")
        or snapshot.get("source")
        or quote_source
        or ""
    ).strip()
    if not quote_source or not provider_name:
        raise RuntimeError(f"scheduler quote provenance missing: {event.symbol}")

    provider_status = str(snapshot.get("provider_status") or "live").strip().lower()
    if provider_status not in _HEALTHY_PROVIDER_STATUSES:
        raise RuntimeError(
            f"scheduler quote provider is not healthy: {event.symbol} "
            f"({provider_status or 'missing'})"
        )

    source_is_estimate = is_fund_estimate_quote_source(quote_source)
    raw_quote_status = snapshot.get("quote_status")
    quote_status = normalize_market_data_status(
        MarketDataStatus.ESTIMATED
        if source_is_estimate
        else (
            MarketDataStatus.LIVE
            if raw_quote_status in {None, ""}
            else raw_quote_status
        )
    )
    if quote_status in {
        MarketDataStatus.CACHE,
        MarketDataStatus.MISSING,
        MarketDataStatus.STALE,
    }:
        raise RuntimeError(
            f"scheduler quote quality is not usable: {event.symbol} "
            f"({quote_status.value})"
        )

    age_seconds = (current - timestamp).total_seconds()
    quote_for_ttl = {
        "asset_class": event.asset_class.value,
        "quote_source": quote_source,
    }
    ttl_seconds = quote_live_ttl_seconds(
        quote_for_ttl,
        live_poll_interval=live_poll_interval,
    )
    if timestamp.date() < expected_quote_date(current) or age_seconds > ttl_seconds:
        raise RuntimeError(f"scheduler quote is stale: {event.symbol}")

    strategy_eligible = quote_status in _STRATEGY_QUOTE_STATUSES
    stale_reason = (
        None
        if strategy_eligible
        else str(
            snapshot.get("stale_reason")
            or (
                "confirmed_fund_nav_missing_estimate_only"
                if source_is_estimate
                else "quote_quality_not_strategy_eligible"
            )
        )
    )
    return SchedulerQuoteEvidence(
        quote_timestamp=timestamp.isoformat(),
        quote_source=quote_source,
        provider_name=provider_name,
        quote_status=quote_status.value,
        provider_status="live",
        stale_reason=stale_reason,
        strategy_eligible=strategy_eligible,
    )
