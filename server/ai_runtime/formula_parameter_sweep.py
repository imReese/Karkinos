"""Bounded, deterministic Formula DSL parameter variants for local research."""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import JsonObject, canonical_json
from .formula_dsl import FormulaValidationError, validate_formula_ast

_SUPPORTED_PARAMETER_FIELDS = frozenset({"window", "period"})
_MAX_PARAMETERS = 2
_MAX_VALUES_PER_PARAMETER = 5
_MAX_VARIANTS = 9


@dataclass(frozen=True)
class FormulaParameterVariant:
    params: JsonObject
    formula_ast: JsonObject


def build_formula_parameter_variants(
    *,
    formula_ast: Mapping[str, Any],
    parameter_values: Mapping[str, Any],
    parameter_ranges: Mapping[str, Any],
) -> list[FormulaParameterVariant]:
    """Return a small, fully bound Cartesian grid including the selected AST."""

    values = dict(parameter_values)
    ranges = dict(parameter_ranges)
    if not values or set(values) != set(ranges):
        raise FormulaValidationError(
            "parameter_range_binding_mismatch", "parameter_ranges"
        )
    if len(values) > _MAX_PARAMETERS:
        raise FormulaValidationError(
            "parameter_count_out_of_bounds", "parameter_values"
        )

    ordered_names = sorted(values)
    normalized_ranges: list[list[int]] = []
    for name in ordered_names:
        if name not in _SUPPORTED_PARAMETER_FIELDS:
            raise FormulaValidationError("parameter_field_unsupported", name)
        selected = values[name]
        tested = ranges[name]
        if (
            not isinstance(selected, int)
            or isinstance(selected, bool)
            or not isinstance(tested, list)
            or not 3 <= len(tested) <= _MAX_VALUES_PER_PARAMETER
            or any(
                not isinstance(item, int) or isinstance(item, bool) for item in tested
            )
            or len(set(tested)) != len(tested)
            or selected not in tested
        ):
            raise FormulaValidationError("parameter_range_invalid", name)
        normalized_ranges.append(sorted(tested))

    combinations = list(itertools.product(*normalized_ranges))
    if len(combinations) > _MAX_VARIANTS:
        raise FormulaValidationError("parameter_grid_out_of_bounds", "parameter_ranges")

    variants: list[FormulaParameterVariant] = []
    for combination in combinations:
        params = dict(zip(ordered_names, combination, strict=True))
        candidate = json.loads(canonical_json(formula_ast))
        for name in ordered_names:
            replacement_count = _replace_bound_field(
                candidate,
                field=name,
                selected=values[name],
                replacement=params[name],
            )
            if replacement_count == 0:
                raise FormulaValidationError("parameter_not_bound_to_formula", name)
        validate_formula_ast(candidate, universe_size=1)
        variants.append(FormulaParameterVariant(params=params, formula_ast=candidate))
    return variants


def _replace_bound_field(
    value: Any,
    *,
    field: str,
    selected: Any,
    replacement: Any,
) -> int:
    count = 0
    if isinstance(value, dict):
        if value.get(field) == selected:
            value[field] = replacement
            count += 1
        for child in value.values():
            count += _replace_bound_field(
                child,
                field=field,
                selected=selected,
                replacement=replacement,
            )
    elif isinstance(value, list):
        for child in value:
            count += _replace_bound_field(
                child,
                field=field,
                selected=selected,
                replacement=replacement,
            )
    return count
