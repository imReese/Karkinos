"""Canonical market-data value models.

This module contains pure immutable domain values only.

It performs no provider access, filesystem I/O, persistence, DataFrame
conversion, or Parquet serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from core.types import InstrumentKey

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DailyBarObservation:
    """One canonical point-in-time daily market-bar observation.

    This is not a provider response and not a Dataset row.

    Provider-specific payloads are normalized into this representation.
    MarketRevision later binds collections of these observations to provider
    capture and revision provenance.
    """

    instrument: InstrumentKey
    session_date: date

    event_time: datetime
    available_at: datetime
    captured_at: datetime

    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    volume: Decimal
    amount: Decimal

    suspended: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, InstrumentKey):
            raise TypeError("daily_bar_instrument_must_be_instrument_key")

        if isinstance(self.session_date, datetime) or not isinstance(
            self.session_date,
            date,
        ):
            raise TypeError("daily_bar_session_date_must_be_date")

        event_time = _utc_instant(
            self.event_time,
            field="event_time",
        )
        available_at = _utc_instant(
            self.available_at,
            field="available_at",
        )
        captured_at = _utc_instant(
            self.captured_at,
            field="captured_at",
        )

        if event_time > available_at:
            raise ValueError("daily_bar_available_before_event")

        if available_at > captured_at:
            raise ValueError("daily_bar_captured_before_available")

        event_session = event_time.astimezone(_SHANGHAI).date()

        if event_session != self.session_date:
            raise ValueError("daily_bar_event_session_mismatch")

        for field_name in ("open", "high", "low", "close"):
            value = getattr(self, field_name)
            _require_positive_decimal(
                value,
                field=field_name,
            )

        _require_non_negative_decimal(
            self.volume,
            field="volume",
        )
        _require_non_negative_decimal(
            self.amount,
            field="amount",
        )

        if self.high < self.low:
            raise ValueError("daily_bar_high_below_low")

        if self.high < self.open or self.high < self.close:
            raise ValueError("daily_bar_high_below_open_or_close")

        if self.low > self.open or self.low > self.close:
            raise ValueError("daily_bar_low_above_open_or_close")

        if not isinstance(self.suspended, bool):
            raise TypeError("daily_bar_suspended_must_be_bool")

        if self.suspended and (self.volume != _ZERO or self.amount != _ZERO):
            raise ValueError("daily_bar_suspended_with_trading_activity")

        # Canonicalize all instants to UTC so equivalent timestamps do not
        # produce different downstream identities merely because they used
        # different timezone offsets.
        object.__setattr__(
            self,
            "event_time",
            event_time,
        )
        object.__setattr__(
            self,
            "available_at",
            available_at,
        )
        object.__setattr__(
            self,
            "captured_at",
            captured_at,
        )


def _utc_instant(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"daily_bar_{field}_must_be_datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"daily_bar_{field}_must_be_timezone_aware")

    return value.astimezone(timezone.utc)


def _require_positive_decimal(
    value: Decimal,
    *,
    field: str,
) -> None:
    _require_decimal(value, field=field)

    if value <= _ZERO:
        raise ValueError(f"daily_bar_{field}_must_be_positive")


def _require_non_negative_decimal(
    value: Decimal,
    *,
    field: str,
) -> None:
    _require_decimal(value, field=field)

    if value < _ZERO:
        raise ValueError(f"daily_bar_{field}_must_be_non_negative")


def _require_decimal(
    value: Decimal,
    *,
    field: str,
) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"daily_bar_{field}_must_be_decimal")

    if not value.is_finite():
        raise ValueError(f"daily_bar_{field}_must_be_finite")
