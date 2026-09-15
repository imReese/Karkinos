"""Market Data canonical normalization 测试。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation
from data.market.normalize import (
    canonicalize_daily_bars,
    normalize_daily_bar,
    normalize_decimal,
    normalize_session_date,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _instrument(
    symbol: str = "600000",
    instrument_type: InstrumentType = InstrumentType.STOCK,
) -> InstrumentKey:
    return InstrumentKey(
        symbol=symbol,
        instrument_type=instrument_type,
    )


def _bar(
    *,
    symbol: str = "600000",
    instrument_type: InstrumentType = InstrumentType.STOCK,
    session_date: date | str = date(2026, 9, 15),
    event_time: datetime | None = None,
    available_at: datetime | None = None,
    captured_at: datetime | None = None,
    open_value: Decimal | int | float | str = "10.31",
    high_value: Decimal | int | float | str = "10.52",
    low_value: Decimal | int | float | str = "10.20",
    close_value: Decimal | int | float | str = "10.48",
    volume: Decimal | int | float | str = "123456",
    amount: Decimal | int | float | str = "1283912.42",
    suspended: bool = False,
) -> DailyBarObservation:
    event = event_time or datetime(
        2026,
        9,
        15,
        15,
        0,
        tzinfo=_SHANGHAI,
    )
    available = available_at or datetime(
        2026,
        9,
        15,
        15,
        1,
        tzinfo=_SHANGHAI,
    )
    captured = captured_at or datetime(
        2026,
        9,
        15,
        15,
        3,
        tzinfo=_SHANGHAI,
    )

    return normalize_daily_bar(
        instrument=_instrument(
            symbol,
            instrument_type,
        ),
        session_date=session_date,
        event_time=event,
        available_at=available,
        captured_at=captured,
        open_value=open_value,
        high_value=high_value,
        low_value=low_value,
        close_value=close_value,
        volume=volume,
        amount=amount,
        suspended=suspended,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("10.31"), Decimal("10.31")),
        (10, Decimal("10")),
        (10.31, Decimal("10.31")),
        ("10.31", Decimal("10.31")),
        (" 10.31 ", Decimal("10.31")),
        ("0", Decimal("0")),
        ("-1.5", Decimal("-1.5")),
    ],
)
def test_normalize_decimal_accepts_common_provider_numeric_types(
    value,
    expected: Decimal,
) -> None:
    assert (
        normalize_decimal(
            value,
            field="close",
        )
        == expected
    )


def test_normalize_decimal_uses_float_decimal_text_representation() -> None:
    value = normalize_decimal(
        10.31,
        field="close",
    )

    # 不直接使用 Decimal(float)，避免把二进制浮点误差带入 canonical data。
    assert value == Decimal("10.31")
    assert value != Decimal(10.31)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
    ],
)
def test_normalize_decimal_rejects_missing_text(
    value: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="market_normalize_close_missing",
    ):
        normalize_decimal(
            value,
            field="close",
        )


@pytest.mark.parametrize(
    "value",
    [
        "not-a-number",
        "--",
        "1,234.56",
        "10.5%",
    ],
)
def test_normalize_decimal_rejects_provider_specific_text_formats(
    value: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="market_normalize_close_invalid",
    ):
        normalize_decimal(
            value,
            field="close",
        )


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
def test_normalize_decimal_rejects_non_finite_values(
    value,
) -> None:
    with pytest.raises(
        ValueError,
        match="market_normalize_close_must_be_finite",
    ):
        normalize_decimal(
            value,
            field="close",
        )


def test_normalize_decimal_rejects_boolean() -> None:
    with pytest.raises(
        TypeError,
        match="market_normalize_close_must_be_numeric",
    ):
        normalize_decimal(
            True,
            field="close",
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        object(),
        [],
        {},
    ],
)
def test_normalize_decimal_rejects_non_numeric_types(
    value,
) -> None:
    with pytest.raises(
        TypeError,
        match="market_normalize_close_must_be_numeric",
    ):
        normalize_decimal(
            value,
            field="close",
        )


def test_normalize_session_date_accepts_date() -> None:
    value = date(2026, 9, 15)

    assert normalize_session_date(value) == value


def test_normalize_session_date_accepts_iso_text() -> None:
    assert normalize_session_date("2026-09-15") == date(2026, 9, 15)


def test_normalize_session_date_rejects_datetime() -> None:
    with pytest.raises(
        TypeError,
        match="market_normalize_session_date_must_be_date",
    ):
        normalize_session_date(
            datetime(
                2026,
                9,
                15,
                15,
                0,
                tzinfo=_SHANGHAI,
            )
        )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
    ],
)
def test_normalize_session_date_rejects_missing_text(
    value: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="market_normalize_session_date_missing",
    ):
        normalize_session_date(value)


@pytest.mark.parametrize(
    "value",
    [
        "2026/09/15",
        "20260915",
        "15-09-2026",
        "not-a-date",
    ],
)
def test_normalize_session_date_rejects_non_iso_text(
    value: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="market_normalize_session_date_invalid",
    ):
        normalize_session_date(value)


def test_normalize_daily_bar_builds_canonical_observation() -> None:
    bar = _bar(
        open_value=10.31,
        high_value="10.52",
        low_value=Decimal("9.90"),
        close_value=10,
        volume=123456,
        amount="1283912.42",
    )

    assert bar.instrument == _instrument()
    assert bar.session_date == date(2026, 9, 15)

    assert bar.open == Decimal("10.31")
    assert bar.high == Decimal("10.52")
    assert bar.low == Decimal("9.90")
    assert bar.close == Decimal("10")

    assert bar.volume == Decimal("123456")
    assert bar.amount == Decimal("1283912.42")


def test_normalize_daily_bar_preserves_explicit_availability_time() -> None:
    available_at = datetime(
        2026,
        9,
        15,
        15,
        17,
        42,
        tzinfo=_SHANGHAI,
    )

    captured_at = datetime(
        2026,
        9,
        15,
        15,
        20,
        tzinfo=_SHANGHAI,
    )

    bar = _bar(
        available_at=available_at,
        captured_at=captured_at,
    )

    assert bar.available_at == available_at.astimezone(timezone.utc)
    assert bar.captured_at == captured_at.astimezone(timezone.utc)


def test_normalize_daily_bar_does_not_guess_invalid_time_order() -> None:
    available_at = datetime(
        2026,
        9,
        15,
        15,
        20,
        tzinfo=_SHANGHAI,
    )

    captured_at = datetime(
        2026,
        9,
        15,
        15,
        10,
        tzinfo=_SHANGHAI,
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_captured_before_available",
    ):
        _bar(
            available_at=available_at,
            captured_at=captured_at,
        )


def test_normalize_daily_bar_rejects_non_instrument_key() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_normalize_instrument_must_be_instrument_key",
    ):
        normalize_daily_bar(
            instrument="600000",
            session_date=date(2026, 9, 15),
            event_time=datetime(
                2026,
                9,
                15,
                15,
                0,
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
            captured_at=datetime(
                2026,
                9,
                15,
                15,
                3,
                tzinfo=_SHANGHAI,
            ),
            open_value="10.31",
            high_value="10.52",
            low_value="10.20",
            close_value="10.48",
            volume="123456",
            amount="1283912.42",
            suspended=False,
        )


def test_normalize_daily_bar_rejects_non_boolean_suspended() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_normalize_suspended_must_be_bool",
    ):
        normalize_daily_bar(
            instrument=_instrument(),
            session_date=date(2026, 9, 15),
            event_time=datetime(
                2026,
                9,
                15,
                15,
                0,
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
            captured_at=datetime(
                2026,
                9,
                15,
                15,
                3,
                tzinfo=_SHANGHAI,
            ),
            open_value="10.31",
            high_value="10.52",
            low_value="10.20",
            close_value="10.48",
            volume="123456",
            amount="1283912.42",
            suspended=1,
        )


def test_canonicalize_daily_bars_sorts_deterministically() -> None:
    bars = [
        _bar(
            symbol="600000",
            session_date=date(2026, 9, 15),
        ),
        _bar(
            symbol="000001",
            session_date=date(2026, 9, 14),
            event_time=datetime(
                2026,
                9,
                14,
                15,
                0,
                tzinfo=_SHANGHAI,
            ),
            available_at=datetime(
                2026,
                9,
                14,
                15,
                1,
                tzinfo=_SHANGHAI,
            ),
            captured_at=datetime(
                2026,
                9,
                14,
                15,
                3,
                tzinfo=_SHANGHAI,
            ),
        ),
        _bar(
            symbol="000001",
            session_date=date(2026, 9, 15),
        ),
    ]

    result = canonicalize_daily_bars(bars)

    assert [
        (
            bar.session_date.isoformat(),
            bar.instrument.instrument_type.value,
            bar.instrument.symbol,
        )
        for bar in result
    ] == [
        (
            "2026-09-14",
            "stock",
            "000001",
        ),
        (
            "2026-09-15",
            "stock",
            "000001",
        ),
        (
            "2026-09-15",
            "stock",
            "600000",
        ),
    ]


def test_canonicalize_daily_bars_is_independent_of_input_order() -> None:
    first = _bar(
        symbol="000001",
    )
    second = _bar(
        symbol="600000",
    )

    forward = canonicalize_daily_bars(
        [
            first,
            second,
        ]
    )

    reverse = canonicalize_daily_bars(
        [
            second,
            first,
        ]
    )

    assert forward == reverse


def test_canonicalize_daily_bars_rejects_duplicate_instrument_session() -> None:
    first = _bar(
        symbol="600000",
        close_value="10.48",
    )

    conflicting = _bar(
        symbol="600000",
        close_value="10.49",
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_duplicate_instrument_session",
    ):
        canonicalize_daily_bars(
            [
                first,
                conflicting,
            ]
        )


def test_same_symbol_with_different_instrument_type_is_not_duplicate() -> None:
    stock = _bar(
        symbol="510300",
        instrument_type=InstrumentType.STOCK,
    )

    etf = _bar(
        symbol="510300",
        instrument_type=InstrumentType.ETF,
    )

    result = canonicalize_daily_bars(
        [
            stock,
            etf,
        ]
    )

    assert len(result) == 2

    assert {bar.instrument.instrument_type for bar in result} == {
        InstrumentType.STOCK,
        InstrumentType.ETF,
    }


def test_canonicalize_daily_bars_accepts_empty_input() -> None:
    assert canonicalize_daily_bars([]) == ()


def test_canonicalize_daily_bars_rejects_invalid_batch_value() -> None:
    with pytest.raises(
        TypeError,
        match="daily_bar_batch_contains_invalid_value",
    ):
        canonicalize_daily_bars(
            [
                _bar(),
                "not-a-daily-bar",
            ]
        )
