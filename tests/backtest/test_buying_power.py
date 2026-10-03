"""Actual fills must fit cash, including final fees and earlier queued trades."""

import json
from dataclasses import replace
from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.events import FillEvent, MarketEvent, OrderEvent, RiskDecisionEvent
from core.types import ZERO, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_gold_spot, make_stock
from execution.commission import MultiAssetCommission, StockACommission
from execution.slippage import PercentSlippage, SlippageModel
from risk.limits import ConcentrationRule, MaxDrawdownRule
from risk.rules import RiskCheckResult, RiskRule
from server.db import AppDatabase
from server.services.reviewed_fee_schedule_commission import (
    _NotionalBoundedCommissionCalculator,
    _RoundedCommissionCalculator,
)
from strategy.base import Strategy

SYMBOL = Symbol("600000")


class Buyer(Strategy):
    def __init__(self, schedule=None):
        super().__init__("cash-bound-fixture", EventBus())
        self.schedule = schedule
        self.count = 0
        self.received_fills = []
        self.quantities = []

    def on_init(self, symbols):
        pass

    def on_data(self, event):
        self._last_timestamp = event.timestamp
        self.count += 1
        if self.schedule is None and self.count == 1:
            self.emit_signal(event.symbol, 1, float(event.close))
        for index, (side, quantity) in enumerate(
            (self.schedule or {}).get(self.count, [])
        ):
            self.event_bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id=f"cash-order-{self.count}-{index}",
                    symbol=event.symbol,
                    side=OrderSide(side),
                    order_type=OrderType.MARKET,
                    quantity=Decimal(quantity),
                    price=event.close,
                )
            )

    def on_fill(self, event):
        self.received_fills.append(event)

    def on_position_update(self, symbol, quantity):
        self.quantities.append(quantity)


def _engine(cash, *, schedule=None, instrument=None, **kwargs):
    instrument = instrument or make_stock(str(SYMBOL), "synthetic")
    frame = pd.DataFrame(
        {
            "timestamp": pd.bdate_range("2026-01-05", periods=3),
            "open": [10] * 3,
            "high": [10] * 3,
            "low": [10] * 3,
            "close": [10] * 3,
            "volume": [100000] * 3,
        }
    )
    return BacktestEngine(
        Buyer(schedule),
        {instrument.symbol: instrument},
        {instrument.symbol: DataHandler(frame, instrument.symbol)},
        initial_cash=Decimal(cash),
        **kwargs,
    )


@pytest.mark.parametrize(
    "cash,slip,quantity,remaining",
    [
        ("1000", "0", "0", "1000"),
        ("1000", "0.01", "0", "1000"),
        ("2000", "0", "100", "994.99"),
        ("2020", "0.01", "100", "1004.9899"),
        ("2005.02", "0", "200", "0"),
    ],
)
def test_next_bar_buy_uses_actual_price_and_complete_fee(
    cash, slip, quantity, remaining
):
    engine = _engine(cash, slippage_model=PercentSlippage(Decimal(slip)))
    decisions = []
    engine.event_bus.subscribe(RiskDecisionEvent, decisions.append)
    result = engine.run()

    assert sum((fill.fill_quantity for fill in result.fills), ZERO) == Decimal(quantity)
    assert engine.portfolio.cash == Decimal(remaining)
    assert decisions[-1].passed is bool(result.fills)
    if result.fills:
        fill = result.fills[0]
        assert fill.timestamp == pd.Timestamp("2026-01-06")
        assert fill.commission == StockACommission().calculate(
            OrderSide.BUY, fill.fill_price, fill.fill_quantity
        )
        assert result.final_equity == Decimal(remaining) + 10 * Decimal(quantity)
    else:
        assert result.positions == {}
        assert result.cost_summary.total_commission == ZERO
        assert result.execution_timing["cash_blocked_count"] == 1


class CapQuantity(RiskRule):
    name = "cap-quantity"

    def check(self, order, positions, portfolio_value):
        return RiskCheckResult(
            True, modified_order=replace(order, quantity=Decimal("200"))
        )


def test_direct_and_risk_modified_buy_share_budget_and_lot_rounding():
    engine = _engine("2000", schedule={1: [("buy", "300")]})
    engine.risk_manager.add_rule(CapQuantity())
    result = engine.run()
    assert [fill.fill_quantity for fill in result.fills] == [Decimal("100")]
    assert engine.portfolio.cash == Decimal("994.99")
    assert result.execution_timing["cash_resized_count"] == 1


@pytest.mark.parametrize("persist", [False, True])
def test_queued_buys_book_cash_and_preserve_rich_fill_once(tmp_path, persist):
    db = None
    if persist:
        db = AppDatabase(tmp_path / "book.db")
        db.init_sync()
    engine = _engine("1500", schedule={1: [("buy", "100"), ("buy", "100")]}, db=db)
    cash_after_fill = []
    engine.event_bus.subscribe(
        FillEvent, lambda _: cash_after_fill.append(engine.portfolio.cash)
    )
    result = engine.run()
    engine.event_bus.drain()

    assert len(result.fills) == 1
    fill = result.fills[0]
    assert engine.strategy.received_fills == [fill]
    assert engine.strategy.quantities == [Decimal("100")]
    assert cash_after_fill == [Decimal("494.99")]
    assert result.positions[SYMBOL].quantity == 100
    assert engine.risk_manager._portfolio_value["cash"] == 494.99
    assert fill.fee_breakdown["total_fee"] == str(fill.commission)
    assert fill.fee_rule_id == "cn_stock_a_default_v1"
    if db:
        assert len(db.list_orders_sync()) == len(db.list_fills_sync()) == 1
        saved = db.get_fill_sync(fill.fill_id)
        assert saved["commission"] == float(fill.commission)
        assert json.loads(saved["metadata_json"])["fee_breakdown"] == fill.fee_breakdown
        assert db.get_order_sync(fill.order_id)["quantity"] == 100


def test_queued_sells_cannot_sell_the_same_settled_shares_twice():
    engine = _engine(
        "1500", schedule={1: [("buy", "100")], 2: [("sell", "100"), ("sell", "100")]}
    )
    result = engine.run()
    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert engine.portfolio.cash == Decimal("1489.48")
    assert result.positions[SYMBOL].quantity == ZERO
    assert engine.strategy.quantities == [Decimal("100"), ZERO]
    assert result.execution_timing["risk_blocked_count"] == 1


def test_queued_buys_preserve_concentration_limit_after_first_fill():
    engine = _engine("5000", schedule={1: [("buy", "100"), ("buy", "100")]})
    engine.risk_manager.add_rule(ConcentrationRule(Decimal("0.30")))

    result = engine.run()

    assert len(result.fills) == 1
    assert result.positions[SYMBOL].market_value == Decimal("1000")
    assert result.execution_timing["risk_blocked_count"] == 1
    assert result.final_equity == Decimal("4994.99")


def test_strategy_fill_callback_sees_complete_book_before_synchronous_followup():
    engine = _engine("5000", schedule={1: [("buy", "100")]})
    engine.risk_manager.add_rule(ConcentrationRule(Decimal("0.30")))
    callback_values = []
    original_callback = engine.strategy.on_fill

    def followup(event):
        original_callback(event)
        callback_values.append(
            (engine.portfolio.total_equity, engine.risk_manager._portfolio_value.copy())
        )
        engine.event_bus.publish_and_process(
            OrderEvent(
                timestamp=event.timestamp,
                order_id="strategy-fill-followup",
                symbol=event.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                price=Decimal("10"),
            )
        )

    engine.event_bus.unsubscribe(FillEvent, original_callback)
    # Match the existing strategy callback's place before position-update sync.
    engine.event_bus.unsubscribe(FillEvent, engine._on_position_fill)
    engine.event_bus.subscribe(FillEvent, followup)
    engine.event_bus.subscribe(FillEvent, engine._on_position_fill)

    result = engine.run()

    assert len(result.fills) == 1
    assert callback_values == [
        (Decimal("4994.99"), {"total": 4994.99, "cash": 3994.99})
    ]
    assert engine.strategy.received_fills == result.fills
    assert engine.strategy.quantities == [Decimal("100")]
    assert result.execution_timing["risk_blocked_count"] == 1


def test_queued_buys_do_not_turn_spent_cash_into_a_phantom_drawdown():
    engine = _engine(
        "3000",
        schedule={1: [("buy", "100"), ("buy", "100")]},
        slippage_model=PercentSlippage(Decimal("0.01")),
    )
    engine.risk_manager.add_rule(MaxDrawdownRule(Decimal("0.15")))
    after_fills = []
    engine.event_bus.subscribe(
        FillEvent,
        lambda _: after_fills.append(
            (engine.portfolio.total_equity, engine.risk_manager._portfolio_value.copy())
        ),
    )

    result = engine.run()

    assert len(result.fills) == 2
    assert after_fills == [
        (Decimal("2984.9899"), {"total": 2984.9899, "cash": 1984.9899}),
        (Decimal("2969.9798"), {"total": 2969.9798, "cash": 969.9798}),
    ]
    assert result.positions[SYMBOL].market_value == Decimal("2000")
    assert result.execution_timing["risk_blocked_count"] == 0


@pytest.mark.parametrize("has_previous_mark", [False, True])
def test_cross_symbol_order_uses_only_already_observed_matching_market_price(
    has_previous_mark,
):
    engine = _engine("3000", schedule={})
    now = pd.Timestamp("2026-01-05")
    # Another symbol's bar must not become this order's market valuation. Its
    # own unread future DataHandler bars must not supply a valuation either.
    engine._current_market_event = MarketEvent(
        timestamp=now,
        symbol=Symbol("600001"),
        open=Decimal("999"),
        high=Decimal("999"),
        low=Decimal("999"),
        close=Decimal("999"),
        volume=Decimal("100000"),
    )
    if has_previous_mark:
        engine._previous_close[SYMBOL] = Decimal("9")
    engine._on_order_event(
        OrderEvent(
            timestamp=now,
            order_id="cross-symbol",
            symbol=SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("100"),
            price=Decimal("10"),
        )
    )

    if has_previous_mark:
        assert len(engine.fills) == 1
        assert engine.portfolio.positions[SYMBOL].market_value == Decimal("900")
        assert engine.portfolio.total_equity == Decimal("2894.99")
        assert engine.risk_manager._portfolio_value["total"] == 2894.99
    else:
        assert engine.fills == []
        assert engine.portfolio.positions == {}
        assert engine.portfolio.cash == 3000


def test_t_plus_zero_buy_sell_buy_queue_uses_completed_proceeds_and_current_risk_cash():
    engine = _engine(
        "1000",
        schedule={1: [("buy", "100"), ("sell", "100"), ("buy", "100")]},
        instrument=make_gold_spot(),
        commission_calc=StockACommission(
            commission_rate=ZERO,
            min_commission=ZERO,
            stamp_tax_rate=ZERO,
            transfer_fee_rate=ZERO,
        ),
    )
    seen_cash = []

    class ObserveCash(RiskRule):
        name = "observe-cash"

        def check(self, order, positions, portfolio_value):
            seen_cash.append(
                (portfolio_value["cash"], engine.risk_manager._portfolio_value["cash"])
            )
            return RiskCheckResult(True)

    engine.risk_manager.add_rule(ObserveCash())
    result = engine.run()
    assert [fill.side for fill in result.fills] == [
        OrderSide.BUY,
        OrderSide.SELL,
        OrderSide.BUY,
    ]
    assert seen_cash == [(1000, 1000), (0, 0), (1000, 1000)]
    assert engine.strategy.quantities == [Decimal("100"), ZERO, Decimal("100")]
    assert engine.portfolio.cash == ZERO


def test_dividend_receivable_is_not_spendable_cash():
    engine = _engine("1000")
    engine.portfolio.accrue_cash_dividend(
        "unpaid",
        symbol=SYMBOL,
        eligible_quantity=Decimal("100"),
        cash_per_share=Decimal("1"),
    )
    result = engine.run()
    assert result.fills == []
    assert engine.portfolio.cash == 1000
    assert engine.portfolio.dividend_receivable == 100


class ChangingSlippage(SlippageModel):
    def __init__(self, prices):
        self.prices = iter(map(Decimal, prices))
        self.quantities = []

    def apply(self, price, side, quantity):
        self.quantities.append(quantity)
        return next(self.prices)


@pytest.mark.parametrize("second_price,expected_count", [("10.7", 1), ("20.5", 0)])
def test_stateful_nonmonotonic_slippage_is_requoted_and_accepted_fill_is_not_executed_again(
    second_price, expected_count
):
    model = ChangingSlippage(["10.1", second_price, "999"])
    engine = _engine("2010", slippage_model=model)
    result = engine.run()
    assert model.quantities == [Decimal("200"), Decimal("100")]
    assert len(result.fills) == expected_count
    assert engine.portfolio.cash >= ZERO
    if expected_count:
        assert result.fills[0].fill_price == Decimal("10.7")
        assert engine.portfolio.cash == Decimal("934.9893")


def test_symbol_reviewed_fee_rounding_is_recomputed_for_final_quantity():
    calculator = MultiAssetCommission(fee_rule_version="reviewed-fixture")
    calculator.set_symbol_commission(
        str(SYMBOL),
        _RoundedCommissionCalculator(
            StockACommission(
                commission_rate=Decimal("0.007"),
                min_commission=ZERO,
                transfer_fee_rate=Decimal("0.000023"),
                other_fee_rate=Decimal("0.000031"),
                fee_rule_id="reviewed-symbol-fixture",
            ),
            precision=Decimal("0.01"),
            rounding_mode="half_up",
        ),
    )
    engine = _engine("2010", commission_calc=calculator)
    result = engine.run()
    fill = result.fills[0]
    assert fill.fill_quantity == 100
    assert fill.commission == Decimal("7.05")
    assert fill.fee_breakdown["transfer_fee"] == "0.02"
    assert fill.fee_breakdown["other_fees"] == "0.03"
    assert fill.fee_rule_id == "reviewed-symbol-fixture"
    assert fill.fee_rule_version == "reviewed-fixture"
    assert engine.portfolio.cash == Decimal("1002.95")


def test_reviewed_fee_range_rejection_never_falls_back_or_records_a_fill(
    tmp_path, caplog
):
    db = AppDatabase(tmp_path / "rejected.db")
    db.init_sync()
    calculator = MultiAssetCommission()
    calculator.set_symbol_commission(
        str(SYMBOL),
        _NotionalBoundedCommissionCalculator(
            StockACommission(), asset_class="stock", maximum_gross_amount=Decimal("500")
        ),
    )
    engine = _engine("2000", commission_calc=calculator, db=db)
    result = engine.run()
    assert result.fills == []
    assert engine.portfolio.cash == 2000
    assert db.list_orders_sync() == db.list_fills_sync() == []
    assert "reviewed_fee_schedule_notional_envelope_exceeded" in caplog.text
