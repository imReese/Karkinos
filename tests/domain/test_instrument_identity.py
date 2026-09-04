"""Authoritative instrument identity remains distinct and fail closed."""

from __future__ import annotations

import pytest

from core.types import InstrumentType, Symbol
from data.manager import DataManager


@pytest.mark.parametrize(
    ("instrument_type", "symbol"),
    [
        (InstrumentType.STOCK, "600519"),
        (InstrumentType.ETF, "510300"),
        (InstrumentType.OPEN_END_FUND, "000001"),
    ],
)
def test_explicit_instrument_type_round_trips_without_symbol_guessing(
    instrument_type: InstrumentType,
    symbol: str,
) -> None:
    instrument = DataManager.get_instrument_by_type(
        Symbol(symbol),
        instrument_type,
    )

    assert instrument.instrument_type is instrument_type


def test_unknown_instrument_type_fails_closed() -> None:
    with pytest.raises(ValueError, match="instrument type is unresolved"):
        DataManager.get_instrument_by_type(
            Symbol("mystery"),
            InstrumentType.UNKNOWN,
        )


@pytest.mark.parametrize(
    ("persisted", "expected"),
    [
        ("stock", InstrumentType.STOCK),
        ("etf", InstrumentType.ETF),
        ("fund", InstrumentType.OPEN_END_FUND),
        ("open-end-fund", InstrumentType.OPEN_END_FUND),
    ],
)
def test_persisted_instrument_type_is_parsed_without_symbol_heuristics(
    persisted: str,
    expected: InstrumentType,
) -> None:
    assert InstrumentType.from_persisted(persisted) is expected


@pytest.mark.parametrize("persisted", [None, "", "other", "unknown"])
def test_unresolved_persisted_instrument_type_fails_closed(persisted: object) -> None:
    with pytest.raises(ValueError, match="instrument type is unresolved"):
        InstrumentType.from_persisted(persisted)
