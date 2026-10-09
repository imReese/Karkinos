"""Tests for strategy/builtins/etf_rotation.py."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import ZERO, OrderSide, Symbol
from data.handler import DataHandler
from data.manager import DataManager
from data.universe import CORE_ETF_UNIVERSE
from execution.commission import ETFCommission
from strategy.builtins.etf_rotation import EtfRotationStrategy
from strategy.registry import StrategyRegistry


def _make_event(symbol: Symbol, price: float, day: int) -> MarketEvent:
    return MarketEvent(
        timestamp=datetime(2026, 1, day + 1),
        symbol=symbol,
        open=Decimal(str(price)),
        high=Decimal(str(price + 0.5)),
        low=Decimal(str(price - 0.5)),
        close=Decimal(str(price)),
        volume=Decimal("1000000"),
    )


def test_etf_rotation_registered() -> None:
    assert "etf_rotation" in StrategyRegistry.list_strategies()
    entry = StrategyRegistry.get("etf_rotation")
    assert entry is not None
    assert entry["display_name"] == "Cross-Sectional ETF Rotation"


def test_etf_rotation_momentum_selection_and_cash_proxy() -> None:
    bus = EventBus()
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=3,
        volatility_window=3,
        top_k=1,
        rebalance_interval=1,
        min_momentum=0.0,
        trend_filter_period=0,
        use_risk_adjusted=False,
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])

    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # Days 0..3: Warmup prices
    # sym_a: 100 -> 101 -> 102 -> 103 (+3%)
    # sym_b: 100 -> 102 -> 105 -> 110 (+10%)
    # sym_cash: 100 -> 100 -> 100 -> 100 (0%)
    prices_a = [100.0, 101.0, 102.0, 103.0]
    prices_b = [100.0, 102.0, 105.0, 110.0]
    prices_c = [100.0, 100.1, 100.2, 100.3]

    for day in range(4):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    # sym_b had higher momentum than sym_a, so sym_b should be selected with target_weight=1.0
    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    assert latest_targets.get(sym_b) == 1.0
    assert latest_targets.get(sym_a) == 0.0


def test_etf_rotation_defensive_switch_when_all_drop() -> None:
    bus = EventBus()
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=2,
        volatility_window=2,
        top_k=2,
        rebalance_interval=1,
        min_momentum=0.0,
        use_risk_adjusted=False,
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])

    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # All equities drop below min_momentum (negative return)
    # Day 0: 100, Day 1: 95, Day 2: 90 (-10%)
    prices_a = [100.0, 95.0, 90.0]
    prices_b = [100.0, 90.0, 80.0]
    prices_c = [100.0, 100.1, 100.2]

    for day in range(3):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    # Both equities have negative momentum (< 0.0), so all weight rotates to cash_proxy
    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    assert latest_targets.get(sym_cash) == 1.0
    assert latest_targets.get(sym_a) == 0.0
    assert latest_targets.get(sym_b) == 0.0


def _rotation_engine(prices, *, cash_proxy=None, **strategy_params):
    params = {
        "lookback_period": 2,
        "volatility_window": 2,
        "top_k": 1,
        "rebalance_interval": 1,
        "min_momentum": 0.001,
        "use_risk_adjusted": False,
        "cash_proxy": cash_proxy,
        **strategy_params,
    }
    strategy = EtfRotationStrategy(EventBus(), **params)
    members = {str(m.symbol): m for m in CORE_ETF_UNIVERSE.members}
    instruments = {
        Symbol(s): DataManager.get_instrument_by_type(
            Symbol(s), members[s].instrument_type, name=members[s].name
        )
        for s in prices
    }
    handlers = {}
    for symbol, values in prices.items():
        frame = pd.DataFrame(
            {
                "timestamp": pd.bdate_range("2026-01-05", periods=len(values)),
                "open": values,
                "high": values,
                "low": values,
                "close": values,
                "volume": [1000000] * len(values),
            }
        )
        handlers[Symbol(symbol)] = DataHandler(frame, Symbol(symbol))
    return BacktestEngine(
        strategy,
        instruments,
        handlers,
        initial_cash=Decimal("10000"),
        commission_calc=ETFCommission(commission_rate=ZERO, min_commission=ZERO),
        strict_event_errors=True,
    )


def test_engine_rejects_unloaded_defensive_asset_before_running():
    engine = _rotation_engine({"510300": [10, 11, 12]}, cash_proxy="511010")
    with pytest.raises(ValueError, match="cash_proxy_input_missing:511010"):
        engine.run()
    assert engine.portfolio.cash == 10000
    assert engine.portfolio.positions == {}
    assert engine.fills == []


def test_rotation_retries_after_buy_precedes_sale_and_uses_real_holdings():
    engine = _rotation_engine(
        {
            "510300": [10, 10, 10, 11, 11.5, 12, 12.5, 13],
            "510500": [10, 10.5, 11, 11, 11, 11, 11, 11],
        }
    )
    books = {}

    def record_book(day):
        books[day] = {
            s: position.quantity for s, position in engine.portfolio.positions.items()
        }

    engine._session_completed = record_book
    result = engine.run()
    # A's later bar arrives before B's sale frees cash. The unchanged A target
    # must be reviewed again rather than falsely treated as already completed.
    assert books[pd.Timestamp("2026-01-09").date()].get("510300", ZERO) == ZERO
    assert books[pd.Timestamp("2026-01-09").date()]["510500"] == ZERO
    assert result.positions[Symbol("510300")].quantity == Decimal("800")
    assert result.positions[Symbol("510500")].quantity == ZERO
    assert [(fill.symbol, fill.side) for fill in result.fills] == [
        (Symbol("510500"), OrderSide.BUY),
        (Symbol("510500"), OrderSide.SELL),
        (Symbol("510300"), OrderSide.BUY),
    ]
    modeled_fees = sum((fill.commission for fill in result.fills), ZERO)
    assert engine.portfolio.cash == Decimal("400") - modeled_fees
    assert result.final_equity == Decimal("10800") - modeled_fees


@pytest.mark.parametrize("symbol", ["518880", "511010"])
def test_gold_and_bond_exposure_trade_as_etfs_through_real_engine(symbol):
    # Both securities use the same ETF lot and cost owner; gold/bond exposure
    # does not turn the exchange-traded fund into a spot metal or cash bond.
    prices = {"510300": [10, 9.9, 9.8, 9.7], symbol: [10, 10.1, 10.2, 10.3]}
    engine = _rotation_engine(prices, cash_proxy=symbol if symbol == "511010" else None)
    engine.execution.commission_calc = ETFCommission()
    result = engine.run()
    position = result.positions[Symbol(symbol)]
    assert position.quantity > ZERO
    assert position.quantity % 100 == ZERO
    assert all(fill.symbol == symbol for fill in result.fills)
    assert all(fill.fee_rule_id == "cn_fund_etf_default_v1" for fill in result.fills)
    assert result.final_equity == engine.portfolio.cash + position.market_value


@pytest.mark.parametrize("top_k", [6, 7])
def test_rebalance_targets_stay_within_gross_cap_after_precision_rounding(top_k):
    from domain.research_targets import build_research_target_weights

    symbols = [str(member.symbol) for member in CORE_ETF_UNIVERSE.members[:top_k]]
    engine = _rotation_engine(
        {symbol: [10, 10.1, 10.2, 10.3] for symbol in symbols}, top_k=top_k
    )
    signals = []
    engine.event_bus.subscribe(SignalEvent, signals.append)
    result = engine.run()
    targets = {str(signal.symbol): signal.target_weight for signal in signals}
    assert sum(targets.values(), ZERO) == 1
    # The forward target cap must preserve the same strategy output, rather than
    # silently rescale a different over-allocated version of this backtest.
    assert (
        build_research_target_weights(
            targets, max_symbol_weight=Decimal(1), max_gross_weight=Decimal(1)
        )
        == targets
    )
    assert len(result.fills) == top_k
    assert engine.portfolio.cash >= ZERO


def test_etf_rotation_composite_momentum_scoring() -> None:
    bus = EventBus()
    # 2 windows: 1 day and 3 days, weights: 0.5 and 0.5
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=3,
        top_k=1,
        rebalance_interval=1,
        min_momentum=-1.0,
        use_risk_adjusted=False,
        composite_lookback="1,3",
        composite_weights="0.5,0.5",
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])
    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # Day 0: 100, Day 1: 100, Day 2: 100, Day 3: 110 (A: 3d mom = 10%, 1d mom = 10% -> comp = 10%)
    # B: Day 0: 100, Day 1: 105, Day 2: 108, Day 3: 109 (B: 3d mom = 9%, 1d mom = 0.92% -> comp = ~4.96%)
    prices_a = [100.0, 100.0, 100.0, 110.0]
    prices_b = [100.0, 105.0, 108.0, 109.0]
    prices_c = [100.0, 100.0, 100.0, 100.0]

    for day in range(4):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    # sym_a has higher composite momentum (10% vs ~4.96%)
    assert latest_targets.get(sym_a) == 1.0
    assert latest_targets.get(sym_b) == 0.0


def test_etf_rotation_market_filter_defensive_trigger() -> None:
    bus = EventBus()
    # Market filter: 510300 with 2-period MA
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=2,
        top_k=1,
        rebalance_interval=1,
        min_momentum=-1.0,
        use_risk_adjusted=False,
        cash_proxy="511010",
        market_filter_symbol="510300",
        market_filter_period=2,
    )
    sym_market = Symbol("510300")
    sym_growth = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_market, sym_growth, sym_cash])
    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # 510300 (Market): Day 0: 100, Day 1: 95, Day 2: 90 (MA=92.5, Current=90 < MA -> Bearish!)
    # 510500 (Growth): Day 0: 100, Day 1: 105, Day 2: 110 (Strong positive momentum)
    # Even though 510500 has strong momentum, market filter triggers global defensive switch to cash proxy
    prices_m = [100.0, 95.0, 90.0]
    prices_g = [100.0, 105.0, 110.0]
    prices_c = [100.0, 100.1, 100.2]

    for day in range(3):
        strategy.on_data(_make_event(sym_market, prices_m[day], day))
        strategy.on_data(_make_event(sym_growth, prices_g[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    assert latest_targets.get(sym_cash) == 1.0
    assert latest_targets.get(sym_growth) == 0.0
    assert latest_targets.get(sym_market) == 0.0


def test_etf_rotation_sortino_risk_adjustment() -> None:
    bus = EventBus()
    strategy = EtfRotationStrategy(
        bus,
        lookback_period=2,
        volatility_window=3,
        top_k=1,
        rebalance_interval=1,
        min_momentum=-1.0,
        use_risk_adjusted=True,
        risk_adjusted_mode="sortino",
        cash_proxy="511010",
    )
    sym_a = Symbol("510300")
    sym_b = Symbol("510500")
    sym_cash = Symbol("511010")

    strategy.on_init([sym_a, sym_b, sym_cash])
    signals: list[SignalEvent] = []
    bus.subscribe(SignalEvent, signals.append)

    # sym_a: smooth upward climb, zero downside return
    # Day 0: 100, Day 1: 101, Day 2: 102, Day 3: 103 (returns: +1%, +1%, +1%)
    # sym_b: volatile with a big dip then jump, same net return
    # Day 0: 100, Day 1: 95, Day 2: 100, Day 3: 103 (returns: -5%, +5.26%, +3%)
    prices_a = [100.0, 101.0, 102.0, 103.0]
    prices_b = [100.0, 95.0, 100.0, 103.0]
    prices_c = [100.0, 100.0, 100.0, 100.0]

    for day in range(4):
        strategy.on_data(_make_event(sym_a, prices_a[day], day))
        strategy.on_data(_make_event(sym_b, prices_b[day], day))
        strategy.on_data(_make_event(sym_cash, prices_c[day], day))
        bus.drain()

    latest_targets = {s.symbol: float(s.target_weight) for s in signals}
    # sym_a has no downside volatility, penalizes less, so sym_a is selected
    assert latest_targets.get(sym_a) == 1.0
    assert latest_targets.get(sym_b) == 0.0


def test_etf_rotation_enhanced_parameter_validations() -> None:
    bus = EventBus()
    # Invalid composite lookback string
    with pytest.raises(ValueError, match="composite_lookback_invalid"):
        EtfRotationStrategy(bus, composite_lookback="invalid")
    with pytest.raises(ValueError, match="composite_lookback_invalid"):
        EtfRotationStrategy(bus, composite_lookback="-1,20")

    # Mismatched weights length
    with pytest.raises(ValueError, match="composite_weights_invalid"):
        EtfRotationStrategy(bus, composite_lookback="5,20", composite_weights="0.5")

    # Missing market filter symbol in universe
    strat = EtfRotationStrategy(
        bus, market_filter_symbol="510300", market_filter_period=20
    )
    with pytest.raises(ValueError, match="market_filter_input_missing:510300"):
        strat.on_init([Symbol("510500"), Symbol("511010")])
