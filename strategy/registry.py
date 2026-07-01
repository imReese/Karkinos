"""策略注册表 — 自动发现与管理策略类。"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Type

from core.event_bus import EventBus
from strategy.base import Strategy
from strategy.schema import (
    STRATEGY_DISPLAY_NAMES,
    STRATEGY_PARAMETER_SCHEMAS,
    StrategyExtensionValidationError,
    StrategyParameterSchema,
    infer_parameter_schema,
    parameter_schema_from_dict,
    validate_strategy_params,
)

logger = logging.getLogger(__name__)

_STRATEGY_REGISTRY_CONTRACT_VERSION = "karkinos.strategy_registry.v1"
_STRATEGY_SCHEMA_VERSION = "karkinos.strategy.v1"
_RESEARCH_ONLY_EXECUTION_BOUNDARY = {
    "research_only": True,
    "can_submit_broker_orders": False,
    "requires_risk_gate": True,
    "requires_account_truth_gate": True,
    "requires_paper_shadow_review": True,
    "requires_manual_confirmation": True,
}
_DEFAULT_BENCHMARK_METADATA = {
    "asset_universe": [],
    "supported_frequencies": ["1d"],
    "benchmark_role": None,
    "benchmark_universe": [],
    "requires_out_of_sample_validation": False,
    "requires_after_cost_report": False,
    "validation_notes": [],
}

_BENCHMARK_METADATA = {
    "dual_ma": {
        "asset_universe": ["stock", "etf"],
        "benchmark_role": "etf_rotation_trend_following",
        "benchmark_universe": ["etf"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Requires after-cost, out-of-sample ETF trend-following validation before promotion.",
            "Intended as a transparent baseline, not a profitability claim.",
        ],
    },
    "monthly_rebalance": {
        "asset_universe": ["equity_etf", "bond", "gold", "cash_proxy"],
        "benchmark_role": "defensive_allocation",
        "benchmark_universe": ["equity_etf", "bond", "gold", "cash_proxy"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Requires after-cost, out-of-sample validation across equity ETF, bond, gold, and cash proxy allocations.",
            "Intended to measure defensive allocation discipline against benchmark drift.",
        ],
    },
    "bollinger": {
        "asset_universe": ["stock", "etf"],
        "benchmark_role": "a_share_or_etf_mean_reversion",
        "benchmark_universe": ["stock", "etf"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Requires after-cost, out-of-sample mean-reversion validation on A-share or ETF fixtures before promotion.",
            "Risk gate must be able to block unsafe data or concentration conditions.",
        ],
    },
    "time_series_momentum": {
        "asset_universe": ["stock", "etf", "index"],
        "benchmark_role": "time_series_momentum",
        "benchmark_universe": ["stock", "etf", "index"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Inspired by time-series momentum literature; requires after-cost, out-of-sample validation before promotion.",
            "Long-only implementation exits to cash instead of using leverage or short futures exposure.",
        ],
    },
    "donchian_breakout": {
        "asset_universe": ["stock", "etf", "index"],
        "benchmark_role": "channel_breakout_trend_following",
        "benchmark_universe": ["stock", "etf", "index"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Common channel-breakout trend-following baseline; requires turnover, whipsaw, and after-cost review.",
            "Uses prior high/low channels only and does not approve execution without risk gates.",
        ],
    },
    "volatility_target_trend": {
        "asset_universe": ["stock", "etf", "index"],
        "benchmark_role": "volatility_target_trend_following",
        "benchmark_universe": ["stock", "etf", "index"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Trend-following baseline with realized-volatility sizing; requires volatility-regime and turnover review.",
            "Long-only volatility targeting caps weight at 1.0 and never implies leverage.",
        ],
    },
    "pairs_ratio_mean_reversion": {
        "asset_universe": ["stock", "etf"],
        "benchmark_role": "pair_relative_value_mean_reversion",
        "benchmark_universe": ["stock", "etf"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Inspired by pairs-trading literature but constrained to long-only target weights.",
            "Requires pair-selection, liquidity, co-movement, and transaction-cost review before promotion.",
        ],
    },
}

_EXTENSION_SCHEMA_VERSION = "karkinos.strategy.v1"
_UNSAFE_EXTENSION_FIELDS = {
    "allow_live_trading",
    "auto_trade",
    "broker_submission",
    "live_auto_start",
    "real_money_execution",
}


class StrategyRegistry:
    """策略注册表。

    提供 @register_strategy 装饰器和 create / list / get 方法。
    """

    _strategies: dict[str, dict[str, Any]] = {}
    _extension_strategy_ids: set[str] = set()
    _loaded_extension_dirs: set[str] = set()

    @classmethod
    def register(cls, name: str) -> Callable[[Type[Strategy]], Type[Strategy]]:
        """装饰器：将策略类注册到注册表。

        用法::

            @register_strategy("dual_ma")
            class DualMAStrategy(Strategy): ...
        """

        def decorator(strategy_cls: Type[Strategy]) -> Type[Strategy]:
            if name in cls._strategies:
                logger.warning("策略 '%s' 已注册，将被覆盖", name)

            # 自动提取构造参数信息（排除 self 和 event_bus）
            import inspect

            sig = inspect.signature(strategy_cls.__init__)
            inferred_params: list[StrategyParameterSchema] = []
            for pname, param in sig.parameters.items():
                if pname in ("self", "event_bus", "strategy_id"):
                    continue
                inferred_params.append(infer_parameter_schema(pname, param))

            benchmark_metadata = {
                **_DEFAULT_BENCHMARK_METADATA,
                **_BENCHMARK_METADATA.get(name, {}),
            }
            parameter_schema = STRATEGY_PARAMETER_SCHEMAS.get(name, inferred_params)
            cls._strategies[name] = {
                "registry_contract_version": _STRATEGY_REGISTRY_CONTRACT_VERSION,
                "schema_version": _STRATEGY_SCHEMA_VERSION,
                "class": strategy_cls,
                "display_name": STRATEGY_DISPLAY_NAMES.get(
                    name, name.replace("_", " ").title()
                ),
                "parameter_schema": parameter_schema,
                "params": [param.to_json_dict() for param in parameter_schema],
                "description": strategy_cls.__doc__ or "",
                "source_type": "builtin",
                "is_extension": False,
                "execution_boundary": dict(_RESEARCH_ONLY_EXECUTION_BOUNDARY),
                **benchmark_metadata,
            }
            logger.debug("策略 '%s' 注册成功", name)
            return strategy_cls

        return decorator

    @classmethod
    def create(cls, name: str, event_bus: EventBus, **kwargs: Any) -> Strategy:
        """工厂方法：按名称创建策略实例。"""
        cls.discover_extensions()
        entry = cls._strategies.get(name)
        if entry is None:
            available = ", ".join(cls._strategies.keys()) or "(none)"
            raise ValueError(f"未知策略 '{name}'，可用策略: {available}")
        strategy_cls = entry.get("class")
        if strategy_cls is None:
            strategy_cls = cls._load_extension_class(entry)
            entry["class"] = strategy_cls
        return strategy_cls(event_bus, **kwargs)

    @classmethod
    def validate_params(
        cls,
        name: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and coerce strategy params against the declared schema."""
        cls.discover_extensions()
        entry = cls._strategies.get(name)
        if entry is None:
            available = ", ".join(cls._strategies.keys()) or "(none)"
            raise ValueError(f"未知策略 '{name}'，可用策略: {available}")
        return validate_strategy_params(
            name,
            entry["parameter_schema"],
            params,
        )

    @classmethod
    def list_strategies(cls) -> list[str]:
        """返回所有已注册策略名称。"""
        cls.discover_extensions()
        return list(cls._strategies.keys())

    @classmethod
    def get(cls, name: str) -> dict[str, Any] | None:
        """获取策略注册信息。"""
        cls.discover_extensions()
        return cls._strategies.get(name)

    @classmethod
    def get_info(cls) -> list[dict[str, Any]]:
        """获取所有策略的详细信息（用于 API 返回）。"""
        cls.discover_extensions()
        result = []
        for name, entry in cls._strategies.items():
            # 将 type 对象转为字符串
            params = []
            for p in entry["params"]:
                params.append(
                    {
                        "name": p["name"],
                        "type": (
                            str(p["type"])
                            if not isinstance(p["type"], str)
                            else p["type"]
                        ),
                        "default": p["default"],
                        "required": p.get("required", False),
                        "min": p.get("min"),
                        "max": p.get("max"),
                        "allowed_values": p.get("allowed_values"),
                        "description": p["description"],
                    }
                )
            result.append(
                {
                    "registry_contract_version": entry["registry_contract_version"],
                    "schema_version": entry["schema_version"],
                    "strategy_id": name,
                    "name": name,
                    "display_name": entry["display_name"],
                    "description": entry["description"].strip(),
                    "source_type": entry["source_type"],
                    "is_extension": bool(entry["is_extension"]),
                    "params": params,
                    "parameter_schema": params,
                    "asset_universe": list(entry.get("asset_universe", [])),
                    "supported_frequencies": list(
                        entry.get("supported_frequencies", [])
                    ),
                    "benchmark_role": entry["benchmark_role"],
                    "benchmark_universe": list(entry["benchmark_universe"]),
                    "requires_out_of_sample_validation": entry[
                        "requires_out_of_sample_validation"
                    ],
                    "requires_after_cost_report": entry["requires_after_cost_report"],
                    "validation_notes": list(entry["validation_notes"]),
                    "execution_boundary": dict(entry["execution_boundary"]),
                }
            )
        return result

    @classmethod
    def discover_extensions(
        cls,
        extension_dir: str | Path | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Discover local research strategy manifests from the extension area."""
        directory = (
            Path(extension_dir) if extension_dir is not None else _extension_dir()
        )
        directory_key = str(directory.resolve())
        if not force and directory_key in cls._loaded_extension_dirs:
            return

        if force:
            cls.clear_extension_strategies_for_tests()

        if not directory.exists():
            cls._loaded_extension_dirs.add(directory_key)
            return

        for manifest_path in sorted(directory.glob("*.strategy.json")):
            cls._register_extension_manifest(manifest_path)
        cls._loaded_extension_dirs.add(directory_key)

    @classmethod
    def clear_extension_strategies_for_tests(cls) -> None:
        """Remove dynamically discovered extension strategies in deterministic tests."""
        for strategy_id in list(cls._extension_strategy_ids):
            cls._strategies.pop(strategy_id, None)
        cls._extension_strategy_ids.clear()
        cls._loaded_extension_dirs.clear()

    @classmethod
    def _register_extension_manifest(cls, manifest_path: Path) -> None:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StrategyExtensionValidationError(
                str(manifest_path),
                [
                    {
                        "field": "manifest",
                        "code": "invalid_json",
                        "message": "Extension manifest must be valid JSON.",
                    }
                ],
            ) from exc

        errors = _validate_extension_manifest(raw)
        if errors:
            raise StrategyExtensionValidationError(str(manifest_path), errors)

        strategy_id = raw["strategy_id"].strip()
        parameter_schema = [
            parameter_schema_from_dict(param) for param in raw.get("parameters", [])
        ]
        entry = {
            "registry_contract_version": _STRATEGY_REGISTRY_CONTRACT_VERSION,
            "schema_version": _STRATEGY_SCHEMA_VERSION,
            "class": None,
            "class_path": raw["class_path"].strip(),
            "manifest_dir": str(manifest_path.parent),
            "display_name": raw["display_name"].strip(),
            "description": raw.get("description", ""),
            "source_type": "extension",
            "parameter_schema": parameter_schema,
            "params": [param.to_json_dict() for param in parameter_schema],
            "asset_universe": list(raw.get("asset_universe", [])),
            "supported_frequencies": list(raw.get("supported_frequencies", ["1d"])),
            "benchmark_role": raw.get("benchmark_role"),
            "benchmark_universe": list(raw.get("benchmark_universe", [])),
            "requires_out_of_sample_validation": bool(
                raw.get("requires_out_of_sample_validation", False)
            ),
            "requires_after_cost_report": bool(
                raw.get("requires_after_cost_report", False)
            ),
            "validation_notes": list(raw.get("validation_notes", [])),
            "is_extension": True,
            "execution_boundary": dict(_RESEARCH_ONLY_EXECUTION_BOUNDARY),
        }
        if (
            strategy_id in cls._strategies
            and strategy_id not in cls._extension_strategy_ids
        ):
            raise StrategyExtensionValidationError(
                str(manifest_path),
                [
                    {
                        "field": "strategy_id",
                        "code": "strategy_id_conflict",
                        "message": (
                            f"Extension strategy_id '{strategy_id}' conflicts "
                            "with a built-in strategy."
                        ),
                    }
                ],
            )
        cls._strategies[strategy_id] = entry
        cls._extension_strategy_ids.add(strategy_id)

    @classmethod
    def _load_extension_class(cls, entry: dict[str, Any]) -> Type[Strategy]:
        class_path = entry.get("class_path")
        if not class_path or ":" not in class_path:
            raise ValueError("Extension strategy class_path must use module:Class.")
        module_name, class_name = class_path.split(":", 1)
        module = _load_extension_module(module_name, entry)
        strategy_cls = getattr(module, class_name)
        if not isinstance(strategy_cls, type) or not issubclass(strategy_cls, Strategy):
            raise TypeError("Extension class_path must resolve to a Strategy subclass.")
        return strategy_cls


def _load_extension_module(module_name: str, entry: dict[str, Any]) -> Any:
    manifest_dir = entry.get("manifest_dir")
    module_path = (
        _module_path_from_extension_dir(Path(manifest_dir), module_name)
        if manifest_dir
        else None
    )
    if module_path is None:
        return importlib.import_module(module_name)

    return _load_extension_module_from_path(
        module_name,
        module_path,
        Path(manifest_dir),
    )


def _load_extension_module_from_path(
    module_name: str,
    module_path: Path,
    extension_dir: Path,
) -> Any:
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load extension strategy module '{module_name}'.")

        module = importlib.util.module_from_spec(spec)
    except OSError as exc:
        raise ImportError(
            f"Cannot prepare extension strategy module '{module_name}'."
        ) from exc

    extension_dir_key = str(extension_dir.resolve())
    inserted_path = False
    if extension_dir_key not in sys.path:
        sys.path.insert(0, extension_dir_key)
        inserted_path = True
    try:
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted_path:
            try:
                sys.path.remove(extension_dir_key)
            except ValueError:
                pass


def _module_path_from_extension_dir(
    extension_dir: Path,
    module_name: str,
) -> Path | None:
    relative_parts = module_name.split(".")
    module_file = extension_dir.joinpath(*relative_parts).with_suffix(".py")
    if module_file.exists():
        return module_file
    package_file = extension_dir.joinpath(*relative_parts, "__init__.py")
    if package_file.exists():
        return package_file
    return None


def _extension_dir() -> Path:
    return Path(
        os.environ.get("KARKINOS_STRATEGY_EXTENSION_DIR") or "strategy/extensions"
    )


def _validate_extension_manifest(raw: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return [
            {
                "field": "manifest",
                "code": "invalid_manifest",
                "message": "Extension manifest must be a JSON object.",
            }
        ]

    if raw.get("schema_version") != _EXTENSION_SCHEMA_VERSION:
        errors.append(
            {
                "field": "schema_version",
                "code": "unsupported_schema_version",
                "message": (
                    "Extension manifest schema_version must be "
                    f"'{_EXTENSION_SCHEMA_VERSION}'."
                ),
            }
        )

    for field in ("strategy_id", "display_name", "class_path"):
        if not str(raw.get(field, "")).strip():
            errors.append(
                {
                    "field": field,
                    "code": "required_field_missing",
                    "message": f"Extension manifest requires '{field}'.",
                }
            )

    for field in _UNSAFE_EXTENSION_FIELDS:
        if raw.get(field) is True:
            errors.append(
                {
                    "field": field,
                    "code": "unsafe_execution_capability",
                    "message": (
                        "Extension strategies cannot declare live or real-money "
                        "execution capabilities."
                    ),
                }
            )

    parameters = raw.get("parameters", [])
    if not isinstance(parameters, list):
        errors.append(
            {
                "field": "parameters",
                "code": "invalid_type",
                "message": "Extension manifest parameters must be a list.",
            }
        )
        return errors

    seen_params: set[str] = set()
    for index, parameter in enumerate(parameters):
        if not isinstance(parameter, dict):
            errors.append(
                {
                    "field": f"parameters[{index}]",
                    "code": "invalid_type",
                    "message": "Each extension parameter must be an object.",
                }
            )
            continue
        name = str(parameter.get("name", "")).strip()
        if not name:
            errors.append(
                {
                    "field": f"parameters[{index}].name",
                    "code": "required_field_missing",
                    "message": "Each extension parameter requires a name.",
                }
            )
        elif name in seen_params:
            errors.append(
                {
                    "field": name,
                    "code": "duplicate_parameter",
                    "message": f"Duplicate extension parameter '{name}'.",
                }
            )
        seen_params.add(name)
    return errors


# 模块级快捷函数
register_strategy = StrategyRegistry.register
