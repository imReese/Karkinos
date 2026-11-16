"""ExecutionModel timing, data visibility, and limit conformance tests."""

from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import (
    BacktestEngine,
    BacktestExecutionConfig,
    research_execution_config,
)
from core.event_bus import EventBus
from core.events import MarketEvent, OrderSide, SignalEvent
from core.types import ExecutionModel, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.slippage import PercentSlippage
from strategy.base import Strategy


class StagedTargetStrategy(Strategy):
    """Strategy that publishes explicit target weights upon receiving bar data."""

    def __init__(self, targets_by_date: dict[str, Decimal]) -> None:
        super().__init__("staged_target_strategy", EventBus())
        self._targets_by_date = targets_by_date
        self.observed_bars: list[MarketEvent] = []
        self.recorded_positions_on_data: list[tuple[str, Decimal]] = []

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self.observed_bars.append(event)
        session_str = event.timestamp.strftime("%Y-%m-%d")
        pos_qty = Decimal("0")
        if hasattr(self, "engine") and self.engine is not None:
            pos = self.engine.portfolio.positions.get(event.symbol)
            if pos is not None:
                pos_qty = pos.quantity
        self.recorded_positions_on_data.append((session_str, pos_qty))

        if session_str in self._targets_by_date:
            target = self._targets_by_date[session_str]
            self.emit_signal(event.symbol, target)


def _make_ohlcv_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = frame[col].map(lambda v: Decimal(str(v)))
    return frame


def _build_engine(
    frame: pd.DataFrame,
    strategy: Strategy,
    *,
    execution_model: ExecutionModel | str = ExecutionModel.NEXT_BAR_CLOSE,
    initial_cash: Decimal = Decimal("100000"),
    slippage_pct: Decimal = Decimal("0"),
    limit_pct: Decimal = Decimal("0.10"),
) -> BacktestEngine:
    symbol = Symbol("600000")
    inst = make_stock(str(symbol), "浦发银行", limit_pct=limit_pct)
    slippage_model = PercentSlippage(slippage_pct) if slippage_pct > 0 else None
    config = BacktestExecutionConfig(
        execution_model=ExecutionModel.from_value(execution_model),
        slippage_model=slippage_model,
    )
    engine = BacktestEngine(
        strategy=strategy,
        instruments={symbol: inst},
        data_handlers={symbol: DataHandler(frame, symbol)},
        initial_cash=initial_cash,
        execution_config=config,
    )
    strategy.engine = engine
    return engine


class TestExecutionModelEnum:
    def test_from_value_parsing(self):
        assert (
            ExecutionModel.from_value(ExecutionModel.NEXT_BAR_OPEN)
            is ExecutionModel.NEXT_BAR_OPEN
        )
        assert (
            ExecutionModel.from_value("next_bar_open") is ExecutionModel.NEXT_BAR_OPEN
        )
        assert (
            ExecutionModel.from_value("NEXT_BAR_OPEN") is ExecutionModel.NEXT_BAR_OPEN
        )
        assert ExecutionModel.from_value("open") is ExecutionModel.NEXT_BAR_OPEN
        assert (
            ExecutionModel.from_value("next_bar_close") is ExecutionModel.NEXT_BAR_CLOSE
        )
        assert (
            ExecutionModel.from_value("NEXT_BAR_CLOSE") is ExecutionModel.NEXT_BAR_CLOSE
        )
        assert ExecutionModel.from_value("close") is ExecutionModel.NEXT_BAR_CLOSE

    def test_from_value_invalid_raises(self):
        with pytest.raises(ValueError, match="unsupported execution model"):
            ExecutionModel.from_value("same_bar_close")


class TestNextBarOpenVsClose:
    def test_next_bar_open_fills_at_open_price(self):
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 9.8,
                    "high": 10.2,
                    "low": 9.7,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.5,
                    "high": 11.0,
                    "low": 10.4,
                    "close": 10.8,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        assert len(result.fills) == 1
        fill = result.fills[0]
        # Filled on 2026-01-06 at Open price (10.5)
        assert fill.timestamp == frame.iloc[1]["timestamp"]
        assert fill.fill_price == Decimal("10.5")
        # Sizing based on Open price: 100000 / 10.5 // 100 * 100 = 9500 shares
        assert fill.fill_quantity == Decimal("9500")
        assert result.execution_timing["execution_model"] == "next_bar_open"
        assert (
            result.execution_timing["policy_id"] == "karkinos.backtest.next_bar_open.v1"
        )
        assert (
            result.execution_timing["fill_basis"]
            == "strictly_later_same_instrument_bar_open"
        )

    def test_next_bar_close_fills_at_close_price_as_default(self):
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 9.8,
                    "high": 10.2,
                    "low": 9.7,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.5,
                    "high": 11.0,
                    "low": 10.4,
                    "close": 10.8,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_CLOSE,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        assert len(result.fills) == 1
        fill = result.fills[0]
        # Filled on 2026-01-06 at Close price (10.8)
        assert fill.timestamp == frame.iloc[1]["timestamp"]
        assert fill.fill_price == Decimal("10.8")
        # Sizing based on Close price: 100000 / 10.8 // 100 * 100 = 9200 shares
        assert fill.fill_quantity == Decimal("9200")
        assert result.execution_timing["execution_model"] == "next_bar_close"
        assert (
            result.execution_timing["policy_id"]
            == "karkinos.backtest.next_bar_close.v2"
        )
        assert (
            result.execution_timing["fill_basis"]
            == "strictly_later_same_instrument_bar_close"
        )

    def test_next_bar_open_sizing_does_not_leak_future_close(self):
        """Intra-day divergence: Open = 10.0 vs Close = 20.0."""
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.8,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.0,
                    "high": 20.0,
                    "low": 10.0,
                    "close": 20.0,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("10000"),
            limit_pct=Decimal("2.0"),
        )
        result = engine.run()

        assert len(result.fills) == 1
        fill = result.fills[0]
        # Sized at Open (10.0): with initial cash 10,000 and 5 yuan min commission,
        # 1000 shares would cost 10,005 > 10,000, so cash-funded fill safely sizes 900 shares.
        # If it leaked Close (20.0), target quantity would be at most 400 shares!
        assert fill.fill_price == Decimal("10.0")
        assert fill.fill_quantity == Decimal("900")

    def test_limit_up_at_open_blocks_buy_under_next_bar_open(self):
        """Stock opens at +10% limit up but closes lower. Next Bar Open blocks buy."""
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 11.0,
                    "high": 11.0,
                    "low": 10.2,
                    "close": 10.3,
                    "volume": 100000,
                },
            ]
        )
        # 1. Under NEXT_BAR_OPEN: Open is limit up (11.0 vs 10.0), buy is blocked!
        strategy_open = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_open = _build_engine(
            frame, strategy_open, execution_model=ExecutionModel.NEXT_BAR_OPEN
        )
        result_open = engine_open.run()
        assert len(result_open.fills) == 0
        assert result_open.execution_timing["limit_blocked_count"] == 1

        # 2. Under NEXT_BAR_CLOSE: Close is not limit up (10.3 vs 10.0), buy is permitted at close!
        strategy_close = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_close = _build_engine(
            frame, strategy_close, execution_model=ExecutionModel.NEXT_BAR_CLOSE
        )
        result_close = engine_close.run()
        assert len(result_close.fills) == 1
        assert result_close.fills[0].fill_price == Decimal("10.3")

    def test_limit_up_at_close_permits_open_buy_under_next_bar_open(self):
        """Stock opens flat but surges to limit up by close. Next Bar Open permits open buy."""
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 10.0,
                    "close": 11.0,
                    "volume": 100000,
                },
            ]
        )
        # 1. Under NEXT_BAR_OPEN: Open is flat (10.0), buy at open is allowed!
        strategy_open = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_open = _build_engine(
            frame, strategy_open, execution_model=ExecutionModel.NEXT_BAR_OPEN
        )
        result_open = engine_open.run()
        assert len(result_open.fills) == 1
        assert result_open.fills[0].fill_price == Decimal("10.0")

        # 2. Under NEXT_BAR_CLOSE: Close is limit up (11.0), buy at close is blocked!
        strategy_close = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_close = _build_engine(
            frame, strategy_close, execution_model=ExecutionModel.NEXT_BAR_CLOSE
        )
        result_close = engine_close.run()
        assert len(result_close.fills) == 0
        assert result_close.execution_timing["limit_blocked_count"] == 1

    def test_limit_down_at_open_blocks_sell_under_next_bar_open(self):
        """Holding shares: next day opens at limit down (-10%). Next Bar Open blocks sell."""
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00",
                    "open": 9.0,
                    "high": 9.5,
                    "low": 9.0,
                    "close": 9.5,
                    "volume": 100000,
                },
            ]
        )
        # Day 1: Buy 1.0 (fills Day 2 open)
        # Day 2: Liquidate 0.0 (attempts Day 3 open, where open = 9.0 is limit down)
        strategy = StagedTargetStrategy(
            {"2026-01-05": Decimal("1.0"), "2026-01-06": Decimal("0.0")}
        )
        engine = _build_engine(
            frame, strategy, execution_model=ExecutionModel.NEXT_BAR_OPEN
        )
        result = engine.run()

        # Day 2 buy filled, Day 3 sell blocked by limit down at open!
        assert len(result.fills) == 1
        assert result.fills[0].side == OrderSide.BUY
        assert result.execution_timing["limit_blocked_count"] == 1

    def test_suspension_blocks_next_bar_open(self):
        """Volume == 0 represents suspension and blocks next bar open."""
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 0,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame, strategy, execution_model=ExecutionModel.NEXT_BAR_OPEN
        )
        result = engine.run()
        assert len(result.fills) == 0
        assert result.execution_timing["suspension_blocked_count"] == 1

    def test_next_bar_open_slippage_applied_to_open_price(self):
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 100000,
                },
            ]
        )
        # Slippage 0.2%: buy price becomes 10.0 * 1.002 = 10.02
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            slippage_pct=Decimal("0.002"),
        )
        result = engine.run()
        assert len(result.fills) == 1
        assert result.fills[0].fill_price == Decimal("10.02")
        assert (
            result.fills[0].slippage == Decimal("0.02") * result.fills[0].fill_quantity
        )

    def test_next_bar_open_multi_day_lifecycle(self):
        """Lifecycle verification:
        Day 1: Signal staged to buy at Day 1 close.
        Day 2: Filled at Day 2 open. Strategy on Day 2 observes new position on_data.
               Strategy stages exit signal at Day 2 close.
        Day 3: Exit filled at Day 3 open. Strategy on Day 3 observes 0 position.
        """
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.2,
                    "high": 10.8,
                    "low": 10.1,
                    "close": 10.5,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00",
                    "open": 10.6,
                    "high": 10.9,
                    "low": 10.5,
                    "close": 10.7,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy(
            {"2026-01-05": Decimal("1.0"), "2026-01-06": Decimal("0.0")}
        )
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        assert len(result.fills) == 2
        buy_fill = result.fills[0]
        sell_fill = result.fills[1]

        # Buy fill at Day 2 Open
        assert buy_fill.side == OrderSide.BUY
        assert buy_fill.fill_price == Decimal("10.2")
        assert buy_fill.timestamp == frame.iloc[1]["timestamp"]

        # Sell fill at Day 3 Open
        assert sell_fill.side == OrderSide.SELL
        assert sell_fill.fill_price == Decimal("10.6")
        assert sell_fill.timestamp == frame.iloc[2]["timestamp"]
        assert sell_fill.fill_quantity == buy_fill.fill_quantity

        # Verify strategy position visibility on_data:
        # Day 1: pos was 0
        # Day 2: pos was buy_fill.fill_quantity (because open execution happened before on_data!)
        # Day 3: pos was 0 (because sell execution happened before on_data!)
        assert strategy.recorded_positions_on_data == [
            ("2026-01-05", Decimal("0")),
            ("2026-01-06", buy_fill.fill_quantity),
            ("2026-01-07", Decimal("0")),
        ]
