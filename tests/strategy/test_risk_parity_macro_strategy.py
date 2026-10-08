"""Aligned daily baskets produce bounded research targets without fallback."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import BarFrequency, Symbol
from strategy.builtins.risk_parity_macro import RiskParityMacroStrategy
from strategy.registry import StrategyRegistry

SYMBOLS = [Symbol("510300"), Symbol("511010")]
PRICES = np.array(
    [
        [100, 100],
        [102, 100.1],
        [101, 100.05],
        [100, 100.2],
        [99, 100.15],
        [98, 100.3],
        [99, 100.25],
        [97, 100.4],
        [96, 100.35],
        [98, 100.5],
        [95, 100.45],
        [97, 100.6],
    ]
)


def event(symbol, price, day):
    close = Decimal(str(price))
    return MarketEvent(
        timestamp=datetime(2026, 1, 1, 15) + timedelta(days=day),
        symbol=symbol,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1000000"),
    )


def setup(**changes):
    bus = EventBus()
    strategy = RiskParityMacroStrategy(
        bus,
        **{
            "lookback_period": 10,
            "rebalance_interval": 1,
            "trend_filter": False,
            **changes,
        },
    )
    strategy.on_init(SYMBOLS)
    signals = []
    bus.subscribe(SignalEvent, signals.append)
    return strategy, bus, signals


def replay(strategy, bus, rows=PRICES, order=(0, 1)):
    for day, prices in enumerate(rows):
        for i in order:
            strategy.on_data(event(SYMBOLS[i], prices[i], day))
        strategy.require_complete_session(
            event(SYMBOLS[0], prices[0], day).timestamp.date()
        )
        bus.drain()


def test_registered_strategy_has_typed_parameters_and_research_boundary():
    entry = next(
        row
        for row in StrategyRegistry.get_info()
        if row["strategy_id"] == "risk_parity_macro"
    )
    schema = {param["name"]: param["type"] for param in entry["parameter_schema"]}
    assert schema["risk_budgets"] == "dict"
    assert schema["cash_proxy"] == "str"
    assert entry["execution_boundary"]["research_only"] is True
    assert entry["requires_after_cost_report"] is True
    assert entry["requires_out_of_sample_validation"] is True
    assert entry["benchmark_role"] == "bounded_macro_risk_budgeting"


def test_warmup_then_cap_and_complete_timestamp_targets_are_order_independent():
    strategy, bus, signals = setup()
    replay(strategy, bus)
    assert len(signals) == 4
    assert signals[0].timestamp == event(SYMBOLS[0], 0, 10).timestamp
    for pair in (signals[:2], signals[2:]):
        assert sum(row.target_weight for row in pair) == Decimal(1)
        assert all(
            Decimal("0.05") <= row.target_weight <= Decimal("0.6") for row in pair
        )
        assert pair[1].target_weight == Decimal("0.6")
    other, other_bus, other_signals = setup()
    replay(other, other_bus, order=(1, 0))
    assert [(s.symbol, s.timestamp, s.target_weight) for s in other_signals] == [
        (s.symbol, s.timestamp, s.target_weight) for s in signals
    ]
    strategy.on_init(SYMBOLS)
    signals.clear()
    replay(strategy, bus)
    assert [s.target_weight for s in signals] == [
        s.target_weight for s in other_signals
    ]


def test_custom_risk_budgets_and_trend_filter_have_expected_risk_contributions():
    strategy, bus, signals = setup(
        trend_filter=True,
        trend_ma_period=5,
        min_asset_weight=0,
        max_asset_weight=1,
        risk_budgets={"510300": 2, "511010": 1},
    )
    replay(strategy, bus, PRICES[:11])
    weights = np.array([float(signal.target_weight) for signal in signals])
    returns = PRICES[1:11] / PRICES[:10] - 1
    cov = np.cov(returns, rowvar=False, ddof=1)
    rc = weights * (cov @ weights)
    # Equity is below its average, so only its budget gets multiplied by 0.2.
    np.testing.assert_allclose(rc / rc.sum(), np.array([0.4, 1]) / 1.4, atol=1e-8)


def test_signal_reference_price_preserves_original_decimal_precision():
    strategy, bus, signals = setup()
    replay(strategy, bus, PRICES[:10])
    exact = Decimal("95.123456789123456789")
    strategy.on_data(event(SYMBOLS[0], exact, 10))
    strategy.on_data(event(SYMBOLS[1], PRICES[10, 1], 10))
    bus.drain()
    assert signals[0].price == exact


@pytest.mark.parametrize(
    "kind,error",
    [
        ("duplicate", "duplicate_session_bar"),
        ("missing", "incomplete_session"),
        ("out_of_order", "bars_out_of_order"),
        ("different_close_time", "timestamps_mismatch"),
        ("intraday", "daily_bars_required"),
    ],
)
def test_bad_bars_never_create_cross_date_return_pairs(kind, error):
    strategy, bus, signals = setup()
    first = event(SYMBOLS[0], 100, 1)
    strategy.on_data(first)
    second = {
        "duplicate": first,
        "missing": event(SYMBOLS[1], 100, 2),
        "out_of_order": event(SYMBOLS[1], 100, 0),
        "different_close_time": replace(
            event(SYMBOLS[1], 100, 1), timestamp=first.timestamp + timedelta(minutes=1)
        ),
        "intraday": replace(event(SYMBOLS[1], 100, 1), frequency=BarFrequency.MIN_1),
    }[kind]
    with pytest.raises(ValueError, match=error):
        strategy.on_data(second)
    bus.drain()
    assert signals == []


def test_last_incomplete_session_and_zero_variance_fail_without_targets():
    strategy, bus, signals = setup()
    first = event(SYMBOLS[0], 100, 0)
    strategy.on_data(first)
    with pytest.raises(ValueError, match="incomplete_session"):
        strategy.require_complete_session(first.timestamp.date())
    strategy.on_init(SYMBOLS)
    with pytest.raises(ValueError, match="risk_budget_covariance_invalid"):
        replay(strategy, bus, np.full((11, 2), 100.0))
    assert signals == []


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"min_asset_weight": 0.6}, "bounds"),
        ({"max_asset_weight": 0.4}, "bounds"),
        ({"max_asset_weight": float("nan")}, "bounds"),
        ({"trend_filter": "false"}, "trend_filter_invalid"),
        ({"risk_budgets": {"510300": 0, "511010": 1}}, "risk_budgets_invalid"),
        ({"risk_budgets": {"510300": 1}}, "universe_mismatch"),
        (
            {"risk_budgets": {"510300": 1, "511010": 1, "518880": 1}},
            "universe_mismatch",
        ),
        ({"cash_proxy": "518880"}, "cash_proxy_input_missing"),
    ],
)
def test_invalid_inputs_fail_before_replay(changes, error):
    with pytest.raises(ValueError, match=error):
        setup(**changes)
