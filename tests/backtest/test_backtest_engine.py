"""BacktestEngine 集成测试。"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from backtest.result import BacktestResult
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent, SignalEvent
from core.types import ZERO, BarFrequency, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_etf, make_stock
from domain.portfolio import Portfolio
from execution.commission import ETFCommission
from execution.slippage import PercentSlippage
from risk.limits import PositionLimitRule
from risk.manager import RiskManager
from server.db import AppDatabase
from strategy.base import Strategy


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
