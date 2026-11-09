"""Finite floor arithmetic, exact grid endpoints, and legacy formula replay."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from itertools import product
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from server.ai_runtime.formula_dsl import (
    CANONICAL_COST_MODEL_REFERENCE,
    FORMULA_AST_CONTRACT,
    FormulaBinding,
    FormulaValidationError,
    evaluate_formula,
    evaluate_formula_expression,
    expression_lookback_rows,
    formula_expression_fields,
    formula_operator_catalog,
    validate_formula_ast,
)
from server.ai_runtime.formula_portfolio import (
    FormulaCrossSectionInputs,
    prepare_formula_sessions,
)
from server.ai_runtime.strategy_research_model_contract import (
    hypothesis_output_contract,
    normalize_hypothesis_payload,
)
from server.services.research.research_observation_inputs import _warmup
from server.services.strategy_scan.universe.evaluation import formula_history_rows


def field(name="close"):
    return {"op": "field", "name": name}


def const(value):
    return {"op": "constant", "value": value}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def floor(value):
    return {"op": "floor", "input": value}


def formula(entry, exit_signal=None):
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry,
        "exit": exit_signal if exit_signal is not None else const(0),
        "position_size": {"op": "equal_weight"},
    }


def grid_count(offset):
    def ceiling(value):
        return binary(
            "multiply", const(-1), floor(binary("multiply", const(-1), value))
        )

    return binary(
        "subtract",
        ceiling(binary("subtract", field("close"), const(offset))),
        ceiling(binary("subtract", field("open"), const(offset))),
    )


def test_floor_is_mathematical_floor_and_preserves_undefined_numeric_inputs():
    values = [
        -3.75,
        -3,
        -0.25,
        -0.0,
        0,
        0.25,
        3,
        3.75,
        "4.75",
        None,
        "invalid",
        float("nan"),
        float("inf"),
        -float("inf"),
    ]
    rows = pd.DataFrame({"close": values}, index=range(100, 100 + len(values)))
    actual = evaluate_formula_expression(floor(field()), rows)
    expected = pd.Series(
        [-4, -3, -1, 0, 0, 0, 3, 3, 4] + [float("nan")] * 5,
        index=rows.index,
        name="close",
        dtype=float,
    )
    pd.testing.assert_series_equal(actual, expected)


def test_floor_does_not_snap_values_on_either_side_of_an_integer():
    rows = pd.DataFrame(
        {
            "close": [
                math.nextafter(10.0, -math.inf),
                10.0,
                math.nextafter(10.0, math.inf),
                math.nextafter(-10.0, -math.inf),
                -10.0,
                math.nextafter(-10.0, math.inf),
            ]
        }
    )
    assert evaluate_formula_expression(floor(field()), rows).tolist() == [
        9,
        10,
        10,
        -11,
        -10,
        -10,
    ]


@pytest.mark.parametrize("offset", [0, 0.5])
def test_grid_crossings_use_start_included_end_excluded_and_signed_reverse(offset):
    # Quarter-unit synthetic values include exact whole/half grids, stationary
    # paths, negative prices, strict interior endpoints, and both directions.
    endpoints = [value / 4 for value in range(-12, 13)]
    paths = list(product(endpoints, repeat=2))
    rows = pd.DataFrame(paths, columns=["open", "close"])
    actual = evaluate_formula_expression(grid_count(offset), rows).tolist()
    expected = []
    for start, end in paths:
        if end >= start:
            expected.append(sum(start <= k + offset < end for k in range(-5, 6)))
        else:
            expected.append(-sum(end <= k + offset < start for k in range(-5, 6)))
    assert actual == expected


def test_grid_missingness_survives_arithmetic_and_requires_explicit_boolean_guard():
    expression = grid_count(0.5)
    rows = pd.DataFrame(
        {
            "open": [10.0, 10.0, float("inf"), 10.0, 10.0],
            "close": [10.75, 10.25, 10.75, float("nan"), "invalid"],
        }
    )
    actual = evaluate_formula_expression(expression, rows)
    assert actual.iloc[:2].tolist() == [1.0, 0.0]
    assert actual.iloc[2:].isna().all()
    zero_crossing = {"op": "not", "input": binary("gt", expression, const(0))}
    # NOT keeps its legacy Boolean semantics; the candidate has to guard the
    # numeric quantity explicitly, since NaN > 0 is False before NOT.
    legacy, _, _ = evaluate_formula(formula(zero_crossing), rows, universe_size=1)
    assert legacy.tolist() == [False, True, True, True, True]
    defined = binary("equal", expression, expression)
    guarded, _, _ = evaluate_formula(
        formula(binary("and", defined, zero_crossing)), rows, universe_size=1
    )
    assert guarded.tolist() == [False, True, False, False, False]


@pytest.mark.parametrize("window", [20, 40, 60])
@pytest.mark.parametrize("outer_lag", [0, 1])
def test_floor_nested_lags_and_rolling_sum_have_exact_cold_history(window, outer_lag):
    expression = {
        "op": "rolling_sum",
        "window": window,
        "input": floor({"op": "lag", "input": field(), "period": 2}),
    }
    if outer_lag:
        expression = {"op": "lag", "input": expression, "period": outer_lag}
    expected_rows = window + 2 + outer_lag
    ast = formula(binary("gt", expression, const(0)))
    assert expression_lookback_rows(expression) == expected_rows
    assert _warmup(expression) == expected_rows
    assert formula_history_rows(ast) == expected_rows
    assert formula_expression_fields(expression) == frozenset({"close"})

    rows = pd.DataFrame(
        {"close": [value / 4 for value in range(1, expected_rows + 15)]}
    )
    full = evaluate_formula_expression(expression, rows)
    assert full.iloc[: expected_rows - 1].isna().all()
    assert full.iloc[expected_rows - 1 :].notna().all()
    cold = evaluate_formula_expression(expression, rows.iloc[-expected_rows:])
    assert cold.iloc[-1] == full.iloc[-1]
    short = evaluate_formula_expression(expression, rows.iloc[-expected_rows + 1 :])
    assert short.isna().all()
    prefix = evaluate_formula_expression(expression, rows.iloc[:-4])
    pd.testing.assert_series_equal(prefix, full.iloc[:-4])
    poisoned = rows.copy()
    poisoned.loc[poisoned.index[-4:], "close"] = -1e9
    pd.testing.assert_series_equal(
        evaluate_formula_expression(expression, poisoned).iloc[:-4], prefix
    )


def test_floor_internal_missing_values_poison_only_dependent_windows_then_recover():
    expression = {
        "op": "lag",
        "period": 1,
        "input": {
            "op": "rolling_sum",
            "window": 3,
            "input": floor({"op": "lag", "period": 2, "input": field()}),
        },
    }
    values = [value + 0.75 for value in range(24)]
    values[6], values[10], values[14] = math.nan, math.inf, -math.inf
    rows = pd.DataFrame({"close": values})
    actual = evaluate_formula_expression(expression, rows)
    # At t, the only dependent source rows are t-5, t-4 and t-3. Enumerate
    # those rows directly, independently of the DSL's lag/window machinery.
    expected = []
    for end in range(len(values)):
        source = values[end - 5 : end - 2] if end >= 5 else []
        expected.append(
            float(sum(math.floor(value) for value in source))
            if len(source) == 3 and all(math.isfinite(value) for value in source)
            else math.nan
        )
    pd.testing.assert_series_equal(
        actual, pd.Series(expected, index=rows.index, name="close")
    )
    assert actual.index[actual.isna()].tolist() == [
        0,
        1,
        2,
        3,
        4,
        9,
        10,
        11,
        13,
        14,
        15,
        17,
        18,
        19,
    ]
    assert actual.iloc[[12, 16, 20]].tolist() == [24.0, 36.0, 48.0]
    assert expression_lookback_rows(expression) == 6
    for end in range(5, len(rows)):
        cold = evaluate_formula_expression(expression, rows.iloc[end - 5 : end + 1])
        if pd.isna(actual.iloc[end]):
            assert pd.isna(cold.iloc[-1])
        else:
            assert cold.iloc[-1] == actual.iloc[end]


@pytest.mark.parametrize(
    "bad",
    [
        {"op": "floor"},
        {"op": "floor", "input": field(), "window": 2},
        {"op": "floor", "input": {"op": "field", "name": "future_close"}},
    ],
)
def test_floor_rejects_malformed_or_future_inputs(bad):
    with pytest.raises(FormulaValidationError):
        validate_formula_ast(formula(bad), universe_size=1)


@pytest.mark.parametrize("op", ["ema", "rsi", "atr"])
@pytest.mark.parametrize("placement", ["child", "sibling"])
def test_floor_rejects_unbounded_history_in_children_or_siblings(op, placement):
    unbounded = {"op": op, "window": 3}
    if op != "atr":
        unbounded["input"] = field()
    expression = (
        floor(unbounded)
        if placement == "child"
        else binary("add", floor(field()), unbounded)
    )
    with pytest.raises(FormulaValidationError, match="floor_finite_history_required"):
        validate_formula_ast(formula(expression), universe_size=1)
    with pytest.raises(FormulaValidationError, match="floor_finite_history_required"):
        evaluate_formula_expression(expression, pd.DataFrame({"close": [1.0]}))
    with pytest.raises(ValueError, match="floor_finite_history_required"):
        formula_history_rows(formula(expression))


def test_plain_legacy_ema_keeps_its_existing_validation_and_history_behavior():
    expression = {"op": "ema", "input": field(), "window": 3}
    assert (
        validate_formula_ast(formula(expression), universe_size=1)["entry"]
        == expression
    )
    assert expression_lookback_rows(expression) is None
    assert formula_history_rows(formula(expression)) == 3
    assert _warmup(expression) == 1


def test_floor_is_resolved_inside_common_mean_without_erasing_cross_section_dependency():
    stamps = pd.date_range(
        datetime(2026, 1, 5, 15, tzinfo=ZoneInfo("Asia/Shanghai")), periods=2
    )
    frames = {}
    for symbol, close in {"600001": [10.9, 11.9], "300001": [12.1, 13.1]}.items():
        frames[symbol] = pd.DataFrame(
            {
                "timestamp": stamps,
                "available_at": stamps + timedelta(minutes=1),
                "captured_at": stamps + timedelta(minutes=2),
                "open": close,
                "high": [value + 1 for value in close],
                "low": [value - 1 for value in close],
                "close": close,
                "volume": 1000.0,
            }
        )
    mean = {"op": "cross_sectional_mean", "input": floor(field())}
    expression = binary("equal", floor(mean), const(11))
    context = FormulaCrossSectionInputs(
        declared_symbols=tuple(frames),
        session_memberships={stamp.date(): tuple(frames) for stamp in stamps},
        minimum_history_rows=1,
        historical_snapshot=True,
    )
    prepared = prepare_formula_sessions(
        formula(expression), frames, universe_size=2, cross_section=context
    )
    assert all(rows["entry"].tolist() == [True, False] for rows in prepared.values())
    assert _warmup(expression, minimum_history_rows=5) == 5


def legacy_formula():
    average = {"op": "rolling_mean", "input": field(), "window": 3}
    ast = formula(binary("cross", field(), average), binary("lt", field(), average))
    ast["position_size"] = {
        "op": "max_weight",
        "input": {"op": "equal_weight"},
        "value": 0.4,
    }
    return ast


def test_old_ast_evaluation_history_and_persisted_binding_are_unchanged():
    ast = legacy_formula()
    rows = pd.DataFrame({"close": [10, 9, 8, 12, 11]})
    entry, exit_signal, weight = evaluate_formula(ast, rows, universe_size=2)
    assert entry.tolist() == [False, False, False, True, False]
    assert exit_signal.tolist() == [False, False, True, False, False]
    assert weight == 0.4
    assert formula_history_rows(ast) == 4
    assert _warmup(ast["entry"]) == 4
    binding = FormulaBinding(
        formula_ast=ast,
        universe=("600000", "510300"),
        dataset_snapshot_id="sha256:dataset",
        start_date="2025-01-01",
        end_date="2025-01-31",
        frequency="1d",
        cost_model_reference=CANONICAL_COST_MODEL_REFERENCE,
        anti_lookahead_assumptions=(
            "Signals use the current completed daily bar and only prior history.",
        ),
        parameter_values={"window": 3},
        parameter_ranges={"window": [3, 5]},
        initial_cash=100_000.0,
    )
    assert (
        binding.fingerprint
        == "sha256:9b3754cb10cd8ba007bd2a5d7d6b21d1df0935a2df0eeafd32e6633cfaf1c23b"
    )


def test_model_contract_and_local_normalization_preserve_the_exact_floor_ast():
    catalog = formula_operator_catalog()
    contract = hypothesis_output_contract(citation_catalog={})
    assert "floor" in catalog["enabled_operators"]
    assert set(catalog["expression_shapes"]["floor"]) == {"op", "input"}
    assert contract["formula_ast_node_exact_keys"]["floor"] == ["op", "input"]
    ast = formula(binary("gt", floor(field()), const(10)))
    draft = {
        "economic_hypothesis": "Synthetic boundary fixture only.",
        "selected_universe": ["600001"],
        "dataset_snapshot_id": "sha256:synthetic",
        "test_window": {"start_date": "2026-01-05", "end_date": "2026-01-06"},
        "frequency": "1d",
        "formula_ast": ast,
        "parameter_values": {},
        "parameter_ranges": {},
        "entry_conditions": "floor(close) > 10",
        "exit_conditions": "none",
        "position_sizing_hypothesis": "equal weight",
        "portfolio_constraints": {},
        "cost_model_reference": CANONICAL_COST_MODEL_REFERENCE,
        "required_evidence": ["synthetic"],
        "anti_lookahead_assumptions": ["completed rows only"],
        "proposed_deterministic_tests": ["integer boundaries"],
        "sample_split_plan": "synthetic only",
        "failure_conditions": ["undefined input"],
        "limitations": ["no financial claim"],
        "risk_impact": "no authority",
        "citations": [],
    }
    normalized = normalize_hypothesis_payload(
        {"drafts": [draft]}, expected_draft_count=1
    )
    assert normalized["drafts"][0]["formula_ast"] == ast
    assert (
        validate_formula_ast(normalized["drafts"][0]["formula_ast"], universe_size=1)
        == ast
    )
    assert catalog["provider_side_tools_allowed"] is False
