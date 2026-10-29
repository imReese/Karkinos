"""Complete, causal cross-sectional forecasts with independent exit maintenance."""

import math
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from core.types import Symbol
from domain.instrument import make_research_stock
from server.ai_runtime.formula_dsl import (
    FORMULA_AST_CONTRACT,
    FormulaValidationError,
    evaluate_formula,
    evaluate_formula_expression,
    expression_lookback_rows,
    validate_formula_ast,
)
from server.ai_runtime.formula_portfolio import (
    FormulaCrossSectionInputs,
    formula_session_input_blockers,
    formula_session_targets,
    prepare_formula_sessions,
)

ZONE = ZoneInfo("Asia/Shanghai")


def field(name="close"):
    return {"op": "field", "name": name}


def const(value):
    return {"op": "constant", "value": value}


def rank(value=None):
    return {"op": "cross_sectional_rank", "input": value or field()}


def common_mean(value=None):
    return {"op": "cross_sectional_mean", "input": value or field()}


def formula(entry=None, *, score=None):
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry or {"op": "equal", "left": rank(score), "right": const(1)},
        "exit": {"op": "lt", "left": field(), "right": const(12)},
        "position_size": {"op": "equal_weight"},
    }


def frame(prices):
    stamps = pd.date_range("2026-01-05 15:00", periods=len(prices), tz=ZONE)
    return pd.DataFrame(
        {
            "timestamp": stamps,
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": 1000000,
            "available_at": stamps + pd.Timedelta(minutes=1),
            "captured_at": stamps + pd.Timedelta(minutes=2),
        }
    )


def inputs(frames, **changes):
    members = {}
    for symbol, rows in frames.items():
        for stamp in rows["timestamp"]:
            members.setdefault(stamp.date(), []).append(symbol)
    values = dict(
        declared_symbols=tuple(frames),
        session_memberships={day: tuple(names) for day, names in members.items()},
        minimum_history_rows=2,
        historical_snapshot=True,
    )
    values.update(changes)
    return FormulaCrossSectionInputs(**values)


def prepare(frames, **changes):
    return prepare_formula_sessions(
        changes.pop("formula_ast", formula()),
        frames,
        universe_size=len(frames),
        cross_section=changes.pop("context", inputs(frames)),
        **changes,
    )


def decide(prepared, *, held=None, board=None):
    day = next(iter(prepared.values())).index[-1]
    quantities = held or {}
    cash = Decimal("1000000") - sum(
        (
            quantity * Decimal(str(prepared[name].loc[day, "close"]))
            for name, quantity in quantities.items()
        ),
        Decimal(0),
    )
    return formula_session_targets(
        prepared=prepared,
        decision_session=day,
        quantities=quantities,
        cash=cash,
        equity=Decimal("1000000"),
        instruments={Symbol(s): make_research_stock(s, s) for s in prepared},
        minimum_history_rows=2,
        entry_board_policy=board,
    )


def test_all_declared_members_compete_before_board_holdings_or_affordability():
    frames = {"600001": frame([10, 11, 11]), "300001": frame([20, 22, 23])}
    prepared = prepare(frames)
    assert not prepared["600001"]["entry"].any()
    assert prepared["300001"]["entry"].tolist() == [False, True, True]
    reversed_prepared = prepare(dict(reversed(list(frames.items()))))
    for name in prepared:
        pd.testing.assert_frame_equal(prepared[name], reversed_prepared[name])
    # An already-held leader cannot cause the runner-up to enter.
    result = decide(prepared, held={"300001": Decimal(100)})
    assert result["selected_entries"] == []
    assert formula_session_input_blockers(prepared) == ()


def test_average_percentile_ties_do_not_choose_a_symbol_by_traversal_order():
    frames = {"600001": frame([10, 12, 14]), "600002": frame([10, 12, 14])}
    prepared = prepare(frames)
    assert all(not rows["entry"].any() for rows in prepared.values())
    assert formula_session_input_blockers(prepared) == ()


def test_missing_foreign_member_blocks_entries_but_preserves_local_exit():
    frames = {"600001": frame([10, 10, 10]), "600002": frame([20, 21, 22])}
    context = inputs(frames)
    broken = {**frames, "600002": frames["600002"].iloc[:-1].copy()}
    prepared = prepare(broken, context=context)
    own = prepared["600001"].iloc[-1]
    assert not own["entry"] and own["exit"]
    assert formula_session_input_blockers(prepared, prepared["600001"].index[-1])
    assert decide(prepared, held={"600001": Decimal(100)})["exit_symbols"] == ["600001"]


def test_missing_context_cannot_turn_not_unknown_into_a_buy():
    rows = frame([10, 10, 10])
    ast = formula(
        {"op": "not", "input": {"op": "gt", "left": rank(), "right": const(0)}}
    )
    entry, exits, _ = evaluate_formula(ast, rows, universe_size=1)
    assert not entry.any() and exits.all()
    prepared = prepare({"600001": rows}, context=None, formula_ast=ast)
    assert not prepared["600001"]["entry"].any()
    assert prepared["600001"]["exit"].all()
    assert formula_session_input_blockers(prepared)


def test_known_undefined_score_has_no_rank_without_hiding_missing_raw_prices():
    # A flat, fully observed stock has undefined risk-normalized drift.
    mean = {"op": "rolling_mean", "window": 2, "input": field()}
    std = {"op": "rolling_std", "window": 2, "input": field()}
    ast = formula(score={"op": "divide", "left": mean, "right": std})
    frames = {"600001": frame([10, 10, 10]), "600002": frame([20, 21, 22])}
    prepared = prepare(frames, formula_ast=ast)
    assert not prepared["600001"]["entry"].any()
    assert prepared["600002"]["entry"].iloc[-1]
    assert formula_session_input_blockers(prepared) == ()
    frames["600001"].loc[2, "close"] = float("nan")
    blocked = prepare(frames, formula_ast=ast)
    assert not blocked["600002"]["entry"].iloc[-1]
    assert formula_session_input_blockers(blocked)


def test_real_capture_clock_and_history_clock_both_control_asof_eligibility():
    frames = {"600001": frame([10, 11, 12]), "600002": frame([20, 21, 22])}
    cutoff = datetime(2026, 1, 7, 16, tzinfo=ZONE)
    context = inputs(frames, historical_snapshot=False, as_of=cutoff)
    assert prepare(frames, context=context)["600002"]["entry"].iloc[-1]
    # Earlier history still counts toward eligibility, so its actual capture
    # clock cannot be replaced by the market date or the current scan time.
    frames["600001"].loc[1, "captured_at"] = cutoff + timedelta(days=1)
    blocked = prepare(frames, context=context)
    assert not blocked["600002"]["entry"].iloc[-1]
    assert formula_session_input_blockers(blocked)


def test_future_tail_and_price_units_cannot_change_previous_ranks():
    initial = {"600001": frame([10, 11, 12]), "600002": frame([20, 21, 22])}
    before = prepare(initial)
    extended = {"600001": frame([10, 11, 12, 10000]), "600002": frame([20, 21, 22, 1])}
    after = prepare(extended)
    for name in before:
        pd.testing.assert_frame_equal(before[name], after[name].iloc[:3])
    scaled = {name: rows.copy() for name, rows in initial.items()}
    for rows in scaled.values():
        rows[["open", "high", "low", "close"]] *= 2
    result = prepare(scaled)
    for name in before:
        pd.testing.assert_series_equal(before[name]["entry"], result[name]["entry"])


def test_foreign_gap_propagates_through_outer_lag_without_blocking_earlier_dates():
    frames = {"600001": frame([10, 11, 12, 13]), "600002": frame([20, 21, 22, 23])}
    context = inputs(frames)
    ast = formula(
        {
            "op": "equal",
            "left": {"op": "lag", "period": 1, "input": rank()},
            "right": const(1),
        }
    )
    # A missing foreign observation on Jan7 invalidates the Jan8 lagged rank.
    frames["600001"] = frames["600001"].drop(index=2)
    result = prepare(frames, context=context, formula_ast=ast)
    assert result["600002"]["entry"].tolist() == [False, False, True, False]
    assert result["600002"]["entry_input_blocker"].iloc[-1]


def test_context_history_floor_is_inside_outer_temporal_dependency():
    outer = {"op": "rolling_mean", "window": 20, "input": rank()}
    assert expression_lookback_rows(outer, minimum_history_rows=60) == 79


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "ema", "window": 20, "input": rank()},
        rank(rank()),
    ],
)
def test_first_release_rejects_unbounded_or_nested_cross_section_dependencies(
    expression,
):
    with pytest.raises(FormulaValidationError):
        validate_formula_ast(
            formula({"op": "gt", "left": expression, "right": const(0)}),
            universe_size=2,
        )


def test_exit_cannot_silently_acquire_a_foreign_dependency():
    ast = formula()
    ast["exit"] = {"op": "gt", "left": rank(), "right": const(0)}
    with pytest.raises(
        FormulaValidationError, match="cross_sectional_exit_unsupported"
    ):
        validate_formula_ast(ast, universe_size=2)


def test_real_shared_capital_engine_executes_global_leader_on_later_close():
    from backtest.engine import BacktestEngine, research_execution_config
    from core.types import AssetClass
    from data.handler import DataHandler
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy

    frames = {"600001": frame([10] * 65), "600002": frame([20] * 65)}
    context = inputs(frames, minimum_history_rows=60)

    def run(names):
        handlers = {
            Symbol(name): DataHandler(
                frames[name].copy(), Symbol(name), asset_class=AssetClass.STOCK
            )
            for name in names
        }
        strategy = _FormulaSignalStrategy(
            formula(), len(frames), portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID
        )
        engine = BacktestEngine(
            strategy=strategy,
            instruments={
                key: make_research_stock(str(key), str(key)) for key in handlers
            },
            data_handlers=handlers,
            initial_cash=Decimal("1000000"),
            execution_config=research_execution_config(None),
            strict_event_errors=True,
        )
        strategy.bind_portfolio_engine(
            engine, handlers, minimum_history_rows=60, cross_section=context
        )
        return engine.run(), strategy

    result, strategy = run(list(frames))
    reversed_result, _ = run(list(reversed(frames)))
    assert len(result.fills) == 1
    assert str(result.fills[0].symbol) == "600002"
    assert (
        result.fills[0].timestamp.date() > frames["600002"].iloc[59]["timestamp"].date()
    )
    assert result.final_equity == reversed_result.final_equity
    assert all(Decimal(row["cash"]) >= 0 for row in strategy.session_books)
    assert all(len(row["position_values"]) <= 4 for row in strategy.session_books)


def test_recursive_atr_remains_legacy_compatible_but_cannot_be_a_finite_rank_input():
    atr = {"op": "atr", "window": 14}
    assert expression_lookback_rows(atr) is None
    with pytest.raises(FormulaValidationError, match="finite_history_required"):
        validate_formula_ast(formula(score=atr), universe_size=2)
    legacy = formula({"op": "gt", "left": atr, "right": const(0)})
    assert validate_formula_ast(legacy, universe_size=2) == legacy


def test_missing_foreign_score_column_does_not_swallow_independent_exit():
    frames = {"600001": frame([10, 10, 10]), "600002": frame([20, 21, 22])}
    frames["600002"] = frames["600002"].drop(columns="open")
    result = prepare(frames, formula_ast=formula(score=field("open")))
    assert not result["600001"]["entry"].any()
    assert result["600001"]["exit"].all()
    assert formula_session_input_blockers(result)


def test_global_rank_cannot_bypass_longer_local_entry_warmup_via_not():
    incomplete_mean = {"op": "rolling_mean", "window": 5, "input": field()}
    local_unknown = {
        "op": "not",
        "input": {"op": "gt", "left": incomplete_mean, "right": const(0)},
    }
    entry = {
        "op": "and",
        "left": {"op": "equal", "left": rank(), "right": const(1)},
        "right": local_unknown,
    }
    frames = {"600001": frame([10, 11, 12]), "600002": frame([20, 21, 22])}
    result = prepare(frames, formula_ast=formula(entry))
    assert not result["600002"]["entry"].any()
    assert formula_session_input_blockers(result) == ()  # known warmup, not a data gap


def test_common_mean_and_rank_of_same_input_keep_distinct_values():
    frames = {
        "600001": frame([1, 3]),
        "600002": frame([2, 6]),
        "300001": frame([3, 9]),
    }
    entry = {
        "op": "and",
        "left": {"op": "gt", "left": common_mean(), "right": const(5)},
        "right": {"op": "equal", "left": rank(), "right": const(1)},
    }
    result = prepare(frames, formula_ast=formula(entry))
    assert result["300001"]["entry"].tolist() == [False, True]
    assert not result["600001"]["entry"].any()
    assert not result["600002"]["entry"].any()
    reversed_result = prepare(
        dict(reversed(list(frames.items()))), formula_ast=formula(entry)
    )
    for name in frames:
        pd.testing.assert_frame_equal(result[name], reversed_result[name])


def test_rank_of_broadcast_mean_ties_instead_of_overwriting_mean_node():
    frames = {"600001": frame([10, 11, 12]), "300001": frame([20, 21, 22])}
    result = prepare(frames, formula_ast=formula(score=common_mean()))
    assert not any(rows["entry"].any() for rows in result.values())
    assert not formula_session_input_blockers(result)


def test_rank_resolves_temporal_common_factor_before_local_residual_score():
    prices = {
        "600001": [10, 11, 12, 13, 14, 15, 16, 17],
        "600002": [20, 18, 21, 22, 20, 23, 24, 25],
        "300001": [30, 32, 31, 29, 34, 33, 35, 36],
    }
    returns = {
        "op": "subtract",
        "left": {
            "op": "divide",
            "left": field(),
            "right": {"op": "lag", "period": 1, "input": field()},
        },
        "right": const(1),
    }
    residual = {"op": "subtract", "left": returns, "right": common_mean(returns)}
    score = {"op": "rolling_mean", "window": 3, "input": residual}
    frames = {name: frame(values) for name, values in prices.items()}
    result = prepare(frames, formula_ast=formula(score=score))
    raw = {
        name: [None] + [values[i] / values[i - 1] - 1 for i in range(1, 8)]
        for name, values in prices.items()
    }
    market = [None] + [sum(raw[name][i] for name in prices) / 3 for i in range(1, 8)]
    for i in range(8):
        scores = (
            {
                name: sum(raw[name][j] - market[j] for j in range(i - 2, i + 1)) / 3
                for name in prices
            }
            if i >= 3
            else {}
        )
        for name in prices:
            expected = bool(scores) and all(
                scores[name] > value for other, value in scores.items() if other != name
            )
            assert bool(result[name]["entry"].iloc[i]) == expected


def test_common_series_is_available_to_young_target_without_an_extra_local_floor():
    mature = frame([20] * 8)
    young = frame([5, 6, 7])
    for column in ("timestamp", "available_at", "captured_at"):
        young[column] = mature[column].iloc[-3:].reset_index(drop=True)
    frames = {"600001": mature, "300001": young}
    entry = {
        "op": "gt",
        "left": {"op": "lag", "period": 1, "input": common_mean()},
        "right": const(0),
    }
    context = inputs(frames, minimum_history_rows=3)
    result = prepare(frames, context=context, formula_ast=formula(entry))
    assert result["300001"]["entry"].tolist() == [False, False, True]
    assert not formula_session_input_blockers(result)


def test_cold_factor_initialization_and_target_eligibility_have_distinct_histories():
    from server.services.research.research_observation_inputs import _warmup

    score = {"op": "rolling_mean", "window": 20, "input": common_mean()}
    value = formula(score=score)["entry"]
    assert expression_lookback_rows(value, minimum_history_rows=60) == 60
    assert _warmup(value, minimum_history_rows=60) == 79


def test_foreign_factor_gap_propagates_through_window_and_lag_but_not_local_exit():
    entry = {
        "op": "not",
        "input": {
            "op": "gt",
            "left": {
                "op": "lag",
                "period": 1,
                "input": {"op": "rolling_mean", "window": 2, "input": common_mean()},
            },
            "right": const(1000),
        },
    }
    frames = {"600001": frame([10] * 8), "300001": frame([20] * 8)}
    clean = prepare(frames, formula_ast=formula(entry))
    frames["300001"].loc[2, "close"] = float("nan")
    result = prepare(frames, formula_ast=formula(entry))
    assert (
        result["600001"]["entry"].iloc[:3].tolist()
        == clean["600001"]["entry"].iloc[:3].tolist()
    )
    assert not result["600001"]["entry"].iloc[3:6].any()
    assert result["600001"]["entry"].iloc[6:].all()
    assert result["600001"]["exit"].all()


def test_undefined_but_known_common_mean_does_not_become_a_not_buy():
    invalid = {"op": "divide", "left": field(), "right": const(0)}
    entry = {
        "op": "not",
        "input": {"op": "gt", "left": common_mean(invalid), "right": const(0)},
    }
    result = prepare({"600001": frame([10] * 3)}, formula_ast=formula(entry))
    assert not result["600001"]["entry"].any()
    assert not formula_session_input_blockers(result)


def test_unavailable_common_factor_cannot_be_ranked_after_not_makes_it_finite():
    invalid = {"op": "divide", "left": field(), "right": const(0)}
    unknown = {
        "op": "not",
        "input": {"op": "gt", "left": common_mean(invalid), "right": const(0)},
    }
    score = {"op": "multiply", "left": field(), "right": unknown}
    frames = {"600001": frame([10] * 3), "600002": frame([20] * 3)}
    result = prepare(frames, formula_ast=formula(score=score))
    assert not any(rows["entry"].any() for rows in result.values())
    assert not formula_session_input_blockers(result)


def test_common_indicator_proportion_is_stable_when_membership_size_changes():
    frames = {str(600000 + i): frame([20] * 3) for i in range(300)}
    for i, rows in enumerate(frames.values()):
        rows["volume"] = [1, 2 if i < 100 else 1, 3 if i == 0 else 1]
    context = inputs(frames)
    last_day = frames["600000"]["timestamp"].iloc[-1].date()
    members = dict(context.session_memberships)
    members[last_day] = ("600000", "600100", "600101")
    context = inputs(frames, session_memberships=members)
    expanding = {
        "op": "multiply",
        "left": const(1),
        "right": {
            "op": "gt",
            "left": field("volume"),
            "right": {"op": "lag", "period": 1, "input": field("volume")},
        },
    }
    proportion = common_mean(expanding)
    result = prepare(
        frames,
        context=context,
        formula_ast=formula(
            {
                "op": "lt",
                "left": proportion,
                "right": {"op": "lag", "period": 1, "input": proportion},
            }
        ),
    )
    # Both dated populations have exactly one third expanding members.
    assert not result["600000"]["entry"].iloc[-1]
    assert not formula_session_input_blockers(result)


def test_common_mean_preserves_identical_nonbinary_values():
    price = 0.1
    frames = {str(600000 + i): frame([price] * 2) for i in range(3)}
    result = prepare(
        frames,
        formula_ast=formula(
            {"op": "equal", "left": common_mean(), "right": const(price)}
        ),
    )
    assert all(rows["entry"].iloc[-1] for rows in result.values())
    assert not formula_session_input_blockers(result)


def test_common_mean_preserves_a_representable_subnormal_mean():
    smallest = math.ulp(0.0)
    frames = {"600001": frame([20] * 2), "300001": frame([20] * 2)}
    for rows in frames.values():
        rows["volume"] = smallest
    result = prepare(
        frames,
        formula_ast=formula(
            {
                "op": "equal",
                "left": common_mean(field("volume")),
                "right": const(smallest),
            }
        ),
    )
    assert all(rows["entry"].iloc[-1] for rows in result.values())


@pytest.mark.parametrize("price", [1e308, float.fromhex("0x1.fffffffffffffp+1023")])
def test_finite_common_mean_does_not_overflow_an_unscaled_sum(price):
    frames = {"600001": frame([price] * 2), "300001": frame([price] * 2)}
    result = prepare(
        frames,
        formula_ast=formula(
            {"op": "equal", "left": common_mean(), "right": const(price)}
        ),
    )
    assert all(rows["entry"].iloc[-1] for rows in result.values())


@pytest.mark.parametrize(
    "score", [common_mean(rank()), common_mean(common_mean()), rank(rank())]
)
def test_common_factor_does_not_admit_reverse_or_recursive_joint_dependencies(score):
    with pytest.raises(
        FormulaValidationError, match="nested_cross_sectional_rank_unsupported"
    ):
        validate_formula_ast(formula(score=score), universe_size=3)


def test_common_factor_keeps_foreign_exit_and_recursive_history_unsupported():
    value = formula()
    value["exit"] = {"op": "gt", "left": common_mean(), "right": const(0)}
    with pytest.raises(
        FormulaValidationError, match="cross_sectional_exit_unsupported"
    ):
        validate_formula_ast(value, universe_size=3)
    with pytest.raises(
        FormulaValidationError, match="cross_sectional_finite_history_required"
    ):
        validate_formula_ast(
            formula(score=common_mean({"op": "ema", "window": 3, "input": field()})),
            universe_size=3,
        )


def test_rolling_sum_counts_complete_windows_without_filling_unknown_numbers():
    values = frame([11, 9, 12, 8, 13])
    counter = {
        "op": "rolling_sum",
        "window": 3,
        "input": {"op": "gt", "left": field(), "right": const(10)},
    }
    result = evaluate_formula_expression(counter, values)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2:].tolist() == [2.0, 1.0, 2.0]
    assert expression_lookback_rows(counter) == 3
    for end in range(1, len(values)):
        pd.testing.assert_series_equal(
            evaluate_formula_expression(counter, values.iloc[:end]), result.iloc[:end]
        )
    raw_sum = {**counter, "input": field()}
    missing = frame([11, 9, float("nan"), 8, 13, 14, 15])
    actual = evaluate_formula_expression(raw_sum, missing)
    assert actual.iloc[:5].isna().all()
    assert actual.iloc[5:].tolist() == [35.0, 42.0]


def test_rolling_common_state_count_keeps_foreign_unknowns_and_local_exit():
    score = {
        "op": "rolling_sum",
        "window": 3,
        "input": {"op": "gt", "left": common_mean(), "right": const(12)},
    }
    entry = {"op": "gt", "left": score, "right": const(0)}
    frames = {"600001": frame([10] * 9), "300001": frame([20] * 9)}
    clean = prepare(frames, formula_ast=formula(entry))
    assert clean["600001"]["entry"].iloc[3:].all()
    frames["300001"].loc[4, "close"] = float("nan")
    result = prepare(frames, formula_ast=formula(entry))
    assert (
        result["600001"]["entry"].iloc[:4].tolist()
        == clean["600001"]["entry"].iloc[:4].tolist()
    )
    assert not result["600001"]["entry"].iloc[4:8].any()
    assert result["600001"]["entry_input_blocker"].iloc[4:8].astype(bool).all()
    assert result["600001"]["entry"].iloc[8]
    assert result["600001"]["entry_input_blocker"].iloc[8] == ""
    assert result["600001"]["exit"].all()


@pytest.mark.parametrize("window", [10, 20, 30])
def test_integer_response_comparison_preserves_exact_equal_three_sevenths(window):
    # Both directed conditional contrasts are exactly 3/7. Subtracting the
    # separately rounded probabilities can falsely produce a positive score.
    x, y = "1110000000", "1111100011"
    values = pd.DataFrame(
        {
            "close": [1 + int(x[i % 10]) for i in range(90)],
            "open": [1 + int(y[i % 10]) for i in range(90)],
        }
    )

    def binary(operator, left, right):
        return {"op": operator, "left": left, "right": right}

    def count(value):
        return {"op": "rolling_sum", "window": window, "input": value}

    def cells(current, previous):
        up = binary("gt", current, const(1.5))
        down = binary("lte", current, const(1.5))
        prior_up = binary("gt", previous, const(1.5))
        prior_down = binary("lte", previous, const(1.5))
        positive = binary(
            "multiply",
            count(binary("multiply", up, prior_up)),
            count(binary("multiply", down, prior_down)),
        )
        negative = binary(
            "multiply",
            count(binary("multiply", up, prior_down)),
            count(binary("multiply", down, prior_up)),
        )
        return binary("subtract", positive, negative), binary(
            "multiply", count(prior_up), count(prior_down)
        )

    own, common = field("close"), field("open")
    lag_own = {"op": "lag", "period": 2, "input": own}
    lag_common = {"op": "lag", "period": 2, "input": common}
    a_num, a_den = cells(own, lag_common)
    r_num, r_den = cells(common, lag_own)
    exact_difference_numerator = binary(
        "subtract",
        binary("multiply", a_num, r_den),
        binary("multiply", r_num, a_den),
    )
    result = evaluate_formula_expression(exact_difference_numerator, values)
    assert result.iloc[window + 1 :].eq(0).all()
    assert evaluate_formula_expression(a_num, values).iloc[window + 1 :].gt(0).all()
