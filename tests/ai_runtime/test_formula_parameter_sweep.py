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
