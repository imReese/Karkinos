"""Shared bootstrap helpers for runtime entrypoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import BacktestConfig
from core.types import AssetClass, Symbol
from data.manager import DataManager, build_sources
from data.store import DataStore

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}

_NON_STRATEGY_FIELDS = {
    "initial_cash",
    "start_date",
    "end_date",
    "assets",
    "data_source",
    "notification",
    "live_poll_interval",
    "strategy",
    "host",
    "port",
    "live_auto_start",
}


@dataclass
class RuntimeContext:
    config: BacktestConfig
    sources: dict[str, Any]
    store: DataStore | None
    data_manager: DataManager
    watchlist: list[tuple[Symbol, AssetClass]]
    instruments: dict[Symbol, Any]


def resolve_config_path() -> Path:
    """Return the runtime config path, defaulting to ./config.json."""
    return Path(os.environ.get("MYQUANT_CONFIG_PATH") or "config.json")


def resolve_data_dir() -> str:
    """Return the runtime data directory, defaulting to data/store."""
    return os.environ.get("MYQUANT_DATA_DIR") or "data/store"


def load_runtime_config(
    config_cls: type[BacktestConfig] = BacktestConfig, **overrides: Any
) -> BacktestConfig:
    """Load config.json when present, otherwise use dataclass defaults."""
    config_path = resolve_config_path()
    if config_path.exists():
        config = config_cls.from_json(config_path)
    else:
        config = config_cls()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def build_watchlist(
    config: BacktestConfig,
) -> list[tuple[Symbol, AssetClass]]:
    """Convert config assets into normalized symbol/asset-class tuples."""
    watchlist: list[tuple[Symbol, AssetClass]] = []
    for asset_cfg in config.assets:
        sym = Symbol(asset_cfg["symbol"])
        asset_class = _ASSET_CLASS_MAP.get(
            asset_cfg["asset_class"], AssetClass.STOCK
        )
        watchlist.append((sym, asset_class))
    return watchlist


def build_strategy(config: BacktestConfig, event_bus: Any) -> Any:
    """Create a registered strategy with config-backed parameters."""
    import strategy.examples  # noqa: F401
    from strategy.registry import StrategyRegistry

    strategy_info = StrategyRegistry.get(config.strategy) or {}
    param_names = {p["name"] for p in strategy_info.get("params", [])}
    strategy_kwargs = {
        key: value
        for key, value in config.__dict__.items()
        if key not in _NON_STRATEGY_FIELDS and key in param_names
    }
    return StrategyRegistry.create(config.strategy, event_bus, **strategy_kwargs)


def create_runtime_context(config: BacktestConfig) -> RuntimeContext:
    """Build shared runtime wiring for data-backed entrypoints."""
    sources = build_sources(
        data_source=config.data_source,
        tushare_token=os.environ.get("TUSHARE_TOKEN") or config.tushare_token,
    )
    store = DataStore(resolve_data_dir())
    data_manager = DataManager(
        sources=sources,
        store=store,
        default_source=config.data_source,
    )
    watchlist = build_watchlist(config)
    instruments = {
        symbol: DataManager.get_instrument(symbol, asset_class)
        for symbol, asset_class in watchlist
    }
    return RuntimeContext(
        config=config,
        sources=sources,
        store=store,
        data_manager=data_manager,
        watchlist=watchlist,
        instruments=instruments,
    )
