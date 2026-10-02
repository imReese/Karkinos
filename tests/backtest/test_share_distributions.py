"""Share awards through real portfolio, strategy, risk and next-bar execution."""

from dataclasses import replace
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.distributions import StockDistribution, distributions_from_evidence
from backtest.engine import BacktestEngine
from core.event_bus import EventBus
from core.events import MarketEvent, OrderEvent
from core.types import ZERO, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import FixedSlippage
from risk.rules import RiskCheckResult, RiskRule
from strategy.base import Strategy
from strategy.builtins.time_series_momentum import TimeSeriesMomentumStrategy
from tests.backtest.test_cash_dividends import _evidence

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = Symbol("600000")
DAYS = [date(2026, 4, day) for day in (6, 7, 8, 9, 10, 13, 14, 15)]


def _close(day):
    return datetime.combine(day, time(15), SHANGHAI)


def _distribution(symbol=SYMBOL, **changes):
    return replace(
        StockDistribution(
            action_id=f"award-{symbol}",
            symbol=symbol,
            record_date=DAYS[3],
            ex_date=DAYS[4],
            pay_date=DAYS[6],
            cash_per_share=Decimal("0.13"),
            bonus_per_share=Decimal("0.1"),
            capitalized_per_share=Decimal("0.2"),
            listing_date=DAYS[6],
            available_at=_close(DAYS[0]),
        ),
        **changes,
    )


def _engine(strategy, *, symbols=(SYMBOL,), suspend_exit=False, distributions=None):
    rows = []
    for day in DAYS:
        price = Decimal("13") if day < DAYS[4] else Decimal("9.9")
        if day in DAYS[:2]:
            price = Decimal("12") + Decimal(DAYS.index(day)) / 2
        rows.append(
            {
                "timestamp": _close(day),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0 if suspend_exit and day == DAYS[5] else 100000,
            }
        )
    return BacktestEngine(
        strategy,
        {symbol: make_stock(str(symbol), "fixture") for symbol in symbols},
        {symbol: DataHandler(pd.DataFrame(rows), symbol) for symbol in symbols},
        initial_cash=Decimal("1300") * len(symbols),
        commission_calc=StockACommission(
            commission_rate=ZERO,
            min_commission=ZERO,
            stamp_tax_rate=ZERO,
            transfer_fee_rate=ZERO,
        ),
        slippage_model=FixedSlippage(ZERO),
        cash_dividends=tuple(_distribution(symbol) for symbol in symbols)
        if distributions is None
        else distributions,
        include_share_distributions=True,
    )


def test_awarded_shares_revalue_once_and_exit_after_listing_with_actual_strategy_state(
    caplog,
):
    strategy = TimeSeriesMomentumStrategy(
        EventBus(), lookback_period=2, min_return=0, exit_return=0
    )
    engine = _engine(strategy, suspend_exit=True)
    states = {}

    def record(event):
        position = engine.portfolio.positions.get(SYMBOL)
        if position:
            states[event.timestamp.date()] = (
                position.quantity,
                position.available_qty,
                position.unlisted_qty,
                engine.portfolio.dividend_receivable,
                engine.portfolio.total_equity,
            )

    engine.event_bus.subscribe(MarketEvent, record)
    result = engine.run()
    assert [(fill.side, fill.fill_quantity) for fill in result.fills] == [
        (OrderSide.BUY, Decimal("100")),
        (OrderSide.SELL, Decimal("130")),
    ]
    assert result.fills[0].timestamp == _close(DAYS[3])
    assert result.fills[1].timestamp == _close(DAYS[6])
    assert states[DAYS[4]] == (
        Decimal("130"),
        Decimal("100"),
        Decimal("30"),
        Decimal("13"),
        Decimal("1300"),
    )
    assert states[DAYS[5]] == states[DAYS[4]]
    assert result.final_equity == Decimal("1300")
    assert result.total_return == ZERO
    assert all(equity == Decimal("1300") for _, equity in result.equity_curve)
    assert result.positions[SYMBOL].quantity == ZERO
    assert strategy._position_quantity[SYMBOL] == ZERO
    accounting = result.cash_dividend_accounting
    assert accounting["mode"] == "reported_distributions_gross"
    assert Decimal(accounting["share_quantity"]) == 30
    assert Decimal(accounting["unlisted_quantity"]) == ZERO
    assert Decimal(accounting["cash_paid"]) == 13
    assert accounting["distributions"][0]["shares_listed"] is True
    assert "Handler on_fill failed" not in caplog.text


class RecordDateTargets(Strategy):
    def __init__(self, *, risky_sell=False, sell_quantity=Decimal("130")):
        super().__init__("record_targets", EventBus())
        self.risky_sell = risky_sell
        self.sell_quantity = sell_quantity

    def on_init(self, symbols):
        self.weight = 1.0 / len(symbols)

    def on_data(self, event):
        self._last_timestamp = event.timestamp
        if event.timestamp.date() == DAYS[2]:
            self.emit_signal(event.symbol, self.weight, float(event.close))
        if self.risky_sell and event.timestamp.date() == DAYS[5]:
            self.event_bus.publish(
                OrderEvent(
                    timestamp=event.timestamp,
                    order_id="sell-unlisted-shares",
                    symbol=event.symbol,
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=self.sell_quantity,
                    price=event.close,
                )
            )


def test_direct_sell_cannot_spend_unlisted_award_before_release():
    engine = _engine(RecordDateTargets(risky_sell=True))
    result = engine.run()
    assert [fill.side for fill in result.fills] == [OrderSide.BUY]
    assert result.execution_timing["risk_blocked_count"] == 1
    assert result.positions[SYMBOL].quantity == Decimal("130")
    assert result.positions[SYMBOL].available_qty == Decimal("130")
    assert result.final_equity == Decimal("1300")


@pytest.mark.parametrize("reverse", [False, True])
def test_all_awards_are_marked_before_first_symbol_sees_ex_date_equity(reverse):
    symbols = (SYMBOL, Symbol("600001"))
    if reverse:
        symbols = symbols[::-1]
    engine = _engine(RecordDateTargets(), symbols=symbols)
    observed = []

    def record(event):
        if event.timestamp.date() == DAYS[4]:
            observed.append((event.symbol, engine.portfolio.total_equity))

    engine.event_bus.subscribe(MarketEvent, record)
    result = engine.run()
    assert {symbol for symbol, _ in observed} == set(symbols)
    assert [equity for _, equity in observed] == [Decimal("2600")] * 2
    assert result.final_equity == Decimal("2600")
    assert all(position.quantity == 130 for position in result.positions.values())


def test_fractional_award_is_rejected_without_rounding_into_fake_shares():
    engine = _engine(
        RecordDateTargets(),
        distributions=(
            _distribution(bonus_per_share=Decimal("0.001"), capitalized_per_share=ZERO),
        ),
    )
    with pytest.raises(
        ValueError, match="portfolio_share_distribution_fractional_unsupported"
    ):
        engine.run()
    assert engine.portfolio.positions[SYMBOL].quantity == 100
    assert engine.portfolio.dividend_income == ZERO


def test_risk_modified_sell_is_checked_against_available_shares_after_modification():
    seen = []

    class ExpandSell(RiskRule):
        @property
        def name(self):
            return "expand_sell_fixture"

        def check(self, order, positions, portfolio_value):
            if order.side is OrderSide.SELL:
                seen.append((order.quantity, positions[order.symbol].available_qty))
                return RiskCheckResult(
                    passed=True,
                    modified_order=replace(order, quantity=Decimal("130")),
                )
            return RiskCheckResult(passed=True)

    engine = _engine(RecordDateTargets(risky_sell=True, sell_quantity=Decimal("100")))
    engine.risk_manager.add_rule(ExpandSell())
    result = engine.run()
    assert seen == [(Decimal("100"), Decimal("100"))]
    assert [fill.side for fill in result.fills] == [OrderSide.BUY]
    assert result.execution_timing["risk_blocked_count"] == 1
    assert result.positions[SYMBOL].quantity == Decimal("130")
    assert result.final_equity == Decimal("1300")


@pytest.mark.parametrize("boundary", ["construction", "evidence"])
def test_finite_share_components_whose_sum_overflows_are_rejected_safely(boundary):
    finite_rate = Decimal("9e999999")
    assert finite_rate.is_finite()
    with pytest.raises(ValueError, match="^share_distribution_terms_invalid$"):
        if boundary == "construction":
            _distribution(
                bonus_per_share=finite_rate, capitalized_per_share=finite_rate
            )
        else:
            evidence = _evidence()
            evidence["events"][0].update(
                stk_div="9e999999", stk_bo_rate="9e999999", stk_co_rate="9e999999"
            )
            distributions_from_evidence(evidence, include_shares=True)
