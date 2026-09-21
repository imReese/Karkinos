from __future__ import annotations

import pytest

from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT, FormulaValidationError
from server.ai_runtime.formula_parameter_sweep import build_formula_parameter_variants


def _formula() -> dict:
    moving_average = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "gt",
            "left": {"op": "field", "name": "close"},
            "right": moving_average,
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": moving_average,
        },
        "position_size": {"op": "equal_weight"},
    }


def test_parameter_variants_are_bounded_and_replace_all_bound_nodes() -> None:
    variants = build_formula_parameter_variants(
        formula_ast=_formula(),
        parameter_values={"window": 3},
        parameter_ranges={"window": [2, 3, 5]},
    )

    assert [item.params for item in variants] == [
        {"window": 2},
        {"window": 3},
        {"window": 5},
    ]
    for item in variants:
        assert item.formula_ast["entry"]["right"]["window"] == item.params["window"]
        assert item.formula_ast["exit"]["right"]["window"] == item.params["window"]


@pytest.mark.parametrize(
    ("values", "ranges", "code"),
    [
        ({"window": 3}, {"window": [3, 5]}, "parameter_range_invalid"),
        ({"window": 3}, {"other": [2, 3, 5]}, "parameter_range_binding_mismatch"),
        ({"threshold": 3}, {"threshold": [2, 3, 5]}, "parameter_field_unsupported"),
    ],
)
def test_parameter_variants_reject_unbound_or_insufficient_grids(
    values: dict, ranges: dict, code: str
) -> None:
    with pytest.raises(FormulaValidationError) as exc_info:
        build_formula_parameter_variants(
            formula_ast=_formula(),
            parameter_values=values,
            parameter_ranges=ranges,
        )

    assert exc_info.value.code == code


def test_parameter_variants_support_semantic_names_and_min_max_ranges() -> None:
    formula = {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "and",
            "left": {
                "op": "gt",
                "left": {"op": "field", "name": "close"},
                "right": {
                    "op": "rolling_mean",
                    "input": {"op": "field", "name": "close"},
                    "window": 20,
                },
            },
            "right": {
                "op": "lt",
                "left": {
                    "op": "return",
                    "input": {"op": "field", "name": "close"},
                    "period": 1,
                },
                "right": {"op": "constant", "value": 0},
            },
        },
        "exit": {
            "op": "gte",
            "left": {
                "op": "rolling_std",
                "input": {"op": "field", "name": "close"},
                "window": 10,
            },
            "right": {
                "op": "rolling_mean",
                "input": {
                    "op": "rolling_std",
                    "input": {"op": "field", "name": "close"},
                    "window": 10,
                },
                "window": 60,
            },
        },
        "position_size": {"op": "equal_weight"},
    }

    variants = build_formula_parameter_variants(
        formula_ast=formula,
        parameter_values={
            "long_window": 20,
            "reversal_period": 1,
            "volatility_mean_window": 60,
            "volatility_window": 10,
        },
        parameter_ranges={
            "long_window": {"min": 10, "max": 60},
            "reversal_period": {"min": 1, "max": 3},
            "volatility_mean_window": {"min": 30, "max": 120},
            "volatility_window": {"min": 5, "max": 20},
        },
    )

    assert len(variants) == 8
    selected = next(
        item
        for item in variants
        if item.params
        == {
            "long_window": 20,
            "reversal_period": 1,
            "volatility_mean_window": 60,
            "volatility_window": 10,
        }
    )
    assert selected.formula_ast == formula
    long_variant = next(item for item in variants if item.params["long_window"] == 10)
    assert long_variant.formula_ast["entry"]["left"]["right"]["window"] == 10
    volatility_variant = next(
        item for item in variants if item.params["volatility_window"] == 5
    )
    assert volatility_variant.formula_ast["exit"]["left"]["window"] == 5
    assert volatility_variant.formula_ast["exit"]["right"]["input"]["window"] == 5
