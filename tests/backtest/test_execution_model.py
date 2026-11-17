"""ExecutionModel timing, data visibility, and limit conformance tests."""

from decimal import Decimal

import pandas as pd
import pytest

from backtest.distributions import StockDistribution
from backtest.engine import (
    BacktestEngine,
    BacktestExecutionConfig,
    research_execution_config,
)
from core.event_bus import EventBus
from core.events import (
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderIntentEvent,
    OrderSide,
    RiskAlertEvent,
    RiskDecisionEvent,
    SignalEvent,
)
from core.types import ExecutionModel, OrderType, Symbol
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


class MultiAssetTargetStrategy(Strategy):
    """Strategy managing explicit target weights across multiple symbols."""

    def __init__(self, targets_by_date: dict[str, dict[Symbol, Decimal]]) -> None:
        super().__init__("multi_asset_target_strategy", EventBus())
        self._targets_by_date = targets_by_date
        self.observed_bars: list[MarketEvent] = []

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        self.observed_bars.append(event)
        session_str = event.timestamp.strftime("%Y-%m-%d")
        if session_str in self._targets_by_date:
            session_targets = self._targets_by_date[session_str]
            if event.symbol in session_targets:
                self.emit_signal(event.symbol, session_targets[event.symbol])


def _build_multi_engine(
    frames: dict[Symbol, pd.DataFrame],
    strategy: Strategy,
    *,
    execution_model: ExecutionModel | str = ExecutionModel.NEXT_BAR_OPEN,
    initial_cash: Decimal = Decimal("100000"),
    slippage_pct: Decimal = Decimal("0"),
    limit_pct: Decimal = Decimal("0.10"),
) -> BacktestEngine:
    instruments = {
        sym: make_stock(str(sym), f"Stock_{sym}", limit_pct=limit_pct) for sym in frames
    }
    handlers = {sym: DataHandler(df, sym) for sym, df in frames.items()}
    slippage_model = PercentSlippage(slippage_pct) if slippage_pct > 0 else None
    config = BacktestExecutionConfig(
        execution_model=ExecutionModel.from_value(execution_model),
        slippage_model=slippage_model,
    )
    engine = BacktestEngine(
        strategy=strategy,
        instruments=instruments,
        data_handlers=handlers,
        initial_cash=initial_cash,
        execution_config=config,
    )
    strategy.engine = engine
    return engine


class TestMultiAssetOpenValuation:
    def test_multi_asset_open_valuation_without_session_decision(self):
        """In NEXT_BAR_OPEN without session_decision, all available session symbols
        are marked to Open before any order execution or sizing occurs."""
        sym_a = Symbol("600000")
        sym_b = Symbol("000001")

        frame_a = _make_ohlcv_frame(
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
                    "open": 10.5,
                    "high": 11.0,
                    "low": 10.4,
                    "close": 10.8,
                    "volume": 100000,
                },
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 19.0,
                    "high": 19.5,
                    "low": 18.8,
                    "close": 19.2,
                    "volume": 100000,
                },
            ]
        )

        strategy = MultiAssetTargetStrategy(
            {
                "2026-01-05": {sym_a: Decimal("0.5"), sym_b: Decimal("0.5")},
            }
        )
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        # Both orders executed on Day 2 Open
        assert len(result.fills) == 2
        fill_a = next(f for f in result.fills if f.symbol == sym_a)
        fill_b = next(f for f in result.fills if f.symbol == sym_b)
        assert fill_a.fill_price == Decimal("10.5")
        assert fill_b.fill_price == Decimal("19.0")

        # Open equity at Day 2 open = initial cash 100000 (no positions held yet)
        # Target weight 0.5 each -> 50,000 target value each.
        # A: 50,000 / 10.5 = 4761 -> 4700 shares.
        # B: 50,000 / 19.0 = 2631 -> 2600 shares.
        assert fill_a.fill_quantity == Decimal("4700")
        assert fill_b.fill_quantity == Decimal("2600")

    def test_multi_asset_event_order_invariance(self):
        """Processing order of session events does not affect target sizing or execution."""
        sym_a = Symbol("600000")
        sym_b = Symbol("000001")

        def run_with_order(
            order_symbols: list[Symbol],
        ) -> list[tuple[Symbol, Decimal, Decimal]]:
            frame_a = _make_ohlcv_frame(
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
                        "open": 10.5,
                        "high": 11.0,
                        "low": 10.4,
                        "close": 10.8,
                        "volume": 100000,
                    },
                ]
            )
            frame_b = _make_ohlcv_frame(
                [
                    {
                        "timestamp": "2026-01-05 15:00",
                        "open": 20.0,
                        "high": 20.0,
                        "low": 20.0,
                        "close": 20.0,
                        "volume": 100000,
                    },
                    {
                        "timestamp": "2026-01-06 15:00",
                        "open": 19.0,
                        "high": 19.5,
                        "low": 18.8,
                        "close": 19.2,
                        "volume": 100000,
                    },
                ]
            )
            frames = {sym_a: frame_a, sym_b: frame_b}
            ordered_frames = {s: frames[s] for s in order_symbols}

            strat = MultiAssetTargetStrategy(
                {"2026-01-05": {sym_a: Decimal("0.4"), sym_b: Decimal("0.6")}}
            )
            eng = _build_multi_engine(
                ordered_frames,
                strat,
                execution_model=ExecutionModel.NEXT_BAR_OPEN,
                initial_cash=Decimal("100000"),
            )
            res = eng.run()
            return sorted(
                [(f.symbol, f.fill_price, f.fill_quantity) for f in res.fills],
                key=lambda x: str(x[0]),
            )

        res_ab = run_with_order([sym_a, sym_b])
        res_ba = run_with_order([sym_b, sym_a])
        assert res_ab == res_ba

    def test_missing_bar_symbol_retains_last_mark_without_fabrication(self):
        """Symbol missing bar on Day 2 retains Day 1 mark without error or price fabrication."""
        sym_a = Symbol("600000")
        sym_b = Symbol("000001")

        frame_a = _make_ohlcv_frame(
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
                    "open": 10.5,
                    "high": 10.8,
                    "low": 10.4,
                    "close": 10.6,
                    "volume": 100000,
                },
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
            ]
        )
        strategy = MultiAssetTargetStrategy(
            {
                "2026-01-05": {sym_a: Decimal("0.5"), sym_b: Decimal("0.5")},
            }
        )
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()
        # Only sym_a fills on Day 2 open; sym_b has no Day 2 bar so cannot fill
        assert len(result.fills) == 1
        assert result.fills[0].symbol == sym_a


class TestPostSlippagePriceLimit:
    def test_buy_slippage_exceeding_limit_up_rejected(self):
        """Pre-slippage price is below limit up, but slippage pushes fill price
        above limit up. Order must be rejected (not clamped), blocking the fill."""
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
                # Open at 10.95: below limit up of 11.00 (10.0 * 1.10 = 11.00)
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.95,
                    "high": 11.0,
                    "low": 10.9,
                    "close": 11.0,
                    "volume": 100000,
                },
            ]
        )
        # +1% slippage -> 10.95 * 1.01 = 11.0595 > 11.00
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            slippage_pct=Decimal("0.01"),
            limit_pct=Decimal("0.10"),
        )
        result = engine.run()
        # The buy must be rejected because slipped price breaches limit-up
        assert len(result.fills) == 0
        assert result.execution_timing["limit_blocked_count"] == 1

    def test_sell_slippage_breaking_below_limit_down_rejected(self):
        """Pre-slippage price is above limit down, but slippage pushes sell price
        below limit down. Order must be rejected (not clamped), blocking the fill."""
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
                # Day 3: Open at 9.05 (limit down is 9.00 based on Day 2 close 10.00).
                # Slipped sell price = 9.05 * 0.99 = 8.9595 < 9.00.
                {
                    "timestamp": "2026-01-07 15:00",
                    "open": 9.05,
                    "high": 9.1,
                    "low": 9.0,
                    "close": 9.0,
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
            slippage_pct=Decimal("0.01"),
            limit_pct=Decimal("0.10"),
        )
        result = engine.run()
        # Day 2 buy filled, but Day 3 sell rejected because slipped price < limit down
        assert len(result.fills) == 1
        assert result.fills[0].side == OrderSide.BUY
        assert result.execution_timing["limit_blocked_count"] == 1

    def test_next_bar_close_post_slippage_limit_enforced(self):
        """NEXT_BAR_CLOSE also rejects orders when slippage breaches legal price limits."""
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
                # Close at 10.95. Slippage +1% -> 11.0595 > 11.00 limit up
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 10.5,
                    "high": 11.0,
                    "low": 10.5,
                    "close": 10.95,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine = _build_engine(
            frame,
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_CLOSE,
            slippage_pct=Decimal("0.01"),
            limit_pct=Decimal("0.10"),
        )
        result = engine.run()
        assert len(result.fills) == 0
        assert result.execution_timing["limit_blocked_count"] == 1


class TestFillMetadataTimeSemantics:
    def test_fill_metadata_contains_open_and_close_time_semantics(self):
        """FillEvent metadata clearly distinguishes open vs close execution without fabricating timestamps."""
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
                    "open": 10.5,
                    "high": 10.8,
                    "low": 10.2,
                    "close": 10.6,
                    "volume": 100000,
                },
            ]
        )

        # NEXT_BAR_OPEN
        strat_open = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_open = _build_engine(
            frame, strat_open, execution_model=ExecutionModel.NEXT_BAR_OPEN
        )
        res_open = engine_open.run()
        assert len(res_open.fills) == 1
        fill_open = res_open.fills[0]
        assert fill_open.timestamp == frame.iloc[1]["timestamp"]
        assert fill_open.metadata is not None
        assert fill_open.metadata["execution_phase"] == "open"
        assert fill_open.metadata["execution_model"] == "next_bar_open"
        assert fill_open.metadata["session_date"] == "2026-01-06"
        assert (
            fill_open.metadata["bar_timestamp"]
            == frame.iloc[1]["timestamp"].isoformat()
        )

        # NEXT_BAR_CLOSE
        strat_close = StagedTargetStrategy({"2026-01-05": Decimal("1.0")})
        engine_close = _build_engine(
            frame, strat_close, execution_model=ExecutionModel.NEXT_BAR_CLOSE
        )
        res_close = engine_close.run()
        assert len(res_close.fills) == 1
        fill_close = res_close.fills[0]
        assert fill_close.timestamp == frame.iloc[1]["timestamp"]
        assert fill_close.metadata is not None
        assert fill_close.metadata["execution_phase"] == "close"
        assert fill_close.metadata["execution_model"] == "next_bar_close"
        assert fill_close.metadata["session_date"] == "2026-01-06"
        assert (
            fill_close.metadata["bar_timestamp"]
            == frame.iloc[1]["timestamp"].isoformat()
        )

    def test_broker_fill_report_retains_metadata_and_converts_to_fillevent(
        self,
    ):
        """BrokerFillReport retains metadata and propagates to FillEvent upon conversion."""
        from execution.tracker import BrokerFillReport

        now = pd.Timestamp("2026-01-06 15:00:00+00:00")
        report = BrokerFillReport(
            fill_id="FILL-123",
            order_id="ORD-123",
            timestamp=now,
            symbol=Symbol("600000"),
            side=OrderSide.BUY,
            fill_price=Decimal("10.5"),
            fill_quantity=Decimal("100"),
            metadata={
                "execution_phase": "open",
                "execution_model": "next_bar_open",
                "session_date": "2026-01-06",
            },
        )
        event = report.to_fill_event()
        assert event.metadata == report.metadata
        assert event.metadata["execution_phase"] == "open"
        assert event.metadata["execution_model"] == "next_bar_open"


class TrackingPhaseStrategy(Strategy):
    """Strategy that logs the sequence of fills vs on_data callbacks."""

    def __init__(self, targets_by_date: dict[str, dict[Symbol, Decimal]]) -> None:
        super().__init__("tracking_phase_strategy", EventBus())
        self._targets_by_date = targets_by_date
        self.timeline: list[tuple[str, Symbol, str]] = []

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_fill(self, event: FillEvent) -> None:
        self.timeline.append(
            ("fill", event.symbol, event.timestamp.strftime("%Y-%m-%d"))
        )

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        session_str = event.timestamp.strftime("%Y-%m-%d")
        self.timeline.append(("on_data", event.symbol, session_str))
        if session_str in self._targets_by_date:
            session_targets = self._targets_by_date[session_str]
            if event.symbol in session_targets:
                self.emit_signal(event.symbol, session_targets[event.symbol])


class InterferingSignalStrategy(Strategy):
    """Strategy that attempts to overwrite B's signal when A's bar data arrives."""

    def __init__(self, sym_a: Symbol, sym_b: Symbol) -> None:
        super().__init__("interfering_signal_strategy", EventBus())
        self.sym_a = sym_a
        self.sym_b = sym_b

    def on_init(self, symbols: list[Symbol]) -> None:
        pass

    def on_data(self, event: MarketEvent) -> None:
        self._last_timestamp = event.timestamp
        session_str = event.timestamp.strftime("%Y-%m-%d")
        if session_str == "2026-01-05":
            # Stage buy signals for both on Day 1
            self.emit_signal(self.sym_a, Decimal("0.3"))
            self.emit_signal(self.sym_b, Decimal("0.3"))
        elif session_str == "2026-01-06" and event.symbol == self.sym_a:
            # When A's data arrives on Day 2, attempt to cancel B's signal
            self.emit_signal(self.sym_b, Decimal("0.0"))


class TestOpenSessionPhaseIsolation:
    def test_multi_asset_future_close_isolation(self):
        """A's future Close price crash must not leak into B's open risk check."""
        from risk.limits import ConcentrationRule

        sym_a = Symbol("600001")
        sym_b = Symbol("600002")

        # Day 1: Both trade at 10.0. Cash = 100,000.
        # Day 2:
        # A opens at 10.0, but closes at 1.0 (90% crash).
        # B opens at 10.0, closes at 10.0.
        frame_a = _make_ohlcv_frame(
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
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100000,
                },
            ]
        )
        frame_b = _make_ohlcv_frame(
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
            ]
        )
        # Stage target weights on Day 1: A -> 0.30, B -> 0.30
        strategy = MultiAssetTargetStrategy(
            {"2026-01-05": {sym_a: Decimal("0.30"), sym_b: Decimal("0.30")}}
        )
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        # Concentration rule: max 32% of total equity
        # At Open: total equity is ~100,000. B's order is 30,000 / 100,000 = 30% <= 32% -> PASS
        # If A's Close (1.0) leaks: total equity is ~73,000. B's order is 30,000 / 73,000 = 41% > 32% -> REJECTED
        engine.risk_manager.add_rule(ConcentrationRule(Decimal("0.32")))
        result = engine.run()

        # Both A and B must fill at Open because at Open A is valued at 10.0, not 1.0!
        fills_by_symbol = {f.symbol: f for f in result.fills}
        assert sym_a in fills_by_symbol, "Sym A must fill"
        assert sym_b in fills_by_symbol, (
            "Sym B must not be rejected due to Sym A's future close crash"
        )

    def test_cross_symbol_signal_isolation(self):
        """A's on_data callback on Day 2 cannot overwrite B's pending Day 2 open signal."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")

        frame_a = _make_ohlcv_frame(
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
            ]
        )
        frame_b = _make_ohlcv_frame(
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
            ]
        )
        strategy = InterferingSignalStrategy(sym_a, sym_b)
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        # B must fill on Day 2 Open, not be wiped out by A's on_data
        fills_by_symbol = {f.symbol: f for f in result.fills}
        assert sym_b in fills_by_symbol, (
            "Sym B must execute at Open despite A's on_data"
        )

    def test_all_open_fills_precede_strategy_on_data(self):
        """All open fills across all symbols must execute before any strategy on_data is called."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")

        frame_a = _make_ohlcv_frame(
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
            ]
        )
        frame_b = _make_ohlcv_frame(
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
            ]
        )
        strategy = TrackingPhaseStrategy(
            {"2026-01-05": {sym_a: Decimal("0.3"), sym_b: Decimal("0.3")}}
        )
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        engine.run()

        day2_timeline = [item for item in strategy.timeline if item[2] == "2026-01-06"]
        # Find index of last fill and index of first on_data
        fill_indices = [i for i, item in enumerate(day2_timeline) if item[0] == "fill"]
        on_data_indices = [
            i for i, item in enumerate(day2_timeline) if item[0] == "on_data"
        ]

        assert fill_indices, "Must have fills on Day 2"
        assert on_data_indices, "Must have on_data on Day 2"
        # Every fill must happen before the FIRST on_data
        assert max(fill_indices) < min(on_data_indices), (
            f"All fills must precede all on_data calls, got timeline: {day2_timeline}"
        )

    def test_next_bar_open_with_volume_participation_unsupported(self):
        """Strict NEXT_BAR_OPEN rejects max_volume_participation as full-day volume cannot fund open capacity."""
        sym = Symbol("600000")
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                }
            ]
        )
        strategy = StagedTargetStrategy({})
        config = research_execution_config(execution_model=ExecutionModel.NEXT_BAR_OPEN)
        assert config.max_volume_participation is not None

        with pytest.raises(
            ValueError, match="next_bar_open_volume_participation_unsupported"
        ):
            BacktestEngine(
                strategy=strategy,
                instruments={sym: make_stock(str(sym), "Stock")},
                data_handlers={sym: DataHandler(frame, sym)},
                execution_config=config,
            )

    def test_existing_position_open_valuation_with_missing_bar_symbol(self):
        """Pre-existing positions in multiple symbols are valued at Open, while a symbol
        missing a bar on Day 3 retains its Day 2 valuation mark without price fabrication."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")
        sym_c = Symbol("600003")

        # Day 1: Signal generation
        # Day 2: Execution establishing positions (A=20%, B=20%, C=20%)
        # Day 3: A and B trade, C has NO bar. Sells (B) execute before buys (A).
        frame_a = _make_ohlcv_frame(
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00",
                    "open": 19.0,
                    "high": 19.0,
                    "low": 19.0,
                    "close": 19.0,
                    "volume": 100000,
                },
            ]
        )
        # Sym C trades on Day 1 and Day 2, but has NO bar on Day 3 (suspended / missing bar)
        frame_c = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 30.0,
                    "high": 30.0,
                    "low": 30.0,
                    "close": 30.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 30.0,
                    "high": 30.0,
                    "low": 30.0,
                    "close": 30.0,
                    "volume": 100000,
                },
            ]
        )

        strategy = MultiAssetTargetStrategy(
            {
                # Day 1: Target equal 20% in A, B, C (fills at Day 2 Open)
                "2026-01-05": {
                    sym_a: Decimal("0.20"),
                    sym_b: Decimal("0.20"),
                    sym_c: Decimal("0.20"),
                },
                # Day 2: Rebalance targets: B down to 10%, A up to 35%, C unchanged (0.20)
                "2026-01-06": {
                    sym_a: Decimal("0.35"),
                    sym_b: Decimal("0.10"),
                    sym_c: Decimal("0.20"),
                },
            }
        )
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b, sym_c: frame_c},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            initial_cash=Decimal("100000"),
        )
        result = engine.run()

        # Check positions exist for all 3 symbols
        assert sym_a in result.positions
        assert sym_b in result.positions
        assert sym_c in result.positions

        # C's quantity must remain exactly what was established on Day 2 (600 shares)
        # because C had no bar on Day 3 to execute rebalancing
        assert result.positions[sym_c].quantity == Decimal("600")

        # Day 3 fills: B must sell first (reduction), A must buy (increase)
        day3_fills = [f for f in result.fills if "2026-01-07" in str(f.timestamp)]
        assert len(day3_fills) == 2
        assert day3_fills[0].symbol == sym_b
        assert day3_fills[0].side is OrderSide.SELL
        assert day3_fills[1].symbol == sym_a
        assert day3_fills[1].side is OrderSide.BUY

        # C has no fill on Day 3
        assert all(f.symbol != sym_c for f in day3_fills)

    def test_inconsistent_bar_timestamps_in_session_rejected(self):
        """Multiple bars in the same session with different timestamps must be rejected."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")

        frame_a = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 14:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                }
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                }
            ]
        )
        strategy = StagedTargetStrategy({})
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        with pytest.raises(ValueError, match="session_bars_timestamp_inconsistent"):
            engine.run()

    def test_duplicate_symbol_bars_in_session_rejected(self):
        """Duplicate bars for the same symbol in a daily session must be rejected."""
        sym = Symbol("600000")
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
                    "timestamp": "2026-01-05 15:00",
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({})
        inst = make_stock(str(sym), "Stock")
        engine = BacktestEngine(
            strategy=strategy,
            instruments={sym: inst},
            data_handlers={sym: DataHandler(frame, sym)},
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        with pytest.raises(ValueError, match="duplicate_symbol_bar_in_session"):
            engine.run()


class TestOrderEntryAndMarketEventContract:
    """Verifies strict order entry timing constraints and completed MarketEvent broadcast."""

    def test_on_data_direct_order_intent_rejected(self):
        """Direct OrderIntentEvent published in on_data is rejected under NEXT_BAR_OPEN."""
        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )

        class DirectIntentStrategy(Strategy):
            def __init__(self):
                super().__init__("direct_intent", EventBus())

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                self.event_bus.publish(
                    OrderIntentEvent(
                        timestamp=event.timestamp,
                        intent_id=f"INTENT-{event.symbol}",
                        strategy_id=self.strategy_id,
                        symbol=event.symbol,
                        side=OrderSide.BUY,
                        target_weight=Decimal("0.2"),
                        quantity=Decimal("100"),
                        reference_price=event.close,
                    )
                )

        events_captured: list[object] = []
        strategy = DirectIntentStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        engine.event_bus.subscribe(RiskDecisionEvent, events_captured.append)
        result = engine.run()

        # Direct order intent in NEXT_BAR_OPEN must NOT execute
        assert len(result.fills) == 0
        assert engine._execution_blocked.get("timing", 0) >= 1
        decisions = [
            e
            for e in events_captured
            if isinstance(e, RiskDecisionEvent) and not e.passed
        ]
        assert len(decisions) >= 1
        assert "next_bar_open_direct_order_unsupported" in decisions[0].reasons

    def test_on_data_direct_order_event_rejected(self):
        """Direct OrderEvent published in on_data is rejected under NEXT_BAR_OPEN."""
        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )

        class DirectOrderStrategy(Strategy):
            def __init__(self):
                super().__init__("direct_order", EventBus())

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                self.event_bus.publish(
                    OrderEvent(
                        timestamp=event.timestamp,
                        order_id=f"ORD-DIRECT-{event.symbol}",
                        symbol=event.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=Decimal("100"),
                        price=event.close,
                    )
                )

        alerts_captured: list[object] = []
        strategy = DirectOrderStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        engine.event_bus.subscribe(RiskAlertEvent, alerts_captured.append)
        result = engine.run()

        assert len(result.fills) == 0
        assert engine._execution_blocked.get("timing", 0) >= 1
        alerts = [e for e in alerts_captured if isinstance(e, RiskAlertEvent)]
        assert len(alerts) >= 1
        assert alerts[0].rule_name == "OrderTimingRule"

    def test_post_close_stale_open_price_rejected(self):
        """Order submitted after close using stale morning open price is rejected."""
        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 11.0,
                    "low": 10.5,
                    "close": 11.0,
                    "volume": 100000,
                },
            ]
        )

        class StalePriceStrategy(Strategy):
            def __init__(self):
                super().__init__("stale_price", EventBus())

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                # Attempt to trade at open price when bar has already closed
                self.event_bus.publish(
                    OrderEvent(
                        timestamp=event.timestamp,
                        order_id=f"ORD-STALE-{event.symbol}",
                        symbol=event.symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=Decimal("100"),
                        price=event.open,
                    )
                )

        strategy = StalePriceStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        result = engine.run()
        assert len(result.fills) == 0
        assert engine._execution_blocked.get("timing", 0) >= 1

    def test_callback_chain_order_in_on_fill_rejected(self):
        """New order generated inside on_fill callback cannot execute in the same Open Phase."""
        sym = Symbol("600001")
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
            ]
        )

        class ChainedOrderStrategy(Strategy):
            def __init__(self):
                super().__init__("chained_order", EventBus())
                self.attempted_chained = False

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                if "2026-01-05" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.20"))

            def on_fill(self, event: FillEvent):
                # When the legitimate Day 2 open order fills, immediately try to place another order
                if not self.attempted_chained:
                    self.attempted_chained = True
                    self.event_bus.publish(
                        OrderIntentEvent(
                            timestamp=event.timestamp,
                            intent_id="CHAINED-INTENT",
                            strategy_id=self.strategy_id,
                            symbol=event.symbol,
                            side=OrderSide.BUY,
                            target_weight=Decimal("0.5"),
                            quantity=Decimal("500"),
                            reference_price=event.fill_price,
                        )
                    )

        strategy = ChainedOrderStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        decisions: list[object] = []
        engine.event_bus.subscribe(RiskDecisionEvent, decisions.append)
        result = engine.run()

        # Only the 1 legitimate frozen signal order fills
        assert len(result.fills) == 1
        assert engine._execution_blocked.get("timing", 0) == 1
        rejected_decisions = [
            d
            for d in decisions
            if isinstance(d, RiskDecisionEvent)
            and not d.passed
            and d.intent_id == "CHAINED-INTENT"
        ]
        assert len(rejected_decisions) == 1

    def test_frozen_signal_executes_normally_once(self):
        """Legitimate frozen signal derived order executes exactly once at Open."""
        sym = Symbol("600001")
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
                    "high": 10.5,
                    "low": 10.0,
                    "close": 10.4,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("0.30")})
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        result = engine.run()
        assert len(result.fills) == 1
        fill = result.fills[0]
        assert fill.fill_price == Decimal("10.2")
        assert fill.metadata.get("execution_phase") == "open"
        assert engine._execution_blocked.get("timing", 0) == 0

    def test_market_event_broadcast_to_external_subscribers(self):
        """External MarketEvent subscribers receive all completed bars under NEXT_BAR_OPEN."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")
        frame_a = _make_ohlcv_frame(
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 20.5,
                    "high": 20.5,
                    "low": 20.5,
                    "close": 20.5,
                    "volume": 100000,
                },
            ]
        )
        strategy = StagedTargetStrategy({})
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        observed_bars: list[MarketEvent] = []
        engine.event_bus.subscribe(MarketEvent, observed_bars.append)
        engine.run()

        # Total 2 symbols * 2 days = 4 completed bars broadcast
        assert len(observed_bars) == 4
        symbols_observed = {b.symbol for b in observed_bars}
        assert symbols_observed == {sym_a, sym_b}

    def test_open_fills_strictly_precede_market_event_broadcast(self):
        """All open fills strictly precede completed MarketEvent broadcast on each day."""
        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )
        timeline: list[tuple[str, str]] = []

        class TimelineStrategy(Strategy):
            def __init__(self):
                super().__init__("timeline", EventBus())

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                timeline.append(("on_data", event.timestamp.strftime("%Y-%m-%d")))
                if "2026-01-05" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.25"))

            def on_fill(self, event: FillEvent):
                timeline.append(("fill", event.timestamp.strftime("%Y-%m-%d")))

        strategy = TimelineStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        engine.event_bus.subscribe(
            MarketEvent,
            lambda ev: timeline.append(
                ("market_event_broadcast", ev.timestamp.strftime("%Y-%m-%d"))
            ),
        )
        engine.run()

        # Day 2: Open fill must precede completed bar broadcast and on_data
        day2_events = [kind for kind, d in timeline if d == "2026-01-06"]
        assert "fill" in day2_events
        assert "market_event_broadcast" in day2_events
        fill_idx = day2_events.index("fill")
        broadcast_idx = day2_events.index("market_event_broadcast")
        assert fill_idx < broadcast_idx, "Fill must precede MarketEvent broadcast"

    def test_no_duplicate_on_data_and_no_duplicate_fills(self):
        """Strategy on_data and fills execute exactly once per expected trigger."""
        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00",
                    "open": 10.8,
                    "high": 10.8,
                    "low": 10.8,
                    "close": 10.8,
                    "volume": 100000,
                },
            ]
        )
        on_data_count = 0

        class CountingStrategy(Strategy):
            def __init__(self):
                super().__init__("counting", EventBus())

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                nonlocal on_data_count
                on_data_count += 1
                self._last_timestamp = event.timestamp
                if "2026-01-05" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.20"))

        strategy = CountingStrategy()
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        result = engine.run()
        assert on_data_count == 3, "on_data must be called exactly 3 times (1 per day)"
        assert len(result.fills) == 1, "Only 1 fill expected"

    def test_warmup_to_formal_market_event_consistency(self):
        """MarketEvent broadcasts arrive consistently across warmup and formal sessions."""
        from datetime import date

        sym = Symbol("600001")
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
                    "open": 10.5,
                    "high": 10.5,
                    "low": 10.5,
                    "close": 10.5,
                    "volume": 100000,
                },
            ]
        )
        observed_bars: list[MarketEvent] = []
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("0.25")})
        inst = make_stock(str(sym), "Stock")
        engine = BacktestEngine(
            strategy=strategy,
            instruments={sym: inst},
            data_handlers={sym: DataHandler(frame, sym)},
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            evaluation_start=date(2026, 1, 6),
        )
        engine.event_bus.subscribe(MarketEvent, observed_bars.append)
        result = engine.run()

        # Both warmup (Jan 5) and formal (Jan 6) broadcast MarketEvents
        assert len(observed_bars) == 2
        # No fills allowed during warmup evaluation boundary
        assert len(result.fills) == 0

    def test_corporate_actions_under_next_bar_open(self):
        """Cash dividend accounting works properly under NEXT_BAR_OPEN."""
        from datetime import date, datetime, timezone

        sym = Symbol("600001")
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00+08:00",
                    "open": 9.5,
                    "high": 9.5,
                    "low": 9.5,
                    "close": 9.5,
                    "volume": 100000,
                },
            ]
        )
        # Ex-date on Jan 7: 0.5 cash dividend per share
        dividend = StockDistribution(
            action_id="DIV-600001-2026",
            symbol=sym,
            record_date=date(2026, 1, 6),
            ex_date=date(2026, 1, 7),
            pay_date=date(2026, 1, 7),
            cash_per_share=Decimal("0.5"),
            available_at=datetime(2026, 1, 6, 15, 0, tzinfo=timezone.utc),
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("0.50")})
        inst = make_stock(str(sym), "Stock")
        engine = BacktestEngine(
            strategy=strategy,
            instruments={sym: inst},
            data_handlers={sym: DataHandler(frame, sym)},
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            cash_dividends=(dividend,),
        )
        result = engine.run()
        assert len(result.fills) == 1
        assert result.cash_dividend_accounting is not None
        assert Decimal(result.cash_dividend_accounting["cash_paid"]) > Decimal("0")

    def test_unconstrained_capacity_metadata_flags_unsimulated_open_capacity(self):
        """Unconstrained capacity in NEXT_BAR_OPEN explicitly flags unsimulated open capacity."""
        sym = Symbol("600001")
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
            ]
        )
        strategy = StagedTargetStrategy({})
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        result = engine.run()
        evidence = result.execution_timing
        assert evidence is not None
        assert evidence["capacity_model"] == "unsimulated_open_capacity"
        assert evidence["open_capacity_simulated"] is False

    def test_prequeued_direct_intent_in_on_position_update_rejected_and_legitimate_signal_fills(
        self,
    ):
        """Pre-queued direct intent in on_position_update callback must NOT steal authorization

        from the legitimate frozen signal. The direct intent must be rejected, and the
        legitimate frozen signal must fill at open price with the correct quantity.
        """
        from datetime import date, datetime, timezone

        sym = Symbol("600001")
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-08 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
            ]
        )

        class PrequeuedIntentStrategy(Strategy):
            def __init__(self):
                super().__init__("prequeued_intent", EventBus())
                self.rogue_emitted = False

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                # Day 1 (Jan 5): stage initial buy (30% weight) -> fills on Jan 6 open
                if "2026-01-05" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.30"))
                # Day 2 (Jan 6): stage legitimate rebalance (60% weight) -> expected to fill on Jan 7 open
                elif "2026-01-06" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.60"))

            def on_position_update(self, symbol: Symbol, quantity: Decimal):
                # On Day 3 (Jan 7) morning, dividend replay syncs positions before session
                # and invokes strategy.on_position_update for held positions.
                if (
                    self._last_timestamp
                    and "2026-01-06" in str(self._last_timestamp)
                    and not self.rogue_emitted
                    and quantity > Decimal("0")
                ):
                    self.rogue_emitted = True
                    self.event_bus.publish(
                        OrderIntentEvent(
                            timestamp=self._last_timestamp,
                            intent_id="ROGUE-PREQUEUED",
                            strategy_id=self.strategy_id,
                            symbol=symbol,
                            side=OrderSide.BUY,
                            target_weight=Decimal("0.90"),
                            quantity=Decimal("200"),
                            reference_price=Decimal("1.00"),  # Stale / wrong price!
                        )
                    )

        dividend = StockDistribution(
            action_id="DIV-600001-2026",
            symbol=sym,
            record_date=date(2026, 1, 7),
            ex_date=date(2026, 1, 8),
            pay_date=date(2026, 1, 8),
            cash_per_share=Decimal("0.5"),
            available_at=datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc),
        )
        strategy = PrequeuedIntentStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            instruments={sym: make_stock(str(sym), "Stock")},
            data_handlers={sym: DataHandler(frame, sym)},
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            cash_dividends=(dividend,),
        )
        decisions: list[RiskDecisionEvent] = []
        engine.event_bus.subscribe(
            RiskDecisionEvent,
            lambda e: decisions.append(e) if isinstance(e, RiskDecisionEvent) else None,
        )
        result = engine.run()

        # Jan 7 must have exactly 1 fill, and it must be the legitimate rebalance fill (2900 shares @ 10.0 due to 100-share lot size)
        jan7_fills = [f for f in result.fills if "2026-01-07" in str(f.timestamp)]
        assert len(jan7_fills) == 1, f"Expected 1 fill on Jan 7, got {len(jan7_fills)}"
        legit_fill = jan7_fills[0]
        assert legit_fill.fill_quantity == Decimal("2900"), (
            f"Expected legitimate quantity 2900, got {legit_fill.fill_quantity}"
        )
        assert legit_fill.fill_price == Decimal("10.0"), (
            f"Expected open price 10.0, got {legit_fill.fill_price}"
        )

        # The rogue pre-queued intent must be rejected with next_bar_open_direct_order_unsupported
        rogue_decisions = [d for d in decisions if d.intent_id == "ROGUE-PREQUEUED"]
        assert len(rogue_decisions) >= 1, "Expected risk decision for ROGUE-PREQUEUED"
        assert not rogue_decisions[0].passed
        assert "next_bar_open_direct_order_unsupported" in rogue_decisions[0].reasons, (
            f"Wrong reasons: {rogue_decisions[0].reasons}"
        )

    def test_prequeued_direct_intent_rejected_when_frozen_signal_needs_no_trade(self):
        """When a legitimate frozen signal requires no trade (value_diff == 0),

        a pre-queued direct intent in the queue must still be rejected and cannot execute.
        """
        from datetime import date, datetime, timezone

        sym = Symbol("600001")
        frame = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-07 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-08 15:00+08:00",
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100000,
                },
            ]
        )

        class PrequeuedNoTradeStrategy(Strategy):
            def __init__(self):
                super().__init__("prequeued_no_trade", EventBus())
                self.rogue_emitted = False

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                # Day 1 (Jan 5): stage initial buy (30% weight) -> fills on Jan 6 open (3000 shares)
                if "2026-01-05" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.30"))
                # Day 2 (Jan 6): target weight is STILL 30% -> no trade needed on Jan 7 open!
                elif "2026-01-06" in str(event.timestamp):
                    self.emit_signal(event.symbol, Decimal("0.30"))

            def on_position_update(self, symbol: Symbol, quantity: Decimal):
                if (
                    self._last_timestamp
                    and "2026-01-06" in str(self._last_timestamp)
                    and not self.rogue_emitted
                    and quantity > Decimal("0")
                ):
                    self.rogue_emitted = True
                    self.event_bus.publish(
                        OrderIntentEvent(
                            timestamp=self._last_timestamp,
                            intent_id="ROGUE-NO-TRADE",
                            strategy_id=self.strategy_id,
                            symbol=symbol,
                            side=OrderSide.BUY,
                            target_weight=Decimal("0.50"),
                            quantity=Decimal("200"),
                            reference_price=Decimal("10.00"),
                        )
                    )

        dividend = StockDistribution(
            action_id="DIV-600001-2026",
            symbol=sym,
            record_date=date(2026, 1, 7),
            ex_date=date(2026, 1, 8),
            pay_date=date(2026, 1, 8),
            cash_per_share=Decimal("0.5"),
            available_at=datetime(2026, 1, 7, 15, 0, tzinfo=timezone.utc),
        )
        strategy = PrequeuedNoTradeStrategy()
        engine = BacktestEngine(
            strategy=strategy,
            instruments={sym: make_stock(str(sym), "Stock")},
            data_handlers={sym: DataHandler(frame, sym)},
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
            cash_dividends=(dividend,),
        )
        decisions: list[RiskDecisionEvent] = []
        engine.event_bus.subscribe(
            RiskDecisionEvent,
            lambda e: decisions.append(e) if isinstance(e, RiskDecisionEvent) else None,
        )
        result = engine.run()

        # On Jan 7, 0 fills expected (frozen signal needed 0 shares, rogue intent must not fill)
        jan7_fills = [f for f in result.fills if "2026-01-07" in str(f.timestamp)]
        assert len(jan7_fills) == 0, f"Expected 0 fills on Jan 7, got {len(jan7_fills)}"

        # ROGUE-NO-TRADE must be rejected
        rogue_decisions = [d for d in decisions if d.intent_id == "ROGUE-NO-TRADE"]
        assert len(rogue_decisions) >= 1
        assert not rogue_decisions[0].passed
        assert "next_bar_open_direct_order_unsupported" in rogue_decisions[0].reasons

    def test_cross_symbol_authorization_isolation(self):
        """When Symbol A is executing its open signal, an intent for Symbol B cannot be authorized."""
        sym_a = Symbol("600001")
        sym_b = Symbol("600002")

        frame_a = _make_ohlcv_frame(
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
            ]
        )
        frame_b = _make_ohlcv_frame(
            [
                {
                    "timestamp": "2026-01-05 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
                {
                    "timestamp": "2026-01-06 15:00",
                    "open": 20.0,
                    "high": 20.0,
                    "low": 20.0,
                    "close": 20.0,
                    "volume": 100000,
                },
            ]
        )

        class CrossSymbolRogueStrategy(Strategy):
            def __init__(self):
                super().__init__("cross_symbol_rogue", EventBus())
                self.b_emitted = False

            def on_init(self, symbols):
                pass

            def on_data(self, event: MarketEvent):
                self._last_timestamp = event.timestamp
                # Day 1: Only Sym A has a signal
                if "2026-01-05" in str(event.timestamp) and event.symbol == sym_a:
                    self.emit_signal(sym_a, Decimal("0.30"))

            def on_fill(self, event: FillEvent):
                # When A fills on Day 2 open, try to emit a direct intent for Sym B
                if event.symbol == sym_a and not self.b_emitted:
                    self.b_emitted = True
                    self.event_bus.publish(
                        OrderIntentEvent(
                            timestamp=event.timestamp,
                            intent_id="ROGUE-SYM-B",
                            strategy_id=self.strategy_id,
                            symbol=sym_b,
                            side=OrderSide.BUY,
                            target_weight=Decimal("0.30"),
                            quantity=Decimal("100"),
                            reference_price=Decimal("20.00"),
                        )
                    )

        strategy = CrossSymbolRogueStrategy()
        engine = _build_multi_engine(
            {sym_a: frame_a, sym_b: frame_b},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        decisions: list[RiskDecisionEvent] = []
        engine.event_bus.subscribe(
            RiskDecisionEvent,
            lambda e: decisions.append(e) if isinstance(e, RiskDecisionEvent) else None,
        )
        result = engine.run()

        # Sym A fills, Sym B does not fill
        fills_by_sym = {f.symbol: f for f in result.fills}
        assert sym_a in fills_by_sym
        assert sym_b not in fills_by_sym

        rogue_b = [d for d in decisions if d.intent_id == "ROGUE-SYM-B"]
        assert len(rogue_b) >= 1
        assert not rogue_b[0].passed
        assert "next_bar_open_direct_order_unsupported" in rogue_b[0].reasons

    def test_authorization_single_use_and_finally_cleaned(self):
        """Authorization cannot leak across session or be reused after context closes."""
        sym = Symbol("600001")
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
            ]
        )
        strategy = StagedTargetStrategy({"2026-01-05": Decimal("0.30")})
        engine = _build_multi_engine(
            {sym: frame},
            strategy,
            execution_model=ExecutionModel.NEXT_BAR_OPEN,
        )
        result = engine.run()

        assert len(result.fills) == 1
        # Internal context variables are cleaned
        assert engine._open_signal_context is None
        assert engine._open_authorized_intent_id is None
        assert engine._open_authorized_order_id is None
        assert engine._executing_at_open is False

        # If a direct intent is submitted after the run, it must be rejected
        decisions: list[RiskDecisionEvent] = []
        engine.event_bus.subscribe(
            RiskDecisionEvent,
            lambda e: decisions.append(e) if isinstance(e, RiskDecisionEvent) else None,
        )
        engine._on_order_intent_event(
            OrderIntentEvent(
                timestamp=frame.index[-1],
                intent_id="POST-RUN-INTENT",
                strategy_id="test",
                symbol=sym,
                side=OrderSide.BUY,
                target_weight=Decimal("0.50"),
                quantity=Decimal("100"),
                reference_price=Decimal("10.00"),
            )
        )
        engine.event_bus.drain()
        assert len(decisions) == 1
        assert not decisions[0].passed
        assert "next_bar_open_direct_order_unsupported" in decisions[0].reasons
