"""P0-4C tests: BacktestEngine lifecycle isolation, critical error fail-closed propagation,
and deterministic replay comparison across independent runs.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.costs import RESEARCH_SLIPPAGE_BPS
from backtest.engine import BacktestEngine, BacktestExecutionConfig
from backtest.result import BacktestResult
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent, SignalEvent
from core.types import InstrumentType, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import PercentSlippage
from server.services.backtest.deterministic_replay import compare_backtest_runs
from strategy.base import Strategy

SH = ZoneInfo("Asia/Shanghai")
SYMBOL = Symbol("600000")


def _make_daily_bars(
    prices: list[float],
    *,
    symbol: Symbol = SYMBOL,
    start_date: str = "2026-01-05",
) -> list[MarketEvent]:
    dates = pd.bdate_range(start_date, periods=len(prices))
    events = []
    for dt, px in zip(dates, prices, strict=True):
        ts = dt.to_pydatetime().replace(hour=15, minute=0, tzinfo=SH)
        val = Decimal(str(px))
        events.append(
            MarketEvent(
                timestamp=ts,
                symbol=symbol,
                open=val,
                high=val,
                low=val,
                close=val,
                volume=Decimal("100000"),
                available_at=ts + timedelta(hours=1),
                instrument_type=InstrumentType.STOCK,
            )
        )
    return events


class SimpleStepStrategy(Strategy):
    """Predictable 2-step buy/sell strategy for replay testing."""

    def __init__(
        self, name: str = "step_strat", buy_step: int = 1, sell_step: int = 3
    ) -> None:
        super().__init__(name, EventBus())
        self.buy_step = buy_step
        self.sell_step = sell_step
        self.step = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self.step += 1
        if self.step == self.buy_step:
            self.emit_signal(event.symbol, target_weight=0.5, price=float(event.close))
        elif self.step == self.sell_step:
            self.emit_signal(event.symbol, target_weight=0.0, price=float(event.close))


class ReentrantStrategy(Strategy):
    """Attempts to reentrantly call engine.run() from on_data."""

    def __init__(self, engine_holder: list[Any]) -> None:
        super().__init__("reentrant", EventBus())
        self.engine_holder = engine_holder
        self.reentrant_error: Exception | None = None

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        try:
            self.engine_holder[0].run()
        except RuntimeError as exc:
            self.reentrant_error = exc


class ExplodingStrategy(Strategy):
    """Raises a critical exception during on_data."""

    def __init__(self, fail_on_step: int = 2) -> None:
        super().__init__("exploding", EventBus())
        self.fail_on_step = fail_on_step
        self.step = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self.step += 1
        if self.step == self.fail_on_step:
            raise ZeroDivisionError("critical_strategy_math_exploded")


def _build_test_engine(
    strategy: Strategy,
    prices: list[float] | None = None,
    *,
    initial_cash: Decimal = Decimal("100000"),
    strict_event_errors: bool = True,
    **kwargs: Any,
) -> BacktestEngine:
    bars = _make_daily_bars(prices or [10.0, 10.5, 11.0, 10.8, 11.2])
    inst = make_stock(str(SYMBOL), "synthetic_stock")
    instruments = {SYMBOL: inst}
    data_handlers = {SYMBOL: bars}
    return BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=data_handlers,
        initial_cash=initial_cash,
        commission_calc=StockACommission(),
        slippage_model=PercentSlippage(RESEARCH_SLIPPAGE_BPS / Decimal("10000")),
        strict_event_errors=strict_event_errors,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Engine Lifecycle & Strategy Ownership Tests
# ---------------------------------------------------------------------------


def test_engine_single_run_contract():
    """Engine enforces single-execution contract: run() can only be called once."""
    strat = SimpleStepStrategy()
    engine = _build_test_engine(strat)
    result = engine.run()
    assert isinstance(result, BacktestResult)
    assert len(result.fills) > 0

    with pytest.raises(RuntimeError, match="backtest_engine_already_executed"):
        engine.run()


def test_closed_engine_cannot_run():
    """Explicitly closed engine rejects execution."""
    strat = SimpleStepStrategy()
    engine = _build_test_engine(strat)
    engine.close()

    with pytest.raises(RuntimeError, match="backtest_engine_already_closed"):
        engine.run()


def test_reentrant_run_is_blocked():
    """Reentrant call to engine.run() during active execution is strictly blocked."""
    engine_holder = []
    strat = ReentrantStrategy(engine_holder)
    engine = _build_test_engine(strat)
    engine_holder.append(engine)

    engine.run()
    assert strat.reentrant_error is not None
    assert "backtest_engine_reentrant_call_blocked" in str(strat.reentrant_error)


def test_strategy_already_bound_to_active_engine_raises():
    """A mutable Strategy cannot be bound to two active engines simultaneously."""
    strat = SimpleStepStrategy()
    engine1 = _build_test_engine(strat)

    with pytest.raises(ValueError, match="strategy_already_bound_to_active_engine"):
        _build_test_engine(strat)

    # After engine1 runs and closes, strategy is released and can be bound to engine2
    engine1.run()
    engine2 = _build_test_engine(strat)
    res2 = engine2.run()
    assert isinstance(res2, BacktestResult)


def test_strategy_released_on_engine_close():
    """Explicit engine.close() or context manager exit releases bound strategy."""
    strat = SimpleStepStrategy()
    with _build_test_engine(strat) as engine:
        assert getattr(strat, "_bound_engine", None) is engine

    assert getattr(strat, "_bound_engine", None) is None
    # Now another engine can bind to it cleanly
    engine2 = _build_test_engine(strat)
    assert getattr(strat, "_bound_engine", None) is engine2
    engine2.close()


def test_strategy_released_on_engine_init_failure():
    """If BacktestEngine.__init__ raises, the strategy's bound engine is cleaned up."""
    strat = SimpleStepStrategy()
    with pytest.raises(ValueError, match="backtest_evaluation_start_invalid"):
        _build_test_engine(strat, evaluation_start="invalid_date_type")

    assert getattr(strat, "_bound_engine", None) is None
    # Can bind to another engine cleanly
    engine = _build_test_engine(strat)
    assert getattr(strat, "_bound_engine", None) is engine
    engine.close()


def test_strategy_released_on_engine_run_failure():
    """If engine.run() fails with critical exception, strategy is still released in finally."""
    strat = ExplodingStrategy(fail_on_step=2)
    engine = _build_test_engine(strat, strict_event_errors=True)

    with pytest.raises(ZeroDivisionError, match="critical_strategy_math_exploded"):
        engine.run()

    # Strategy is released despite exception
    assert getattr(strat, "_bound_engine", None) is None


# ---------------------------------------------------------------------------
# 2. Critical Exceptions Failing Closed
# ---------------------------------------------------------------------------


def test_critical_strategy_exception_propagates_out():
    """Exceptions during strategy on_data propagate out of engine.run() when strict_event_errors=True."""
    strat = ExplodingStrategy(fail_on_step=2)
    engine = _build_test_engine(strat, strict_event_errors=True)

    with pytest.raises(ZeroDivisionError, match="critical_strategy_math_exploded"):
        engine.run()


# ---------------------------------------------------------------------------
# 3. Deterministic Replay Comparison Tests
# ---------------------------------------------------------------------------


def test_deterministic_replay_same_process_a_to_a():
    """Replay A -> A with identical inputs yields deterministically identical results."""
    prices = [10.0, 10.5, 11.0, 10.8, 11.2, 11.5, 11.0]

    strat_a1 = SimpleStepStrategy("step_a", buy_step=1, sell_step=4)
    eng_a1 = _build_test_engine(strat_a1, prices)
    res_a1 = eng_a1.run()

    strat_a2 = SimpleStepStrategy("step_a", buy_step=1, sell_step=4)
    eng_a2 = _build_test_engine(strat_a2, prices)
    res_a2 = eng_a2.run()

    comparison = compare_backtest_runs(res_a1, res_a2)
    assert comparison["is_identical"] is True
    assert comparison["first_difference"] is None
    assert comparison["details"]["fill_count"] == 2
    assert comparison["details"]["equity_points"] == len(prices)


def test_deterministic_replay_a_b_a():
    """Interleaved run sequence A -> B -> A preserves exact determinism for A."""
    prices = [10.0, 10.5, 11.0, 10.8, 11.2, 11.5, 11.0]

    # Run A1
    strat_a1 = SimpleStepStrategy("step_a", buy_step=1, sell_step=4)
    eng_a1 = _build_test_engine(strat_a1, prices)
    res_a1 = eng_a1.run()

    # Run B (different parameters: buy on step 2, sell on step 5)
    strat_b = SimpleStepStrategy("step_b", buy_step=2, sell_step=5)
    eng_b = _build_test_engine(strat_b, prices)
    res_b = eng_b.run()

    # Run A2
    strat_a2 = SimpleStepStrategy("step_a", buy_step=1, sell_step=4)
    eng_a2 = _build_test_engine(strat_a2, prices)
    res_a2 = eng_a2.run()

    # Verify A1 vs A2 is identical
    comp_aa = compare_backtest_runs(res_a1, res_a2)
    assert comp_aa["is_identical"] is True
    assert comp_aa["first_difference"] is None

    # Verify A1 vs B detects discrepancy
    comp_ab = compare_backtest_runs(res_a1, res_b)
    assert comp_ab["is_identical"] is False
    assert comp_ab["first_difference"] is not None


def test_deterministic_replay_after_failure():
    """Running an exploding strategy, then running clean instance A produces identical result to baseline A."""
    prices = [10.0, 10.5, 11.0, 10.8, 11.2]

    # Baseline A
    strat_a1 = SimpleStepStrategy("step_a", buy_step=1, sell_step=3)
    eng_a1 = _build_test_engine(strat_a1, prices)
    res_a1 = eng_a1.run()

    # Exploding run
    exploding_strat = ExplodingStrategy(fail_on_step=2)
    eng_fail = _build_test_engine(exploding_strat, prices)
    with pytest.raises(ZeroDivisionError):
        eng_fail.run()

    # Post-failure A2
    strat_a2 = SimpleStepStrategy("step_a", buy_step=1, sell_step=3)
    eng_a2 = _build_test_engine(strat_a2, prices)
    res_a2 = eng_a2.run()

    comparison = compare_backtest_runs(res_a1, res_a2)
    assert comparison["is_identical"] is True
    assert comparison["first_difference"] is None


def test_comparator_detects_altered_quantity():
    """Comparator detects discrepancy if quantity is altered."""
    prices = [10.0, 10.5, 11.0]
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()

    # Alter quantity on one fill
    res2.fills[0] = replace(res2.fills[0], fill_quantity=Decimal("999"))

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "fills[0].quantity"


def test_comparator_detects_altered_price():
    """Comparator detects discrepancy if fill price is altered."""
    prices = [10.0, 10.5, 11.0]
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()

    res2.fills[0] = replace(res2.fills[0], fill_price=Decimal("99.99"))

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "fills[0].price"


def test_comparator_detects_altered_commission():
    """Comparator detects discrepancy if fee/commission is altered."""
    prices = [10.0, 10.5, 11.0]
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()

    res2.fills[0] = replace(res2.fills[0], commission=Decimal("12.34"))

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "fills[0].commission"


def test_comparator_detects_altered_execution_phase():
    """Comparator detects discrepancy if execution phase is altered."""
    prices = [10.0, 10.5, 11.0]
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2), prices).run()

    meta = dict(res2.fills[0].metadata) if res2.fills[0].metadata else {}
    meta["execution_phase"] = (
        "open" if meta.get("execution_phase") == "close" else "close"
    )
    res2.fills[0] = replace(res2.fills[0], metadata=meta)

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "fills[0].execution_phase"


def test_comparator_detects_broken_order_linkage():
    """Comparator normalizes isomorphic UUIDs, but detects broken cross-reference linkage."""
    run_a = {
        "fills": [
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "commission": "5",
                "slippage": "0",
                "timestamp": "2026-01-05T15:00:00",
                "order_id": "ord_AAA",
                "fill_id": "fill_1",
            },
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "commission": "5",
                "slippage": "0",
                "timestamp": "2026-01-06T15:00:00",
                "order_id": "ord_AAA",
                "fill_id": "fill_2",
            },
        ],
        "equity_curve": [
            ("2026-01-05T15:00:00", Decimal("100000")),
            ("2026-01-06T15:00:00", Decimal("100000")),
        ],
        "positions": {},
    }
    # run_b has different UUIDs (ord_XXX), but preserves the exact same 2 fills referencing the same order
    run_b_isomorphic = {
        "fills": [
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "commission": "5",
                "slippage": "0",
                "timestamp": "2026-01-05T15:00:00",
                "order_id": "ord_XXX",
                "fill_id": "fill_99",
            },
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "commission": "5",
                "slippage": "0",
                "timestamp": "2026-01-06T15:00:00",
                "order_id": "ord_XXX",
                "fill_id": "fill_100",
            },
        ],
        "equity_curve": [
            ("2026-01-05T15:00:00", Decimal("100000")),
            ("2026-01-06T15:00:00", Decimal("100000")),
        ],
        "positions": {},
    }
    comp_iso = compare_backtest_runs(run_a, run_b_isomorphic)
    assert comp_iso["is_identical"] is True

    # run_b_broken: the second fill points to a DIFFERENT order (ord_YYY)
    run_b_broken = copy.deepcopy(run_b_isomorphic)
    run_b_broken["fills"][1]["order_id"] = "ord_YYY"
    comp_broken = compare_backtest_runs(run_a, run_b_broken)
    assert comp_broken["is_identical"] is False
    assert comp_broken["first_difference"]["field"] in {"id_linkage", "id_isomorphism"}


def test_comparator_detects_altered_blocked_counts():
    """Comparator detects differences in execution timing blocked counts."""
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()

    timing2 = dict(res2.execution_timing)
    timing2["limit_blocked_count"] = timing2.get("limit_blocked_count", 0) + 1
    res2.execution_timing = timing2

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "execution_timing.limit_blocked_count"


def test_comparator_detects_audit_mismatch():
    """Comparator detects discrepancies in fill execution audits."""
    payload_a = {
        "fills": [
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "commission": "5",
                "slippage": "0",
                "timestamp": "2026-01-05T15:00:00",
            }
        ],
        "fill_execution_audits": [
            {
                "symbol": "600000",
                "session_date": "2026-01-05",
                "bar_timestamp": "2026-01-05T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
            }
        ],
        "equity_curve": [("2026-01-05T15:00:00", Decimal("100000"))],
        "positions": {},
    }
    payload_b = copy.deepcopy(payload_a)
    payload_b["fill_execution_audits"][0]["execution_phase"] = "open"

    comp = compare_backtest_runs(payload_a, payload_b)
    assert comp["is_identical"] is False
    assert (
        comp["first_difference"]["path"] == "fill_execution_audits[0].execution_phase"
    )
