"""Tests for data/universe.py curated multi-asset and ETF universes."""

from __future__ import annotations

from data.universe import (
    CORE_ETF_UNIVERSE,
    DIVIDEND_DEFENSIVE_UNIVERSE,
    SECTOR_ETF_UNIVERSE,
    UniverseDefinition,
    get_universe,
    list_universes,
)


def test_core_etf_universe_members() -> None:
    univ = CORE_ETF_UNIVERSE
    assert univ.universe_id == "core_etf_universe"
    assert len(univ.members) >= 5
    assert univ.benchmark_symbol == "510300"
    assert univ.cash_proxy_symbol == "511010"

    symbols = univ.symbols
    assert "510300" in symbols
    assert "510500" in symbols
    assert "518880" in symbols
    assert "511010" in symbols

    tradable = univ.tradable_symbols
    assert "511010" not in tradable  # cash proxy excluded from active tradables
    assert "510300" in tradable


def test_sector_etf_universe_members() -> None:
    univ = SECTOR_ETF_UNIVERSE
    assert univ.universe_id == "sector_etf_universe"
    assert len(univ.members) >= 6
    assert "512880" in univ.symbols  # 券商
    assert "512760" in univ.symbols  # 芯片


def test_dividend_defensive_universe() -> None:
    univ = DIVIDEND_DEFENSIVE_UNIVERSE
    assert univ.universe_id == "dividend_defensive_universe"
    assert "512890" in univ.symbols
    assert "511010" in univ.symbols


def test_get_and_list_universes() -> None:
    all_univs = list_universes()
    assert len(all_univs) >= 3
    assert all(isinstance(u, UniverseDefinition) for u in all_univs)

    retrieved = get_universe("core_etf_universe")
    assert retrieved is not None
    assert retrieved.universe_id == "core_etf_universe"

    assert get_universe("non_existent_universe") is None
