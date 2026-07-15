from __future__ import annotations

import math

import pandas as pd
import pytest

from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
    FormulaValidationError,
    evaluate_formula,
    formula_operator_catalog,
    validate_formula_ast,
)


def _formula() -> dict:
    moving_average = {
        "op": "rolling_mean",
        "input": {"op": "field", "name": "close"},
        "window": 3,
    }
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "cross",
            "left": {"op": "field", "name": "close"},
            "right": moving_average,
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": moving_average,
        },
        "position_size": {
            "op": "max_weight",
            "input": {"op": "equal_weight"},
            "value": 0.4,
        },
    }


def _binding(**overrides) -> FormulaBinding:
    values = {
        "formula_ast": _formula(),
        "universe": ("600000", "510300"),
        "dataset_snapshot_id": "sha256:dataset",
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "frequency": "1d",
        "cost_model_reference": CANONICAL_COST_MODEL_REFERENCE,
        "anti_lookahead_assumptions": (
            "Signals use the current completed daily bar and only prior history.",
        ),
        "parameter_values": {"window": 3},
        "parameter_ranges": {"window": [3, 5]},
        "initial_cash": 100_000.0,
    }
    values.update(overrides)
    return FormulaBinding(**values)


def test_formula_dsl_serialization_and_binding_fingerprint_are_deterministic() -> None:
    left = _binding()
    right = _binding(parameter_values={"window": 3})

    assert left.to_dict() == right.to_dict()
    assert left.fingerprint == right.fingerprint
    assert left.fingerprint.startswith("sha256:")
    assert formula_operator_catalog()["provider_side_tools_allowed"] is False


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda ast: ast["entry"].update(op="python"), "unknown_operator"),
        (lambda ast: ast["entry"].update(op="SELECT * FROM bars"), "unknown_operator"),
        (
            lambda ast: ast["entry"].update(op="https://example.test"),
            "unknown_operator",
        ),
        (lambda ast: ast["entry"].update(op="../../private/key"), "unknown_operator"),
        (
            lambda ast: ast.update(
                entry={
                    "op": "lag",
                    "input": {"op": "field", "name": "close"},
                    "period": -1,
                }
            ),
            "future_or_invalid_period",
        ),
        (
            lambda ast: ast.update(
                entry={
                    "op": "rolling_mean",
                    "input": {"op": "field", "name": "close"},
                    "window": 1000,
                }
            ),
            "window_out_of_bounds",
        ),
        (
            lambda ast: ast.update(entry={"op": "field", "name": "future_close"}),
            "unknown_field",
        ),
        (
            lambda ast: ast.update(entry={"op": "constant", "value": float("nan")}),
            "non_finite_number",
        ),
        (
            lambda ast: ast.update(
                entry={"op": "rank", "input": {"op": "field", "name": "close"}}
            ),
            "operator_not_canonically_supported",
        ),
    ],
)
def test_formula_dsl_rejects_unknown_future_unbounded_or_unsafe_inputs(
    mutator,
    code: str,
) -> None:
    ast = _formula()
    mutator(ast)

    with pytest.raises(FormulaValidationError) as exc_info:
        validate_formula_ast(ast, universe_size=2)

    assert exc_info.value.code == code


def test_formula_binding_rejects_ai_changes_to_cost_or_missing_anti_lookahead() -> None:
    with pytest.raises(
        FormulaValidationError, match="cost_model_not_operator_approved"
    ):
        _binding(cost_model_reference="provider.suggested.cost")

    with pytest.raises(
        FormulaValidationError, match="anti_lookahead_assumptions_required"
    ):
        _binding(anti_lookahead_assumptions=())


@pytest.mark.parametrize(
    "override",
    [
        {"formula_ast": {**_formula(), "position_size": {"op": "equal_weight"}}},
        {"universe": ("600000",)},
        {"dataset_snapshot_id": "sha256:other-dataset"},
        {"start_date": "2025-01-02"},
        {"end_date": "2025-02-01"},
        {"anti_lookahead_assumptions": ("Use lagged completed bars only.",)},
        {"parameter_values": {"window": 5}},
        {"parameter_ranges": {"window": [3, 5, 8]}},
        {"initial_cash": 200_000.0},
    ],
)
def test_every_mutable_formula_research_input_changes_binding_fingerprint(
    override,
) -> None:
    assert _binding(**override).fingerprint != _binding().fingerprint


def test_formula_evaluation_uses_only_current_and_prior_rows() -> None:
    frame = pd.DataFrame(
        {
            "open": [10, 9, 8, 12, 11],
            "high": [11, 10, 9, 13, 12],
            "low": [9, 8, 7, 11, 10],
            "close": [10, 9, 8, 12, 11],
            "volume": [1000, 1000, 1000, 1000, 1000],
        }
    )

    entry, exit_signal, weight = evaluate_formula(_formula(), frame, universe_size=2)

    assert entry.tolist() == [False, False, False, True, False]
    assert exit_signal.tolist() == [False, False, True, False, False]
    assert math.isclose(weight, 0.4)
