"""Typed command contract for one complete quote-ingestion observation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentType

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_MIN_QUOTE_INSTANT = datetime.min.replace(tzinfo=timezone.utc)
PUBLISHED_QUOTE_RUN_STATUSES = frozenset({"success"})
_QUOTE_AUTHORITY_FIELDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("price", ("price", "value"), True),
    ("previous_close", ("previous_close",), True),
    ("change", ("change",), True),
    ("change_percent", ("change_percent",), True),
    ("volume", ("volume",), True),
    ("turnover", ("turnover",), True),
    ("quote_source", ("quote_source", "source"), False),
    ("provider_name", ("provider_name",), False),
    ("provider_status", ("provider_status",), False),
    ("quote_status", ("quote_status", "status"), False),
    ("stale_reason", ("stale_reason",), False),
    ("error", ("error", "error_message"), False),
    ("nav_date", ("nav_date",), False),
    ("previous_close_date", ("previous_close_date",), False),
    ("daily_close_price", ("daily_close_price",), True),
    ("daily_close_date", ("daily_close_date",), False),
    ("daily_close_source", ("daily_close_source",), False),
)


class DailyCloseEvidenceConflict(ValueError):
    """Carry the failed transaction's fact bindings across its rollback."""

    def __init__(self, binding: dict[str, Any] | None = None) -> None:
        super().__init__("daily close evidence conflict")
        self.binding = binding


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
    identity_provenance: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    daily_close_price: float | None = None
    daily_close_date: str | None = None
    daily_close_source: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("quote ingestion symbol must not be empty")
        if not self.asset_type.strip():
            raise ValueError("quote ingestion asset_type must not be empty")
        raw_asset_type = self.asset_type.strip().lower().replace("-", "_")
        try:
            canonical_type = InstrumentType.from_persisted(raw_asset_type)
        except ValueError as exc:
            raise ValueError("quote ingestion instrument type is unresolved") from exc
        object.__setattr__(self, "asset_type", canonical_type.value)
        identity_provenance = (
            "legacy_fund_compatibility"
            if raw_asset_type == "fund"
            else self.identity_provenance or "explicit_canonical"
        )
        object.__setattr__(self, "identity_provenance", identity_provenance)
        object.__setattr__(
            self,
            "metadata",
            {**self.metadata, "identity_provenance": identity_provenance},
        )
        if not self.quote_timestamp.strip():
            raise ValueError("quote ingestion timestamp must not be empty")
        _require_iso_datetime("quote_timestamp", self.quote_timestamp)
        if self.captured_at is not None:
            _require_iso_datetime("captured_at", self.captured_at)
            validate_quote_authority_time(
                quote_timestamp=self.quote_timestamp,
                authority_timestamp=self.captured_at,
            )
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
        broad_asset_class = (
            "fund"
            if self.asset_type == InstrumentType.OPEN_END_FUND.value
            else self.asset_type
        )
        return {
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "instrument_type": self.asset_type,
            "asset_class": broad_asset_class,
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
            "identity_provenance": self.identity_provenance,
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


def quote_timestamp_instant(value: Any) -> datetime:
    """Normalize one quote timestamp to its canonical UTC instant."""

    text = str(value or "").strip()
    if not text:
        return _MIN_QUOTE_INSTANT
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _MIN_QUOTE_INSTANT
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed.astimezone(timezone.utc)


def validate_quote_authority_time(
    *,
    quote_timestamp: str,
    authority_timestamp: str,
) -> None:
    """Reject observations later than their explicit authoritative capture time."""

    quote_instant = quote_timestamp_instant(quote_timestamp)
    authority_instant = quote_timestamp_instant(authority_timestamp)
    if quote_instant == _MIN_QUOTE_INSTANT:
        raise ValueError("quote ingestion quote_timestamp must be an ISO datetime")
    if authority_instant == _MIN_QUOTE_INSTANT:
        raise ValueError("quote ingestion authority timestamp must be an ISO datetime")
    if quote_instant > authority_instant:
        raise ValueError(
            "quote ingestion quote_timestamp must not be later than "
            "the authoritative capture time"
        )


def quote_authority_conflict_fields(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return conflicting same-observation authority fields deterministically."""

    conflicts: list[str] = []
    for field_name, aliases, numeric in _QUOTE_AUTHORITY_FIELDS:
        left_present, left_value = _authority_value(left, aliases)
        right_present, right_value = _authority_value(right, aliases)
        if not left_present or not right_present:
            continue
        if _normalized_authority_value(left_value, numeric=numeric) != (
            _normalized_authority_value(right_value, numeric=numeric)
        ):
            conflicts.append(field_name)
    return tuple(conflicts)


def _authority_value(
    row: Mapping[str, Any], aliases: tuple[str, ...]
) -> tuple[bool, Any]:
    for alias in aliases:
        if alias in row:
            return True, row[alias]
    return False, None


def _normalized_authority_value(value: Any, *, numeric: bool) -> Any:
    if not numeric:
        return None if value is None else str(value).strip()
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def _require_positive_finite(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) <= 0:
        raise ValueError(f"quote ingestion {name} must be positive")


def _require_non_negative_finite(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) < 0:
        raise ValueError(f"quote ingestion {name} must be non-negative")


__all__ = [
    "PUBLISHED_QUOTE_RUN_STATUSES",
    "QuoteIngestionCommand",
    "quote_authority_conflict_fields",
    "quote_timestamp_instant",
    "validate_quote_authority_time",
]
