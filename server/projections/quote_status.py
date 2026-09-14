"""Canonical quote timestamp and freshness projections.

This module is intentionally independent from HTTP routes so market and
portfolio delivery adapters can share one fail-closed freshness contract.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from data.market_data import FUND_ESTIMATE_QUOTE_SOURCES, is_fund_estimate_quote_source
from server.services.market_calendar_dates import project_market_session
from server.services.market_hours import get_shanghai_now, is_cn_trading_session

_CN_MORNING_OPEN = time(9, 30)
_FUND_ESTIMATE_QUOTE_SOURCES = FUND_ESTIMATE_QUOTE_SOURCES | {"eastmoney_fund_page"}
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MISSING_VALUATION_STATUSES = {"missing", "error", "conflicting", "conflict", "unknown"}
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
    if quote_status_value not in {
        "live",
        "confirmed",
        "fresh",
        "healthy",
        "cache",
        "cached",
        "cache_only",
        "cache_only_after_market_data_permission_fallback",
        *_DEGRADED_VALUATION_STATUSES,
    }:
        return "missing"
    if quote_status_value in _DEGRADED_VALUATION_STATUSES:
        return "degraded"
    if is_fund_estimate_quote_source(quote_source_name(quote)):
        return "degraded"
    if quote_pricing_semantics(quote)["pricing_authority"] in {
        "missing",
        "non_authoritative",
        "conflicting",
    }:
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
    authority = quote_pricing_semantics(quote)["pricing_authority"]
    if authority in {"missing", "non_authoritative", "conflicting"}:
        return f"pricing_authority_{authority}:{symbol}"
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
    db: Any = None,
    market_session: dict[str, Any] | None = None,
    for_valuation: bool = False,
) -> bool:
    return (
        quote_freshness_reason(
            quote,
            now=now,
            live_poll_interval=live_poll_interval,
            db=db,
            market_session=market_session,
            for_valuation=for_valuation,
        )
        is not None
    )


def quote_freshness_reason(
    quote: dict | None,
    *,
    now: datetime | None = None,
    live_poll_interval: int | None = None,
    db: Any = None,
    market_session: dict[str, Any] | None = None,
    for_valuation: bool = False,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return "no_real_data_available"

    timestamp = parse_quote_timestamp(
        quote.get("quote_timestamp") or quote.get("timestamp")
    )
    if timestamp is None:
        return "invalid_quote_timestamp"

    current = get_shanghai_now(now)
    if timestamp > current + timedelta(minutes=1):
        return "quote_timestamp_after_valuation_clock"
    session = (
        market_session
        if market_session is not None
        else project_market_session(db, current)
    )
    if session["calendar_available"] and (
        not session["calendar_verified"] or session["blockers"]
    ):
        return "market_calendar_not_verified"
    published_nav = (
        for_valuation
        and quote_pricing_semantics(quote)["pricing_kind"] == "published_nav"
    )
    expected = (
        session["latest_completed_trade_date"]
        if published_nav
        else session["expected_quote_date"]
    )
    expected_date = (
        date.fromisoformat(expected) if expected else expected_quote_date(current)
    )
    pricing_date = timestamp.date()
    if published_nav and quote.get("nav_date"):
        nav_timestamp = parse_quote_timestamp(quote["nav_date"])
        if nav_timestamp is None or nav_timestamp.date() > current.date():
            return "invalid_nav_date"
        pricing_date = nav_timestamp.date()
    if pricing_date < expected_date:
        return "quote_older_than_expected_session"
    if session["calendar_verified"] and pricing_date > expected_date:
        return "quote_after_expected_session"
    market_open = (
        session["status"] == "open"
        if session["calendar_verified"]
        else is_cn_trading_session(current)
    )
    if market_open and not published_nav:
        ttl_seconds = quote_live_ttl_seconds(
            quote,
            live_poll_interval=live_poll_interval,
        )
        if (current - timestamp).total_seconds() > ttl_seconds:
            return "quote_older_than_live_ttl"

    return None


def current_quote_valuation_evidence(
    quote: dict,
    *,
    now: datetime | None = None,
    market_session: dict[str, Any] | None = None,
) -> dict:
    """Reassess a copy of published evidence without rewriting its identity."""
    projected = dict(quote)
    if quote_valuation_status(projected) != "complete":
        return projected
    reason = quote_freshness_reason(
        projected, now=now, market_session=market_session, for_valuation=True
    )
    if reason:
        projected.setdefault("observed_quote_status", projected.get("quote_status"))
        projected["quote_status"] = "stale"
        projected["stale_reason"] = reason
        projected["valuation_evidence_status"] = "stale"
    return projected


def quote_pricing_semantics(
    quote: dict | None,
    *,
    instrument_type: str | None = None,
    asset_class: str | None = None,
    market_session: dict[str, Any] | None = None,
) -> dict[str, str | None]:
    """Present the economic price kind independently of storage and freshness."""
    row = quote or {}
    timestamp = parse_quote_timestamp(
        row.get("quote_timestamp") or row.get("timestamp")
    )
    as_of = timestamp.isoformat() if timestamp else None
    status = str(row.get("quote_status") or "").strip().lower()
    source = quote_source_name(row)
    kind = "unknown"
    authority = "unknown"
    raw_type = (
        instrument_type
        or row.get("instrument_type")
        or asset_class
        or quote_asset_class(row)
    )
    normalized_type = (
        str(getattr(raw_type, "value", raw_type) or "").lower().replace("-", "_")
    )
    is_fund = normalized_type in {"fund", "open_end_fund", "openend_fund"}
    if status in {"conflict", "conflicting"}:
        kind, authority = "unavailable", "conflicting"
    elif (
        row.get("price") in {None, "", 0, 0.0} or status in _MISSING_VALUATION_STATUSES
    ):
        kind, authority = "unavailable", "missing"
    elif source in {"manual", "manual_mark", "manual_valuation"}:
        kind, authority = "manual_mark", "non_authoritative"
    elif is_fund and (is_fund_estimate_quote_source(source) or status == "estimated"):
        kind, authority = "estimated_nav", "non_authoritative"
    elif is_fund and status in {
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }:
        kind, authority = "nav_pending", "missing"
    elif is_fund:
        observed_status = str(row.get("observed_quote_status") or status).lower()
        if (
            source in {"eastmoney_fund_page", "tushare_fund_nav"}
            or observed_status == "confirmed"
        ):
            kind, authority = "published_nav", "authoritative"
            as_of = (
                str(
                    row.get("nav_date")
                    or (timestamp.date().isoformat() if timestamp else "")
                )
                or None
            )
        else:
            kind, authority = "nav_pending", "missing"
    elif normalized_type in {"stock", "etf"}:
        kind, authority = "realtime_quote", "authoritative"
        if (
            source == "market_bar_close"
            or row.get("valuation_price_source") == "market_bar_close"
            or (timestamp and timestamp.time() >= time(15))
        ):
            kind = "session_close"
            as_of = (
                str(row.get("valuation_price_date") or timestamp.date().isoformat())
                if timestamp
                else str(row.get("valuation_price_date") or "") or None
            )
    return {
        "pricing_kind": kind,
        "pricing_as_of": as_of,
        "pricing_authority": authority,
    }


def quote_status(
    state: object,
    quote: dict | None,
    *,
    now: datetime | None = None,
) -> str:
    raw_status = str(quote.get("quote_status") or "").strip().lower() if quote else ""
    if raw_status in _MISSING_VALUATION_STATUSES | {"stale", "estimated"}:
        return raw_status
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
            db=getattr(state, "db", None),
        )
        else (
            "cache"
            if raw_status
            in {
                "cache",
                "cached",
                "cache_only",
                "cache_only_after_market_data_permission_fallback",
            }
            else "live"
        )
    )
