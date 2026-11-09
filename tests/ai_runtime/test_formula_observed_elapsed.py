"""Actual observed time is causal, typed, and cannot turn unknowns into signals."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from server.ai_runtime.formula_dsl import (
    FORMULA_AST_CONTRACT,
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
    formula_session_input_blockers,
    prepare_formula_sessions,
)
from server.services.research.research_observation_inputs import (
    ResearchObservationInputError,
    _warmup,
)
from server.services.strategy_scan.universe.evaluation import formula_history_rows

ZONE = ZoneInfo("Asia/Shanghai")


def elapsed():
    return {"op": "observed_elapsed_seconds"}


def constant(value):
    return {"op": "constant", "value": value}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def formula(entry, exit_signal=None):
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry,
        "exit": exit_signal if exit_signal is not None else constant(0),
        "position_size": {"op": "equal_weight"},
    }


def frame(days):
    stamps = pd.DatetimeIndex([datetime(2026, 1, day, 15, tzinfo=ZONE) for day in days])
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "available_at": stamps + timedelta(minutes=1),
            "captured_at": stamps + timedelta(minutes=2),
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1_000_000.0,
        }
    )


def context(frames, **changes):
    memberships = {}
    for symbol, rows in frames.items():
        for stamp in rows["timestamp"]:
            memberships.setdefault(stamp.date(), []).append(symbol)
    values = {
        "declared_symbols": tuple(frames),
        "session_memberships": {
            day: tuple(names) for day, names in memberships.items()
        },
        "minimum_history_rows": 2,
        "historical_snapshot": True,
    }
    values.update(changes)
    return FormulaCrossSectionInputs(**values)


def prepare(ast, frames, ctx=None):
    return prepare_formula_sessions(
        ast, frames, universe_size=len(frames), cross_section=ctx or context(frames)
    )


def test_leaf_contract_and_actual_weekend_elapsed_seconds():
    rows = frame([8, 9, 12])
    result = evaluate_formula_expression(elapsed(), rows)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1:].tolist() == [86400.0, 259200.0]
    assert formula_expression_fields(elapsed()) == {"timestamp"}
    assert expression_lookback_rows(elapsed()) == 2
    assert _warmup(elapsed()) == 2
    assert formula_history_rows(formula(elapsed())) == 2
    assert "observed_elapsed_seconds" in formula_operator_catalog()["enabled_operators"]
    with pytest.raises(FormulaValidationError, match="expression_keys_mismatch"):
        evaluate_formula_expression({**elapsed(), "period": 2}, rows)
    with pytest.raises(FormulaValidationError, match="unknown_field"):
        evaluate_formula_expression({"op": "field", "name": "timestamp"}, rows)


def test_timezone_offsets_and_dst_use_instants_without_day_rounding():
    rows = pd.DataFrame(
        {"timestamp": ["2026-03-07T15:00:00-05:00", "2026-03-08T15:00:00-04:00"]}
    )
    assert evaluate_formula_expression(elapsed(), rows).iloc[-1] == 23 * 3600
    equivalent = pd.DataFrame(
        {"timestamp": ["2026-01-05T15:00:00+08:00", "2026-01-05T07:00:00Z"]}
    )
    assert evaluate_formula_expression(elapsed(), equivalent).isna().all()


@pytest.mark.parametrize("bad", [None, pd.NaT, "bad", "2026-01-06T15:00:00", 0])
def test_invalid_or_naive_endpoint_poison_both_adjacent_intervals_then_recover(bad):
    rows = pd.DataFrame(
        {
            "timestamp": [
                "2026-01-05T15:00:00+08:00",
                bad,
                "2026-01-07T15:00:00+08:00",
                "2026-01-08T15:00:00+08:00",
            ]
        }
    )
    result = evaluate_formula_expression(elapsed(), rows)
    assert result.iloc[:3].isna().all()
    assert result.iloc[3] == 86400


def test_negative_zero_and_absent_timestamp_are_not_valid_signals_after_not():
    rows = frame([7, 6, 6, 8])
    positive = binary("gt", elapsed(), constant(0))
    invert = {"op": "not", "input": positive}
    for entry in (
        invert,
        binary("or", invert, constant(1)),
        binary("multiply", invert, constant(1)),
    ):
        numeric = evaluate_formula_expression(entry, rows)
        assert numeric.iloc[:3].isna().all()
        signals, exits, _ = evaluate_formula(
            formula(entry, entry), rows, universe_size=1
        )
        assert not signals.iloc[:3].any()
        assert not exits.iloc[:3].any()
        missing, _, _ = evaluate_formula(
            formula(entry), rows.drop(columns="timestamp"), universe_size=1
        )
        assert not missing.any()


@pytest.mark.parametrize("op", ["lag", "delta", "return", "roc"])
def test_period_dependency_and_exact_prefix_replay(op):
    node = {"op": op, "input": elapsed(), "period": 2}
    rows = frame([5, 6, 8, 11, 12, 16])
    for owner in (expression_lookback_rows, _warmup):
        assert owner(node) == 4
    assert formula_history_rows(formula(node, node)) == 4
    full = evaluate_formula_expression(node, rows)
    suffix = evaluate_formula_expression(node, rows.tail(4).reset_index(drop=True))
    assert full.iloc[-1] == suffix.iloc[-1]


@pytest.mark.parametrize("op", ["rolling_mean", "rolling_sum", "rank"])
def test_window_dependency_is_w_plus_one_and_unknown_not_cannot_fill_it(op):
    invert = {"op": "not", "input": binary("gt", elapsed(), constant(86400))}
    node = {"op": op, "input": invert, "window": 3}
    rows = frame([5, 6, 8, 11, 12, 16])
    assert expression_lookback_rows(node) == _warmup(node) == 4
    assert formula_history_rows(formula(node, node)) == 4
    result = evaluate_formula_expression(node, rows)
    assert result.iloc[:3].isna().all()
    assert result.iloc[3:].notna().all()
    assert result.iloc[-1] == evaluate_formula_expression(node, rows.tail(4)).iloc[-1]


@pytest.mark.parametrize("op", ["ema", "rsi"])
def test_new_elapsed_recursive_history_is_rejected_but_old_operators_stay_valid(op):
    node = {"op": op, "input": elapsed(), "window": 3}
    with pytest.raises(FormulaValidationError, match="observed_elapsed_finite_history"):
        validate_formula_ast(formula(node), universe_size=1)
    with pytest.raises(FormulaValidationError, match="observed_elapsed_finite_history"):
        evaluate_formula_expression(node, frame([5, 6, 7]))
    with pytest.raises(ResearchObservationInputError, match="finite_history"):
        _warmup(node)
    with pytest.raises(ValueError, match="observed_elapsed_finite_history"):
        formula_history_rows(formula(node))
    legacy = {"op": op, "input": {"op": "field", "name": "close"}, "window": 3}
    assert validate_formula_ast(formula(legacy), universe_size=1)["entry"] == legacy
    evaluate_formula_expression(legacy, frame([5, 6, 7]))


@pytest.mark.parametrize("op", ["rolling_std", "zscore"])
def test_new_elapsed_variance_combinations_reject_inexact_prefix_boundaries(op):
    # The original failing std prefix fixture is retained in attempt1 artifacts.
    # This is an unsupported new combination, not a tolerance-based comparison.
    inverted = {"op": "not", "input": binary("gt", elapsed(), constant(86400))}
    node = {"op": op, "input": inverted, "window": 3}
    rows = frame([5, 6, 8, 11, 12, 16])
    with pytest.raises(
        FormulaValidationError, match="observed_elapsed_window_unsupported"
    ):
        validate_formula_ast(formula(node), universe_size=1)
    with pytest.raises(
        FormulaValidationError, match="observed_elapsed_window_unsupported"
    ):
        evaluate_formula_expression(node, rows)
    legacy = {"op": op, "input": {"op": "field", "name": "close"}, "window": 3}
    assert validate_formula_ast(formula(legacy), universe_size=1)["entry"] == legacy
    evaluate_formula_expression(legacy, rows)
    with pytest.raises(
        FormulaValidationError, match="observed_elapsed_window_unsupported"
    ):
        validate_formula_ast(formula(binary("add", elapsed(), legacy)), universe_size=1)


def test_complete_dated_pool_including_nonbuy_member_changes_common_elapsed():
    frames = {"600001": frame([5, 7, 9]), "300001": frame([5, 6, 9])}
    common = {"op": "cross_sectional_mean", "input": elapsed()}
    ast = formula(binary("gt", common, constant(2 * 86400)))
    result = prepare(ast, frames)
    assert result["600001"]["entry"].iloc[-1]  # mean of two and three actual days
    assert formula_session_input_blockers(result) == ()
    only_main = {"600001": frames["600001"]}
    assert not prepare(ast, only_main)["600001"]["entry"].iloc[-1]


def test_first_undefined_interval_cannot_be_not_ranked_or_contribute_to_common():
    frames = {"600001": frame([5, 6, 7]), "300001": frame([7])}
    inverted = {"op": "not", "input": binary("gt", elapsed(), constant(0))}
    mean = {"op": "cross_sectional_mean", "input": inverted}
    ctx = context(frames, minimum_history_rows=1)
    result = prepare(formula(binary("gt", mean, constant(0))), frames, ctx)
    assert not result["600001"]["entry"].any()
    assert not result["300001"]["entry"].any()
    assert formula_session_input_blockers(result) == ()  # known prehistory only
    rank = {"op": "cross_sectional_rank", "input": inverted}
    ranked = prepare(formula(binary("equal", rank, constant(1))), frames, ctx)
    assert ranked["600001"]["entry"].iloc[-1]
    assert not ranked["300001"]["entry"].iloc[-1]


@pytest.mark.parametrize("clock", ["available_at", "captured_at"])
def test_previous_endpoint_clock_blocks_common_and_local_entry_but_not_local_exit(
    clock,
):
    frames = {"600001": frame([5, 6, 7]), "300001": frame([5, 6, 7])}
    cutoff = datetime(2026, 1, 7, 16, tzinfo=ZONE)
    frames["300001"].loc[1, clock] = cutoff + timedelta(days=1)
    common = {"op": "cross_sectional_mean", "input": elapsed()}
    ast = formula(binary("gt", common, constant(0)), constant(1))
    ctx = context(frames, historical_snapshot=False, as_of=cutoff)
    result = prepare(ast, frames, ctx)
    assert all(not rows["entry"].iloc[-1] for rows in result.values())
    assert all(rows["exit"].iloc[-1] for rows in result.values())
    assert formula_session_input_blockers(result) == (
        "cross_sectional_inputs_unavailable",
    )


def test_missing_member_is_blocker_and_duplicate_session_remains_rejected():
    frames = {"600001": frame([5, 6, 7]), "300001": frame([5, 6, 7])}
    ctx = context(frames)
    common = {"op": "cross_sectional_mean", "input": elapsed()}
    ast = formula(binary("gt", common, constant(0)))
    missing = {**frames, "300001": frames["300001"].iloc[:-1]}
    assert formula_session_input_blockers(prepare(ast, missing, ctx)) == (
        "cross_sectional_inputs_unavailable",
    )
    frames["300001"] = frame([5, 6, 6])
    with pytest.raises(ValueError, match="formula_cross_section_duplicate_session"):
        prepare(ast, frames, ctx)


def test_future_tail_and_member_iteration_order_cannot_change_existing_signals():
    initial = {"600001": frame([5, 7, 9]), "300001": frame([5, 6, 9])}
    extended = {"300001": frame([5, 6, 9, 16]), "600001": frame([5, 7, 9, 12])}
    common = {"op": "cross_sectional_mean", "input": elapsed()}
    ast = formula(binary("gt", elapsed(), common))
    before, after = prepare(ast, initial), prepare(ast, extended)
    for symbol in initial:
        pd.testing.assert_frame_equal(before[symbol], after[symbol].iloc[:3])
