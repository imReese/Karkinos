"""Research-only, deterministic Formula DSL for AI strategy hypotheses.

The DSL deliberately describes signals rather than executable code.  It may be
evaluated only by the restricted research adapter and never enters the strategy
registry, OMS, ledger, risk, capital-authority, or broker boundaries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from data.features import FeatureEngine

from .contracts import JsonObject, canonical_json, content_fingerprint

FORMULA_AST_CONTRACT = "karkinos.ai.formula_ast.v1"
FORMULA_BINDING_CONTRACT = "karkinos.ai.formula_binding.v1"
CANONICAL_COST_MODEL_REFERENCE = "karkinos.backtest.multi_asset_commission.default.v1"

_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
_WINDOW_OPERATORS = frozenset(
    {"rolling_mean", "rolling_std", "zscore", "ema", "rsi", "atr"}
)
_PERIOD_OPERATORS = frozenset({"lag", "delta", "return"})
_BINARY_OPERATORS = frozenset(
    {
        "add",
        "subtract",
        "multiply",
        "divide",
        "gt",
        "gte",
        "lt",
        "lte",
        "equal",
        "and",
        "or",
        "cross",
    }
)
_UNARY_OPERATORS = frozenset({"not"})
_UNSUPPORTED_REVIEWED_OPERATORS = frozenset({"rank", "roc", "volatility_target"})
_MAX_WINDOW = 252
_MAX_DEPTH = 32


class FormulaValidationError(ValueError):
    """A stable, fail-closed Formula DSL rejection."""

    def __init__(self, code: str, path: str = "formula_ast") -> None:
        super().__init__(f"{code}:{path}")
        self.code = code
        self.path = path


@dataclass(frozen=True)
class FormulaBinding:
    """Operator-frozen inputs that form one deterministic research identity."""

    formula_ast: JsonObject
    universe: tuple[str, ...]
    dataset_snapshot_id: str
    start_date: str
    end_date: str
    frequency: str
    cost_model_reference: str
    anti_lookahead_assumptions: tuple[str, ...]
    parameter_values: JsonObject
    parameter_ranges: JsonObject
    initial_cash: float
    schema_version: str = FORMULA_BINDING_CONTRACT

    def __post_init__(self) -> None:
        if not self.universe or len(self.universe) != len(set(self.universe)):
            raise FormulaValidationError("invalid_universe", "universe")
        if any(not str(symbol).strip() for symbol in self.universe):
            raise FormulaValidationError("invalid_universe", "universe")
        for field_name in (
            "dataset_snapshot_id",
            "start_date",
            "end_date",
            "frequency",
            "cost_model_reference",
        ):
            if not str(getattr(self, field_name)).strip():
                raise FormulaValidationError("missing_binding", field_name)
        if self.start_date > self.end_date:
            raise FormulaValidationError("invalid_date_range", "date_range")
        if self.frequency != "1d":
            raise FormulaValidationError("unsupported_frequency", "frequency")
        if self.cost_model_reference != CANONICAL_COST_MODEL_REFERENCE:
            raise FormulaValidationError(
                "cost_model_not_operator_approved", "cost_model_reference"
            )
        if not self.anti_lookahead_assumptions or any(
            not str(item).strip() for item in self.anti_lookahead_assumptions
        ):
            raise FormulaValidationError(
                "anti_lookahead_assumptions_required",
                "anti_lookahead_assumptions",
            )
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise FormulaValidationError("invalid_initial_cash", "initial_cash")
        validate_formula_ast(self.formula_ast, universe_size=len(self.universe))
        _reject_non_finite(self.parameter_values, "parameter_values")
        _reject_non_finite(self.parameter_ranges, "parameter_ranges")

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "formula_ast": self.formula_ast,
            "universe": list(self.universe),
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "frequency": self.frequency,
            "cost_model_reference": self.cost_model_reference,
            "anti_lookahead_assumptions": list(self.anti_lookahead_assumptions),
            "parameter_values": self.parameter_values,
            "parameter_ranges": self.parameter_ranges,
            "initial_cash": float(self.initial_cash),
        }

    @property
    def fingerprint(self) -> str:
        return "sha256:" + content_fingerprint(self.to_dict())


def formula_operator_catalog() -> JsonObject:
    """Return the reviewed local catalog; unsupported entries stay explicit."""
    return {
        "schema_version": "karkinos.ai.formula_operator_catalog.v1",
        "formula_contract": FORMULA_AST_CONTRACT,
        "allowed_fields": sorted(_FIELDS),
        "enabled_operators": sorted(
            {
                "field",
                "constant",
                "equal_weight",
                "max_weight",
                *_WINDOW_OPERATORS,
                *_PERIOD_OPERATORS,
                *_BINARY_OPERATORS,
                *_UNARY_OPERATORS,
            }
        ),
        "reviewed_but_unsupported": {
            "rank": "cross-sectional timestamp alignment is not yet exposed by the canonical engine adapter",
            "roc": "no canonical feature implementation is registered",
            "volatility_target": "canonical portfolio sizing does not expose this as a research-only input",
        },
        "expression_shapes": {
            "field": {"op": "field", "name": "open|high|low|close|volume"},
            "constant": {"op": "constant", "value": "finite number"},
            "period_operator": {
                "op": "lag|delta|return",
                "input": "expression",
                "period": "integer 1..252",
            },
            "window_operator": {
                "op": "rolling_mean|rolling_std|zscore|ema|rsi",
                "input": "expression",
                "window": "integer 2..252",
            },
            "atr": {"op": "atr", "window": "integer 2..252"},
            "binary_operator": {
                "op": ("add|subtract|multiply|divide|gt|gte|lt|lte|equal|and|or|cross"),
                "left": "expression",
                "right": "expression",
            },
            "not": {"op": "not", "input": "expression"},
            "equal_weight": {"op": "equal_weight"},
            "max_weight": {
                "op": "max_weight",
                "input": "equal_weight|max_weight sizing object",
                "value": "finite number in (0, 1]",
            },
        },
        "window_bounds": {"minimum": 2, "maximum": _MAX_WINDOW},
        "signal_timing": (
            "expressions observe completed bars; target changes execute on the next "
            "available persisted bar"
        ),
        "future_references_allowed": False,
        "arbitrary_code_allowed": False,
        "provider_side_tools_allowed": False,
        "authority_effect": "none",
    }


def validate_formula_ast(
    formula_ast: Mapping[str, Any],
    *,
    universe_size: int,
) -> JsonObject:
    """Validate the exact v1 strategy formula and return a normalized copy."""
    if not isinstance(formula_ast, Mapping):
        raise FormulaValidationError("formula_must_be_object")
    _expect_keys(
        formula_ast,
        required={"schema_version", "entry", "exit", "position_size"},
        path="formula_ast",
    )
    if formula_ast.get("schema_version") != FORMULA_AST_CONTRACT:
        raise FormulaValidationError("unknown_formula_schema", "schema_version")
    _validate_expression(formula_ast["entry"], "formula_ast.entry", depth=0)
    _validate_expression(formula_ast["exit"], "formula_ast.exit", depth=0)
    _validate_sizing(
        formula_ast["position_size"],
        "formula_ast.position_size",
        universe_size=universe_size,
    )
    _reject_non_finite(formula_ast, "formula_ast")
    return _json_copy(formula_ast)


def evaluate_formula(
    formula_ast: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    universe_size: int,
) -> tuple[pd.Series, pd.Series, float]:
    """Evaluate validated expressions over history without future references."""
    normalized = validate_formula_ast(formula_ast, universe_size=universe_size)
    entry = _evaluate_expression(normalized["entry"], frame).fillna(False).astype(bool)
    exit_signal = (
        _evaluate_expression(normalized["exit"], frame).fillna(False).astype(bool)
    )
    target_weight = _evaluate_sizing(
        normalized["position_size"], universe_size=universe_size
    )
    return entry, exit_signal, target_weight


def formula_fingerprint(binding: FormulaBinding) -> str:
    """Expose a named helper for stable fixtures and API contracts."""
    return binding.fingerprint


def _validate_expression(value: Any, path: str, *, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise FormulaValidationError("formula_too_deep", path)
    if not isinstance(value, Mapping):
        raise FormulaValidationError("expression_must_be_object", path)
    op = value.get("op")
    if not isinstance(op, str) or not op:
        raise FormulaValidationError("operator_missing", f"{path}.op")
    if op in _UNSUPPORTED_REVIEWED_OPERATORS:
        raise FormulaValidationError("operator_not_canonically_supported", path)
    if op == "field":
        _expect_keys(value, required={"op", "name"}, path=path)
        if value.get("name") not in _FIELDS:
            raise FormulaValidationError("unknown_field", f"{path}.name")
        return
    if op == "constant":
        _expect_keys(value, required={"op", "value"}, path=path)
        if isinstance(value.get("value"), bool) or not isinstance(
            value.get("value"), (int, float)
        ):
            raise FormulaValidationError("constant_not_numeric", f"{path}.value")
        if not math.isfinite(float(value["value"])):
            raise FormulaValidationError("non_finite_number", f"{path}.value")
        return
    if op in _PERIOD_OPERATORS:
        _expect_keys(value, required={"op", "input", "period"}, path=path)
        period = value.get("period")
        if not isinstance(period, int) or isinstance(period, bool) or period < 1:
            raise FormulaValidationError("future_or_invalid_period", f"{path}.period")
        if period > _MAX_WINDOW:
            raise FormulaValidationError("period_out_of_bounds", f"{path}.period")
        _validate_expression(value["input"], f"{path}.input", depth=depth + 1)
        return
    if op in _WINDOW_OPERATORS:
        required = {"op", "window"} if op == "atr" else {"op", "input", "window"}
        _expect_keys(value, required=required, path=path)
        window = value.get("window")
        if (
            not isinstance(window, int)
            or isinstance(window, bool)
            or window < 2
            or window > _MAX_WINDOW
        ):
            raise FormulaValidationError("window_out_of_bounds", f"{path}.window")
        if op != "atr":
            _validate_expression(value["input"], f"{path}.input", depth=depth + 1)
        return
    if op in _BINARY_OPERATORS:
        _expect_keys(value, required={"op", "left", "right"}, path=path)
        _validate_expression(value["left"], f"{path}.left", depth=depth + 1)
        _validate_expression(value["right"], f"{path}.right", depth=depth + 1)
        return
    if op in _UNARY_OPERATORS:
        _expect_keys(value, required={"op", "input"}, path=path)
        _validate_expression(value["input"], f"{path}.input", depth=depth + 1)
        return
    raise FormulaValidationError("unknown_operator", path)


def _validate_sizing(value: Any, path: str, *, universe_size: int) -> None:
    if universe_size <= 0:
        raise FormulaValidationError("invalid_universe", path)
    if not isinstance(value, Mapping):
        raise FormulaValidationError("sizing_must_be_object", path)
    op = value.get("op")
    if op == "equal_weight":
        _expect_keys(value, required={"op"}, path=path)
        return
    if op == "max_weight":
        _expect_keys(value, required={"op", "input", "value"}, path=path)
        cap = value.get("value")
        if isinstance(cap, bool) or not isinstance(cap, (int, float)):
            raise FormulaValidationError("max_weight_not_numeric", f"{path}.value")
        if not math.isfinite(float(cap)) or not 0 < float(cap) <= 1:
            raise FormulaValidationError("max_weight_out_of_bounds", f"{path}.value")
        _validate_sizing(value["input"], f"{path}.input", universe_size=universe_size)
        return
    if op == "volatility_target":
        raise FormulaValidationError("operator_not_canonically_supported", path)
    raise FormulaValidationError("unknown_sizing_operator", path)


def _evaluate_expression(value: Mapping[str, Any], frame: pd.DataFrame) -> pd.Series:
    op = str(value["op"])
    index = frame.index
    if op == "field":
        return pd.to_numeric(frame[str(value["name"])], errors="coerce")
    if op == "constant":
        return pd.Series(float(value["value"]), index=index, dtype=float)
    if op in _PERIOD_OPERATORS:
        item = _evaluate_expression(value["input"], frame)
        period = int(value["period"])
        if op == "lag":
            return item.shift(period)
        if op == "delta":
            return item.diff(period)
        return item.pct_change(period, fill_method=None)
    if op in _WINDOW_OPERATORS:
        window = int(value["window"])
        if op == "atr":
            return FeatureEngine.atr(frame, period=window)
        item = _evaluate_expression(value["input"], frame)
        scratch = pd.DataFrame({"value": item}, index=index)
        if op == "rolling_mean":
            return FeatureEngine.sma(scratch, column="value", period=window)
        if op == "rolling_std":
            return item.rolling(window=window).std()
        if op == "zscore":
            mean = item.rolling(window=window).mean()
            std = item.rolling(window=window).std()
            return (item - mean) / std.replace(0, float("nan"))
        if op == "ema":
            return FeatureEngine.ema(scratch, column="value", period=window)
        if op == "rsi":
            return FeatureEngine.rsi(scratch, column="value", period=window)
    if op in _BINARY_OPERATORS:
        left = _evaluate_expression(value["left"], frame)
        right = _evaluate_expression(value["right"], frame)
        if op == "add":
            return left + right
        if op == "subtract":
            return left - right
        if op == "multiply":
            return left * right
        if op == "divide":
            return left / right.replace(0, float("nan"))
        if op == "gt":
            return left > right
        if op == "gte":
            return left >= right
        if op == "lt":
            return left < right
        if op == "lte":
            return left <= right
        if op == "equal":
            return left == right
        if op == "and":
            return left.fillna(False).astype(bool) & right.fillna(False).astype(bool)
        if op == "or":
            return left.fillna(False).astype(bool) | right.fillna(False).astype(bool)
        if op == "cross":
            return (left > right) & (left.shift(1) <= right.shift(1))
    if op == "not":
        return ~_evaluate_expression(value["input"], frame).fillna(False).astype(bool)
    raise FormulaValidationError("unknown_operator", "evaluation")


def _evaluate_sizing(value: Mapping[str, Any], *, universe_size: int) -> float:
    op = str(value["op"])
    if op == "equal_weight":
        return 1.0 / universe_size
    if op == "max_weight":
        return min(
            float(value["value"]),
            _evaluate_sizing(value["input"], universe_size=universe_size),
        )
    raise FormulaValidationError("unknown_sizing_operator", "position_size")


def _expect_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    path: str,
) -> None:
    keys = set(value)
    if keys != required:
        raise FormulaValidationError(
            "expression_keys_mismatch",
            f"{path}:required={','.join(sorted(required))}:actual={','.join(sorted(keys))}",
        )


def _reject_non_finite(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise FormulaValidationError("non_finite_number", path)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")
        return
    raise FormulaValidationError("non_json_value", path)


def _json_copy(value: Mapping[str, Any]) -> JsonObject:
    import json

    return json.loads(canonical_json(value))
