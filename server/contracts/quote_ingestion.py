"""Typed command contract for one complete quote-ingestion observation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class QuoteIngestionCommand:
    symbol: str
    asset_type: str
    price: float
    quote_timestamp: str
    volume: float | None = None
    previous_close: float | None = None
    previous_close_date: str | None = None
    change: float | None = None
    change_percent: float | None = None
    turnover: float | None = None
    quote_source: str | None = None
    provider_name: str | None = None
    provider_status: str | None = None
    quote_status: str = "live"
    stale_reason: str | None = None
    captured_at: str | None = None
    captured_reason: str | None = None
    nav_date: str | None = None
    fetch_run_id: str | None = None
    display_name: str | None = None
    provider_symbol: str | None = None
    exchange: str | None = None
    market: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    daily_close_price: float | None = None
    daily_close_date: str | None = None
    daily_close_source: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("quote ingestion symbol must not be empty")
        if not self.asset_type.strip():
            raise ValueError("quote ingestion asset_type must not be empty")
        if not self.quote_timestamp.strip():
            raise ValueError("quote ingestion timestamp must not be empty")
        _require_iso_datetime("quote_timestamp", self.quote_timestamp)
        if self.captured_at is not None:
            _require_iso_datetime("captured_at", self.captured_at)
        if self.fetch_run_id is not None and not self.fetch_run_id.strip():
            raise ValueError("quote ingestion fetch_run_id must not be blank")
        if (self.daily_close_price is None) != (self.daily_close_date is None):
            raise ValueError("daily close price and date must be provided together")
        _require_positive_finite("price", self.price)
        for name in ("previous_close", "daily_close_price"):
            value = getattr(self, name)
            if value is not None:
                _require_positive_finite(name, value)
        for name in ("volume", "turnover"):
            value = getattr(self, name)
            if value is not None:
                _require_non_negative_finite(name, value)
        for name in ("change", "change_percent"):
            value = getattr(self, name)
            if value is not None:
                _require_finite(name, value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def valuation_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "asset_class": self.asset_type,
            "price": self.price,
            "previous_close": self.previous_close,
            "previous_close_date": self.previous_close_date,
            "change": self.change,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "turnover": self.turnover,
            "quote_timestamp": self.quote_timestamp,
            "timestamp": self.quote_timestamp,
            "quote_source": self.quote_source,
            "source": self.source or self.quote_source,
            "provider_name": self.provider_name,
            "provider_status": self.provider_status,
            "quote_status": self.quote_status,
            "stale_reason": self.stale_reason,
            "captured_at": self.captured_at,
            "captured_reason": self.captured_reason,
            "nav_date": self.nav_date,
            "fetch_run_id": self.fetch_run_id,
            "display_name": self.display_name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> QuoteIngestionCommand:
        return cls(**payload)


def _require_finite(name: str, value: float) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"quote ingestion {name} must be finite")


def _require_iso_datetime(name: str, value: str) -> None:
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"quote ingestion {name} must be an ISO datetime") from None


def _require_positive_finite(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) <= 0:
        raise ValueError(f"quote ingestion {name} must be positive")


def _require_non_negative_finite(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) < 0:
        raise ValueError(f"quote ingestion {name} must be non-negative")


__all__ = ["QuoteIngestionCommand"]
