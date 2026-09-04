"""Canonical quote timestamp and freshness projections.

This module is intentionally independent from HTTP routes so market and
portfolio delivery adapters can share one fail-closed freshness contract.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from data.market_data import FUND_ESTIMATE_QUOTE_SOURCES
from server.services.market_hours import get_shanghai_now, is_cn_trading_session

_CN_MORNING_OPEN = time(9, 30)
_FUND_ESTIMATE_QUOTE_SOURCES = FUND_ESTIMATE_QUOTE_SOURCES | {"eastmoney_fund_page"}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MISSING_VALUATION_STATUSES = {"missing", "error"}
_DEGRADED_VALUATION_STATUSES = {
    "stale",
    "estimated",
    "confirmed_nav_missing",
    "confirmed_fund_nav_missing_estimate_only",
}


def quote_valuation_status(quote: dict) -> str:
    """Classify whether one persisted quote can support account valuation."""

    quote_status_value = str(quote.get("quote_status") or "live").strip().lower()
    if quote_status_value in _MISSING_VALUATION_STATUSES:
        return "missing"
    if quote_status_value in _DEGRADED_VALUATION_STATUSES:
        return "degraded"
    if quote.get("valuation_baseline_status") == "missing":
        return "degraded"
    return "complete"


def quote_valuation_blocker(quote: dict | None, *, symbol: str) -> str:
    """Return the canonical account-valuation blocker for one holding."""

    if not quote or quote.get("price") in {None, "", 0, 0.0}:
        return f"missing_market_price:{symbol}"
    quote_status_value = str(quote.get("quote_status") or "").strip().lower()
    if quote_status_value in {
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }:
        return f"confirmed_nav_missing:{symbol}"
    if quote.get("valuation_baseline_status") == "missing":
        return f"valuation_baseline_missing:{symbol}"
    return f"market_evidence_{quote_status_value or 'degraded'}:{symbol}"


def parse_quote_timestamp(timestamp: object) -> datetime | None:
    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str) and timestamp.strip():
        value = timestamp.strip().replace("T ", "T")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(f"{value}T00:00:00")
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ)


def previous_weekday(day: date) -> date:
    current = day - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def expected_quote_date(now: datetime | None = None) -> date:
    current = get_shanghai_now(now)
    if current.weekday() >= 5:
        return previous_weekday(current.date())
    if current.time() < _CN_MORNING_OPEN:
        return previous_weekday(current.date())
    return current.date()


def quote_asset_class(quote: dict | None) -> str:
    if not quote:
        return ""
    value = quote.get("asset_class") or quote.get("asset_type")
    if hasattr(value, "value"):
        value = value.value
    return str(value or "").strip().lower()


def quote_source_name(quote: dict | None) -> str:
    if not quote:
        return ""
    value = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    return str(value or "").strip().lower()


def quote_live_ttl_seconds(
    quote: dict | None,
    *,
    live_poll_interval: int | None = None,
) -> int:
    base_seconds = max(int(live_poll_interval or 60), 15)
    asset_class = quote_asset_class(quote)
    source = quote_source_name(quote)
    if asset_class in {"fund", "etf"} and source in _FUND_ESTIMATE_QUOTE_SOURCES:
        return max(base_seconds * 10, 600)
    return max(base_seconds * 5, 300)


def quote_is_stale(
    quote: dict | None,
    *,
    now: datetime | None = None,
    live_poll_interval: int | None = None,
) -> bool:
    if not quote or quote.get("price") in {None, ""}:
        return True

    timestamp = parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return True

    current = get_shanghai_now(now)
    if timestamp.date() < expected_quote_date(current):
        return True

    if is_cn_trading_session(current):
        ttl_seconds = quote_live_ttl_seconds(
            quote,
            live_poll_interval=live_poll_interval,
        )
        return (current - timestamp).total_seconds() > ttl_seconds

    return False


def quote_status(
    state: object,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    raw_status = str(quote.get("quote_status") or "").strip().lower() if quote else ""
    if raw_status in {"missing", "error", "stale", "estimated"}:
        return raw_status
    if raw_status in {
        "cache",
        "cached",
        "cache_only",
        "cache_only_after_market_data_permission_fallback",
    }:
        return "cache"
    if raw_status in {
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }:
        return "confirmed_nav_missing"
    config = getattr(state, "config", None)
    return (
        "stale"
        if quote_is_stale(
            quote,
            now=now,
            live_poll_interval=getattr(config, "live_poll_interval", 60),
        )
        else "live"
    )
