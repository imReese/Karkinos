"""Deterministic local parameter perturbations for Formula DSL research."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contracts import JsonObject, canonical_json
from .formula_dsl import FormulaValidationError, validate_formula_ast

_TUNABLE_AST_FIELDS = frozenset({"window", "period"})
_MAX_PARAMETERS = 4
_MAX_VALUES_PER_PARAMETER = 5
FORMULA_PARAMETER_SWEEP_MAX_VARIANTS = 9


@dataclass(frozen=True)
class FormulaParameterVariant:
    params: JsonObject
    formula_ast: JsonObject


@dataclass(frozen=True)
class _ParameterBinding:
    name: str
    selected: int
    tested_values: tuple[int, ...]
    paths: tuple[tuple[Any, ...], ...]


def build_formula_parameter_variants(
    *,
    formula_ast: Mapping[str, Any],
    parameter_values: Mapping[str, Any],
    parameter_ranges: Mapping[str, Any],
) -> list[FormulaParameterVariant]:
    """Return a bounded local stability panel around the selected formula.

    Provider-facing parameter names are descriptive metadata, not AST field
    names. Karkinos resolves each integer parameter to exact window or period
    sites in the validated Formula AST, then runs either the legacy small
    Cartesian grid or a one-at-a-time sensitivity panel capped at nine
    deterministic variants.
    """

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

    bindings = [
        _parameter_binding(
            formula_ast=formula_ast,
            name=name,
            selected=values[name],
            tested=ranges[name],
        )
        for name in sorted(values)
    ]
    _reject_overlapping_bindings(bindings)

    full_grid_size = 1
    for binding in bindings:
        full_grid_size *= len(binding.tested_values)

    if full_grid_size <= FORMULA_PARAMETER_SWEEP_MAX_VARIANTS:
        combinations = list(
            itertools.product(*(binding.tested_values for binding in bindings))
        )
        names = [binding.name for binding in bindings]
        parameter_sets = [
            dict(zip(names, combination, strict=True)) for combination in combinations
        ]
    else:
        selected_params = {binding.name: binding.selected for binding in bindings}
        parameter_sets = [selected_params]
        for binding in bindings:
            lower = [
                value for value in binding.tested_values if value < binding.selected
            ]
            upper = [
                value for value in binding.tested_values if value > binding.selected
            ]
            neighbors: list[int] = []
            if lower:
                neighbors.append(max(lower))
            if upper:
                neighbors.append(min(upper))
            for value in neighbors:
                parameter_sets.append({**selected_params, binding.name: value})

    unique_parameter_sets: list[dict[str, int]] = []
    identities: set[str] = set()
    for params in parameter_sets:
        identity = canonical_json(params)
        if identity in identities:
            continue
        identities.add(identity)
        unique_parameter_sets.append(params)
    if not 3 <= len(unique_parameter_sets) <= FORMULA_PARAMETER_SWEEP_MAX_VARIANTS:
        raise FormulaValidationError("parameter_grid_out_of_bounds", "parameter_ranges")

    variants: list[FormulaParameterVariant] = []
    for params in unique_parameter_sets:
        candidate = json.loads(canonical_json(formula_ast))
        for binding in bindings:
            replacement = params[binding.name]
            for parameter_path in binding.paths:
                _set_path(candidate, parameter_path, replacement)
        validate_formula_ast(candidate, universe_size=1)
        variants.append(FormulaParameterVariant(params=params, formula_ast=candidate))
    return variants


def _parameter_binding(
    *,
    formula_ast: Mapping[str, Any],
    name: str,
    selected: Any,
    tested: Any,
) -> _ParameterBinding:
    if not isinstance(selected, int) or isinstance(selected, bool):
        raise FormulaValidationError("parameter_range_invalid", name)
    tested_values = _normalized_tested_values(
        selected=selected,
        tested=tested,
        name=name,
    )
    preferred_field = _preferred_ast_field(name)
    candidates = {
        field: _matching_paths(formula_ast, field=field, selected=selected)
        for field in _TUNABLE_AST_FIELDS
    }
    if preferred_field is None:
        raise FormulaValidationError("parameter_field_unsupported", name)
    paths = candidates[preferred_field]
    if not paths:
        raise FormulaValidationError("parameter_not_bound_to_formula", name)
    return _ParameterBinding(
        name=name,
        selected=selected,
        tested_values=tuple(tested_values),
        paths=tuple(paths),
    )


def _normalized_tested_values(
    *,
    selected: int,
    tested: Any,
    name: str,
) -> list[int]:
    if isinstance(tested, Mapping):
        if set(tested) != {"min", "max"}:
            raise FormulaValidationError("parameter_range_invalid", name)
        low = tested.get("min")
        high = tested.get("max")
        if (
            not isinstance(low, int)
            or isinstance(low, bool)
            or not isinstance(high, int)
            or isinstance(high, bool)
            or low >= high
            or not low <= selected <= high
        ):
            raise FormulaValidationError("parameter_range_invalid", name)
        values = sorted({low, selected, high})
        if len(values) < 3 and high - low >= 2:
            midpoint = low + (high - low) // 2
            if midpoint in {low, high}:
                midpoint = low + 1
            values = sorted({*values, midpoint})
    elif isinstance(tested, list):
        if (
            not 3 <= len(tested) <= _MAX_VALUES_PER_PARAMETER
            or any(
                not isinstance(item, int) or isinstance(item, bool) for item in tested
            )
            or len(set(tested)) != len(tested)
            or selected not in tested
        ):
            raise FormulaValidationError("parameter_range_invalid", name)
        values = sorted(tested)
    else:
        raise FormulaValidationError("parameter_range_invalid", name)
    if len(values) < 3:
        raise FormulaValidationError("parameter_range_invalid", name)
    return values


def _preferred_ast_field(name: str) -> str | None:
    if name in _TUNABLE_AST_FIELDS:
        return name
    if name.endswith("_window"):
        return "window"
    if name.endswith("_period"):
        return "period"
    return None


def _matching_paths(
    value: Any,
    *,
    field: str,
    selected: int,
    path: tuple[Any, ...] = (),
) -> list[tuple[Any, ...]]:
    matches: list[tuple[Any, ...]] = []
    if isinstance(value, Mapping):
        if value.get(field) == selected:
            matches.append((*path, field))
        for key, child in value.items():
            matches.extend(
                _matching_paths(
                    child,
                    field=field,
                    selected=selected,
                    path=(*path, key),
                )
            )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            matches.extend(
                _matching_paths(
                    child,
                    field=field,
                    selected=selected,
                    path=(*path, index),
                )
            )
    return matches


def _reject_overlapping_bindings(bindings: list[_ParameterBinding]) -> None:
    owner_by_path: dict[tuple[Any, ...], str] = {}
    for binding in bindings:
        for parameter_path in binding.paths:
            owner = owner_by_path.get(parameter_path)
            if owner is not None and owner != binding.name:
                raise FormulaValidationError(
                    "parameter_binding_ambiguous",
                    binding.name,
                )
            owner_by_path[parameter_path] = binding.name


def _set_path(value: Any, path: tuple[Any, ...], replacement: int) -> None:
    cursor = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
