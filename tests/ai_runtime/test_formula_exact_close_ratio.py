"""Exact price-ratio ordering, undefined inputs, and existing caller history."""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction

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
from server.ai_runtime.strategy_research_model_contract import (
    hypothesis_output_contract,
)
from server.services.research.research_observation_inputs import _warmup
from server.services.strategy_scan.universe.evaluation import formula_history_rows


def ratio(window=1):
    return {"op": "rolling_max_close_ratio", "window": window}


def constant(value):
    return {"op": "constant", "value": value}


def binary(op, left, right):
    return {"op": op, "left": left, "right": right}


def formula(entry, exit_signal=None):
    return {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": entry,
        "exit": constant(0) if exit_signal is None else exit_signal,
        "position_size": {"op": "equal_weight"},
    }


def frame(prices):
    dates = pd.date_range("2026-01-05T07:00:00Z", periods=len(prices))
    return pd.DataFrame(
        {
            "timestamp": dates,
            "available_at": dates,
            "captured_at": dates,
            "close": prices,
            "volume": 1000,
            "amount": 10000,
        }
    )


def prepare(prices, *, threshold=0.1, minimum=1):
    frames = {symbol: frame(values) for symbol, values in prices.items()}
    dates = next(iter(frames.values()))["timestamp"]
    ranked = {"op": "cross_sectional_rank", "input": ratio()}
    ast = formula(
        binary("lte", ranked, constant(threshold)), binary("gt", ratio(), constant(1))
    )
    context = FormulaCrossSectionInputs(
        declared_symbols=tuple(frames),
        session_memberships={day.date(): tuple(frames) for day in dates},
        minimum_history_rows=minimum,
        historical_snapshot=True,
    )
    return prepare_formula_sessions(
        ast, frames, universe_size=len(frames), cross_section=context
    )


@pytest.mark.parametrize("window", [1, 2, 10, 20, 30, 252])
def test_exact_rolling_max_matches_independent_complete_window_enumeration(window):
    values = [Decimal((index * 17) % 101 + 1) / 100 for index in range(window + 45)]
    rows = frame(values)
    result = evaluate_formula_expression(ratio(window), rows)
    for end in range(len(rows)):
        if end < window:
            assert pd.isna(result.iloc[end])
        else:
            expected = max(
                Fraction(values[t]) / Fraction(values[t - 1])
                for t in range(end - window + 1, end + 1)
            )
            assert result.iloc[end] == expected
            assert type(result.iloc[end]) is Fraction
    assert expression_lookback_rows(ratio(window)) == window + 1
    assert formula_expression_fields(ratio(window)) == {"close"}


@pytest.mark.parametrize(
    "bad",
    [None, Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity"), 1.1, "1.1"],
)
def test_bad_raw_close_poisoning_recovers_only_after_complete_window(bad):
    values = [Decimal(index + 2) for index in range(15)]
    values[5] = bad
    rows = frame(values)
    score = evaluate_formula_expression(ratio(3), rows)
    assert score.iloc[:3].isna().all()
    assert score.iloc[3:5].notna().all()
    assert score.iloc[5:9].isna().all()
    assert score.iloc[9:].notna().all()
    entry, exits, _ = evaluate_formula(
        formula(
            {"op": "not", "input": binary("gt", ratio(3), constant(1))},
            binary("equal", ratio(3), ratio(3)),
        ),
        rows,
        universe_size=1,
    )
    assert not entry.iloc[5:9].any()
    assert not exits.iloc[5:9].any()


def test_exact_tie_at_decile_is_not_split_by_float_representations():
    values = {"a": [Decimal("3"), Decimal("3.3")], "b": [Decimal("1"), Decimal("1.1")]}
    values.update({f"higher{i}": [Decimal(1), Decimal(2 + i)] for i in range(8)})
    result = prepare(values)
    assert not any(rows["entry"].iloc[-1] for rows in result.values())
    assert formula_session_input_blockers(result) == ()
    reverse = prepare(dict(reversed(list(values.items()))))
    for symbol in result:
        pd.testing.assert_frame_equal(result[symbol], reverse[symbol])


def test_distinct_exact_ratios_with_same_float_do_not_merge():
    result = prepare(
        {
            "a": [Decimal("49999.99999999"), Decimal("50000.00000000")],
            "b": [Decimal("50000.00000000"), Decimal("50000.00000001")],
        },
        threshold=0.5,
    )
    assert not result["a"]["entry"].iloc[-1]
    assert result["b"]["entry"].iloc[-1]


def test_float_member_blocks_reference_pool_instead_of_being_silently_removed():
    result = prepare(
        {"a": [Decimal(1), Decimal(2)], "b": [Decimal(1), 3.0]}, threshold=0.5
    )
    assert not any(rows["entry"].iloc[-1] for rows in result.values())
    assert formula_session_input_blockers(result)
    assert result["a"]["exit"].iloc[-1]
    assert not result["b"]["exit"].iloc[-1]


def test_exact_ratios_do_not_depend_on_decimal_precision_or_float_range():
    rows = frame([Decimal("1e-900"), Decimal("1e900"), Decimal("2e900")])
    with localcontext() as context:
        context.prec = 3
        result = evaluate_formula_expression(ratio(), rows)
    assert result.iloc[1] == Fraction(10**1800)
    assert result.iloc[2] == Fraction(2)
    prepared = prepare(
        {"a": [Decimal("1e-900"), Decimal("1e900")], "b": [Decimal(1), Decimal(2)]},
        threshold=0.5,
    )
    assert prepared["b"]["entry"].iloc[-1]
    assert not prepared["a"]["entry"].iloc[-1]


def test_lag_comparison_full_history_and_prefix_replay():
    current = ratio()
    prior_max = {"op": "lag", "input": ratio(30), "period": 1}
    exit_signal = binary(
        "and", binary("gt", current, constant(1)), binary("gt", current, prior_max)
    )
    ast = formula(binary("equal", ratio(31), ratio(31)), exit_signal)
    values = [Decimal(index + 100) for index in range(100)]
    values[90] = Decimal(400)
    rows = frame(values)
    entry, exits, _ = evaluate_formula(ast, rows, universe_size=1)
    assert not entry.iloc[:31].any() and entry.iloc[31:].all()
    assert exits.iloc[90]
    assert formula_history_rows(ast) == _warmup(exit_signal) == 32
    for end in (31, 32, 89, 90, 99):
        cold = evaluate_formula(ast, rows.iloc[end - 31 : end + 1], universe_size=1)
        assert bool(cold[0].iloc[-1]) == bool(entry.iloc[end])
        assert bool(cold[1].iloc[-1]) == bool(exits.iloc[end])
    prefix = evaluate_formula(ast, rows.iloc[:91], universe_size=1)
    pd.testing.assert_series_equal(prefix[1], exits.iloc[:91])


@pytest.mark.parametrize("op", ["add", "subtract", "multiply", "divide", "cross"])
def test_exact_values_reject_float_binary_consumers(op):
    with pytest.raises(
        FormulaValidationError, match="exact_close_ratio_consumer_unsupported"
    ):
        evaluate_formula_expression(
            binary(op, ratio(), constant(1)), frame([Decimal(1)])
        )


@pytest.mark.parametrize(
    "node",
    [
        {"op": "cross_sectional_zscore", "input": ratio()},
        {"op": "rolling_max", "input": ratio(), "window": 2},
        {"op": "cross_sectional_mean", "input": ratio()},
        {"op": "not", "input": ratio()},
        binary("and", ratio(), constant(1)),
        {"op": "not", "input": {"op": "cross_sectional_rank", "input": ratio()}},
        binary("gt", ratio(), constant(1.1)),
        binary("gt", ratio(), {"op": "field", "name": "close"}),
    ],
)
def test_unsupported_exact_value_consumers_fail_validation(node):
    with pytest.raises(FormulaValidationError, match="exact_close_ratio_"):
        validate_formula_ast(formula(node), universe_size=1)


@pytest.mark.parametrize("window", [0, 253, True, 1.0])
def test_window_contract_rejects_invalid_shapes(window):
    with pytest.raises(FormulaValidationError, match="window_out_of_bounds"):
        validate_formula_ast(
            formula(binary("gt", ratio(window), constant(1))), universe_size=1
        )


def test_catalog_and_model_contract_publish_new_exact_shape():
    catalog = formula_operator_catalog()
    assert "rolling_max_close_ratio" in catalog["enabled_operators"]
    assert set(catalog["expression_shapes"]["rolling_max_close_ratio"]) == {
        "op",
        "window",
    }
    contract = hypothesis_output_contract(citation_catalog={})
    assert contract["formula_ast_node_exact_keys"]["rolling_max_close_ratio"] == [
        "op",
        "window",
    ]


def bk_formula(window=20):
    valid = binary("equal", ratio(31), ratio(31))
    return formula(
        binary(
            "and",
            valid,
            binary(
                "lte",
                {"op": "cross_sectional_rank", "input": ratio(window)},
                constant(0.1),
            ),
        ),
        binary(
            "and",
            valid,
            binary(
                "and",
                binary("gt", ratio(), constant(1)),
                binary(
                    "gt", ratio(), {"op": "lag", "period": 1, "input": ratio(window)}
                ),
            ),
        ),
    )


@pytest.mark.parametrize("window", [10, 20, 30])
def test_bk_native_paper_and_account_callers_share_exact_inputs(monkeypatch, window):
    """Exercise the real frame adapters and signal owners, without engine/DB writes."""
    from types import SimpleNamespace

    from core.types import Symbol
    from data.dataset import reader
    from data.handler import DataHandler
    from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
    from server.ai_runtime import formula_portfolio
    from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy
    from server.persistence import research_paper_books
    from server.services.research import research_observations as module
    from server.services.strategy_scan.universe.evaluation import (
        evaluate_strategy_signals,
    )

    ast = bk_formula(window)
    frames = {}
    for index in range(10):
        prices = [Decimal(100 + index * offset) for offset in range(40)]
        if index == 9:
            prices[-1] = Decimal(1000)
        rows = frame(prices)
        for name in ("open", "high", "low"):
            rows[name] = rows["close"]
        frames[f"60000{index}"] = rows
    stamps = frames["600000"]["timestamp"]
    day, now = stamps.iloc[-1].date(), stamps.iloc[-1].to_pydatetime()
    context = FormulaCrossSectionInputs(
        declared_symbols=tuple(frames),
        session_memberships={stamp.date(): tuple(frames) for stamp in stamps},
        minimum_history_rows=32,
        as_of=now,
    )
    strategy = _FormulaSignalStrategy(
        ast, 10, portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID
    )
    strategy.bind_portfolio_engine(
        SimpleNamespace(),
        {
            Symbol(symbol): DataHandler(rows, Symbol(symbol))
            for symbol, rows in frames.items()
        },
        minimum_history_rows=32,
        cross_section=context,
    )
    native = strategy._prepared_sessions
    assert native["600000"].loc[day, "entry"]
    assert native["600009"].loc[day, "exit"]
    signals = evaluate_strategy_signals(
        strategy_id="bk-synthetic",
        formula_ast=ast,
        universe_size=10,
        target_weight=0.25,
        frames=frames,
        eligible_symbols=["600000"],
        maintenance_symbols=["600009"],
        held_symbols={"600009"},
        market_date=day.isoformat(),
        cross_section=context,
    )
    assert {(row["symbol"], row["direction"]) for row in signals} == {
        ("600000", "buy"),
        ("600009", "sell"),
    }
    keys = tuple(SimpleNamespace(symbol=s) for s in frames)
    snapshot = SimpleNamespace(instruments=keys, instruments_for_session=lambda _: keys)
    monkeypatch.setattr(
        research_paper_books,
        "ResearchPaperBooksRepository",
        lambda *_a, **_k: SimpleNamespace(
            get=lambda _: {"lifecycle": "active", "evaluation_start": "2027-01-01"}
        ),
    )
    monkeypatch.setattr(
        module,
        "observation_deployment_scope",
        lambda _: {"universe_policy": {"minimum_history_rows": 32}},
    )
    monkeypatch.setattr(
        reader,
        "dataset_cross_section_memberships",
        lambda *_a, **_k: {stamp.date(): keys for stamp in stamps},
    )
    real_prepare = prepare_formula_sessions

    class PreparedBoundaryReached(Exception):
        pass

    def inspect_prepare(actual_ast, actual_frames, **kwargs):
        assert actual_ast == ast
        assert all(
            type(value) is Decimal
            for rows in actual_frames.values()
            for value in rows["close"]
        )
        actual = real_prepare(actual_ast, actual_frames, **kwargs)
        for symbol in actual:
            pd.testing.assert_frame_equal(
                actual[symbol][["entry", "exit"]], native[symbol][["entry", "exit"]]
            )
        raise PreparedBoundaryReached

    monkeypatch.setattr(formula_portfolio, "prepare_formula_sessions", inspect_prepare)
    service = object.__new__(module.ResearchObservationService)
    service.db, service.clock, service.objects = (
        SimpleNamespace(path=None),
        lambda: now,
        object(),
    )
    bars = [
        SimpleNamespace(
            instrument=key,
            event_time=row.timestamp,
            available_at=row.available_at,
            captured_at=row.captured_at,
            **{
                name: getattr(row, name)
                for name in ("open", "high", "low", "close", "volume", "amount")
            },
        )
        for key in keys
        for row in frames[key.symbol].itertuples()
    ]
    with pytest.raises(PreparedBoundaryReached):
        service._portfolio_publication(
            {
                "id": "bk-synthetic",
                "source": {
                    "formula_binding": {"formula_ast": ast},
                    "instruments": list(frames),
                },
            },
            bars,
            "synthetic-dataset",
            day,
            day,
            day,
            snapshot=snapshot,
            as_of=now,
        )
