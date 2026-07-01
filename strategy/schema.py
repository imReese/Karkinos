"""Typed strategy parameter schemas and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter
from typing import Any


@dataclass(frozen=True)
class StrategyParameterSchema:
    name: str
    type: str
    default: Any = None
    required: bool = False
    min: int | float | None = None
    max: int | float | None = None
    allowed_values: list[Any] | None = None
    description: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "min": self.min,
            "max": self.max,
            "allowed_values": self.allowed_values,
            "description": self.description,
        }


class StrategyParameterValidationError(ValueError):
    """Raised when strategy parameters do not match their declared schema."""

    def __init__(self, strategy_id: str, errors: list[dict[str, Any]]) -> None:
        self.strategy_id = strategy_id
        self.errors = errors
        super().__init__(f"Invalid parameters for strategy '{strategy_id}'")


class StrategyExtensionValidationError(ValueError):
    """Raised when a local strategy extension manifest is invalid or unsafe."""

    def __init__(self, manifest_path: str, errors: list[dict[str, Any]]) -> None:
        self.manifest_path = manifest_path
        self.errors = errors
        super().__init__(f"Invalid strategy extension manifest '{manifest_path}'")


STRATEGY_DISPLAY_NAMES = {
    "dual_ma": "Dual Moving Average",
    "monthly_rebalance": "Monthly Rebalance",
    "bollinger": "Bollinger Mean Reversion",
    "rsi": "RSI Mean Reversion",
    "time_series_momentum": "Time Series Momentum",
    "donchian_breakout": "Donchian Channel Breakout",
    "volatility_target_trend": "Volatility Target Trend",
    "pairs_ratio_mean_reversion": "Pairs Ratio Mean Reversion",
}


STRATEGY_PARAMETER_SCHEMAS = {
    "dual_ma": [
        StrategyParameterSchema(
            name="short_period",
            type="int",
            default=5,
            min=1,
            max=250,
            description="Short moving-average window in trading bars.",
        ),
        StrategyParameterSchema(
            name="long_period",
            type="int",
            default=20,
            min=2,
            max=500,
            description="Long moving-average window in trading bars.",
        ),
    ],
    "monthly_rebalance": [
        StrategyParameterSchema(
            name="target_weights",
            type="dict",
            default=None,
            description="Target weights by symbol, expressed as 0-1 decimals.",
        )
    ],
    "bollinger": [
        StrategyParameterSchema(
            name="bb_period",
            type="int",
            default=20,
            min=2,
            max=500,
            description="Bollinger lookback window in trading bars.",
        ),
        StrategyParameterSchema(
            name="num_std",
            type="float",
            default=2.0,
            min=0.1,
            max=10.0,
            description="Number of standard deviations used for bands.",
        ),
    ],
    "rsi": [
        StrategyParameterSchema(
            name="rsi_period",
            type="int",
            default=14,
            min=2,
            max=250,
            description="RSI smoothing window in trading bars.",
        ),
        StrategyParameterSchema(
            name="oversold",
            type="float",
            default=30.0,
            min=0.0,
            max=100.0,
            description="RSI threshold crossed upward to emit buy signals.",
        ),
        StrategyParameterSchema(
            name="overbought",
            type="float",
            default=70.0,
            min=0.0,
            max=100.0,
            description="RSI threshold crossed downward to emit sell signals.",
        ),
    ],
    "time_series_momentum": [
        StrategyParameterSchema(
            name="lookback_period",
            type="int",
            default=126,
            min=2,
            max=500,
            description="Return lookback window in trading bars.",
        ),
        StrategyParameterSchema(
            name="min_return",
            type="float",
            default=0.0,
            min=-1.0,
            max=10.0,
            description="Minimum lookback return required to enter.",
        ),
        StrategyParameterSchema(
            name="exit_return",
            type="float",
            default=0.0,
            min=-1.0,
            max=10.0,
            description="Lookback return threshold at or below which to exit.",
        ),
        StrategyParameterSchema(
            name="target_weight",
            type="float",
            default=1.0,
            min=0.0,
            max=1.0,
            description="Target long-only weight when momentum is positive.",
        ),
    ],
    "donchian_breakout": [
        StrategyParameterSchema(
            name="entry_window",
            type="int",
            default=55,
            min=2,
            max=500,
            description="Prior high channel window used for breakout entries.",
        ),
        StrategyParameterSchema(
            name="exit_window",
            type="int",
            default=20,
            min=1,
            max=500,
            description="Prior low channel window used for exits.",
        ),
        StrategyParameterSchema(
            name="target_weight",
            type="float",
            default=1.0,
            min=0.0,
            max=1.0,
            description="Target long-only weight after an upside breakout.",
        ),
    ],
    "volatility_target_trend": [
        StrategyParameterSchema(
            name="lookback_period",
            type="int",
            default=126,
            min=2,
            max=500,
            description="Return lookback window used to confirm trend.",
        ),
        StrategyParameterSchema(
            name="volatility_window",
            type="int",
            default=20,
            min=2,
            max=250,
            description="Rolling return window used to estimate realized volatility.",
        ),
        StrategyParameterSchema(
            name="target_annual_volatility",
            type="float",
            default=0.15,
            min=0.01,
            max=2.0,
            description="Annualized volatility target used for position sizing.",
        ),
        StrategyParameterSchema(
            name="max_weight",
            type="float",
            default=1.0,
            min=0.0,
            max=1.0,
            description="Maximum long-only target weight.",
        ),
        StrategyParameterSchema(
            name="min_momentum",
            type="float",
            default=0.0,
            min=-1.0,
            max=10.0,
            description="Minimum lookback return required to hold risk.",
        ),
        StrategyParameterSchema(
            name="rebalance_threshold",
            type="float",
            default=0.05,
            min=0.0,
            max=1.0,
            description="Minimum target-weight change required to emit a rebalance.",
        ),
    ],
    "pairs_ratio_mean_reversion": [
        StrategyParameterSchema(
            name="symbol_a",
            type="str",
            default="",
            description="First leg symbol. Empty value uses the first run symbol.",
        ),
        StrategyParameterSchema(
            name="symbol_b",
            type="str",
            default="",
            description="Second leg symbol. Empty value uses the second run symbol.",
        ),
        StrategyParameterSchema(
            name="lookback_period",
            type="int",
            default=60,
            min=3,
            max=500,
            description="A/B ratio lookback window used for z-score estimation.",
        ),
        StrategyParameterSchema(
            name="entry_z",
            type="float",
            default=2.0,
            min=0.1,
            max=10.0,
            description="Absolute z-score threshold used to rotate into one leg.",
        ),
        StrategyParameterSchema(
            name="exit_z",
            type="float",
            default=0.5,
            min=0.0,
            max=10.0,
            description="Absolute z-score threshold used to return to neutral weights.",
        ),
        StrategyParameterSchema(
            name="pair_weight",
            type="float",
            default=1.0,
            min=0.0,
            max=1.0,
            description="Target weight assigned to the cheap relative-value leg.",
        ),
        StrategyParameterSchema(
            name="neutral_weight",
            type="float",
            default=0.5,
            min=0.0,
            max=1.0,
            description="Target weight for each leg when the ratio normalizes.",
        ),
    ],
}


def infer_parameter_schema(name: str, param: Parameter) -> StrategyParameterSchema:
    required = param.default is Parameter.empty
    default = None if required else param.default
    return StrategyParameterSchema(
        name=name,
        type=_annotation_to_type(param.annotation),
        default=default,
        required=required,
    )


def parameter_schema_from_dict(raw: dict[str, Any]) -> StrategyParameterSchema:
    return StrategyParameterSchema(
        name=str(raw.get("name", "")).strip(),
        type=str(raw.get("type", "any")).strip() or "any",
        default=raw.get("default"),
        required=bool(raw.get("required", False)),
        min=raw.get("min"),
        max=raw.get("max"),
        allowed_values=raw.get("allowed_values"),
        description=str(raw.get("description", "")).strip(),
    )


def validate_strategy_params(
    strategy_id: str,
    schema: list[StrategyParameterSchema],
    raw_params: dict[str, Any] | None,
) -> dict[str, Any]:
    params = raw_params or {}
    schema_by_name = {param.name: param for param in schema}
    errors: list[dict[str, Any]] = []

    for key in params:
        if key not in schema_by_name:
            errors.append(
                {
                    "field": key,
                    "code": "unknown_parameter",
                    "message": (
                        f"Unknown parameter '{key}' for strategy '{strategy_id}'."
                    ),
                }
            )

    validated: dict[str, Any] = {}
    for param in schema:
        if param.name in params:
            value = params[param.name]
        elif param.required:
            errors.append(
                {
                    "field": param.name,
                    "code": "required_parameter_missing",
                    "message": (
                        f"Parameter '{param.name}' is required for strategy "
                        f"'{strategy_id}'."
                    ),
                }
            )
            continue
        else:
            value = param.default

        if value is None and not param.required:
            validated[param.name] = None
            continue

        parsed = _parse_value(param, value, errors)
        if parsed is not None:
            validated[param.name] = parsed

    _validate_cross_fields(strategy_id, validated, errors)
    if errors:
        raise StrategyParameterValidationError(strategy_id, errors)
    return validated


def _annotation_to_type(annotation: Any) -> str:
    if annotation is Parameter.empty:
        return "any"
    if annotation in (int, "int"):
        return "int"
    if annotation in (float, "float"):
        return "float"
    if annotation in (str, "str"):
        return "str"
    if annotation in (bool, "bool"):
        return "bool"
    text = str(annotation)
    if "int" in text and "|" not in text:
        return "int"
    if "float" in text and "|" not in text:
        return "float"
    if "dict" in text:
        return "dict"
    return text


def _parse_value(
    schema: StrategyParameterSchema,
    value: Any,
    errors: list[dict[str, Any]],
) -> Any:
    try:
        if schema.type == "int":
            if isinstance(value, bool):
                raise ValueError
            parsed = int(value)
        elif schema.type == "float":
            if isinstance(value, bool):
                raise ValueError
            parsed = float(value)
        elif schema.type == "bool":
            parsed = _parse_bool(value)
        elif schema.type == "str":
            parsed = str(value)
        elif schema.type == "dict":
            if not isinstance(value, dict):
                raise ValueError
            parsed = value
        else:
            parsed = value
    except (TypeError, ValueError):
        errors.append(
            {
                "field": schema.name,
                "code": "invalid_type",
                "message": (
                    f"Parameter '{schema.name}' must be of type {schema.type}."
                ),
            }
        )
        return None

    if schema.min is not None and parsed < schema.min:
        errors.append(
            {
                "field": schema.name,
                "code": "below_min",
                "message": f"Parameter '{schema.name}' must be >= {schema.min}.",
            }
        )
    if schema.max is not None and parsed > schema.max:
        errors.append(
            {
                "field": schema.name,
                "code": "above_max",
                "message": f"Parameter '{schema.name}' must be <= {schema.max}.",
            }
        )
    if schema.allowed_values is not None and parsed not in schema.allowed_values:
        errors.append(
            {
                "field": schema.name,
                "code": "not_allowed",
                "message": (
                    f"Parameter '{schema.name}' must be one of "
                    f"{schema.allowed_values}."
                ),
            }
        )
    return parsed


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    raise ValueError


def _validate_cross_fields(
    strategy_id: str,
    params: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    if strategy_id == "dual_ma":
        short = params.get("short_period")
        long = params.get("long_period")
        if short is not None and long is not None and short >= long:
            errors.append(
                {
                    "field": "short_period",
                    "code": "cross_field_validation_failed",
                    "message": "short_period must be less than long_period.",
                }
            )
    if strategy_id == "rsi":
        oversold = params.get("oversold")
        overbought = params.get("overbought")
        if oversold is not None and overbought is not None and oversold >= overbought:
            errors.append(
                {
                    "field": "oversold",
                    "code": "cross_field_validation_failed",
                    "message": "oversold must be less than overbought.",
                }
            )
    if strategy_id == "donchian_breakout":
        entry_window = params.get("entry_window")
        exit_window = params.get("exit_window")
        if (
            entry_window is not None
            and exit_window is not None
            and exit_window >= entry_window
        ):
            errors.append(
                {
                    "field": "exit_window",
                    "code": "cross_field_validation_failed",
                    "message": "exit_window must be less than entry_window.",
                }
            )
    if strategy_id == "pairs_ratio_mean_reversion":
        symbol_a = str(params.get("symbol_a") or "").strip()
        symbol_b = str(params.get("symbol_b") or "").strip()
        if symbol_a and symbol_b and symbol_a == symbol_b:
            errors.append(
                {
                    "field": "symbol_b",
                    "code": "cross_field_validation_failed",
                    "message": "symbol_a and symbol_b must be different.",
                }
            )
        entry_z = params.get("entry_z")
        exit_z = params.get("exit_z")
        if entry_z is not None and exit_z is not None and exit_z >= entry_z:
            errors.append(
                {
                    "field": "exit_z",
                    "code": "cross_field_validation_failed",
                    "message": "exit_z must be less than entry_z.",
                }
            )
