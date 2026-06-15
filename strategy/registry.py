"""策略注册表 — 自动发现与管理策略类。"""

from __future__ import annotations

import logging
from typing import Any, Callable, Type

from core.event_bus import EventBus
from strategy.base import Strategy
from strategy.schema import (
    STRATEGY_DISPLAY_NAMES,
    STRATEGY_PARAMETER_SCHEMAS,
    StrategyParameterSchema,
    infer_parameter_schema,
    validate_strategy_params,
)

logger = logging.getLogger(__name__)

_DEFAULT_BENCHMARK_METADATA = {
    "benchmark_role": None,
    "benchmark_universe": [],
    "requires_out_of_sample_validation": False,
    "requires_after_cost_report": False,
    "validation_notes": [],
}

_BENCHMARK_METADATA = {
    "dual_ma": {
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
        "benchmark_role": "a_share_or_etf_mean_reversion",
        "benchmark_universe": ["stock", "etf"],
        "requires_out_of_sample_validation": True,
        "requires_after_cost_report": True,
        "validation_notes": [
            "Requires after-cost, out-of-sample mean-reversion validation on A-share or ETF fixtures before promotion.",
            "Risk gate must be able to block unsafe data or concentration conditions.",
        ],
    },
}


class StrategyRegistry:
    """策略注册表。

    提供 @register_strategy 装饰器和 create / list / get 方法。
    """

    _strategies: dict[str, dict[str, Any]] = {}

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
                "class": strategy_cls,
                "display_name": STRATEGY_DISPLAY_NAMES.get(
                    name, name.replace("_", " ").title()
                ),
                "parameter_schema": parameter_schema,
                "params": [param.to_json_dict() for param in parameter_schema],
                "description": strategy_cls.__doc__ or "",
                **benchmark_metadata,
            }
            logger.debug("策略 '%s' 注册成功", name)
            return strategy_cls

        return decorator

    @classmethod
    def create(cls, name: str, event_bus: EventBus, **kwargs: Any) -> Strategy:
        """工厂方法：按名称创建策略实例。"""
        entry = cls._strategies.get(name)
        if entry is None:
            available = ", ".join(cls._strategies.keys()) or "(none)"
            raise ValueError(f"未知策略 '{name}'，可用策略: {available}")
        strategy_cls = entry["class"]
        return strategy_cls(event_bus, **kwargs)

    @classmethod
    def validate_params(
        cls,
        name: str,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and coerce strategy params against the declared schema."""
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
        return list(cls._strategies.keys())

    @classmethod
    def get(cls, name: str) -> dict[str, Any] | None:
        """获取策略注册信息。"""
        return cls._strategies.get(name)

    @classmethod
    def get_info(cls) -> list[dict[str, Any]]:
        """获取所有策略的详细信息（用于 API 返回）。"""
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
                    "strategy_id": name,
                    "name": name,
                    "display_name": entry["display_name"],
                    "description": entry["description"].strip(),
                    "params": params,
                    "parameter_schema": params,
                    "benchmark_role": entry["benchmark_role"],
                    "benchmark_universe": list(entry["benchmark_universe"]),
                    "requires_out_of_sample_validation": entry[
                        "requires_out_of_sample_validation"
                    ],
                    "requires_after_cost_report": entry["requires_after_cost_report"],
                    "validation_notes": list(entry["validation_notes"]),
                }
            )
        return result


# 模块级快捷函数
register_strategy = StrategyRegistry.register
