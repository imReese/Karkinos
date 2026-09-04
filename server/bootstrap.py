"""Shared bootstrap helpers for runtime entrypoints."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from core.types import AssetClass, InstrumentType, Symbol
from data.manager import DataManager, build_sources
from data.store import DataStore
from server.config import BacktestConfig
from server.config_contract import (
    MIN_LIVE_POLL_INTERVAL_SECONDS,
    SUPPORTED_DATA_SOURCES,
)
from server.runtime_paths import resolve_data_dir, resolve_runtime_home

_INSTRUMENT_ASSET_CLASS_MAP = {
    InstrumentType.STOCK: AssetClass.STOCK,
    InstrumentType.ETF: AssetClass.FUND,
    InstrumentType.OPEN_END_FUND: AssetClass.FUND,
    InstrumentType.GOLD: AssetClass.GOLD,
    InstrumentType.BOND: AssetClass.BOND,
    InstrumentType.INDEX: AssetClass.INDEX,
}

_NON_STRATEGY_FIELDS = {
    "initial_cash",
    "start_date",
    "end_date",
    "assets",
    "instruments",
    "data_source",
    "data_source_provider_config",
    "notification",
    "live_poll_interval",
    "strategy",
    "host",
    "port",
    "cors_allowed_origins",
    "ai",
}

_IGNORED_LEGACY_RUNTIME_FIELDS = frozenset({"live_auto_start"})

_RUNTIME_ENV_FIELDS = {
    "KARKINOS_HOST": "host",
    "KARKINOS_PORT": "port",
    "KARKINOS_CORS_ALLOWED_ORIGINS": "cors_allowed_origins",
    "KARKINOS_DATA_SOURCE": "data_source",
    "KARKINOS_LIVE_POLL_INTERVAL": "live_poll_interval",
    "KARKINOS_AI_ENABLED": "ai.enabled",
    "KARKINOS_AI_PROVIDER": "ai.provider",
    "KARKINOS_AI_MODEL": "ai.model",
    "KARKINOS_AI_BASE_URL": "ai.base_url",
    "KARKINOS_AI_ADAPTER_KIND": "ai.adapter_kind",
    "KARKINOS_AI_TIMEOUT_SECONDS": "ai.timeout_seconds",
}
_EMPTY_ENV_MEANS_UNSET = {
    "KARKINOS_TUSHARE_TOKEN",
    "KARKINOS_AI_API_KEY",
    "KARKINOS_AI_PROVIDER",
    "KARKINOS_AI_MODEL",
    "KARKINOS_AI_BASE_URL",
    "KARKINOS_TELEGRAM_BOT_TOKEN",
    "KARKINOS_TELEGRAM_CHAT_ID",
    "KARKINOS_WECHAT_SENDKEY",
}


@dataclass
class RuntimeContext:
    config: BacktestConfig
    sources: dict[str, Any]
    store: DataStore | None
    data_manager: DataManager
    watchlist: list[tuple[Symbol, AssetClass]]
    instruments: dict[Symbol, Any]
    instrument_types: dict[Symbol, InstrumentType]
    instrument_identity_provenance: dict[Symbol, str]


@dataclass(frozen=True)
class _ConfiguredInstrumentIdentity:
    symbol: Symbol
    instrument_type: InstrumentType
    provenance: str


def resolve_config_path() -> Path:
    """Return the runtime config path without coupling native releases to cwd."""
    configured = os.environ.get("KARKINOS_CONFIG_PATH")
    if configured:
        return Path(configured)
    home = resolve_runtime_home()
    return home / "config" / "config.json" if home is not None else Path("config.json")


def load_runtime_environment_file(
    path: str | Path = ".env",
    *,
    environ: MutableMapping[str, str] | None = None,
    required: bool = False,
) -> bool:
    """Load one dotenv file without overriding the existing process environment."""
    from dotenv import dotenv_values  # pyright: ignore[reportMissingImports]

    dotenv_path = Path(path)
    if not dotenv_path.exists():
        if required:
            raise ValueError(f"environment file does not exist: {dotenv_path}")
        return False
    try:
        values = dotenv_values(dotenv_path)
    except OSError as exc:
        raise ValueError(
            f"environment file could not be loaded: {dotenv_path}"
        ) from exc
    target = os.environ if environ is None else environ
    for name, value in values.items():
        if value is None:
            raise ValueError(f"environment file variable has no value: {name}")
        current_value = target.get(name)
        if name not in target or (
            name in _EMPTY_ENV_MEANS_UNSET
            and isinstance(current_value, str)
            and not current_value.strip()
        ):
            target[name] = value
    return True


def load_selected_runtime_environment_file(
    explicit_path: str | Path | None = None,
) -> bool:
    """Load the CLI-selected, process-selected, or default runtime dotenv file."""
    configured_path = os.environ.get("KARKINOS_ENV_FILE")
    env_file = explicit_path or configured_path or ".env"
    return load_runtime_environment_file(
        env_file,
        required=explicit_path is not None or configured_path is not None,
    )


def load_runtime_config(
    config_cls: type[BacktestConfig] = BacktestConfig, **overrides: Any
) -> BacktestConfig:
    """Resolve defaults, config.json, environment, then explicit overrides."""
    overrides = {
        key: value
        for key, value in overrides.items()
        if key not in _IGNORED_LEGACY_RUNTIME_FIELDS
    }
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
        root_field, _, nested_field = field_name.partition(".")
        if not hasattr(config, root_field):
            continue
        if nested_field and not hasattr(getattr(config, root_field), nested_field):
            continue
        raw_value = os.environ.get(env_name)
        if raw_value is None:
            continue
        if env_name in _EMPTY_ENV_MEANS_UNSET and not raw_value.strip():
            continue
        resolved[field_name] = _parse_runtime_environment_value(env_name, raw_value)
    provider_config = getattr(config, "data_source_provider_config", None)
    token_env_name = str(
        getattr(
            provider_config,
            "tushare_token_env",
            "KARKINOS_TUSHARE_TOKEN",
        )
        or "KARKINOS_TUSHARE_TOKEN"
    )
    token_value = os.environ.get(token_env_name)
    if token_value is not None and token_value.strip():
        resolved["tushare_token"] = token_value
    return resolved


def _parse_runtime_environment_value(env_name: str, raw_value: str) -> Any:
    value = raw_value.strip()
    if env_name == "KARKINOS_AI_ENABLED":
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
        lower_bound = (
            MIN_LIVE_POLL_INTERVAL_SECONDS
            if env_name == "KARKINOS_LIVE_POLL_INTERVAL"
            else 1
        )
        if parsed < lower_bound or (upper_bound is not None and parsed > upper_bound):
            raise ValueError(f"{env_name} is outside the supported range")
        return parsed
    if env_name == "KARKINOS_AI_TIMEOUT_SECONDS":
        try:
            parsed_timeout = float(value)
        except ValueError as exc:
            raise ValueError(f"{env_name} must be numeric") from exc
        if parsed_timeout <= 0 or parsed_timeout > 60:
            raise ValueError(f"{env_name} is outside the supported range")
        return parsed_timeout
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
        if provider not in SUPPORTED_DATA_SOURCES:
            raise ValueError(f"{env_name} must be akshare or tushare")
        return provider
    if not value:
        raise ValueError(f"{env_name} must not be empty")
    return value


def _apply_runtime_overrides(
    config: BacktestConfig,
    overrides: dict[str, Any],
) -> None:
    nested_overrides: dict[str, dict[str, Any]] = {}
    for key, value in overrides.items():
        root_field, separator, nested_field = key.partition(".")
        if separator:
            if not hasattr(config, root_field) or not hasattr(
                getattr(config, root_field), nested_field
            ):
                raise ValueError(f"unsupported runtime config override: {key}")
            nested_overrides.setdefault(root_field, {})[nested_field] = value
            continue
        if not hasattr(config, key):
            raise ValueError(f"unsupported runtime config override: {key}")
        setattr(config, key, value)
    for root_field, values in nested_overrides.items():
        setattr(config, root_field, replace(getattr(config, root_field), **values))


def _configured_instrument_identities(
    config: BacktestConfig,
) -> list[_ConfiguredInstrumentIdentity]:
    """Resolve explicit config identity without inspecting symbol syntax."""

    identities: list[_ConfiguredInstrumentIdentity] = []
    seen: dict[Symbol, _ConfiguredInstrumentIdentity] = {}
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
        sym = Symbol(str(asset_cfg["symbol"]).strip())
        if not str(sym):
            raise ValueError("configured instrument symbol is required")
        raw_instrument_type = asset_cfg.get("instrument_type") or asset_cfg.get(
            "asset_class", "stock"
        )
        instrument_type = InstrumentType.from_persisted(raw_instrument_type)
        provenance = (
            "legacy_config_fund_compatibility"
            if str(raw_instrument_type).strip().lower() == "fund"
            else "config_canonical"
        )
        previous = seen.get(sym)
        if previous is not None and previous.instrument_type is not instrument_type:
            raise ValueError(
                "configured instrument identity conflicts for "
                f"{sym}: {previous.instrument_type.value},{instrument_type.value}"
            )
        if previous is None:
            identity = _ConfiguredInstrumentIdentity(
                symbol=sym,
                instrument_type=instrument_type,
                provenance=provenance,
            )
            identities.append(identity)
            seen[sym] = identity
        elif (
            previous.provenance == "legacy_config_fund_compatibility"
            and provenance == "config_canonical"
        ):
            replacement = _ConfiguredInstrumentIdentity(
                symbol=sym,
                instrument_type=instrument_type,
                provenance=provenance,
            )
            identities[identities.index(previous)] = replacement
            seen[sym] = replacement
    return identities


def build_watchlist(
    config: BacktestConfig,
) -> list[tuple[Symbol, AssetClass]]:
    """Build the broad provider watchlist from explicit instrument identities."""

    watchlist: list[tuple[Symbol, AssetClass]] = []
    for identity in _configured_instrument_identities(config):
        asset_class = _INSTRUMENT_ASSET_CLASS_MAP.get(identity.instrument_type)
        if asset_class is None:
            raise ValueError(
                "configured instrument type is unsupported: "
                f"{identity.instrument_type.value}"
            )
        watchlist.append((identity.symbol, asset_class))
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
        tushare_token=config.tushare_token,
    )
    store = DataStore(resolve_data_dir())
    data_manager = DataManager(
        sources=sources,
        store=store,
        default_source=config.data_source,
    )
    configured_identities = _configured_instrument_identities(config)
    configured_instrument_types = {
        identity.symbol: identity.instrument_type for identity in configured_identities
    }
    watchlist = [
        (
            identity.symbol,
            _INSTRUMENT_ASSET_CLASS_MAP[identity.instrument_type],
        )
        for identity in configured_identities
    ]
    instruments = {
        symbol: DataManager.get_instrument_by_type(symbol, instrument_type)
        for symbol, instrument_type in configured_instrument_types.items()
    }
    return RuntimeContext(
        config=config,
        sources=sources,
        store=store,
        data_manager=data_manager,
        watchlist=watchlist,
        instruments=instruments,
        instrument_types=configured_instrument_types,
        instrument_identity_provenance={
            identity.symbol: identity.provenance for identity in configured_identities
        },
    )
