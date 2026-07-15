"""Shared bootstrap helpers for runtime entrypoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.types import AssetClass, Symbol
from data.manager import DataManager, build_sources
from data.store import DataStore
from server.config import BacktestConfig

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}

_NON_STRATEGY_FIELDS = {
    "initial_cash",
    "start_date",
    "end_date",
    "assets",
    "instruments",
    "data_source",
    "notification",
    "live_poll_interval",
    "strategy",
    "host",
    "port",
    "live_auto_start",
    "cors_allowed_origins",
}

_RUNTIME_ENV_FIELDS = {
    "KARKINOS_HOST": "host",
    "KARKINOS_PORT": "port",
    "KARKINOS_LIVE_AUTO_START": "live_auto_start",
    "KARKINOS_CORS_ALLOWED_ORIGINS": "cors_allowed_origins",
    "KARKINOS_DATA_SOURCE": "data_source",
    "KARKINOS_LIVE_POLL_INTERVAL": "live_poll_interval",
    "TUSHARE_TOKEN": "tushare_token",
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
    return Path(os.environ.get("KARKINOS_CONFIG_PATH") or "config.json")


def resolve_data_dir() -> str:
    """Return the runtime data directory, defaulting to data/store."""
    return os.environ.get("KARKINOS_DATA_DIR") or "data/store"


def load_runtime_config(
    config_cls: type[BacktestConfig] = BacktestConfig, **overrides: Any
) -> BacktestConfig:
    """Resolve defaults, config.json, environment, then explicit overrides."""
    config_path = resolve_config_path()
    if config_path.exists():
        config = config_cls.from_json(config_path)
    else:
        config = config_cls()
    _apply_runtime_overrides(config, _runtime_environment_overrides(config))
    _apply_runtime_overrides(config, overrides)
    return config


def _runtime_environment_overrides(config: BacktestConfig) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for env_name, field_name in _RUNTIME_ENV_FIELDS.items():
        if not hasattr(config, field_name):
            continue
        raw_value = os.environ.get(env_name)
        if raw_value is None:
            continue
        if env_name == "TUSHARE_TOKEN" and not raw_value.strip():
            continue
        resolved[field_name] = _parse_runtime_environment_value(env_name, raw_value)
    return resolved


def _parse_runtime_environment_value(env_name: str, raw_value: str) -> Any:
    value = raw_value.strip()
    if env_name == "KARKINOS_LIVE_AUTO_START":
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"{env_name} must be a boolean")
    if env_name in {"KARKINOS_PORT", "KARKINOS_LIVE_POLL_INTERVAL"}:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{env_name} must be an integer") from exc
        upper_bound = 65_535 if env_name == "KARKINOS_PORT" else None
        if parsed <= 0 or (upper_bound is not None and parsed > upper_bound):
            raise ValueError(f"{env_name} is outside the supported range")
        return parsed
    if env_name == "KARKINOS_CORS_ALLOWED_ORIGINS":
        origins = tuple(
            dict.fromkeys(
                origin.strip() for origin in raw_value.split(",") if origin.strip()
            )
        )
        if not origins:
            raise ValueError(f"{env_name} must contain at least one origin")
        return list(origins)
    if env_name == "KARKINOS_DATA_SOURCE":
        provider = value.lower()
        if provider not in {"akshare", "tushare"}:
            raise ValueError(f"{env_name} must be akshare or tushare")
        return provider
    if not value:
        raise ValueError(f"{env_name} must not be empty")
    return value


def _apply_runtime_overrides(
    config: BacktestConfig,
    overrides: dict[str, Any],
) -> None:
    for key, value in overrides.items():
        if not hasattr(config, key):
            raise ValueError(f"unsupported runtime config override: {key}")
        setattr(config, key, value)


def build_watchlist(
    config: BacktestConfig,
) -> list[tuple[Symbol, AssetClass]]:
    """Convert config assets into normalized symbol/asset-class tuples."""
    watchlist: list[tuple[Symbol, AssetClass]] = []
    assets = (
        config.assets.items()
        if isinstance(config.assets, dict)
        else enumerate(config.assets)
    )
    for key, asset_cfg in assets:
        if isinstance(asset_cfg, str):
            asset_cfg = {
                "symbol": str(key) if not isinstance(key, int) else asset_cfg,
                "asset_class": "stock",
            }
        elif (
            isinstance(asset_cfg, dict)
            and not asset_cfg.get("symbol")
            and not isinstance(key, int)
        ):
            asset_cfg = {**asset_cfg, "symbol": str(key)}
        sym = Symbol(asset_cfg["symbol"])
        asset_class = _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
        watchlist.append((sym, asset_class))
    return watchlist


def build_strategy(config: BacktestConfig, event_bus: Any) -> Any:
    """Create a registered strategy with config-backed parameters."""
    import strategy.builtins  # noqa: F401
    from strategy.registry import StrategyRegistry

    strategy_info = StrategyRegistry.get(config.strategy) or {}
    param_names = {p["name"] for p in strategy_info.get("params", [])}
    raw_params = getattr(config, "params", None)
    if raw_params is None:
        raw_params = getattr(config, "strategy_params", None)
    if raw_params is None:
        raw_params = {
            key: value
            for key, value in config.__dict__.items()
            if key not in _NON_STRATEGY_FIELDS and key in param_names
        }
    strategy_kwargs = StrategyRegistry.validate_params(config.strategy, raw_params)
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
