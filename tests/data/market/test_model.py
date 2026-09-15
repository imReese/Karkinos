"""Market Data 核心值对象测试。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        symbol="600000",
        instrument_type=InstrumentType.STOCK,
    )


def _bar(
    *,
    instrument: InstrumentKey | None = None,
    session_date: date = date(2026, 9, 15),
    event_time: datetime | None = None,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    open_price: Decimal = Decimal("10.31"),
    high: Decimal = Decimal("10.52"),
    low: Decimal = Decimal("10.20"),
    close: Decimal = Decimal("10.48"),
    volume: Decimal = Decimal("123456"),
    amount: Decimal = Decimal("1283912.42"),
    suspended: bool = False,
) -> DailyBarObservation:
    return DailyBarObservation(
        instrument=instrument or _instrument(),
        session_date=session_date,
        event_time=event_time
        or datetime(
            2026,
            9,
            15,
            15,
            0,
            tzinfo=_SHANGHAI,
        ),
        available_at=available_at
        or datetime(
            2026,
            9,
            15,
            15,
            1,
            tzinfo=_SHANGHAI,
        ),
        captured_at=captured_at
        or datetime(
            2026,
            9,
            15,
            15,
            3,
            tzinfo=_SHANGHAI,
        ),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=amount,
        suspended=suspended,
    )


def test_daily_bar_accepts_valid_observation() -> None:
    bar = _bar()

    assert bar.instrument == _instrument()
    assert bar.session_date == date(2026, 9, 15)

    assert bar.open == Decimal("10.31")
    assert bar.high == Decimal("10.52")
    assert bar.low == Decimal("10.20")
    assert bar.close == Decimal("10.48")

    assert bar.volume == Decimal("123456")
    assert bar.amount == Decimal("1283912.42")

    assert bar.suspended is False


def test_daily_bar_normalizes_instants_to_utc() -> None:
    bar = _bar()

    assert bar.event_time == datetime(
        2026,
        9,
        15,
        7,
        0,
        tzinfo=timezone.utc,
    )
    assert bar.available_at == datetime(
        2026,
        9,
        15,
        7,
        1,
        tzinfo=timezone.utc,
    )
    assert bar.captured_at == datetime(
        2026,
        9,
        15,
        7,
        3,
        tzinfo=timezone.utc,
    )


def test_equivalent_timezone_instants_have_same_canonical_value() -> None:
    shanghai = _bar()

    utc = _bar(
        event_time=datetime(
            2026,
            9,
            15,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        available_at=datetime(
            2026,
            9,
            15,
            7,
            1,
            tzinfo=timezone.utc,
        ),
        captured_at=datetime(
            2026,
            9,
            15,
            7,
            3,
            tzinfo=timezone.utc,
        ),
    )

    assert shanghai == utc


@pytest.mark.parametrize(
    "field",
    [
        "event_time",
        "available_at",
        "captured_at",
    ],
)
def test_daily_bar_rejects_naive_datetime(field: str) -> None:
    kwargs = {
        field: datetime(
            2026,
            9,
            15,
            15,
            0,
        )
    }

    with pytest.raises(
        ValueError,
        match=f"daily_bar_{field}_must_be_timezone_aware",
    ):
        _bar(**kwargs)


def test_daily_bar_requires_event_before_availability() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_available_before_event",
    ):
        _bar(
            event_time=datetime(
                2026,
                9,
                15,
                15,
                2,
                tzinfo=_SHANGHAI,
            ),
            available_at=datetime(
                2026,
                9,
                15,
                15,
                1,
                tzinfo=_SHANGHAI,
            ),
        )


def test_daily_bar_requires_availability_before_capture() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_captured_before_available",
    ):
        _bar(
            available_at=datetime(
                2026,
                9,
                15,
                15,
                5,
                tzinfo=_SHANGHAI,
            ),
            captured_at=datetime(
                2026,
                9,
                15,
                15,
                3,
                tzinfo=_SHANGHAI,
            ),
        )


def test_daily_bar_event_must_belong_to_session_date() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_event_session_mismatch",
    ):
        _bar(
            session_date=date(2026, 9, 14),
        )


def test_daily_bar_rejects_datetime_as_session_date() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_session_date_must_be_date",
    ):
        _bar(
            session_date=datetime(
                2026,
                9,
                15,
                tzinfo=timezone.utc,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_price", Decimal("0")),
        ("high", Decimal("0")),
        ("low", Decimal("0")),
        ("close", Decimal("0")),
        ("open_price", Decimal("-1")),
        ("close", Decimal("-0.01")),
    ],
)
def test_daily_bar_requires_positive_prices(
    field: str,
    value: Decimal,
) -> None:
    kwargs = {field: value}

    expected_field = "open" if field == "open_price" else field

    with pytest.raises(
        ValueError,
        match=f"daily_bar_{expected_field}_must_be_positive",
    ):
        _bar(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("volume", Decimal("-1")),
        ("amount", Decimal("-0.01")),
    ],
)
def test_daily_bar_requires_non_negative_activity(
    field: str,
    value: Decimal,
) -> None:
    with pytest.raises(
        ValueError,
        match=f"daily_bar_{field}_must_be_non_negative",
    ):
        _bar(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_price", 10.31),
        ("high", 10.52),
        ("low", 10.20),
        ("close", 10.48),
        ("volume", 123456),
        ("amount", 1283912.42),
    ],
)
def test_daily_bar_requires_decimal_numeric_values(
    field: str,
    value: object,
) -> None:
    expected_field = "open" if field == "open_price" else field

    with pytest.raises(
        TypeError,
        match=f"daily_bar_{expected_field}_must_be_decimal",
    ):
        _bar(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open_price", Decimal("NaN")),
        ("high", Decimal("Infinity")),
        ("low", Decimal("-Infinity")),
        ("volume", Decimal("NaN")),
        ("amount", Decimal("Infinity")),
    ],
)
def test_daily_bar_rejects_non_finite_decimals(
    field: str,
    value: Decimal,
) -> None:
    expected_field = "open" if field == "open_price" else field

    with pytest.raises(
        ValueError,
        match=f"daily_bar_{expected_field}_must_be_finite",
    ):
        _bar(**{field: value})


def test_daily_bar_requires_high_not_below_low() -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_high_below_low",
    ):
        _bar(
            high=Decimal("10.10"),
            low=Decimal("10.20"),
        )


@pytest.mark.parametrize(
    ("open_price", "high", "close"),
    [
        (
            Decimal("10.60"),
            Decimal("10.52"),
            Decimal("10.48"),
        ),
        (
            Decimal("10.31"),
            Decimal("10.40"),
            Decimal("10.48"),
        ),
    ],
)
def test_daily_bar_high_must_cover_open_and_close(
    open_price: Decimal,
    high: Decimal,
    close: Decimal,
) -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_high_below_open_or_close",
    ):
        _bar(
            open_price=open_price,
            high=high,
            close=close,
        )


@pytest.mark.parametrize(
    ("open_price", "low", "close"),
    [
        (
            Decimal("10.10"),
            Decimal("10.20"),
            Decimal("10.48"),
        ),
        (
            Decimal("10.31"),
            Decimal("10.40"),
            Decimal("10.30"),
        ),
    ],
)
def test_daily_bar_low_must_cover_open_and_close(
    open_price: Decimal,
    low: Decimal,
    close: Decimal,
) -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_low_above_open_or_close",
    ):
        _bar(
            open_price=open_price,
            low=low,
            close=close,
        )


def test_suspended_daily_bar_allows_zero_activity() -> None:
    bar = _bar(
        volume=Decimal("0"),
        amount=Decimal("0"),
        suspended=True,
    )

    assert bar.suspended is True
    assert bar.volume == Decimal("0")
    assert bar.amount == Decimal("0")


@pytest.mark.parametrize(
    ("volume", "amount"),
    [
        (Decimal("1"), Decimal("0")),
        (Decimal("0"), Decimal("1")),
        (Decimal("1"), Decimal("1")),
    ],
)
def test_suspended_daily_bar_rejects_trading_activity(
    volume: Decimal,
    amount: Decimal,
) -> None:
    with pytest.raises(
        ValueError,
        match="daily_bar_suspended_with_trading_activity",
    ):
        _bar(
            volume=volume,
            amount=amount,
            suspended=True,
        )


def test_daily_bar_requires_instrument_key() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_instrument_must_be_instrument_key",
    ):
        _bar(
            instrument="600000",
        )


def test_daily_bar_requires_boolean_suspension_state() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_suspended_must_be_bool",
    ):
        _bar(
            suspended=1,
        )
