"""Typed application command for atomic quote-fact ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from server.contracts.quote_ingestion import QuoteIngestionCommand

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class QuoteIngestionPersistence(Protocol):
    def persist_quote_ingestion_sync(
        self,
        command: QuoteIngestionCommand,
    ) -> dict[str, Any]: ...


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
) -> QuoteIngestionCommand:
    captured_at_value = captured_at or datetime.now(_SHANGHAI_TZ).isoformat()
    timestamp = _normalize_quote_timestamp(
        str(snapshot.get("timestamp") or "").strip(),
        captured_at=captured_at_value,
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
    previous_close_date = _validated_previous_close_date(
        reported_previous_close_date,
        quote_timestamp=timestamp,
    )
    if daily_close_price is None and previous_close is not None and previous_close_date:
        daily_close_price = previous_close
        daily_close_date = previous_close_date
        daily_close_source = "reported_previous_close"
    metadata = {
        "source": snapshot.get("source"),
        "quote_source": quote_source,
        "display_name": display_name or None,
    }
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
            snapshot.get("change_percent") or snapshot.get("pct_chg")
        ),
        turnover=_optional_float(snapshot.get("turnover") or snapshot.get("amount")),
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


def _validated_previous_close_date(
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


def _shanghai_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    else:
        parsed = parsed.astimezone(_SHANGHAI_TZ)
    return parsed.date()


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
]
