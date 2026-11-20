"""BacktestEngine lifecycle isolation, critical error fail-closed propagation,
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
from server.contracts.http.strategy_models import (
    BacktestCostAssumptions,
    BacktestRequest,
)
from server.services.backtest.deterministic_replay import compare_backtest_runs
from server.services.backtest_views.execution import run_single_backtest
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
        "final_equity": Decimal("100000"),
        "cost_summary": {
            "total_commission": Decimal("10"),
            "total_slippage": Decimal("0"),
            "gross_turnover": Decimal("2000"),
            "total_trades": Decimal("2"),
        },
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
        "fill_execution_audits": [
            {
                "symbol": "600000",
                "order_id": "ord_AAA",
                "fill_id": "fill_1",
                "session_date": "2026-01-05",
                "bar_timestamp": "2026-01-05T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
            },
            {
                "symbol": "600000",
                "order_id": "ord_AAA",
                "fill_id": "fill_2",
                "session_date": "2026-01-06",
                "bar_timestamp": "2026-01-06T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
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
        "final_equity": Decimal("100000"),
        "cost_summary": {
            "total_commission": Decimal("10"),
            "total_slippage": Decimal("0"),
            "gross_turnover": Decimal("2000"),
            "total_trades": Decimal("2"),
        },
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
        "fill_execution_audits": [
            {
                "symbol": "600000",
                "order_id": "ord_XXX",
                "fill_id": "fill_99",
                "session_date": "2026-01-05",
                "bar_timestamp": "2026-01-05T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
            },
            {
                "symbol": "600000",
                "order_id": "ord_XXX",
                "fill_id": "fill_100",
                "session_date": "2026-01-06",
                "bar_timestamp": "2026-01-06T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
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
    run_b_broken["fill_execution_audits"][1]["order_id"] = "ord_YYY"
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


def test_comparator_detects_altered_risk_blocked_count():
    """Comparator detects discrepancy when risk_blocked_count in execution_timing differs."""
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()

    timing2 = dict(res2.execution_timing)
    timing2["risk_blocked_count"] = timing2.get("risk_blocked_count", 0) + 1
    res2.execution_timing = timing2

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "execution_timing.risk_blocked_count"


def test_comparator_detects_execution_context_id_mismatch():
    """Comparator detects discrepancy when execution_context_id differs (different input identity)."""
    payload_a = {
        "dataset_binding": {"execution_context_id": "ctx_alpha_111"},
        "fills": [],
        "equity_curve": [("2026-01-05T15:00:00", Decimal("100000"))],
        "positions": {},
    }
    payload_b = {
        "dataset_binding": {"execution_context_id": "ctx_beta_222"},
        "fills": [],
        "equity_curve": [("2026-01-05T15:00:00", Decimal("100000"))],
        "positions": {},
    }
    comp = compare_backtest_runs(payload_a, payload_b)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["field"] == "execution_context_id"
    assert "execution_context_id" in comp["first_difference"]["path"]


def test_comparator_detects_cost_summary_mismatch():
    """Comparator detects discrepancy when cost_summary numbers differ."""
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()

    # Alter total_commission in cost_summary of res2
    from dataclasses import replace

    res2.cost_summary = replace(
        res2.cost_summary,
        total_commission=res2.cost_summary.total_commission + Decimal("10.00"),
    )

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "cost_summary.total_commission"


def test_comparator_detects_final_equity_mismatch():
    """Comparator detects discrepancy when final_equity differs."""
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()

    res2.final_equity = res2.final_equity + Decimal("500.00")

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "final_equity"


def test_comparator_detects_fill_bar_timestamp_mismatch():
    """Comparator detects discrepancy when fill metadata bar_timestamp differs."""
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()

    meta = dict(res2.fills[0].metadata) if res2.fills[0].metadata else {}
    meta["bar_timestamp"] = "2026-01-05T14:59:00"
    res2.fills[0] = replace(res2.fills[0], metadata=meta)

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is False
    assert comp["first_difference"]["path"] == "fills[0].bar_timestamp"


def test_comparator_legitimate_zero_fills_and_positions():
    """Strategies that legitimately produce zero fills/positions must compare as identical."""

    class NoTradeStrategy(Strategy):
        def on_init(self, symbols: list[Symbol]) -> None:
            pass

        def on_data(self, event: MarketEvent) -> None:
            pass

    res1 = _build_test_engine(NoTradeStrategy("no_trade_1", EventBus())).run()
    res2 = _build_test_engine(NoTradeStrategy("no_trade_2", EventBus())).run()

    assert len(res1.fills) == 0
    assert len(res2.fills) == 0

    comp = compare_backtest_runs(res1, res2)
    assert comp["is_identical"] is True
    assert comp["first_difference"] is None


def _build_real_service_inputs(
    price_sequence: list[float] | None = None,
    dataset_id: str | None = None,
    execution_context_id: str | None = None,
) -> tuple[dict, dict, dict, dict]:
    sym = Symbol("600000")
    inst = make_stock(sym, "浦发银行")
    if price_sequence is None:
        price_sequence = [10.0, 9.0, 8.0, 11.0, 12.0, 13.0]

    dates = [
        datetime(2026, 1, 5, 15, 0, tzinfo=SH),
        datetime(2026, 1, 6, 15, 0, tzinfo=SH),
        datetime(2026, 1, 7, 15, 0, tzinfo=SH),
        datetime(2026, 1, 8, 15, 0, tzinfo=SH),
        datetime(2026, 1, 9, 15, 0, tzinfo=SH),
        datetime(2026, 1, 12, 15, 0, tzinfo=SH),
    ][: len(price_sequence)]

    df = pd.DataFrame(
        [
            {
                "timestamp": dt,
                "open": p,
                "high": p * 1.02,
                "low": p * 0.98,
                "close": p,
                "volume": 10000,
            }
            for dt, p in zip(dates, price_sequence, strict=True)
        ]
    )

    ds_id = dataset_id or ("sha256:" + "a" * 64)
    ctx_id = execution_context_id or "ctx_real_service_001"
    binding = {
        "dataset_id": ds_id,
        "execution_context_id": ctx_id,
        "execution_context": {"content_hash": ctx_id},
    }
    snapshot = {
        "immutable_dataset_id": ds_id,
        "dataset_id": ds_id,
        "date_range": {"start": "2026-01-05", "end": "2026-01-12"},
    }
    return ({sym: inst}, {sym: DataHandler(df, sym)}, binding, snapshot)


def _build_real_service_request(
    dataset_id: str | None = None,
    execution_context_id: str | None = None,
    **kwargs: Any,
) -> BacktestRequest:
    ds_id = dataset_id or ("sha256:" + "a" * 64)
    ctx_id = execution_context_id or "ctx_real_service_001"
    params = {"short_period": 2, "long_period": 3}
    if "params" in kwargs:
        params = kwargs.pop("params")
    return BacktestRequest(
        strategy="dual_ma",
        dataset_id=ds_id,
        execution_context_id=ctx_id,
        start_date="2026-01-05",
        end_date="2026-01-12",
        initial_cash=100000.0,
        params=params,
        **kwargs,
    )


def test_comparator_counterexample_1_missing_context_id_rejected():
    """Counterexample 1: One side lacks execution_context_id -> rejected as input_identity."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out_a = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    out_b = copy.deepcopy(out_a)
    out_b["execution_context_id"] = None
    if "metrics_json" in out_b:
        out_b["metrics_json"]["execution_context_id"] = None
        if "dataset_binding" in out_b["metrics_json"]:
            out_b["metrics_json"]["dataset_binding"]["execution_context_id"] = None
    if "dataset_binding" in out_b:
        out_b["dataset_binding"]["execution_context_id"] = None

    comp = compare_backtest_runs(out_a, out_b)
    assert comp["is_identical"] is False
    assert comp["category"] == "input_identity"
    assert comp["first_difference"]["field"] == "execution_context_id"


def test_comparator_counterexample_2_missing_equity_or_cost_rejected():
    """Counterexample 2: One side lacks cost_summary_json or final_equity -> rejected as missing_evidence."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out_a = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    # 2a: Missing final_equity on run_b
    out_b_no_eq = copy.deepcopy(out_a)
    del out_b_no_eq["final_equity"]
    if "metrics_json" in out_b_no_eq:
        out_b_no_eq["metrics_json"].pop("final_equity", None)
    comp_eq = compare_backtest_runs(out_a, out_b_no_eq)
    assert comp_eq["is_identical"] is False
    assert comp_eq["category"] == "missing_evidence"
    assert comp_eq["first_difference"]["field"] == "final_equity"

    # 2b: Missing cost_summary_json on run_b
    out_b_no_cost = copy.deepcopy(out_a)
    del out_b_no_cost["cost_summary_json"]
    if "metrics_json" in out_b_no_cost:
        out_b_no_cost["metrics_json"].pop("cost_summary", None)
    comp_cost = compare_backtest_runs(out_a, out_b_no_cost)
    assert comp_cost["is_identical"] is False
    assert comp_cost["category"] == "missing_evidence"
    assert comp_cost["first_difference"]["field"] == "cost_summary"


def test_comparator_counterexample_3_fills_without_audits_rejected():
    """Counterexample 3: Both sides have fills but BOTH lack fill_execution_audits -> rejected as missing_evidence."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out_a = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )
    assert len(out_a["fills"]) > 0

    out_a_no_audit = copy.deepcopy(out_a)
    out_a_no_audit["fill_execution_audits"] = []
    out_a_no_audit["metrics_json"]["fill_execution_audits"] = []
    out_a_no_audit["evidence_json"]["fill_execution_audits"] = []

    out_b_no_audit = copy.deepcopy(out_a_no_audit)

    comp = compare_backtest_runs(out_a_no_audit, out_b_no_audit)
    assert comp["is_identical"] is False
    assert comp["category"] == "missing_evidence"
    assert comp["first_difference"]["field"] == "fill_execution_audits"


def test_comparator_counterexample_4_empty_payload_rejected():
    """Counterexample 4: compare_backtest_runs({}, {}) -> rejected as missing_evidence."""
    comp = compare_backtest_runs({}, {})
    assert comp["is_identical"] is False
    assert comp["category"] == "missing_evidence"
    assert comp["first_difference"]["field"] == "run_payload"


def test_comparator_counterexample_5_input_qualification_change_rejected():
    """Counterexample 5: dataset_id, cost_assumptions, execution_window, execution_policy differences -> rejected as input_identity."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out_a = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    # 5a: dataset_id change
    out_diff_ds = copy.deepcopy(out_a)
    out_diff_ds["metrics_json"]["dataset_id"] = "sha256:" + "b" * 64
    if "dataset_binding" in out_diff_ds.get("metrics_json", {}):
        out_diff_ds["metrics_json"]["dataset_binding"]["dataset_id"] = (
            "sha256:" + "b" * 64
        )
    if "config" in out_diff_ds:
        out_diff_ds["config"]["dataset_id"] = "sha256:" + "b" * 64
    comp_ds = compare_backtest_runs(out_a, out_diff_ds)
    assert comp_ds["is_identical"] is False
    assert comp_ds["category"] == "input_identity"
    assert comp_ds["first_difference"]["field"] == "dataset_id"

    # 5b: cost_assumptions change
    out_diff_cost = copy.deepcopy(out_a)
    out_diff_cost["cost_assumptions"] = {
        "commission_ratio": 0.001,
        "slippage_bps": 50.0,
    }
    comp_cost = compare_backtest_runs(out_a, out_diff_cost)
    assert comp_cost["is_identical"] is False
    assert comp_cost["category"] == "input_identity"
    assert comp_cost["first_difference"]["field"] == "cost_assumptions"

    # 5c: execution_window change
    out_diff_window = copy.deepcopy(out_a)
    out_diff_window["execution_window"] = {
        "start_date": "2026-01-01",
        "end_date": "2026-01-12",
    }
    comp_window = compare_backtest_runs(out_a, out_diff_window)
    assert comp_window["is_identical"] is False
    assert comp_window["category"] == "input_identity"
    assert comp_window["first_difference"]["field"] == "execution_window"

    # 5d: execution policy (strict_security_status) change
    out_diff_policy = copy.deepcopy(out_a)
    out_diff_policy["strict_security_status"] = True
    comp_policy = compare_backtest_runs(out_a, out_diff_policy)
    assert comp_policy["is_identical"] is False
    assert comp_policy["category"] == "input_identity"
    assert comp_policy["first_difference"]["field"] == "strict_security_status"


def test_comparator_counterexample_6_missing_positions_rejected():
    """Counterexample 6: Service payload missing positions -> rejected as missing_evidence, NOT defaulting to 0 positions."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out_a = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    out_no_pos_a = copy.deepcopy(out_a)
    del out_no_pos_a["positions"]
    out_no_pos_a["metrics_json"].pop("positions", None)
    out_no_pos_a["evidence_json"].pop("positions", None)

    out_no_pos_b = copy.deepcopy(out_no_pos_a)

    comp = compare_backtest_runs(out_no_pos_a, out_no_pos_b)
    assert comp["is_identical"] is False
    assert comp["category"] == "missing_evidence"
    assert comp["first_difference"]["field"] == "positions"


def test_real_service_same_process_a_to_a():
    """Real service entrypoint: unmocked run_single_backtest A1 vs A2 in same process produces identical replay."""
    from types import SimpleNamespace

    inputs1 = _build_real_service_inputs()
    req1 = _build_real_service_request()
    out1 = run_single_backtest(
        req1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs1
    )

    inputs2 = _build_real_service_inputs()
    req2 = _build_real_service_request()
    out2 = run_single_backtest(
        req2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs2
    )

    comp = compare_backtest_runs(out1, out2)
    assert comp["is_identical"] is True
    assert comp["category"] == "identical"
    assert comp["first_difference"] is None
    assert comp["details"]["comparison_scope"] == "full_replay"
    assert comp["details"]["fill_count"] > 0
    assert comp["details"]["position_count"] > 0


def test_real_service_interleaved_a_b_a():
    """Real service entrypoint: A1 -> B -> A2 isolates runs, A1 vs A2 identical, A1 vs B detects discrepancy."""
    from types import SimpleNamespace

    inputs_a1 = _build_real_service_inputs()
    req_a1 = _build_real_service_request()
    out_a1 = run_single_backtest(
        req_a1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_a1
    )

    # Strategy B with different parameters
    inputs_b = _build_real_service_inputs()
    req_b = _build_real_service_request(params={"short_period": 3, "long_period": 4})
    out_b = run_single_backtest(
        req_b, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_b
    )

    inputs_a2 = _build_real_service_inputs()
    req_a2 = _build_real_service_request()
    out_a2 = run_single_backtest(
        req_a2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_a2
    )

    # A1 vs A2 is identical
    comp_aa = compare_backtest_runs(out_a1, out_a2)
    assert comp_aa["is_identical"] is True
    assert comp_aa["category"] == "identical"

    # A1 vs B detects parameter input identity difference
    comp_ab = compare_backtest_runs(out_a1, out_b)
    assert comp_ab["is_identical"] is False
    assert comp_ab["category"] in {"input_identity", "output_difference"}


def test_real_service_after_failure():
    """Real service entrypoint: Engine/service failure in between does not contaminate subsequent A2 run."""
    from types import SimpleNamespace

    from server.services.research.datasets import ResearchDatasetError

    inputs_a1 = _build_real_service_inputs()
    req_a1 = _build_real_service_request()
    out_a1 = run_single_backtest(
        req_a1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_a1
    )

    # Failed run: mismatched context ID triggers ResearchDatasetError
    bad_req = _build_real_service_request(execution_context_id="ctx_wrong_mismatch")
    with pytest.raises(ResearchDatasetError):
        run_single_backtest(
            bad_req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_a1
        )

    # Subsequent clean run A2
    inputs_a2 = _build_real_service_inputs()
    req_a2 = _build_real_service_request()
    out_a2 = run_single_backtest(
        req_a2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_a2
    )

    comp = compare_backtest_runs(out_a1, out_a2)
    assert comp["is_identical"] is True
    assert comp["category"] == "identical"


def test_real_service_legitimate_zero_fills_and_zero_positions():
    """Real service entrypoint: Flat price sequence legitimately produces 0 fills and 0 positions, compares identical."""
    from types import SimpleNamespace

    flat_prices = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    inputs1 = _build_real_service_inputs(price_sequence=flat_prices)
    req1 = _build_real_service_request()
    out1 = run_single_backtest(
        req1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs1
    )

    inputs2 = _build_real_service_inputs(price_sequence=flat_prices)
    req2 = _build_real_service_request()
    out2 = run_single_backtest(
        req2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs2
    )

    assert len(out1["fills"]) == 0
    assert out1["positions"] == {}

    comp = compare_backtest_runs(out1, out2)
    assert comp["is_identical"] is True
    assert comp["category"] == "identical"
    assert comp["details"]["fill_count"] == 0
    assert comp["details"]["position_count"] == 0


def test_real_service_with_buy_and_nonzero_ending_positions():
    """Real service entrypoint: Golden cross produces 1 buy fill and 1 ending position, compares identical."""
    from types import SimpleNamespace

    inputs1 = _build_real_service_inputs()
    req1 = _build_real_service_request()
    out1 = run_single_backtest(
        req1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs1
    )

    inputs2 = _build_real_service_inputs()
    req2 = _build_real_service_request()
    out2 = run_single_backtest(
        req2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs2
    )

    assert len(out1["fills"]) == 1
    assert "600000" in out1["positions"]
    assert out1["positions"]["600000"]["quantity"] == "100"

    comp = compare_backtest_runs(out1, out2)
    assert comp["is_identical"] is True
    assert comp["category"] == "identical"
    assert comp["details"]["fill_count"] == 1
    assert comp["details"]["position_count"] == 1


def test_real_service_missing_evidence_controls():
    """Real service entrypoint: Stripping key evidence from real service output triggers missing_evidence."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    # 1. Missing final_equity
    p_no_eq = copy.deepcopy(out)
    del p_no_eq["final_equity"]
    p_no_eq["metrics_json"].pop("final_equity", None)
    assert compare_backtest_runs(out, p_no_eq)["category"] == "missing_evidence"

    # 2. Missing cost_summary_json
    p_no_cost = copy.deepcopy(out)
    del p_no_cost["cost_summary_json"]
    p_no_cost["metrics_json"].pop("cost_summary", None)
    assert compare_backtest_runs(out, p_no_cost)["category"] == "missing_evidence"

    # 3. Missing positions
    p_no_pos = copy.deepcopy(out)
    del p_no_pos["positions"]
    p_no_pos["metrics_json"].pop("positions", None)
    p_no_pos["evidence_json"].pop("positions", None)
    assert compare_backtest_runs(out, p_no_pos)["category"] == "missing_evidence"

    # 4. Missing audits when fills > 0
    p_no_audit = copy.deepcopy(out)
    p_no_audit["fill_execution_audits"] = []
    p_no_audit["metrics_json"]["fill_execution_audits"] = []
    p_no_audit["evidence_json"]["fill_execution_audits"] = []
    assert compare_backtest_runs(out, p_no_audit)["category"] == "missing_evidence"


def test_real_service_numerical_perturbations():
    """Real service entrypoint: Perturbing real service numerical values triggers output_difference."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )

    # 1. Perturb final_equity
    p_eq = copy.deepcopy(out)
    p_eq["final_equity"] = float(out["final_equity"]) + 100.0
    comp_eq = compare_backtest_runs(out, p_eq)
    assert comp_eq["is_identical"] is False
    assert comp_eq["category"] == "output_difference"
    assert comp_eq["first_difference"]["path"] == "final_equity"

    # 2. Perturb cost_summary_json
    p_cost = copy.deepcopy(out)
    p_cost["cost_summary_json"]["total_commission"] = (
        float(p_cost["cost_summary_json"]["total_commission"]) + 50.0
    )
    comp_cost = compare_backtest_runs(out, p_cost)
    assert comp_cost["is_identical"] is False
    assert comp_cost["category"] == "output_difference"
    assert comp_cost["first_difference"]["path"] == "cost_summary.total_commission"

    # 3. Perturb bar_timestamp in fills
    p_bar = copy.deepcopy(out)
    p_bar["fills"][0]["bar_timestamp"] = "2026-01-05T14:50:00"
    comp_bar = compare_backtest_runs(out, p_bar)
    assert comp_bar["is_identical"] is False
    assert comp_bar["category"] == "output_difference"
    assert comp_bar["first_difference"]["path"] == "fills[0].bar_timestamp"

    # 4. Perturb position quantity
    p_pos = copy.deepcopy(out)
    p_pos["positions"]["600000"]["quantity"] = "200"
    comp_pos = compare_backtest_runs(out, p_pos)
    assert comp_pos["is_identical"] is False
    assert comp_pos["category"] == "output_difference"
    assert comp_pos["first_difference"]["path"] == "positions['600000'].quantity"

    # 5. Perturb risk_blocked_count
    p_risk = copy.deepcopy(out)
    p_risk["metrics_json"]["execution_timing"]["risk_blocked_count"] = 1
    comp_risk = compare_backtest_runs(out, p_risk)
    assert comp_risk["is_identical"] is False
    assert comp_risk["category"] == "output_difference"
    assert (
        comp_risk["first_difference"]["path"] == "execution_timing.risk_blocked_count"
    )


def test_comparator_detects_altered_policy_id():
    """Altering policy_id on BacktestResult or service payload returns category='input_identity'."""
    from types import SimpleNamespace

    # 1. BacktestResult
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = copy.deepcopy(res1)
    if res2.execution_timing is None:
        res2.execution_timing = {}
    res2.execution_timing["policy_id"] = "policy_custom_altered"
    comp_res = compare_backtest_runs(res1, res2)
    assert comp_res["is_identical"] is False
    assert comp_res["category"] == "input_identity"
    assert comp_res["first_difference"]["field"] == "policy_id"

    # 2. Service payload
    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out1 = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )
    out2 = copy.deepcopy(out1)
    if "execution_timing" in out2:
        out2["execution_timing"]["policy_id"] = "policy_custom_altered"
    out2["metrics_json"]["execution_timing"]["policy_id"] = "policy_custom_altered"
    comp_out = compare_backtest_runs(out1, out2)
    assert comp_out["is_identical"] is False
    assert comp_out["category"] == "input_identity"
    assert comp_out["first_difference"]["field"] == "policy_id"


def test_comparator_detects_altered_initial_cash():
    """Altering initial_cash on BacktestResult or service payload returns category='input_identity'."""
    from types import SimpleNamespace

    # 1. BacktestResult
    res1 = _build_test_engine(SimpleStepStrategy(buy_step=1, sell_step=2)).run()
    res2 = copy.deepcopy(res1)
    res2.initial_cash = Decimal("200000")
    comp_res = compare_backtest_runs(res1, res2)
    assert comp_res["is_identical"] is False
    assert comp_res["category"] == "input_identity"
    assert comp_res["first_difference"]["field"] == "initial_cash"

    # 2. Service payload
    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out1 = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )
    out2 = copy.deepcopy(out1)
    out2["initial_cash"] = 250000.0
    out2["metrics_json"]["initial_cash"] = 250000.0
    comp_out = compare_backtest_runs(out1, out2)
    assert comp_out["is_identical"] is False
    assert comp_out["category"] == "input_identity"
    assert comp_out["first_difference"]["field"] == "initial_cash"


def test_comparator_detects_effective_params_mismatch_with_identical_trades():
    """Different effective params (when params=None via top-level fields) with zero trades returns input_identity."""
    from types import SimpleNamespace

    flat_prices = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    inputs1 = _build_real_service_inputs(price_sequence=flat_prices)
    req1 = _build_real_service_request(
        params=None,
        short_period=2,
        long_period=3,
    )
    out1 = run_single_backtest(
        req1, SimpleNamespace(), None, preloaded_dataset_inputs=inputs1
    )

    inputs2 = _build_real_service_inputs(price_sequence=flat_prices)
    req2 = _build_real_service_request(
        params=None,
        short_period=3,
        long_period=4,
    )
    out2 = run_single_backtest(
        req2, SimpleNamespace(), None, preloaded_dataset_inputs=inputs2
    )

    assert len(out1["fills"]) == 0
    assert len(out2["fills"]) == 0
    assert out1["metrics_json"]["strategy_metadata"]["params"] == {
        "short_period": 2,
        "long_period": 3,
    }
    assert out2["metrics_json"]["strategy_metadata"]["params"] == {
        "short_period": 3,
        "long_period": 4,
    }

    comp = compare_backtest_runs(out1, out2)
    assert comp["is_identical"] is False
    assert comp["category"] == "input_identity"
    assert comp["first_difference"]["field"] == "strategy_metadata"


def test_comparator_audit_completeness_and_coverage():
    """Incomplete, duplicate or missing audit records return missing_evidence; legitimate 0 fills returns identical."""
    from types import SimpleNamespace

    inputs = _build_real_service_inputs()
    req = _build_real_service_request()
    out = run_single_backtest(
        req, SimpleNamespace(), None, preloaded_dataset_inputs=inputs
    )
    assert len(out["fills"]) == 1
    assert len(out["fill_execution_audits"]) == 1

    # Base payload with 2 fills and 2 complete valid audits
    base = copy.deepcopy(out)
    fill2 = copy.deepcopy(base["fills"][0])
    fill2["fill_id"] = "fill_synth_002"
    fill2["order_id"] = "ord_synth_002"
    fill2["timestamp"] = "2026-01-06T15:00:00"
    base["fills"].append(fill2)

    audit2 = copy.deepcopy(base["fill_execution_audits"][0])
    audit2["fill_id"] = "fill_synth_002"
    audit2["order_id"] = "ord_synth_002"
    audit2["session_date"] = "2026-01-06"
    audit2["bar_timestamp"] = "2026-01-06T15:00:00"
    base["fill_execution_audits"].append(audit2)

    # Valid 2 fills and 2 complete audits compares identical with itself
    comp_valid = compare_backtest_runs(base, copy.deepcopy(base))
    assert comp_valid["is_identical"] is True
    assert comp_valid["category"] == "identical"

    # Counterexample 1: 2 fills with 1 audit entry -> missing_evidence
    p1 = copy.deepcopy(base)
    p1["fill_execution_audits"] = [base["fill_execution_audits"][0]]
    comp1 = compare_backtest_runs(base, p1)
    assert comp1["is_identical"] is False
    assert comp1["category"] == "missing_evidence"
    assert comp1["first_difference"]["field"] == "fill_execution_audits"

    # Counterexample 2: 2 fills with empty audits [{}, {}] -> missing_evidence
    p2 = copy.deepcopy(base)
    p2["fill_execution_audits"] = [{}, {}]
    comp2 = compare_backtest_runs(base, p2)
    assert comp2["is_identical"] is False
    assert comp2["category"] == "missing_evidence"
    assert comp2["first_difference"]["field"] in (
        "symbol",
        "session_date",
        "bar_timestamp",
        "execution_phase",
        "execution_model",
    )

    # Counterexample 3: 2 fills with duplicate padded audits [audit0, audit0] -> missing_evidence
    p3 = copy.deepcopy(base)
    p3["fill_execution_audits"] = [
        copy.deepcopy(base["fill_execution_audits"][0]),
        copy.deepcopy(base["fill_execution_audits"][0]),
    ]
    comp3 = compare_backtest_runs(base, p3)
    assert comp3["is_identical"] is False
    assert comp3["category"] == "missing_evidence"
    assert comp3["first_difference"]["field"] in (
        "fill_id",
        "order_id",
        "fill_execution_audits",
    )

    # Counterexample 3b: duplicate audit entries sharing the exact same fill_key
    p3_dup_key = {
        "fills": [
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "timestamp": "2026-01-05T15:00:00",
            },
            {
                "symbol": "600000",
                "side": "buy",
                "price": "10",
                "quantity": "100",
                "timestamp": "2026-01-06T15:00:00",
            },
        ],
        "fill_execution_audits": [
            {
                "symbol": "600000",
                "session_date": "2026-01-05",
                "bar_timestamp": "2026-01-05T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
            },
            {
                "symbol": "600000",
                "session_date": "2026-01-05",
                "bar_timestamp": "2026-01-05T15:00:00",
                "execution_phase": "close",
                "execution_model": "next_bar_close",
            },
        ],
        "final_equity": Decimal("100000"),
        "cost_summary": {
            "total_commission": Decimal("10"),
            "total_slippage": Decimal("0"),
            "gross_turnover": Decimal("2000"),
            "total_trades": Decimal("2"),
        },
        "equity_curve": [("2026-01-05T15:00:00", Decimal("100000"))],
        "positions": {},
    }
    comp_dup = compare_backtest_runs(p3_dup_key, p3_dup_key)
    assert comp_dup["is_identical"] is False
    assert comp_dup["category"] == "missing_evidence"
    assert comp_dup["first_difference"]["field"] == "fill_execution_audits"
    assert "duplicate" in comp_dup["first_difference"]["actual"]

    # Valid 0 fills and 0 audits -> identical
    flat_prices = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    inputs_flat = _build_real_service_inputs(price_sequence=flat_prices)
    req_flat = _build_real_service_request()
    out_flat1 = run_single_backtest(
        req_flat, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_flat
    )
    out_flat2 = run_single_backtest(
        req_flat, SimpleNamespace(), None, preloaded_dataset_inputs=inputs_flat
    )
    assert len(out_flat1["fills"]) == 0
    assert len(out_flat1["fill_execution_audits"]) == 0
    comp_flat = compare_backtest_runs(out_flat1, out_flat2)
    assert comp_flat["is_identical"] is True
    assert comp_flat["category"] == "identical"
