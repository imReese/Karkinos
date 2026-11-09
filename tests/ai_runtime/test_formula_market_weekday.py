"""Shanghai weekday has one observed endpoint, separate from elapsed's two."""

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


def weekday():
    return {"op": "market_weekday_shanghai"}


def elapsed():
    return {"op": "observed_elapsed_seconds"}


def const(value):
    return {"op": "constant", "value": value}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def formula(entry, exit_signal=None):
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry,
        "exit": exit_signal if exit_signal is not None else const(0),
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
        "minimum_history_rows": 1,
        "historical_snapshot": True,
    }
    values.update(changes)
    return FormulaCrossSectionInputs(**values)


def prepare(ast, frames, ctx=None):
    return prepare_formula_sessions(
        ast, frames, universe_size=len(frames), cross_section=ctx or context(frames)
    )


def test_monday_zero_is_defined_on_first_real_row_and_leaf_contract_is_strict():
    rows = frame([5])
    assert evaluate_formula_expression(weekday(), rows).tolist() == [0]
    monday = binary("equal", weekday(), const(0))
    entry, exits, _ = evaluate_formula(formula(monday, monday), rows, universe_size=1)
    assert entry.tolist() == exits.tolist() == [True]
    assert expression_lookback_rows(weekday()) == _warmup(weekday()) == 1
    assert formula_history_rows(formula(weekday())) == 1
    assert formula_expression_fields(weekday()) == {"timestamp"}
    assert "market_weekday_shanghai" in formula_operator_catalog()["enabled_operators"]
    with pytest.raises(FormulaValidationError, match="expression_keys_mismatch"):
        evaluate_formula_expression({**weekday(), "timezone": "UTC"}, rows)


def test_shanghai_midnight_equivalent_instants_and_weekend_values():
    rows = pd.DataFrame(
        {
            "timestamp": [
                "2026-01-04T15:59:59Z",
                "2026-01-04T16:00:00Z",
                "2026-01-05T00:00:00+08:00",
                "2026-01-04T11:00:00-05:00",
                "2026-01-03T07:00:00Z",
            ]
        }
    )
    assert evaluate_formula_expression(weekday(), rows).tolist() == [6, 0, 0, 0, 5]


@pytest.mark.parametrize("bad", [None, pd.NaT, "bad", "2026-01-06T15:00:00", 0])
def test_only_current_endpoint_controls_weekday_but_elapsed_needs_previous(bad):
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
    day = evaluate_formula_expression(weekday(), rows)
    gap = evaluate_formula_expression(elapsed(), rows)
    assert day.iloc[[0, 2, 3]].tolist() == [0, 2, 3]
    assert pd.isna(day.iloc[1])
    assert gap.iloc[:3].isna().all() and gap.iloc[3] == 86400
    both = binary("add", weekday(), elapsed())
    assert evaluate_formula_expression(both, rows).iloc[:3].isna().all()


def test_unknown_weekday_cannot_become_numeric_score_or_nonjoint_entry_exit():
    rows = pd.DataFrame(
        {"timestamp": [None, "2026-01-05T15:00:00", "2026-01-05T15:00:00+08:00"]}
    )
    inverted = {"op": "not", "input": binary("gt", weekday(), const(6))}
    nodes = [
        inverted,
        binary("or", inverted, const(1)),
        binary("multiply", inverted, const(1)),
    ]
    for node in nodes:
        score = evaluate_formula_expression(node, rows)
        assert score.iloc[:2].isna().all() and score.iloc[2] == 1
        entry, exits, _ = evaluate_formula(formula(node, node), rows, universe_size=1)
        assert entry.tolist() == exits.tolist() == [False, False, True]
        missing, missing_exit, _ = evaluate_formula(
            formula(node, node), rows.drop(columns="timestamp"), universe_size=1
        )
        assert not missing.any() and not missing_exit.any()


def test_weekday_and_elapsed_masks_remain_independent_under_or():
    rows = frame([5, 6])
    weekday_true = {"op": "not", "input": binary("gt", weekday(), const(6))}
    elapsed_true = binary("gt", elapsed(), const(0))
    first, _, _ = evaluate_formula(formula(weekday_true), rows, universe_size=1)
    mixed, _, _ = evaluate_formula(
        formula(binary("or", weekday_true, elapsed_true)), rows, universe_size=1
    )
    assert first.tolist() == [True, True]
    assert mixed.tolist() == [False, True]


def test_lag_is_observed_rows_and_rolling_sum_needs_w_rows_not_w_plus_one():
    rows = frame([2, 5, 6, 8, 9])
    lag = {"op": "lag", "input": weekday(), "period": 2}
    assert expression_lookback_rows(lag) == _warmup(lag) == 3
    assert formula_history_rows(formula(lag, lag)) == 3
    result = evaluate_formula_expression(lag, rows)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2:].tolist() == [4, 0, 1]  # Friday, Monday, Tuesday
    monday = binary("equal", weekday(), const(0))
    count = {"op": "rolling_sum", "input": monday, "window": 3}
    assert expression_lookback_rows(count) == _warmup(count) == 3
    assert formula_history_rows(formula(count, count)) == 3
    actual = evaluate_formula_expression(count, rows)
    assert actual.iloc[:2].isna().all()
    assert actual.iloc[2:].tolist() == [1, 1, 0]
    assert actual.iloc[-1] == evaluate_formula_expression(count, rows.tail(3)).iloc[-1]


def test_missing_weekday_propagates_across_complete_rolling_window():
    rows = pd.DataFrame(
        {
            "timestamp": [
                "2026-01-05T15:00:00+08:00",
                None,
                "2026-01-07T15:00:00+08:00",
                "2026-01-08T15:00:00+08:00",
                "2026-01-09T15:00:00+08:00",
            ]
        }
    )
    inverted = {"op": "not", "input": binary("gt", weekday(), const(6))}
    count = {"op": "rolling_sum", "input": inverted, "window": 3}
    result = evaluate_formula_expression(count, rows)
    assert result.iloc[:4].isna().all() and result.iloc[4] == 3


@pytest.mark.parametrize("op", ["ema", "rsi", "rolling_std", "zscore"])
def test_weekday_restrictions_are_explicit_and_mixed_elapsed_errors_stay_first(op):
    node = {"op": op, "input": weekday(), "window": 3}
    code = "finite_history_required" if op in {"ema", "rsi"} else "window_unsupported"
    with pytest.raises(FormulaValidationError, match="market_weekday_" + code):
        validate_formula_ast(formula(node), universe_size=1)
    with pytest.raises(FormulaValidationError, match="market_weekday_" + code):
        evaluate_formula_expression(node, frame([5, 6, 7]))
    if op in {"ema", "rsi"}:
        with pytest.raises(
            ResearchObservationInputError, match="market_weekday_finite_history"
        ):
            _warmup(node)
        with pytest.raises(ValueError, match="market_weekday_finite_history"):
            formula_history_rows(formula(node))
    mixed = binary("add", node, elapsed())
    with pytest.raises(FormulaValidationError, match="observed_elapsed_" + code):
        validate_formula_ast(formula(mixed), universe_size=1)
    with pytest.raises(FormulaValidationError, match="observed_elapsed_" + code):
        evaluate_formula_expression(mixed, frame([5, 6, 7]))
    legacy = {"op": op, "input": {"op": "field", "name": "close"}, "window": 3}
    assert validate_formula_ast(formula(legacy), universe_size=1)["entry"] == legacy


def test_common_weekday_is_available_to_a_first_row_target_without_elapsed_history():
    frames = {"600001": frame([2, 5]), "300001": frame([5])}
    mean = {"op": "cross_sectional_mean", "input": weekday()}
    result = prepare(formula(binary("equal", mean, const(0))), frames)
    assert all(rows["entry"].iloc[-1] for rows in result.values())
    assert formula_session_input_blockers(result) == ()


@pytest.mark.parametrize("clock", ["available_at", "captured_at"])
def test_source_clock_dependency_is_one_endpoint_for_weekday_two_for_elapsed(clock):
    frames = {"600001": frame([5, 6]), "300001": frame([5, 6])}
    cutoff = datetime(2026, 1, 6, 16, tzinfo=ZONE)
    frames["300001"].loc[0, clock] = cutoff + timedelta(days=1)
    ctx = context(frames, historical_snapshot=False, as_of=cutoff)
    day = cutoff.date()
    common_day = {"op": "cross_sectional_mean", "input": weekday()}
    current = prepare(formula(binary("gte", common_day, const(0))), frames, ctx)
    assert all(rows["entry"].iloc[-1] for rows in current.values())
    assert formula_session_input_blockers(current, day) == ()
    common_elapsed = {"op": "cross_sectional_mean", "input": elapsed()}
    prior = prepare(formula(binary("gt", common_elapsed, const(0))), frames, ctx)
    assert all(not rows["entry"].iloc[-1] for rows in prior.values())
    assert formula_session_input_blockers(prior, day) == (
        "cross_sectional_inputs_unavailable",
    )
    frames["300001"].loc[1, clock] = cutoff + timedelta(days=1)
    blocked = prepare(
        formula(binary("gte", common_day, const(0)), const(1)), frames, ctx
    )
    assert all(
        not rows["entry"].iloc[-1] and rows["exit"].iloc[-1]
        for rows in blocked.values()
    )


def test_unknown_nonbuy_member_cannot_be_not_contributor_or_silently_removed():
    frames = {"600001": frame([5, 6]), "300001": frame([5, 6])}
    inverted = {"op": "not", "input": binary("gt", weekday(), const(6))}
    mean = {"op": "cross_sectional_mean", "input": inverted}
    ast = formula(binary("equal", mean, const(1)))
    ctx = context(frames)
    frames["300001"]["timestamp"] = frames["300001"]["timestamp"].dt.tz_localize(None)
    blocked = prepare(ast, frames, ctx)
    assert all(not rows["entry"].any() for rows in blocked.values())
    assert formula_session_input_blockers(blocked) == (
        "cross_sectional_inputs_unavailable",
    )
    missing = {"600001": frame([5, 6]), "300001": frame([5])}
    assert formula_session_input_blockers(prepare(ast, missing, ctx)) == (
        "cross_sectional_inputs_unavailable",
    )


def test_future_prefix_member_order_and_original_minimum_history_are_preserved():
    original = {"600001": frame([2, 5, 6]), "300001": frame([2, 5, 6])}
    future = {"300001": frame([2, 5, 6, 9]), "600001": frame([2, 5, 6, 8])}
    mean = {"op": "cross_sectional_mean", "input": weekday()}
    ast = formula(binary("gte", mean, const(0)))
    before, after = prepare(ast, original), prepare(ast, future)
    for symbol in original:
        pd.testing.assert_frame_equal(before[symbol], after[symbol].iloc[:3])
    cold = prepare(ast, original, context(original, minimum_history_rows=3))
    assert all(rows["entry"].tolist() == [False, False, True] for rows in cold.values())


def test_duplicate_session_stays_rejected_even_when_weekday_matches():
    frames = {"600001": frame([5, 5])}
    mean = {"op": "cross_sectional_mean", "input": weekday()}
    with pytest.raises(ValueError, match="formula_cross_section_duplicate_session"):
        prepare(formula(binary("equal", mean, const(0))), frames)
