"""Curated multi-asset and ETF universes for research and cross-sectional rotation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.types import AssetClass, InstrumentType, Symbol


@dataclass(frozen=True)
class UniverseMember:
    """One instrument member within a quantitative universe."""

    symbol: Symbol
    name: str
    # Investment exposure; instrument_type owns trading identity.
    asset_class: AssetClass
    instrument_type: InstrumentType
    benchmark: bool = False
    cash_proxy: bool = False
    description: str = ""


@dataclass(frozen=True)
class UniverseDefinition:
    """A canonical curated universe of tradeable instruments."""

    universe_id: str
    display_name: str
    description: str
    members: tuple[UniverseMember, ...]
    benchmark_symbol: Symbol | None = None
    cash_proxy_symbol: Symbol | None = None

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        return tuple(member.symbol for member in self.members)

    @property
    def tradable_symbols(self) -> tuple[Symbol, ...]:
        """Symbols eligible for active allocation (excluding pure cash proxies)."""
        return tuple(member.symbol for member in self.members if not member.cash_proxy)


CORE_ETF_UNIVERSE = UniverseDefinition(
    universe_id="core_etf_universe",
    display_name="China Core Macro & Broad Index ETFs",
    description="Broad equity indexes, style factors, gold, and treasury bond ETFs for macro rotation.",
    members=(
        UniverseMember(
            symbol=Symbol("510300"),
            name="沪深300ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            benchmark=True,
            description="Large-cap core equity benchmark.",
        ),
        UniverseMember(
            symbol=Symbol("510500"),
            name="中证500ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Mid-cap growth equity.",
        ),
        UniverseMember(
            symbol=Symbol("512100"),
            name="中证1000ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Small-cap growth equity.",
        ),
        UniverseMember(
            symbol=Symbol("159915"),
            name="创业板ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="ChiNext tech & innovation benchmark.",
        ),
        UniverseMember(
            symbol=Symbol("588000"),
            name="科创50ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="STAR Market hard tech benchmark.",
        ),
        UniverseMember(
            symbol=Symbol("512890"),
            name="红利低波ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="High dividend yield & low volatility factor.",
        ),
        UniverseMember(
            symbol=Symbol("518880"),
            name="黄金ETF",
            asset_class=AssetClass.GOLD,
            instrument_type=InstrumentType.ETF,
            description="Physical gold hedge against inflation and equity drawdown.",
        ),
        UniverseMember(
            symbol=Symbol("511010"),
            name="国债ETF",
            asset_class=AssetClass.BOND,
            instrument_type=InstrumentType.ETF,
            cash_proxy=True,
            description="5-year Chinese treasury bond ETF, serving as defense and cash proxy.",
        ),
    ),
    benchmark_symbol=Symbol("510300"),
    cash_proxy_symbol=Symbol("511010"),
)

SECTOR_ETF_UNIVERSE = UniverseDefinition(
    universe_id="sector_etf_universe",
    display_name="China Key Sector ETFs",
    description="High-beta liquid sector ETFs for cross-sectional industry rotation.",
    members=(
        UniverseMember(
            symbol=Symbol("512880"),
            name="证券ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Securities & brokerage, high beta liquidity proxy.",
        ),
        UniverseMember(
            symbol=Symbol("512760"),
            name="芯片ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Semiconductors & microelectronics.",
        ),
        UniverseMember(
            symbol=Symbol("512660"),
            name="军工ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Defense & aerospace industry.",
        ),
        UniverseMember(
            symbol=Symbol("512010"),
            name="医药ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Healthcare and pharmaceuticals.",
        ),
        UniverseMember(
            symbol=Symbol("512690"),
            name="酒ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Liquor & consumer goods.",
        ),
        UniverseMember(
            symbol=Symbol("516160"),
            name="新能源ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="New energy & green tech.",
        ),
        UniverseMember(
            symbol=Symbol("512800"),
            name="银行ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Commercial banks, low valuation high dividend.",
        ),
        UniverseMember(
            symbol=Symbol("511010"),
            name="国债ETF",
            asset_class=AssetClass.BOND,
            instrument_type=InstrumentType.ETF,
            cash_proxy=True,
            description="Treasury bond defense proxy.",
        ),
    ),
    benchmark_symbol=Symbol("510300"),
    cash_proxy_symbol=Symbol("511010"),
)

DIVIDEND_DEFENSIVE_UNIVERSE = UniverseDefinition(
    universe_id="dividend_defensive_universe",
    display_name="High Dividend & Defensive Allocation ETFs",
    description="Low-drawdown income and defensive ETFs.",
    members=(
        UniverseMember(
            symbol=Symbol("512890"),
            name="红利低波ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="Dividend low volatility.",
        ),
        UniverseMember(
            symbol=Symbol("512950"),
            name="央企红利ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="SOE high dividend yield.",
        ),
        UniverseMember(
            symbol=Symbol("510880"),
            name="红利ETF",
            asset_class=AssetClass.FUND,
            instrument_type=InstrumentType.ETF,
            description="SSE dividend index.",
        ),
        UniverseMember(
            symbol=Symbol("511010"),
            name="国债ETF",
            asset_class=AssetClass.BOND,
            instrument_type=InstrumentType.ETF,
            cash_proxy=True,
            description="5-year Treasury bond ETF.",
        ),
    ),
    benchmark_symbol=Symbol("510880"),
    cash_proxy_symbol=Symbol("511010"),
)

_CURATED_UNIVERSES: Mapping[str, UniverseDefinition] = {
    CORE_ETF_UNIVERSE.universe_id: CORE_ETF_UNIVERSE,
    SECTOR_ETF_UNIVERSE.universe_id: SECTOR_ETF_UNIVERSE,
    DIVIDEND_DEFENSIVE_UNIVERSE.universe_id: DIVIDEND_DEFENSIVE_UNIVERSE,
}


def get_universe(universe_id: str) -> UniverseDefinition | None:
    """Retrieve a curated universe definition by its ID."""
    return _CURATED_UNIVERSES.get(universe_id)


def list_universes() -> list[UniverseDefinition]:
    """List all available curated universe definitions."""
    return list(_CURATED_UNIVERSES.values())
