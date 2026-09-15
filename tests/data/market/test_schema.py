"""Market Data Arrow Schema 测试。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pyarrow as pa
import pytest

from core.types import InstrumentKey, InstrumentType
from data.market.model import DailyBarObservation
from data.market.schema import (
    DAILY_BAR_SCHEMA,
    DAILY_BAR_SCHEMA_VERSION,
    daily_bars_from_table,
    daily_bars_to_table,
    validate_daily_bar_table,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bar(
    *,
    symbol: str = "600000",
    close: Decimal = Decimal("10.48"),
) -> DailyBarObservation:
    return DailyBarObservation(
        instrument=InstrumentKey(
            symbol=symbol,
            instrument_type=InstrumentType.STOCK,
        ),
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
        open=Decimal("10.31"),
        high=Decimal("10.52"),
        low=Decimal("10.20"),
        close=close,
        volume=Decimal("123456"),
        amount=Decimal("1283912.42"),
        suspended=False,
    )


def test_daily_bar_schema_has_explicit_version() -> None:
    assert DAILY_BAR_SCHEMA.metadata is not None
    assert (
        DAILY_BAR_SCHEMA.metadata[b"karkinos.schema_version"].decode()
        == DAILY_BAR_SCHEMA_VERSION
    )


def test_daily_bars_to_table_uses_exact_schema() -> None:
    table = daily_bars_to_table([_bar()])

    assert table.schema.equals(
        DAILY_BAR_SCHEMA,
        check_metadata=True,
    )
    assert table.num_rows == 1
    assert table.num_columns == len(DAILY_BAR_SCHEMA)


def test_daily_bar_round_trip_is_lossless() -> None:
    original = _bar()

    table = daily_bars_to_table([original])
    restored = daily_bars_from_table(table)

    assert restored == (original,)


def test_multiple_daily_bars_preserve_input_order() -> None:
    first = _bar(
        symbol="600000",
        close=Decimal("10.48"),
    )
    second = _bar(
        symbol="000001",
        close=Decimal("10.34"),
    )

    table = daily_bars_to_table(
        [
            first,
            second,
        ]
    )

    assert table["symbol"].to_pylist() == [
        "600000",
        "000001",
    ]

    assert daily_bars_from_table(table) == (
        first,
        second,
    )


def test_daily_bar_decimals_are_stored_with_canonical_scale() -> None:
    table = daily_bars_to_table([_bar()])

    assert str(table["open"][0].as_py()) == "10.31000000"
    assert str(table["close"][0].as_py()) == "10.48000000"
    assert str(table["volume"][0].as_py()) == "123456.00000000"
    assert str(table["amount"][0].as_py()) == "1283912.42000000"


def test_daily_bar_rejects_value_exceeding_storage_scale() -> None:
    bar = _bar(
        close=Decimal("10.203456789"),
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_close_exceeds_storage_scale",
    ):
        daily_bars_to_table([bar])


def test_daily_bar_timestamps_are_stored_as_utc() -> None:
    table = daily_bars_to_table([_bar()])

    event_time = table["event_time"][0].as_py()
    available_at = table["available_at"][0].as_py()
    captured_at = table["captured_at"][0].as_py()

    assert event_time.isoformat() == "2026-09-15T07:00:00+00:00"
    assert available_at.isoformat() == "2026-09-15T07:01:00+00:00"
    assert captured_at.isoformat() == "2026-09-15T07:03:00+00:00"


def test_empty_daily_bar_table_is_valid() -> None:
    table = daily_bars_to_table([])

    assert table.num_rows == 0
    assert table.schema.equals(
        DAILY_BAR_SCHEMA,
        check_metadata=True,
    )
    assert daily_bars_from_table(table) == ()


def test_validate_rejects_wrong_schema() -> None:
    table = daily_bars_to_table([_bar()])

    wrong = table.drop(["amount"])

    with pytest.raises(
        ValueError,
        match="daily_bar_table_schema_mismatch",
    ):
        validate_daily_bar_table(wrong)


def test_validate_rejects_schema_without_metadata() -> None:
    table = daily_bars_to_table([_bar()])

    schema_without_metadata = table.schema.remove_metadata()

    wrong = pa.Table.from_arrays(
        table.columns,
        schema=schema_without_metadata,
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_table_schema_mismatch",
    ):
        validate_daily_bar_table(wrong)


def test_validate_rejects_null_values() -> None:
    table = daily_bars_to_table([_bar()])

    arrays = []

    for field in DAILY_BAR_SCHEMA:
        if field.name == "close":
            arrays.append(
                pa.array(
                    [None],
                    type=field.type,
                )
            )
        else:
            arrays.append(table[field.name])

    table_with_null = pa.Table.from_arrays(
        arrays,
        schema=DAILY_BAR_SCHEMA,
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_table_null_value:close",
    ):
        validate_daily_bar_table(table_with_null)


def test_daily_bars_from_table_rejects_wrong_schema() -> None:
    table = pa.table(
        {
            "symbol": ["600000"],
            "close": [10.48],
        }
    )

    with pytest.raises(
        ValueError,
        match="daily_bar_table_schema_mismatch",
    ):
        daily_bars_from_table(table)
