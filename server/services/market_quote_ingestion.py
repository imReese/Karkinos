"""Typed application command for atomic quote-fact ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
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
    previous_close_date = str(snapshot.get("previous_close_date") or "").strip()
    if daily_close_price is None and previous_close is not None and previous_close_date:
        daily_close_price = previous_close
        daily_close_date = previous_close_date
        daily_close_source = "reported_previous_close"
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type=asset_type,
        price=float(snapshot["price"]),
        quote_timestamp=timestamp,
        volume=_optional_float(snapshot.get("volume")),
        previous_close=previous_close,
        previous_close_date=previous_close_date or None,
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
        metadata={
            "source": snapshot.get("source"),
            "quote_source": quote_source,
            "display_name": display_name or None,
        },
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


def _optional_float(value: object) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


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
