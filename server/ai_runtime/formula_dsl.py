"""Deterministic Formula DSL for research and human-promoted shadow signals.

The DSL describes signals rather than executable code.  Research drafts remain
non-authorizing; only an exact, evidence-bound, human-promoted snapshot may feed
the local daily-candidate scanner.  Its output still cannot enter OMS, ledger,
capital-authority, automatic execution, or broker-submission boundaries.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

import pandas as pd

from data.features import FeatureEngine
from server.contracts.normalized_strategy_research import (
    CANONICAL_COST_MODEL_REFERENCE,
)

from .contracts import JsonObject, canonical_json, content_fingerprint

FORMULA_AST_CONTRACT = "karkinos.ai.formula_ast.v1"
FORMULA_BINDING_CONTRACT = "karkinos.ai.formula_binding.v1"
REVIEWED_ACCOUNT_COST_MODEL_PREFIX = (
    "karkinos.backtest.reviewed_account_fee_schedule.v1:"
)
_REVIEWED_ACCOUNT_COST_MODEL_REFERENCE = re.compile(
    re.escape(REVIEWED_ACCOUNT_COST_MODEL_PREFIX)
    + r"fee_review_[0-9a-f]{32}:[0-9a-f]{64}$"
)

_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
_WINDOW_OPERATORS = frozenset(
    {
        "rolling_mean",
        "rolling_sum",
        "rolling_std",
        "rolling_max",
        "rolling_min",
        "zscore",
        "ema",
        "rsi",
        "atr",
        "rank",
    }
)
_PERIOD_OPERATORS = frozenset({"lag", "delta", "return", "roc"})
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
_CROSS_SECTIONAL_OPERATOR = "cross_sectional_rank"
_CROSS_SECTIONAL_MEAN_OPERATOR = "cross_sectional_mean"
_CROSS_SECTIONAL_ZSCORE_OPERATOR = "cross_sectional_zscore"
_CROSS_SECTIONAL_OPERATORS = frozenset(
    {
        _CROSS_SECTIONAL_OPERATOR,
        _CROSS_SECTIONAL_MEAN_OPERATOR,
        _CROSS_SECTIONAL_ZSCORE_OPERATOR,
    }
)
_CROSS_SECTIONAL_ALIASES = {
    "cs_rank": _CROSS_SECTIONAL_OPERATOR,
    "cs_zscore": _CROSS_SECTIONAL_ZSCORE_OPERATOR,
}
_ALL_CROSS_SECTIONAL_OPERATORS = _CROSS_SECTIONAL_OPERATORS | frozenset(
    _CROSS_SECTIONAL_ALIASES
)
_UNSUPPORTED_REVIEWED_OPERATORS = frozenset({"volatility_target"})
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
        if not is_operator_approved_cost_model_reference(self.cost_model_reference):
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


def is_operator_approved_cost_model_reference(value: object) -> bool:
    """Accept the default estimate or one exact persisted reviewed schedule."""
    normalized = str(value or "").strip()
    return normalized == CANONICAL_COST_MODEL_REFERENCE or bool(
        _REVIEWED_ACCOUNT_COST_MODEL_REFERENCE.fullmatch(normalized)
    )


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
                *_CROSS_SECTIONAL_OPERATORS,
            }
        ),
        "reviewed_but_unsupported": {
            "volatility_target": "canonical portfolio sizing does not expose this as a research-only input",
        },
        "expression_shapes": {
            "field": {"op": "field", "name": "open|high|low|close|volume"},
            "constant": {"op": "constant", "value": "finite number"},
            "period_operator": {
                "op": "lag|delta|return|roc",
                "input": "expression",
                "period": "integer 1..252",
            },
            "window_operator": {
                "op": "rolling_mean|rolling_sum|rolling_std|rolling_max|rolling_min|zscore|ema|rsi|rank",
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
            "cross_sectional_rank": {
                "op": _CROSS_SECTIONAL_OPERATOR,
                "input": "finite-history expression without another cross-sectional rank; a resolved cross-sectional mean is allowed",
            },
            "cross_sectional_mean": {
                "op": _CROSS_SECTIONAL_MEAN_OPERATOR,
                "input": "finite-history local expression; equal-weight same-session mean over the complete defined reference pool",
            },
            "cross_sectional_zscore": {
                "op": _CROSS_SECTIONAL_ZSCORE_OPERATOR,
                "input": "finite-history local expression; cross-sectional z-score (mean 0, unit variance) over the reference pool",
            },
            "cross_sectional_operator": {
                "op": f"{_CROSS_SECTIONAL_OPERATOR}|{_CROSS_SECTIONAL_MEAN_OPERATOR}|{_CROSS_SECTIONAL_ZSCORE_OPERATOR}",
                "input": "expression",
            },
            "equal_weight": {"op": "equal_weight"},
            "max_weight": {
                "op": "max_weight",
                "input": "equal_weight|max_weight sizing object",
                "value": "finite number in (0, 1]",
            },
        },
        "window_bounds": {"minimum": 2, "maximum": _MAX_WINDOW},
        "operator_semantics": {
            "rolling_sum": "sum of the complete trailing window, including the current bar; undefined inputs remain missing",
            "return": "fractional change: current / lagged - 1",
            "roc": "percentage change: 100 * (current / lagged - 1); undefined changes are missing",
            "rolling_max": "maximum of the complete trailing window, including the current bar",
            "rolling_min": "minimum of the complete trailing window, including the current bar",
            "rank": "percentile rank (0.0 to 1.0) of the current value within the trailing window",
            "cross_sectional_rank": (
                "entry-only ascending average percentile among defined scores in the "
                "complete dated declared market after the frozen history requirement; "
                "includes held and non-permitted entry boards, never cash/lot filtering; "
                "ties receive their average percentile; incomplete inputs block new "
                "entries while an independent local exit remains available"
            ),
            "cross_sectional_mean": (
                "equal-weight same-session mean over the complete defined reference pool"
            ),
            "cross_sectional_zscore": (
                "cross-sectional z-score (mean 0, unit variance) over the complete defined reference pool"
            ),
        },
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
    if formula_requires_cross_section(formula_ast["exit"]):
        raise FormulaValidationError(
            "cross_sectional_exit_unsupported", "formula_ast.exit"
        )
    if formula_requires_cross_section(formula_ast["entry"]) and (
        expression_lookback_rows(formula_ast["entry"]) is None
    ):
        raise FormulaValidationError(
            "cross_sectional_finite_history_required", "formula_ast.entry"
        )
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
    cross_section_values: Mapping[str, pd.Series] | None = None,
    cross_section_available: Mapping[str, pd.Series] | None = None,
) -> tuple[pd.Series, pd.Series, float]:
    """Evaluate validated expressions over history without future references."""
    normalized = validate_formula_ast(formula_ast, universe_size=universe_size)
    joint = formula_requires_cross_section(normalized["entry"])
    if joint and universe_size > 1 and cross_section_values is None:
        raise FormulaValidationError(
            "cross_sectional_context_required", "formula_ast.entry"
        )
    if joint and not formula_expression_fields(normalized["entry"]) <= set(frame):
        entry = pd.Series(False, index=frame.index, dtype=bool)
    else:
        entry = (
            _evaluate_expression(
                normalized["entry"],
                frame,
                universe_size=universe_size,
                cross_section_values=cross_section_values,
            )
            .fillna(False)
            .astype(bool)
        )
    if joint and (universe_size > 1 or cross_section_available is not None):
        entry &= cross_section_expression_available(
            normalized["entry"], frame.index, cross_section_available or {}
        )
    if joint and not formula_expression_fields(normalized["exit"]) <= set(frame):
        exit_signal = pd.Series(False, index=frame.index, dtype=bool)
    else:
        exit_signal = (
            _evaluate_expression(normalized["exit"], frame, universe_size=universe_size)
            .fillna(False)
            .astype(bool)
        )
    target_weight = _evaluate_sizing(
        normalized["position_size"], universe_size=universe_size
    )
    return entry, exit_signal, target_weight


def formula_requires_cross_section(value: Mapping[str, Any]) -> bool:
    return bool(formula_cross_sectional_inputs(value))


def formula_expression_fields(value: Mapping[str, Any]) -> set[str]:
    """Raw fields needed by an expression, including its section score."""
    if value.get("op") == "field":
        return {str(value["name"])}
    if value.get("op") == "atr":
        return {"high", "low", "close"}
    fields: set[str] = set()
    for child in value.values():
        if isinstance(child, Mapping):
            fields.update(formula_expression_fields(child))
    return fields


def formula_cross_sectional_inputs(value: Mapping[str, Any]) -> dict[str, JsonObject]:
    """Name operations in dependency order, retaining historical rank keys."""
    inputs: dict[str, JsonObject] = {}
    for child in value.values():
        if isinstance(child, Mapping):
            inputs.update(formula_cross_sectional_inputs(child))
    if value.get("op") in _ALL_CROSS_SECTIONAL_OPERATORS:
        inputs[_cross_sectional_key(value)] = dict(value)
    return inputs


def _cross_sectional_key(value: Mapping[str, Any]) -> str:
    child = canonical_json(value["input"])
    op = _CROSS_SECTIONAL_ALIASES.get(value["op"], value["op"])
    # Persisted rank ASTs and their prepared-series callers keep their old key.
    # A mean or zscore of the same input (or rank(mean(input))) must be a distinct node.
    return child if op == _CROSS_SECTIONAL_OPERATOR else f"{op}:{child}"


def expression_lookback_rows(
    value: Mapping[str, Any],
    *,
    minimum_history_rows: int = 1,
    common_history_rows: int = 1,
) -> int | None:
    """Finite target history, or complete cold initialization when requested.

    A broadcast common series has its own contributor history. Consumers retain
    actual availability masks rather than imposing that floor again on a young
    target. Cold Dataset preparation can request the common contributor floor.
    """
    op = value["op"]
    if op in {"field", "constant"}:
        return 1
    if op in {"ema", "rsi", "atr"}:
        return None
    if "left" in value:
        left = expression_lookback_rows(
            value["left"],
            minimum_history_rows=minimum_history_rows,
            common_history_rows=common_history_rows,
        )
        right = expression_lookback_rows(
            value["right"],
            minimum_history_rows=minimum_history_rows,
            common_history_rows=common_history_rows,
        )
        if left is None or right is None:
            return None
        return max(left, right) + (op == "cross")
    child = expression_lookback_rows(
        value["input"],
        minimum_history_rows=minimum_history_rows,
        common_history_rows=common_history_rows,
    )
    if child is None:
        return None
    if op in (_CROSS_SECTIONAL_OPERATOR, "cs_rank"):
        return max(child, minimum_history_rows)
    if op in (
        _CROSS_SECTIONAL_MEAN_OPERATOR,
        _CROSS_SECTIONAL_ZSCORE_OPERATOR,
        "cs_zscore",
    ):
        # Contributor qualification belongs to the joint resolver. A target may
        # consume an already available common series before its own 60th row;
        # actual factor availability propagates through every temporal operator.
        return max(child, common_history_rows)
    if "period" in value:
        return child + int(value["period"])
    if "window" in value:
        return child + int(value["window"]) - 1
    return child


def evaluate_formula_expression(
    value: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    universe_size: int = 1,
    cross_section_values: Mapping[str, pd.Series] | None = None,
) -> pd.Series:
    """Evaluate a score using only already resolved common input series."""
    _validate_expression(value, "expression", depth=0)
    dependencies = formula_cross_sectional_inputs(value)
    if any(node["op"] == _CROSS_SECTIONAL_OPERATOR for node in dependencies.values()):
        raise FormulaValidationError(
            "nested_cross_sectional_rank_unsupported", "expression"
        )
    if dependencies and cross_section_values is None:
        raise FormulaValidationError("cross_sectional_context_required", "expression")
    return _evaluate_expression(
        value,
        frame,
        universe_size=universe_size,
        cross_section_values=cross_section_values,
    )


def cross_section_expression_available(
    value: Mapping[str, Any],
    index: pd.Index,
    available: Mapping[str, pd.Series],
    *,
    known_warmup: bool = False,
) -> pd.Series:
    """Propagate actual context gaps through the entry's causal dependencies.

    Score availability uses false for warmup; source completeness uses true for
    known prehistory. Neither turns an unknown foreign value into a buy signal.
    """
    if not formula_requires_cross_section(value):
        return pd.Series(True, index=index, dtype=bool)
    op = value["op"]
    if op in _CROSS_SECTIONAL_OPERATORS:
        result = available.get(_cross_sectional_key(value))
        if result is None:
            return pd.Series(False, index=index, dtype=bool)
        if not result.index.equals(index):
            raise FormulaValidationError("cross_sectional_index_mismatch", "evaluation")
        return result.fillna(False).astype(bool)
    if "left" in value:
        result = cross_section_expression_available(
            value["left"], index, available, known_warmup=known_warmup
        ) & cross_section_expression_available(
            value["right"], index, available, known_warmup=known_warmup
        )
        if op == "cross":
            result &= result.shift(1, fill_value=known_warmup)
        return result
    result = cross_section_expression_available(
        value["input"], index, available, known_warmup=known_warmup
    )
    if "period" in value:
        previous = result.shift(int(value["period"]), fill_value=known_warmup)
        return previous if op == "lag" else result & previous
    if "window" in value:
        window = int(value["window"])
        return (
            result.rolling(window, min_periods=1 if known_warmup else window)
            .min()
            .eq(1)
        )
    return result


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
    if op in _CROSS_SECTIONAL_ALIASES:
        canonical_op = _CROSS_SECTIONAL_ALIASES[op]
        if isinstance(value, dict):
            value["op"] = canonical_op
        op = canonical_op
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
    if op in _CROSS_SECTIONAL_OPERATORS:
        _expect_keys(value, required={"op", "input"}, path=path)
        dependencies = formula_cross_sectional_inputs(value["input"])
        if dependencies and (
            op in (_CROSS_SECTIONAL_MEAN_OPERATOR, _CROSS_SECTIONAL_ZSCORE_OPERATOR)
            or any(
                _CROSS_SECTIONAL_ALIASES.get(node["op"], node["op"])
                == _CROSS_SECTIONAL_OPERATOR
                for node in dependencies.values()
            )
        ):
            raise FormulaValidationError(
                "nested_cross_sectional_rank_unsupported", path
            )
        _validate_expression(value["input"], f"{path}.input", depth=depth + 1)
        if expression_lookback_rows(value["input"]) is None:
            raise FormulaValidationError(
                "cross_sectional_finite_history_required", path
            )
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


def _evaluate_expression(
    value: Mapping[str, Any],
    frame: pd.DataFrame,
    *,
    universe_size: int = 1,
    cross_section_values: Mapping[str, pd.Series] | None = None,
) -> pd.Series:
    op = str(value["op"])
    canonical_op = _CROSS_SECTIONAL_ALIASES.get(op, op)
    index = frame.index
    if op == "field":
        return pd.to_numeric(frame[str(value["name"])], errors="coerce")
    if op == "constant":
        return pd.Series(float(value["value"]), index=index, dtype=float)
    if canonical_op in _CROSS_SECTIONAL_OPERATORS:
        resolved = (cross_section_values or {}).get(_cross_sectional_key(value))
        if resolved is not None:
            if not resolved.index.equals(index):
                raise FormulaValidationError(
                    "cross_sectional_index_mismatch", "evaluation"
                )
            return resolved
        if universe_size == 1:
            raw = _evaluate_expression(
                value["input"],
                frame,
                universe_size=universe_size,
                cross_section_values=cross_section_values,
            )
            if canonical_op == _CROSS_SECTIONAL_OPERATOR:
                return raw.where(raw.isna(), 1.0)
            if canonical_op == _CROSS_SECTIONAL_MEAN_OPERATOR:
                return raw
            if canonical_op == _CROSS_SECTIONAL_ZSCORE_OPERATOR:
                return pd.Series(float("nan"), index=index, dtype=float)
        return pd.Series(float("nan"), index=index, dtype=float)
    if op in _PERIOD_OPERATORS:
        item = _evaluate_expression(
            value["input"],
            frame,
            universe_size=universe_size,
            cross_section_values=cross_section_values,
        )
        period = int(value["period"])
        if op == "lag":
            return item.shift(period)
        if op == "delta":
            return item.diff(period)
        if op == "roc":
            return (item.pct_change(period, fill_method=None) * 100.0).replace(
                [float("inf"), float("-inf")], float("nan")
            )
        return item.pct_change(period, fill_method=None)
    if op in _WINDOW_OPERATORS:
        window = int(value["window"])
        if op == "atr":
            return FeatureEngine.atr(frame, period=window)
        item = _evaluate_expression(
            value["input"],
            frame,
            universe_size=universe_size,
            cross_section_values=cross_section_values,
        )
        scratch = pd.DataFrame({"value": item}, index=index)
        if op == "rolling_mean":
            return FeatureEngine.sma(scratch, column="value", period=window)
        if op == "rolling_sum":
            return item.rolling(window=window).sum()
        if op == "rolling_std":
            return item.rolling(window=window).std()
        if op == "rolling_max":
            return item.rolling(window=window).max()
        if op == "rolling_min":
            return item.rolling(window=window).min()
        if op == "zscore":
            mean = item.rolling(window=window).mean()
            std = item.rolling(window=window).std()
            return (item - mean) / std.replace(0, float("nan"))
        if op == "ema":
            return FeatureEngine.ema(scratch, column="value", period=window)
        if op == "rsi":
            return FeatureEngine.rsi(scratch, column="value", period=window)
        if op == "rank":
            return FeatureEngine.rolling_percentile(item, window=window)
    if op in _BINARY_OPERATORS:
        left = _evaluate_expression(
            value["left"],
            frame,
            universe_size=universe_size,
            cross_section_values=cross_section_values,
        )
        right = _evaluate_expression(
            value["right"],
            frame,
            universe_size=universe_size,
            cross_section_values=cross_section_values,
        )
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
        return ~_evaluate_expression(
            value["input"],
            frame,
            universe_size=universe_size,
            cross_section_values=cross_section_values,
        ).fillna(False).astype(bool)
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


def evaluate_formula_universe(
    formula_ast: Mapping[str, Any],
    frames: Mapping[str, pd.DataFrame],
    *,
    universe_size: int | None = None,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series], float]:
    """Evaluate validated expressions across an entire universe of frames."""
    effective_universe_size = (
        universe_size if universe_size is not None else len(frames)
    )
    if formula_requires_cross_section(formula_ast) and len(frames) > 1:
        from server.ai_runtime.formula_portfolio import (
            FormulaCrossSectionInputs,
            prepare_formula_sessions,
        )

        members: dict[date, list[str]] = {}
        for s, f in frames.items():
            if "timestamp" in f.columns:
                for ts in pd.to_datetime(f["timestamp"]):
                    members.setdefault(ts.date(), []).append(str(s))
            elif isinstance(f.index, pd.DatetimeIndex):
                for ts in f.index:
                    members.setdefault(ts.date(), []).append(str(s))
            else:
                for d in pd.date_range("2026-01-01", periods=len(f)):
                    members.setdefault(d.date(), []).append(str(s))
        cross_section = FormulaCrossSectionInputs(
            declared_symbols=tuple(frames),
            session_memberships={d: tuple(names) for d, names in members.items()},
            minimum_history_rows=1,
            historical_snapshot=True,
        )
        prepared = prepare_formula_sessions(
            formula_ast,
            frames,
            universe_size=effective_universe_size,
            cross_section=cross_section,
        )
        entries = {}
        exits = {}
        for s in frames:
            df = prepared[s]
            orig_idx = frames[s].index
            entries[s] = pd.Series(df["entry"].values, index=orig_idx, dtype=bool)
            exits[s] = pd.Series(df["exit"].values, index=orig_idx, dtype=bool)
        normalized = validate_formula_ast(
            formula_ast, universe_size=effective_universe_size
        )
        target_weight = _evaluate_sizing(
            normalized["position_size"], universe_size=effective_universe_size
        )
        return entries, exits, target_weight

    entries: dict[str, pd.Series] = {}
    exits: dict[str, pd.Series] = {}
    weight = 0.0
    for symbol, frame in frames.items():
        entry, exit_sig, weight = evaluate_formula(
            formula_ast,
            frame,
            universe_size=effective_universe_size,
        )
        entries[str(symbol)] = entry
        exits[str(symbol)] = exit_sig
    return entries, exits, weight
