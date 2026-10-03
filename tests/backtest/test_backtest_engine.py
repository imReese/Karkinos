"""BacktestEngine 集成测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestExecutionConfig
from backtest.result import BacktestResult
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent, RiskDecisionEvent, SignalEvent
from core.types import ZERO, BarFrequency, CommissionType, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_etf, make_gold_spot, make_stock
from domain.portfolio import Portfolio
from domain.position import Position
from execution.commission import ETFCommission, MultiAssetCommission, StockACommission
from execution.slippage import PercentSlippage
from risk.limits import PositionLimitRule
from risk.manager import RiskManager
from server.db import AppDatabase
from strategy.base import Strategy


def _direct_order_market(symbol: Symbol) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2024, 1, 1),
        symbol=symbol,
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        volume=Decimal("100000"),
    )


class SimpleBuyStrategy(Strategy):
    """测试用简单策略：第 5 根 K 线全仓买入，之后不动。"""

    def __init__(self, event_bus: EventBus) -> None:
        super().__init__("simple_buy", event_bus)
        self._count = 0

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self._count += 1
        if self._count == 5:
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))


class FinalBarBuyStrategy(Strategy):
    """测试用策略：最后一根 K 线才开仓。"""

    def __init__(self, event_bus: EventBus, final_bar: int) -> None:
        super().__init__("final_bar_buy", event_bus)
        self._count = 0
        self._final_bar = final_bar

    def on_init(self, symbols: list[Symbol]) -> None:
        self.symbols = symbols

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self._count += 1
        if self._count == self._final_bar:
            self.emit_signal(event.symbol, target_weight=1.0, price=float(event.close))


def make_price_df(base: float = 1800.0, n: int = 30, seed: int = 42) -> pd.DataFrame:
    """生成模拟行情 DataFrame。"""
    import numpy as np

    np.random.seed(seed)
    dates = pd.bdate_range("2024-01-02", periods=n)
    changes = np.random.randn(n) * 5
    close = base + np.cumsum(changes)
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": [10000.0] * n,
        }
    )


class TestBacktestEngine:
    def test_simple_backtest_runs(self):
        """简单回测能完整运行。"""
        symbol = Symbol("600519")
        inst = make_stock("600519", "贵州茅台")
        df = make_price_df()

        data_handler = DataHandler(df, symbol)
        bus = EventBus()
        strategy = SimpleBuyStrategy(bus)

        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: data_handler},
            initial_cash=Decimal("1000000"),
        )
        result = engine.run()

        assert result is not None
        assert len(result.equity_curve) > 0
        assert result.initial_cash == Decimal("1000000")

    def test_multi_asset_equity_curve_keeps_one_point_per_timestamp(self):
        """Performance history must represent portfolio timestamps, not symbol events."""
        left = Symbol("600001")
        right = Symbol("600002")
        left_df = make_price_df(base=20.0, n=8, seed=1)
        right_df = make_price_df(base=30.0, n=8, seed=2)

        engine = BacktestEngine(
            strategy=SimpleBuyStrategy(EventBus()),
            instruments={
                left: make_stock(str(left), "left"),
                right: make_stock(str(right), "right"),
            },
            data_handlers={
                left: DataHandler(left_df, left),
                right: DataHandler(right_df, right),
            },
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        assert len(result.equity_curve) == 8
        timestamps = [timestamp for timestamp, _ in result.equity_curve]
        assert timestamps == sorted(set(timestamps))
        assert result.final_equity == result.equity_curve[-1][1]

    def test_portfolio_updates_after_fill(self):
        """回测后持仓应正确更新。"""
        symbol = Symbol("600519")
        inst = make_stock("600519", "贵州茅台")
        df = make_price_df()

        data_handler = DataHandler(df, symbol)
        bus = EventBus()
        strategy = SimpleBuyStrategy(bus)

        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: data_handler},
            initial_cash=Decimal("1000000"),
        )
        result = engine.run()

        # 策略在第 5 根 K 线发出买入信号，应有持仓
        pos = result.positions.get(symbol)
        assert pos is not None
        assert pos.quantity > ZERO

    def test_final_bar_signal_has_no_future_fill(self):
        """A final-bar signal cannot invent an execution opportunity."""
        symbol = Symbol("600519")
        inst = make_stock("600519", "贵州茅台")
        df = make_price_df(n=6)

        engine = BacktestEngine(
            strategy=FinalBarBuyStrategy(EventBus(), final_bar=len(df)),
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(df, symbol)},
            initial_cash=Decimal("1000000"),
        )
        result = engine.run()

        assert result.fills == []
        assert result.execution_timing["pending_signal_count"] == 1
        assert result.final_equity == result.initial_cash
        assert result.final_equity == result.equity_curve[-1][1]
        assert result.metrics.final_equity == pytest.approx(float(result.final_equity))

    def test_t_plus_1_settlement(self):
        """T+1 冻结应在次日解冻。"""
        symbol = Symbol("600519")
        inst = make_stock("600519", "贵州茅台")
        df = make_price_df()

        data_handler = DataHandler(df, symbol)
        bus = EventBus()
        strategy = SimpleBuyStrategy(bus)

        engine = BacktestEngine(
            strategy=strategy,
            instruments={symbol: inst},
            data_handlers={symbol: data_handler},
        )
        result = engine.run()

        # 回测结束后所有持仓应已解冻
        pos = result.positions.get(symbol)
        if pos:
            assert pos.frozen_qty == ZERO or pos.available_qty > ZERO

    def test_multi_asset_commission_uses_slipped_fill_price(self):
        symbol = Symbol("510300")
        inst = make_etf("510300", "沪深300ETF")
        df = make_price_df(base=100.0)
        engine = BacktestEngine(
            strategy=SimpleBuyStrategy(EventBus()),
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(df, symbol)},
            slippage_model=PercentSlippage(Decimal("0.01")),
        )
        position = Position(symbol)
        position.update_on_fill("buy", Decimal("100"), Decimal("100"))
        position.advance_settlement_day()
        engine.portfolio.positions[symbol] = position
        engine._current_market_event = _direct_order_market(symbol)
        engine._on_order_event(
            OrderEvent(
                timestamp=datetime(2024, 1, 1),
                order_id="ORD-ETF",
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                price=Decimal("100"),
            )
        )

        assert engine.fills[0].fill_price == Decimal("99.00")
        assert engine.fills[0].commission == ETFCommission().calculate(
            OrderSide.SELL, Decimal("99.00"), Decimal("100")
        )

    def test_multi_asset_commission_uses_symbol_override_and_review_version(self):
        symbol = Symbol("600519")
        calculator = MultiAssetCommission(
            fee_rule_version="reviewed-fee-schedule-reference"
        )
        calculator.set_commission(
            CommissionType.STOCK_A,
            StockACommission(
                commission_rate=Decimal("0.001"),
                min_commission=Decimal("0"),
            ),
        )
        calculator.set_symbol_commission(
            str(symbol),
            StockACommission(
                commission_rate=Decimal("0.01"),
                min_commission=Decimal("0"),
                fee_rule_id="reviewed-symbol-rule",
            ),
        )
        engine = BacktestEngine(
            strategy=SimpleBuyStrategy(EventBus()),
            instruments={symbol: make_stock(str(symbol), "reviewed stock")},
            data_handlers={symbol: DataHandler(make_price_df(), symbol)},
            commission_calc=calculator,
        )

        engine._current_market_event = _direct_order_market(symbol)
        engine._on_order_event(
            OrderEvent(
                timestamp=datetime(2024, 1, 1),
                order_id="ORD-REVIEWED-FEE",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                price=Decimal("100"),
            )
        )

        fill = engine.fills[0]
        assert fill.commission == Decimal("100.10000")
        assert fill.fee_breakdown["commission"] == "100.00"
        assert fill.fee_rule_id == "reviewed-symbol-rule"
        assert fill.fee_rule_version == "reviewed-fee-schedule-reference"

    def test_backtest_engine_persists_order_and_fill_when_db_is_supplied(
        self,
        tmp_path,
    ):
        symbol = Symbol("600519")
        inst = make_stock("600519", "贵州茅台")
        db = AppDatabase(tmp_path / "app.db")
        db.init_sync()
        engine = BacktestEngine(
            strategy=SimpleBuyStrategy(EventBus()),
            instruments={symbol: inst},
            data_handlers={symbol: DataHandler(make_price_df(), symbol)},
            db=db,
        )

        engine._current_market_event = _direct_order_market(symbol)
        engine._on_order_event(
            OrderEvent(
                timestamp=datetime(2024, 1, 1),
                order_id="ORD-BACKTEST-1",
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                price=Decimal("100"),
                intent_id="INTENT-BACKTEST-1",
                risk_decision_id="RISK-BACKTEST-1",
                execution_mode="paper",
            )
        )

        saved_order = db.get_order_sync("ORD-BACKTEST-1")
        fills = db.list_fills_sync(order_id="ORD-BACKTEST-1")

        assert saved_order is not None
        assert saved_order["status"] == "filled"
        assert saved_order["execution_mode"] == "backtest"
        assert saved_order["source"] == "backtest_execution"
        assert len(fills) == 1
        assert fills[0]["execution_mode"] == "backtest"
        assert fills[0]["source"] == "backtest_execution"
        assert fills[0]["fill_price"] == 100.0


class TestBacktestResult:
    def test_total_return_calculation(self):
        result = BacktestResult(
            equity_curve=[(datetime(2024, 1, 1), Decimal("1000000"))],
            positions={},
            initial_cash=Decimal("1000000"),
            final_equity=Decimal("1100000"),
        )
        assert result.total_return == Decimal("0.1")
        assert result.total_pnl == Decimal("100000")

    def test_duration_days(self):
        result = BacktestResult(
            equity_curve=[
                (datetime(2024, 1, 1), Decimal("1000000")),
                (datetime(2024, 1, 31), Decimal("1050000")),
            ],
            positions={},
            initial_cash=Decimal("1000000"),
            final_equity=Decimal("1050000"),
        )
        assert result.duration_days == 31

    def test_result_has_metrics_fills_and_cost_summary_defaults(self):
        result = BacktestResult(
            equity_curve=[(datetime(2024, 1, 1), Decimal("1000000"))],
            positions={},
            initial_cash=Decimal("1000000"),
            final_equity=Decimal("1000000"),
        )

        assert result.metrics.sharpe == 0.0
        assert result.fills == []
        assert result.cost_summary.total_commission == Decimal("0")
        assert result.execution_timing is None


class FirstBarTargetStrategy(Strategy):
    def __init__(self, target_symbol=None, *, exit_on_second=False):
        super().__init__("first_bar_target", EventBus())
        self.target_symbol = target_symbol
        self.exit_on_second = exit_on_second
        self.observed = []
        self.initialized = False

    def on_init(self, symbols):
        self.initialized = True
        self.symbols = symbols

    def on_data(self, event):
        self._last_timestamp = event.timestamp
        self.observed.append(event)
        if len(self.observed) == 1:
            self.emit_signal(
                self.target_symbol or event.symbol, 1.0, float(event.close)
            )
        elif len(self.observed) == 2 and self.exit_on_second:
            self.emit_signal(event.symbol, 0.0, float(event.close))


def _timing_frame(closes, *, volume=None, available_at=None):
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-05 15:00", periods=len(closes)),
            "open": [value - 1 for value in closes],
            "high": closes,
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": volume or [100000] * len(closes),
        }
    )
    if available_at is not None:
        frame["available_at"] = available_at
    return frame


def _timing_engine(frame, *, strategy=None, execution_config=None):
    symbol = Symbol("600000")
    return BacktestEngine(
        strategy=strategy or FirstBarTargetStrategy(),
        instruments={symbol: make_stock(str(symbol), "fixture")},
        data_handlers={symbol: DataHandler(frame, symbol)},
        initial_cash=Decimal("10000"),
        execution_config=execution_config,
    )


def test_pending_target_sizes_at_next_close_and_does_not_fill_at_next_open():
    frame = _timing_frame([10, 10.5])
    result = _timing_engine(frame).run()
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.timestamp == frame.iloc[1]["timestamp"]
    assert fill.fill_price == Decimal("10.5")
    assert fill.fill_quantity == Decimal("900")
    assert result.execution_timing["policy_id"] == "karkinos.backtest.next_bar_close.v2"
    assert result.execution_timing["historical_pit_verified"] is False


def test_another_symbol_at_same_timestamp_cannot_execute_new_signal():
    left, right = Symbol("600000"), Symbol("600001")
    frame = _timing_frame([10, 10.5])
    engine = BacktestEngine(
        strategy=FirstBarTargetStrategy(target_symbol=right),
        instruments={
            left: make_stock(str(left), "left"),
            right: make_stock(str(right), "right"),
        },
        data_handlers={
            right: DataHandler(frame, right),
            left: DataHandler(frame, left),
        },
        initial_cash=Decimal("10000"),
    )
    result = engine.run()
    assert [(fill.symbol, fill.timestamp) for fill in result.fills] == [
        (right, frame.iloc[1]["timestamp"])
    ]


@pytest.mark.parametrize(
    ("closes", "volumes", "reason"),
    [([10, 11], [100000, 100000], "limit"), ([10, 10.5], [100000, 0], "suspension")],
)
def test_next_bar_constraints_apply_to_all_strategies(closes, volumes, reason):
    result = _timing_engine(_timing_frame(closes, volume=volumes)).run()
    assert result.fills == []
    assert result.execution_timing[f"{reason}_blocked_count"] == 1


def test_pending_exit_respects_limit_down_on_execution_bar():
    strategy = FirstBarTargetStrategy(exit_on_second=True)
    result = _timing_engine(_timing_frame([10, 10.5, 9.45]), strategy=strategy).run()
    assert [fill.side for fill in result.fills] == [OrderSide.BUY]
    assert result.execution_timing["limit_blocked_count"] == 1


def test_pending_exit_fills_after_t_plus_one_settlement():
    strategy = FirstBarTargetStrategy(exit_on_second=True)
    result = _timing_engine(_timing_frame([10, 10.5, 10.6]), strategy=strategy).run()
    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert result.positions[Symbol("600000")].quantity == ZERO


@pytest.mark.parametrize(
    ("instrument", "expected_sides", "remaining_quantity", "blocked"),
    [
        (make_gold_spot(), [OrderSide.BUY, OrderSide.SELL], ZERO, 0),
        (make_stock("600000", "fixture"), [OrderSide.BUY], Decimal("100"), 1),
    ],
    ids=["t_plus_zero_same_day_sale", "t_plus_one_same_day_sale_rejected"],
)
def test_direct_same_day_sell_respects_instrument_settlement(
    instrument, expected_sides, remaining_quantity, blocked, caplog
):
    class IntradayDirectOrders(Strategy):
        def on_init(self, symbols):
            self.count = 0

        def on_data(self, event):
            self.count += 1
            self.event_bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id=f"intraday-{self.count}",
                    symbol=event.symbol,
                    side=OrderSide.BUY if self.count == 1 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=Decimal("100"),
                    price=event.close,
                )
            )

    frame = _timing_frame([400, 400])
    frame["timestamp"] = pd.date_range("2026-04-09 10:00", periods=2, freq="min")
    engine = BacktestEngine(
        strategy=IntradayDirectOrders("direct", EventBus()),
        instruments={instrument.symbol: instrument},
        data_handlers={
            instrument.symbol: DataHandler(
                frame, instrument.symbol, frequency=BarFrequency.MIN_1
            )
        },
        initial_cash=Decimal("100000"),
    )

    result = engine.run()

    assert [fill.side for fill in result.fills] == expected_sides
    assert (
        result.fills[-1].timestamp == frame.iloc[len(expected_sides) - 1]["timestamp"]
    )
    assert result.positions[instrument.symbol].quantity == remaining_quantity
    assert result.execution_timing["risk_blocked_count"] == blocked
    assert "Handler" not in caplog.text


def test_execution_time_risk_rejection_prevents_fill():
    engine = _timing_engine(_timing_frame([10, 10.5]))
    engine.risk_manager.add_rule(PositionLimitRule(Decimal("100")))
    decisions = []
    engine.event_bus.subscribe(RiskDecisionEvent, decisions.append)
    result = engine.run()
    assert result.fills == []
    assert result.execution_timing["risk_blocked_count"] == 1
    assert len(decisions) == 1
    assert decisions[0].passed is False
    assert decisions[0].resulting_order_id is None


@pytest.mark.parametrize("missing", [False, True])
def test_observed_mode_rejects_unavailable_input_before_strategy_observes_it(missing):
    strategy = FirstBarTargetStrategy()
    frame = _timing_frame([10, 10.5])
    if not missing:
        frame["available_at"] = frame["timestamp"] + pd.Timedelta(seconds=1)
    engine = _timing_engine(
        frame,
        strategy=strategy,
        execution_config=BacktestExecutionConfig(availability_mode="observed"),
    )
    with pytest.raises(ValueError, match="backtest_observation_"):
        engine.run()
    assert strategy.observed == []
    assert strategy.initialized is False
    assert engine.fills == []


def test_observed_mode_preserves_availability_and_accepts_visible_bars():
    frame = _timing_frame([10, 10.5])
    frame["available_at"] = frame["timestamp"]
    engine = _timing_engine(
        frame, execution_config=BacktestExecutionConfig(availability_mode="observed")
    )
    result = engine.run()
    assert engine.strategy.observed[0].available_at == frame.iloc[0]["available_at"]
    assert result.fills[0].timestamp > engine.strategy.observed[0].available_at
    assert result.execution_timing["availability_mode"] == "observed"


def test_historical_snapshot_mode_keeps_late_availability_explicit():
    frame = _timing_frame([10, 10.5])
    frame["available_at"] = frame["timestamp"] + pd.Timedelta(days=30)
    engine = _timing_engine(frame)
    result = engine.run()
    assert result.fills
    assert engine.strategy.observed[0].available_at == frame.iloc[0]["available_at"]
    assert result.execution_timing["availability_mode"] == "historical_snapshot"
    assert result.execution_timing["historical_pit_verified"] is False


@pytest.mark.parametrize("timezone", ["UTC", None])
def test_observed_mode_checks_timezone_before_callbacks(timezone):
    strategy = FirstBarTargetStrategy()
    frame = _timing_frame([10, 10.5])
    visible = frame["timestamp"].dt.tz_localize("Asia/Shanghai")
    frame["available_at"] = visible
    if timezone is not None:
        frame["timestamp"] = visible.dt.tz_convert(timezone)
    engine = _timing_engine(
        frame,
        strategy=strategy,
        execution_config=BacktestExecutionConfig(availability_mode="observed"),
    )
    if timezone is None:
        with pytest.raises(ValueError, match="backtest_observation_timezone_mismatch"):
            engine.run()
        assert strategy.initialized is False
        assert strategy.observed == []
    else:
        result = engine.run()
        assert len(result.fills) == 1
        assert result.fills[0].timestamp > visible.iloc[0]


def test_execution_time_risk_modification_does_not_also_fill_original_order():
    from dataclasses import replace

    from risk.rules import RiskCheckResult, RiskRule

    class CapQuantity(RiskRule):
        @property
        def name(self):
            return "cap_quantity"

        def check(self, order, positions, portfolio_value):
            return RiskCheckResult(
                passed=True,
                modified_order=replace(order, quantity=Decimal("100")),
            )

    engine = _timing_engine(_timing_frame([10, 10.5]))
    engine.risk_manager.add_rule(CapQuantity())
    result = engine.run()
    assert len(result.fills) == 1
    assert result.fills[0].fill_quantity == Decimal("100")


def test_etf_execution_uses_instrument_tick_for_price_limit():
    symbol = Symbol("510300")
    frame = _timing_frame([1.005, 1.106])
    engine = BacktestEngine(
        strategy=FirstBarTargetStrategy(),
        instruments={symbol: make_etf(str(symbol), "fixture")},
        data_handlers={symbol: DataHandler(frame, symbol)},
    )
    result = engine.run()
    assert result.fills == []
    assert result.execution_timing["limit_blocked_count"] == 1


def test_zero_price_limit_does_not_disable_suspension_admission():
    from dataclasses import replace

    symbol = Symbol("510300")
    frame = _timing_frame([1.005, 1.106], volume=[10000, 0])
    engine = BacktestEngine(
        strategy=FirstBarTargetStrategy(),
        instruments={symbol: replace(make_etf(str(symbol), "fixture"), limit_pct=ZERO)},
        data_handlers={symbol: DataHandler(frame, symbol)},
    )
    result = engine.run()
    assert result.fills == []
    assert result.execution_timing["suspension_blocked_count"] == 1
