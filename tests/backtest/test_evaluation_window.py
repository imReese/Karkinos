"""Heldout bars use warmed strategy history and a fresh simulation book."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.distributions import StockDistribution
from backtest.engine import BacktestEngine, BacktestExecutionConfig
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent, OrderIntentEvent, SignalEvent
from core.types import ZERO, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import FixedSlippage
from strategy.base import Strategy
from strategy.builtins.dual_ma import DualMAStrategy

SYMBOL = Symbol("600001")
SHANGHAI = ZoneInfo("Asia/Shanghai")
DAYS = [day.date() for day in pd.bdate_range("2026-04-06", periods=8)]


def _close(day):
    return datetime.combine(day, time(15), SHANGHAI)


def _frame(prices, *, days=DAYS):
    return pd.DataFrame(
        [
            {
                "timestamp": _close(day),
                "available_at": _close(day),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 100000,
            }
            for day, price in zip(days, prices, strict=True)
        ]
    )


def _engine(strategy=None, *, frame=None, evaluation_start=DAYS[5], **kwargs):
    if strategy is None:
        strategy = DualMAStrategy(EventBus(), short_period=2, long_period=3)
    if frame is None:
        frame = _frame([10, 9.8, 9.6, 9.8, 10, 10.2, 10.3, 10.4])
    return BacktestEngine(
        strategy,
        {SYMBOL: make_stock(str(SYMBOL), "synthetic stock")},
        {SYMBOL: DataHandler(frame, SYMBOL)},
        evaluation_start=evaluation_start,
        slippage_model=FixedSlippage(Decimal("0.01")),
        **kwargs,
    )


class DatedActions(Strategy):
    def __init__(self, targets=None, *, direct_days=(), init_orders=False):
        super().__init__("dated_actions", EventBus())
        self.targets = targets or {}
        self.direct_days = direct_days
        self.init_orders = init_orders
        self.observed = []
        self.initialized = False

    def on_init(self, symbols):
        self.initialized = True
        if self.init_orders:
            self._direct_orders(_close(DAYS[0]), Decimal("10"))

    def _direct_orders(self, timestamp, price):
        self.event_bus.publish(
            OrderEvent(
                timestamp=timestamp,
                order_id="direct-order",
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("100"),
                price=price,
            )
        )
        self.event_bus.publish(
            OrderIntentEvent(
                timestamp=timestamp,
                intent_id="direct-intent",
                strategy_id=self.strategy_id,
                symbol=SYMBOL,
                side=OrderSide.BUY,
                target_weight=Decimal("0.1"),
                quantity=Decimal("100"),
                reference_price=price,
            )
        )

    def on_data(self, event):
        day = event.timestamp.date()
        self.observed.append(day)
        if day in self.targets:
            self.event_bus.publish(
                SignalEvent(
                    timestamp=event.timestamp,
                    strategy_id=self.strategy_id,
                    symbol=event.symbol,
                    target_weight=self.targets[day],
                    price=event.close,
                )
            )
        if day in self.direct_days:
            self._direct_orders(event.timestamp, event.close)


def test_warmup_crossover_is_discarded_and_above_ma_does_not_fabricate_entry():
    full = _engine(evaluation_start=None).run()
    engine = _engine()

    result = engine.run()

    assert len(full.fills) == 1
    assert full.cost_summary.total_commission > ZERO
    assert result.fills == []
    assert engine.portfolio.positions == {}
    assert engine.portfolio.cash == result.initial_cash == result.final_equity
    assert result.cost_summary.total_commission == ZERO
    assert result.cost_summary.total_slippage == ZERO
    assert result.execution_timing["pending_signal_count"] == 0
    assert result.equity_curve == [
        (_close(day), result.initial_cash) for day in DAYS[5:]
    ]
    assert engine.strategy._prices[SYMBOL] == [10, 9.8, 9.6, 9.8, 10, 10.2, 10.3, 10.4]
    assert engine.strategy._prev_short_above_long[SYMBOL] is True
    assert "evaluation_start" not in full.execution_timing
    assert result.execution_timing["evaluation_start"] == DAYS[5].isoformat()


def test_first_evaluation_crossover_fills_only_on_later_bar_with_normal_costs():
    engine = _engine(evaluation_start=DAYS[4])
    first_states = []

    def observe(event):
        if event.timestamp.date() == DAYS[4]:
            first_states.append(
                (engine.portfolio.cash, dict(engine.portfolio.positions))
            )

    engine.event_bus.subscribe(MarketEvent, observe)
    result = engine.run()

    assert first_states == [(result.initial_cash, {})]
    assert result.equity_curve[0] == (_close(DAYS[4]), result.initial_cash)
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == _close(DAYS[5])
    assert result.fills[0].fill_price == Decimal("10.21")
    assert result.cost_summary.total_commission == result.fills[0].commission > ZERO
    assert result.cost_summary.total_slippage > ZERO


def test_warmup_direct_orders_intents_and_signals_never_touch_book_or_storage():
    strategy = DatedActions(
        {DAYS[0]: Decimal("1"), DAYS[4]: Decimal("1")},
        direct_days=DAYS[:5],
        init_orders=True,
    )
    db = MagicMock()
    engine = _engine(strategy, db=db)
    settle = engine.portfolio.advance_settlement_day
    engine.portfolio.advance_settlement_day = MagicMock(wraps=settle)
    warmup_states = []

    def observe(event):
        if event.timestamp.date() < DAYS[5]:
            warmup_states.append(
                (
                    engine.portfolio.cash,
                    dict(engine.portfolio.positions),
                    len(engine.portfolio.equity_curve),
                    len(engine.fills),
                )
            )

    engine.event_bus.subscribe(MarketEvent, observe)
    result = engine.run()

    assert strategy.observed == DAYS
    assert warmup_states == [(result.initial_cash, {}, 0, 0)] * 5
    assert result.fills == []
    assert result.execution_timing["pending_signal_count"] == 0
    assert result.execution_timing["risk_blocked_count"] == 0
    assert engine.portfolio.advance_settlement_day.call_count == 2
    assert engine.event_bus.queue_size == 0
    assert db.mock_calls == []


def test_warmup_previous_close_still_blocks_first_evaluation_limit_up_orders():
    engine = _engine(
        DatedActions(direct_days=[DAYS[5]]),
        frame=_frame([10, 10, 10, 10, 10, 11, 11, 11]),
    )

    result = engine.run()

    assert result.fills == []
    assert result.execution_timing["limit_blocked_count"] == 2


def _distribution(**changes):
    return StockDistribution(
        **{
            "action_id": "synthetic-distribution",
            "symbol": SYMBOL,
            "record_date": DAYS[2],
            "ex_date": DAYS[3],
            "pay_date": DAYS[6],
            "listing_date": DAYS[6],
            "cash_per_share": Decimal("0.13"),
            "bonus_per_share": Decimal("0.1"),
            "capitalized_per_share": Decimal("0.2"),
            "available_at": _close(DAYS[0]),
            **changes,
        }
    )


@pytest.mark.parametrize("evaluation_start", [DAYS[3], DAYS[4]])
def test_warmup_record_date_cannot_award_cash_or_shares_to_later_purchase(
    evaluation_start,
):
    engine = _engine(
        DatedActions({DAYS[0]: Decimal("1"), DAYS[4]: Decimal("0.1")}),
        frame=_frame([10] * 8),
        evaluation_start=evaluation_start,
        initial_cash=Decimal("10000"),
        cash_dividends=(_distribution(),),
        include_share_distributions=True,
    )

    result = engine.run()

    assert [fill.timestamp for fill in result.fills] == [_close(DAYS[5])]
    assert result.positions[SYMBOL].quantity == Decimal("100")
    assert result.positions[SYMBOL].unlisted_qty == ZERO
    assert engine.portfolio.dividend_income == ZERO
    assert engine.portfolio.dividend_receivable == ZERO
    accounting = result.cash_dividend_accounting
    assert Decimal(accounting["cash_paid"]) == ZERO
    assert Decimal(accounting["share_quantity"]) == ZERO
    assert accounting["distributions"][0]["eligible_quantity"] == "0"
    assert result.equity_curve[0] == (_close(evaluation_start), result.initial_cash)


def test_evaluation_record_date_earns_normal_cash_and_locked_share_awards():
    engine = _engine(
        DatedActions({DAYS[0]: Decimal("1"), DAYS[1]: Decimal("1")}),
        frame=_frame([13, 13, 13, 9.9, 9.9, 9.9, 9.9, 9.9]),
        evaluation_start=DAYS[1],
        initial_cash=Decimal("1300"),
        commission_calc=StockACommission(
            commission_rate=ZERO,
            min_commission=ZERO,
            stamp_tax_rate=ZERO,
            transfer_fee_rate=ZERO,
        ),
        cash_dividends=(_distribution(),),
        include_share_distributions=True,
    )
    # Use exact prices to isolate distribution and settlement ownership.
    engine.execution.slippage_model = FixedSlippage(ZERO)
    states = {}

    def observe(event):
        position = engine.portfolio.positions.get(SYMBOL)
        if position:
            states[event.timestamp.date()] = (
                position.quantity,
                position.available_qty,
                position.unlisted_qty,
                engine.portfolio.dividend_receivable,
            )

    engine.event_bus.subscribe(MarketEvent, observe)
    result = engine.run()

    assert [fill.timestamp for fill in result.fills] == [_close(DAYS[2])]
    assert states[DAYS[3]] == (
        Decimal("130"),
        Decimal("100"),
        Decimal("30"),
        Decimal("13"),
    )
    assert states[DAYS[6]] == (Decimal("130"), Decimal("130"), ZERO, ZERO)
    assert (
        result.cash_dividend_accounting["distributions"][0]["eligible_quantity"]
        == "100"
    )
    assert result.final_equity == Decimal("1300")
    assert all(value == result.initial_cash for _, value in result.equity_curve)


@pytest.mark.parametrize("missing", [DAYS[2], DAYS[3]])
def test_warmup_required_corporate_action_bars_still_fail_closed(missing):
    strategy = DatedActions()
    days = [day for day in DAYS if day != missing]
    engine = _engine(
        strategy,
        frame=_frame([10] * len(days), days=days),
        cash_dividends=(_distribution(),),
        include_share_distributions=True,
    )

    with pytest.raises(ValueError, match="cash_dividend_required_session_missing"):
        engine.run()

    assert strategy.initialized is False
    assert strategy.observed == []
    assert engine.portfolio.equity_curve == []


@pytest.mark.parametrize("late_ca", [False, True])
def test_warmup_availability_is_validated_before_any_strategy_observation(late_ca):
    strategy = DatedActions()
    frame = _frame([10] * 8)
    distribution = _distribution()
    if late_ca:
        distribution = _distribution(
            available_at=_close(DAYS[3]) + timedelta(seconds=1)
        )
        reason = "cash_dividend_historical_availability_unverified"
    else:
        frame.loc[0, "available_at"] = _close(DAYS[0]) + timedelta(seconds=1)
        reason = "backtest_observation_unavailable_at_event_time"
    engine = _engine(
        strategy,
        frame=frame,
        cash_dividends=(distribution,),
        include_share_distributions=True,
        execution_config=BacktestExecutionConfig(availability_mode="observed"),
    )

    with pytest.raises(ValueError, match=reason):
        engine.run()

    assert strategy.initialized is False
    assert strategy.observed == []


@pytest.mark.parametrize("boundary", ["2026-04-13", datetime(2026, 4, 13), True])
def test_evaluation_start_requires_a_session_date(boundary):
    with pytest.raises(ValueError, match="backtest_evaluation_start_invalid"):
        _engine(evaluation_start=boundary)
