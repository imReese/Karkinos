"""Typed application command for atomic quote-fact ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from core.types import InstrumentType
from data.market_data import (
    PUBLISHED_FUND_NAV_QUOTE_SOURCES,
    is_healthy_published_fund_nav,
)
from server.contracts.quote_ingestion import (
    QuoteIngestionCommand,
    fund_nav_pricing_date,
)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class QuoteIngestionPersistence(Protocol):
    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]: ...


def resolve_daily_close_evidence(
    *,
    asset_type: str,
    price: float | None,
    quote_timestamp: str,
    quote_source: str,
    provider_status: str | None,
    quote_status: str,
    stale_reason: str | None = None,
    nav_date: str | None,
    previous_close: float | None,
    previous_close_date: str | None,
    daily_close_price: float | None = None,
    daily_close_date: str | None = None,
    daily_close_source: str | None = None,
    include_reported_previous_close: bool = True,
    allow_scheduler_close: bool = False,
    afternoon_close: time | None = None,
) -> tuple[float | None, str | None, str | None]:
    """Admit official daily close facts while keeping estimates auditable only."""
    if InstrumentType.from_persisted(asset_type) is InstrumentType.OPEN_END_FUND:
        if not is_healthy_published_fund_nav(
            quote_source, quote_status, provider_status, stale_reason
        ):
            return None, None, None
        observed_day = _shanghai_date(quote_timestamp)
        pricing_day = fund_nav_pricing_date(nav_date, quote_timestamp)
        if (
            price is None
            or price <= 0
            or observed_day is None
            or not pricing_day
            or pricing_day > observed_day.isoformat()
        ):
            return None, None, None
        if daily_close_price is not None:
            if daily_close_date != pricing_day or daily_close_price != price:
                return None, None, None
            return daily_close_price, daily_close_date, daily_close_source
        if include_reported_previous_close:
            return price, pricing_day, quote_source.strip().lower()
        return None, None, None

    if daily_close_price is not None:
        return daily_close_price, daily_close_date, daily_close_source
    if not include_reported_previous_close:
        return None, None, None
    if previous_close is not None and previous_close_date:
        return float(previous_close), previous_close_date, "reported_previous_close"
    if allow_scheduler_close and afternoon_close is not None and price is not None:
        observed = _shanghai_datetime(quote_timestamp)
        if observed is not None and observed.time() >= afternoon_close:
            return float(price), observed.date().isoformat(), "scheduler_close"
    return None, None, None


def build_quote_ingestion_command(
    *,
    symbol: str,
    asset_type: str,
    snapshot: Mapping[str, Any],
    quote_source: str | None,
    provider_name: str | None,
    provider_status: str | None,
    quote_status: str,
    captured_reason: str,
    fetch_run_id: str | None,
    captured_at: str | None = None,
    nav_date: str | None = None,
    daily_close_price: float | None = None,
    daily_close_date: str | None = None,
    daily_close_source: str | None = None,
    include_reported_previous_close: bool = True,
) -> QuoteIngestionCommand:
    """Build one observation under the caller's daily-close admission policy."""
    captured_at_value = captured_at or datetime.now(_SHANGHAI_TZ).isoformat()
    source_timestamp = str(snapshot.get("timestamp") or "").strip()
    timestamp = _normalize_quote_timestamp(
        source_timestamp, captured_at=captured_at_value
    )
    if not timestamp:
        raise ValueError("quote snapshot timestamp is required")
    display_name = str(
        snapshot.get("display_name")
        or snapshot.get("name")
        or snapshot.get("asset_name")
        or ""
    ).strip()
    previous_close = _optional_float(snapshot.get("previous_close"))
    reported_previous_close_date = str(
        snapshot.get("previous_close_date") or ""
    ).strip()
    previous_close_date = validated_previous_close_date(
        reported_previous_close_date,
        quote_timestamp=timestamp,
    )
    resolved_quote_source = str(
        quote_source or snapshot.get("quote_source") or snapshot.get("source") or ""
    ).strip()
    if (
        InstrumentType.from_persisted(asset_type) is InstrumentType.OPEN_END_FUND
        and resolved_quote_source.lower() in PUBLISHED_FUND_NAV_QUOTE_SOURCES
        and not nav_date
        and not fund_nav_pricing_date(None, source_timestamp)
    ):
        raise ValueError("missing_nav_date")
    daily_close_price, daily_close_date, daily_close_source = (
        resolve_daily_close_evidence(
            asset_type=asset_type,
            price=_optional_float(snapshot.get("price")),
            quote_timestamp=timestamp,
            quote_source=resolved_quote_source,
            provider_status=provider_status,
            quote_status=quote_status,
            stale_reason=(
                str(snapshot.get("stale_reason"))
                if snapshot.get("stale_reason")
                else None
            ),
            nav_date=nav_date,
            previous_close=previous_close,
            previous_close_date=previous_close_date,
            daily_close_price=daily_close_price,
            daily_close_date=daily_close_date,
            daily_close_source=daily_close_source,
            include_reported_previous_close=include_reported_previous_close,
        )
    )
    metadata = {
        "source": snapshot.get("source"),
        "quote_source": quote_source,
        "display_name": display_name or None,
    }
    source_metadata = snapshot.get("metadata")
    if isinstance(source_metadata, Mapping):
        for key in ("upstream_group", "transport_sdk"):
            value = source_metadata.get(key)
            if isinstance(value, str) and value.strip():
                metadata[key] = value.strip()
    if reported_previous_close_date and previous_close_date is None:
        metadata.update(
            {
                "discarded_previous_close_date": reported_previous_close_date,
                "discarded_previous_close_date_reason": (
                    "not_strictly_before_quote_trade_date"
                ),
            }
        )
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type=asset_type,
        price=float(snapshot["price"]),
        quote_timestamp=timestamp,
        volume=_optional_float(snapshot.get("volume")),
        previous_close=previous_close,
        previous_close_date=previous_close_date,
        change=_optional_float(snapshot.get("change")),
        change_percent=_optional_float(
            snapshot.get("change_percent")
            if snapshot.get("change_percent") is not None
            else snapshot.get("pct_chg")
        ),
        turnover=_optional_float(
            snapshot.get("turnover")
            if snapshot.get("turnover") is not None
            else snapshot.get("amount")
        ),
        quote_source=quote_source,
        provider_name=provider_name,
        provider_status=provider_status,
        quote_status=quote_status,
        stale_reason=(
            str(snapshot.get("stale_reason")) if snapshot.get("stale_reason") else None
        ),
        captured_at=captured_at_value,
        captured_reason=captured_reason,
        nav_date=nav_date,
        fetch_run_id=fetch_run_id,
        display_name=display_name or None,
        provider_symbol=str(snapshot.get("provider_symbol") or symbol),
        exchange=_optional_text(snapshot.get("exchange")),
        market=_optional_text(snapshot.get("market")),
        source=_optional_text(snapshot.get("source")) or quote_source,
        metadata=metadata,
        daily_close_price=daily_close_price,
        daily_close_date=daily_close_date,
        daily_close_source=daily_close_source,
    )


def persist_quote_ingestion(
    database: QuoteIngestionPersistence,
    command: QuoteIngestionCommand,
) -> dict[str, Any]:
    """Persist through the only write boundary for complete quote facts."""

    return database.persist_quote_ingestion_sync(command)


def _optional_float(value) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_text(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def validated_previous_close_date(
    value: str,
    *,
    quote_timestamp: str,
) -> str | None:
    """Keep a PRE_CLOSE date only when it owns an earlier Shanghai session.

    Some realtime providers label PRE_CLOSE beside the current quote date even
    though the value belongs to the preceding trading session. Treating that
    request date as authoritative used to materialize yesterday's price as
    today's daily close and later conflicted with verified post-close bars.
    """

    if not value:
        return None
    previous_date = _shanghai_date(value)
    quote_date = _shanghai_date(quote_timestamp)
    if previous_date is None or quote_date is None or previous_date >= quote_date:
        return None
    return previous_date.isoformat()


def _shanghai_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(_SHANGHAI_TZ)


def _shanghai_date(value: str) -> date | None:
    parsed = _shanghai_datetime(value)
    return None if parsed is None else parsed.date()


def _normalize_quote_timestamp(value: str, *, captured_at: str) -> str:
    """Bind provider time-only observations to the Shanghai capture date."""

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        pass
    try:
        observed_time = time.fromisoformat(value)
        captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        return value
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=_SHANGHAI_TZ)
    else:
        captured = captured.astimezone(_SHANGHAI_TZ)
    observed = datetime.combine(captured.date(), observed_time)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=_SHANGHAI_TZ)
    else:
        observed = observed.astimezone(_SHANGHAI_TZ)
    return observed.isoformat()


__all__ = [
    "QuoteIngestionPersistence",
    "build_quote_ingestion_command",
    "persist_quote_ingestion",
    "resolve_daily_close_evidence",
    "validated_previous_close_date",
]
