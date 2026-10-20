from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine, research_execution_config
from core.types import AssetClass, Symbol
from data.handler import DataHandler
from domain.instrument import make_research_stock
from domain.research_targets import FORMULA_PORTFOLIO_POLICY_ID
from server.ai_runtime.formula_dsl import FORMULA_AST_CONTRACT
from server.ai_runtime.strategy_research_backtest import _FormulaSignalStrategy


def _run(reverse=False, *, retain_session_decisions=True):
    names = [f"600{index:03d}" for index in range(81)]
    if reverse:
        names.reverse()
    handlers = {}
    for name in names:
        handlers[Symbol(name)] = DataHandler(
            pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-01-01", periods=65),
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.0,
                    "volume": 10000000,
                    "amount": 100000000 + int(name),
                }
            ),
            Symbol(name),
            asset_class=AssetClass.STOCK,
        )
    formula = {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "gt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "exit": {
            "op": "lt",
            "left": {"op": "field", "name": "close"},
            "right": {"op": "constant", "value": 0},
        },
        "position_size": {"op": "equal_weight"},
    }
    strategy = _FormulaSignalStrategy(
        formula,
        len(names),
        portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
        retain_session_decisions=retain_session_decisions,
    )
    engine = BacktestEngine(
        strategy=strategy,
        instruments={s: make_research_stock(str(s), str(s)) for s in handlers},
        data_handlers=handlers,
        initial_cash=Decimal("1000000"),
        execution_config=research_execution_config(None),
        strict_event_errors=True,
    )
    strategy.bind_portfolio_engine(engine, handlers, minimum_history_rows=60)
    return engine.run(), strategy


def test_more_than_40_symbols_use_global_ranking_actual_cash_and_later_fills():
    result, strategy = _run()
    reversed_result, reversed_strategy = _run(reverse=True)
    selected = strategy.session_decisions[59]["selected_entries"]
    assert selected == ["600080", "600079", "600078", "600077"]
    assert selected == reversed_strategy.session_decisions[59]["selected_entries"]
    assert {str(fill.symbol) for fill in result.fills} == set(selected)
    assert all(
        fill.timestamp.date() > pd.Timestamp("2026-03-01").date()
        for fill in result.fills
    )
    assert result.final_equity == reversed_result.final_equity
    assert all(Decimal(row["cash"]) >= 0 for row in strategy.session_books)
    assert all(len(row["position_values"]) <= 4 for row in strategy.session_books)
    compact_result, compact_strategy = _run(retain_session_decisions=False)
    assert compact_strategy.session_decisions == []
    assert compact_strategy.session_books == strategy.session_books
    assert compact_result.equity_curve == result.equity_curve
    assert [
        (fill.symbol, fill.side, fill.fill_quantity, fill.fill_price, fill.commission)
        for fill in compact_result.fills
    ] == [
        (fill.symbol, fill.side, fill.fill_quantity, fill.fill_price, fill.commission)
        for fill in result.fills
    ]
    assert compact_strategy.execution_evidence(
        fill_count=len(compact_result.fills),
        execution_timing=compact_result.execution_timing,
    ) == strategy.execution_evidence(
        fill_count=len(result.fills), execution_timing=result.execution_timing
    )


@pytest.mark.parametrize(
    "prices",
    [
        [10, 10.8, 11.6, 12.4, 12.4, 12.4, 12.4, 12.4],
        [10, 9.2, 8.5, 7.9, 7.9, 7.9, 7.9, 7.9],
    ],
    ids=["rising", "falling"],
)
def test_actual_quantity_holds_until_exit_then_reentry_across_three_consumers(prices):
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    from backtest.paper_replay import PublishedPaperTarget, replay_paper_book
    from server.services.promoted_strategy_universe_scan_support import (
        evaluate_strategy_signals,
    )

    shanghai = ZoneInfo("Asia/Shanghai")
    symbol = Symbol("600000")
    stamps = pd.date_range("2026-01-01 15:00", periods=128, tz=shanghai)
    frame = pd.DataFrame(
        {
            "timestamp": stamps,
            "open": [10] * 120 + prices,
            "high": [10] * 120 + prices,
            "low": [10] * 120 + prices,
            "close": [10] * 120 + prices,
            "volume": [3000000] * 128,
        }
    )
    # Signals are fixed independently of prices, so both drift directions have
    # the same initial entry, explicit exit, and subsequent fresh entry.
    frame.loc[[119, 126], "volume"] = 1000000
    frame.loc[124, "volume"] = 2000000
    formula = {
        "schema_version": FORMULA_AST_CONTRACT,
        "entry": {
            "op": "equal",
            "left": {"op": "field", "name": "volume"},
            "right": {"op": "constant", "value": 1000000},
        },
        "exit": {
            "op": "equal",
            "left": {"op": "field", "name": "volume"},
            "right": {"op": "constant", "value": 2000000},
        },
        "position_size": {"op": "equal_weight"},
    }
    handler = DataHandler(frame, symbol, asset_class=AssetClass.STOCK)
    instruments = {symbol: make_research_stock(str(symbol), "fixture")}
    strategy = _FormulaSignalStrategy(
        formula,
        1,
        portfolio_policy_id=FORMULA_PORTFOLIO_POLICY_ID,
        retain_session_decisions=True,
    )
    quantities = []
    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers={symbol: handler},
        initial_cash=Decimal("100000"),
        execution_config=research_execution_config(None),
        evaluation_start=stamps[120].date(),
        warmup_final_bar_targets=True,
        strict_event_errors=True,
        session_completed=lambda _: quantities.append(
            engine.portfolio.positions[symbol].quantity
        ),
    )
    strategy.bind_portfolio_engine(engine, {symbol: handler}, minimum_history_rows=120)
    result = engine.run()
    assert [fill.side.value for fill in result.fills] == ["buy", "sell", "buy"]
    assert len(set(quantities[:5])) == 1
    assert quantities[0] > 0 and quantities[5] == quantities[6] == 0
    assert quantities[7] > 0

    publications = []
    for index in range(119, 127):
        decision = strategy.session_decisions[index]
        selected = [*decision["exit_symbols"], *decision["selected_entries"]]
        scanner = evaluate_strategy_signals(
            strategy_id="fixture",
            formula_ast=formula,
            universe_size=1,
            target_weight=0.25,
            frames={str(symbol): frame.iloc[: index + 1]},
            eligible_symbols=[str(symbol)],
            maintenance_symbols=[],
            held_symbols={str(symbol)}
            if index >= 120 and quantities[index - 120] > 0
            else set(),
            market_date=stamps[index].date().isoformat(),
        )
        assert [row["symbol"] for row in scanner] == selected
        publications.append(
            PublishedPaperTarget(
                str(index),
                datetime.combine(stamps[index].date(), time(16), shanghai),
                stamps[index + 1].date(),
                {key: decision["target_weights"][key] for key in selected},
            )
        )
    paper = replay_paper_book(
        book_id="same-book",
        initial_cash=Decimal("100000"),
        instruments=instruments,
        bars=list(
            DataHandler(
                frame,
                symbol,
                asset_class=AssetClass.STOCK,
                instrument_type=instruments[symbol].instrument_type,
            )
        ),
        publications=publications,
        evaluation_start=stamps[120].date(),
        through_session=stamps[-1].date(),
        cost_config=research_execution_config(None),
        session_instruments={stamp.date(): [symbol] for stamp in stamps},
    )
    assert [
        Decimal(row["positions"][symbol]["quantity"]) for row in paper["sessions"]
    ] == quantities
    assert [
        (row["side"], Decimal(row["fill_quantity"]), Decimal(row["fill_price"]))
        for row in paper["fills"]
    ] == [
        (fill.side.value, fill.fill_quantity, fill.fill_price) for fill in result.fills
    ]
    assert Decimal(paper["sessions"][-1]["equity"]) == result.final_equity
    assert Decimal(paper["sessions"][-1]["cash"]) == engine.portfolio.cash
