"""Portfolio order intent behavior."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from core.event_bus import EventBus
from core.events import FillEvent, OrderEvent, OrderIntentEvent, SignalEvent
from core.types import OrderSide, Symbol
from domain.instrument import make_stock
from domain.portfolio import Portfolio


def test_portfolio_defaults_to_no_real_cash() -> None:
    portfolio = Portfolio(EventBus())

    assert portfolio.cash == Decimal("0")
    assert portfolio.initial_cash == Decimal("0")


def test_signal_emits_order_intent_not_order_event() -> None:
    bus = EventBus()
    symbol = Symbol("600519")
    intents: list[OrderIntentEvent] = []
    orders: list[OrderEvent] = []

    portfolio = Portfolio(bus, initial_cash=Decimal("100000"))
    portfolio.add_instrument(make_stock("600519", "贵州茅台"))
    bus.subscribe(OrderIntentEvent, intents.append)
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(
        SignalEvent(
            timestamp=datetime(2024, 1, 2, 14, 50),
            strategy_id="unit_test",
            symbol=symbol,
            target_weight=Decimal("0.50"),
            price=Decimal("100"),
        )
    )
    bus.drain()

    assert len(intents) == 1
    assert orders == []
    intent = intents[0]
    assert intent.strategy_id == "unit_test"
    assert intent.symbol == symbol
    assert intent.target_weight == Decimal("0.50")
    assert intent.quantity == Decimal("500")
    assert intent.reference_price == Decimal("100")


def test_multi_asset_equity_uses_each_positions_own_mark_price() -> None:
    bus = EventBus()
    portfolio = Portfolio(bus, initial_cash=Decimal("100000"))
    first = Symbol("600001")
    second = Symbol("000001")
    for symbol in (first, second):
        portfolio.add_instrument(make_stock(str(symbol), str(symbol)))
        portfolio.on_fill(
            FillEvent(
                timestamp=datetime(2026, 8, 21, 10),
                fill_id=f"fill-{symbol}",
                order_id=f"order-{symbol}",
                symbol=symbol,
                side=OrderSide.BUY,
                fill_price=Decimal("10"),
                fill_quantity=Decimal("100"),
                commission=Decimal("0"),
                slippage=Decimal("0"),
            )
        )
    portfolio.mark_to_market({first: Decimal("11"), second: Decimal("23")})

    assert portfolio._calculate_equity() == Decimal("101400")


def test_dividend_receivable_preserves_equity_without_spendable_cash() -> None:
    bus = EventBus()
    portfolio = Portfolio(bus, initial_cash=Decimal("1000"))
    symbol = Symbol("600001")
    instrument = make_stock(str(symbol), str(symbol))
    portfolio.add_instrument(instrument)
    portfolio.on_fill(
        FillEvent(
            timestamp=datetime(2026, 4, 9, 15),
            fill_id="buy-before-record-date",
            order_id="order-before-record-date",
            symbol=symbol,
            side=OrderSide.BUY,
            fill_price=Decimal("10"),
            fill_quantity=Decimal("100"),
            commission=Decimal("0"),
            slippage=Decimal("0"),
        )
    )
    position = portfolio.positions[symbol]
    portfolio.mark_to_market({symbol: Decimal("10")})
    assert portfolio.total_equity == Decimal("1000")
    # The caller applies ex-date accounting against the frozen record-date holding.
    assert portfolio.accrue_cash_dividend(
        "dividend-1",
        symbol=symbol,
        eligible_quantity=Decimal("100"),
        cash_per_share=Decimal("1"),
    ) == Decimal("100")
    portfolio.mark_to_market({symbol: Decimal("9")})

    assert portfolio.cash == Decimal("0")
    assert portfolio.dividend_receivable == portfolio.dividend_income == Decimal("100")
    assert portfolio.total_equity == portfolio._calculate_equity() == Decimal("1000")
    assert portfolio._calculate_equity_with_prices({symbol: Decimal("8")}) == Decimal(
        "900"
    )
    assert portfolio._calculate_buy_quantity(
        instrument, Decimal("1"), Decimal("100")
    ) == Decimal("0")
    portfolio.record_equity(datetime(2026, 4, 10, 15), {symbol: Decimal("9")})
    assert portfolio.equity_curve[-1][1] == Decimal("1000")
    assert portfolio.pay_cash_dividend("dividend-1") == Decimal("100")
    assert portfolio.cash == Decimal("100")
    assert portfolio.dividend_receivable == Decimal("0")
    assert portfolio.dividend_income == Decimal("100")
    assert portfolio.total_equity == Decimal("1000")
    assert portfolio._calculate_buy_quantity(
        instrument, Decimal("1"), Decimal("100")
    ) == Decimal("100")
    assert position.quantity == position.frozen_qty == Decimal("100")
    assert position.avg_cost == Decimal("10")
    assert position.realized_pnl == position.commission_paid == Decimal("0")
    assert portfolio.initial_cash == Decimal("1000")


def test_cash_dividend_replay_is_idempotent_and_rejects_conflicting_facts() -> None:
    portfolio = Portfolio(EventBus())
    facts = {
        "symbol": Symbol("600001"),
        "eligible_quantity": Decimal("100"),
        "cash_per_share": Decimal("0.5"),
    }
    for _ in range(2):
        assert portfolio.accrue_cash_dividend("cash-1", **facts) == Decimal("50")
    assert portfolio.dividend_income == portfolio.dividend_receivable == Decimal("50")
    assert portfolio.pay_cash_dividend("cash-1") == Decimal("50")
    assert portfolio.pay_cash_dividend("cash-1") == Decimal("0")
    assert portfolio.accrue_cash_dividend("cash-1", **facts) == Decimal("50")
    for field, changed in (
        ("symbol", Symbol("600002")),
        ("eligible_quantity", Decimal("200")),
        ("cash_per_share", Decimal("0.25")),
    ):
        with pytest.raises(ValueError, match="portfolio_cash_dividend_conflict"):
            portfolio.accrue_cash_dividend("cash-1", **{**facts, field: changed})
    with pytest.raises(ValueError, match="portfolio_cash_dividend_unknown"):
        portfolio.pay_cash_dividend("unrecognized")
    assert portfolio.cash == portfolio.total_equity == Decimal("50")
    assert portfolio.dividend_receivable == Decimal("0")
    assert portfolio.dividend_income == Decimal("50")


def test_zero_dividend_entitlement_is_recorded_without_cash_or_income() -> None:
    portfolio = Portfolio(EventBus())
    facts = {
        "symbol": Symbol("600001"),
        "eligible_quantity": Decimal("0"),
        "cash_per_share": Decimal("1"),
    }
    assert portfolio.accrue_cash_dividend("zero", **facts) == Decimal("0")
    assert portfolio.pay_cash_dividend("zero") == Decimal("0")
    with pytest.raises(ValueError, match="portfolio_cash_dividend_conflict"):
        portfolio.accrue_cash_dividend(
            "zero", **{**facts, "eligible_quantity": Decimal("1")}
        )
    assert portfolio.total_equity == portfolio.dividend_income == Decimal("0")


@pytest.mark.parametrize("field", ["eligible_quantity", "cash_per_share"])
@pytest.mark.parametrize(
    "value", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 1]
)
def test_cash_dividend_rejects_invalid_decimal_facts_without_state_change(
    field, value
) -> None:
    portfolio = Portfolio(EventBus(), initial_cash=Decimal("100"))
    facts = {
        "symbol": Symbol("600001"),
        "eligible_quantity": Decimal("1"),
        "cash_per_share": Decimal("1"),
    }
    with pytest.raises(ValueError, match="portfolio_cash_dividend_.*_invalid"):
        portfolio.accrue_cash_dividend("bad", **{**facts, field: value})
    assert portfolio.cash == portfolio.total_equity == Decimal("100")
    assert portfolio.dividend_income == portfolio.dividend_receivable == Decimal("0")
    with pytest.raises(ValueError, match="portfolio_cash_dividend_unknown"):
        portfolio.pay_cash_dividend("bad")


def test_cash_dividend_rejects_overflow_before_recording_entitlement() -> None:
    portfolio = Portfolio(EventBus())
    with pytest.raises(ValueError, match="portfolio_cash_dividend_amount_invalid"):
        portfolio.accrue_cash_dividend(
            "overflow",
            symbol=Symbol("600001"),
            eligible_quantity=Decimal("1"),
            cash_per_share=Decimal("1E1000000"),
        )
    assert portfolio.dividend_income == portfolio.dividend_receivable == Decimal("0")
    with pytest.raises(ValueError, match="portfolio_cash_dividend_unknown"):
        portfolio.pay_cash_dividend("overflow")


def test_share_distribution_is_idempotent_and_release_adds_no_equity() -> None:
    portfolio = Portfolio(EventBus(), initial_cash=Decimal("1000"))
    facts = {
        "symbol": Symbol("600001"),
        "eligible_quantity": Decimal("100"),
        "shares_per_share": Decimal("0.3"),
    }
    assert portfolio.accrue_share_distribution("shares-1", **facts) == Decimal("30")
    assert portfolio.accrue_share_distribution("shares-1", **facts) == Decimal("30")
    position = portfolio.positions[facts["symbol"]]
    portfolio.mark_to_market({facts["symbol"]: Decimal("10")})
    assert position.quantity == position.unlisted_qty == Decimal("30")
    assert position.available_qty == position.cost_basis == Decimal("0")
    assert portfolio.cash == Decimal("1000")
    assert portfolio.total_equity == Decimal("1300")
    assert portfolio.dividend_income == Decimal("0")

    assert portfolio.release_share_distribution("shares-1") == Decimal("30")
    assert portfolio.release_share_distribution("shares-1") == Decimal("0")
    assert portfolio.accrue_share_distribution("shares-1", **facts) == Decimal("30")
    assert position.quantity == position.available_qty == Decimal("30")
    assert position.unlisted_qty == Decimal("0")
    assert portfolio.total_equity == Decimal("1300")
    with pytest.raises(ValueError, match="portfolio_share_distribution_conflict"):
        portfolio.accrue_share_distribution(
            "shares-1", **{**facts, "eligible_quantity": Decimal("200")}
        )
    with pytest.raises(ValueError, match="portfolio_share_distribution_unknown"):
        portfolio.release_share_distribution("unknown")


def test_zero_share_award_binds_facts_without_creating_a_position() -> None:
    portfolio = Portfolio(EventBus())
    facts = {
        "symbol": Symbol("600001"),
        "eligible_quantity": Decimal("0"),
        "shares_per_share": Decimal("0.3"),
    }
    assert portfolio.accrue_share_distribution("zero", **facts) == Decimal("0")
    assert portfolio.release_share_distribution("zero") == Decimal("0")
    assert portfolio.positions == {}
    with pytest.raises(ValueError, match="portfolio_share_distribution_conflict"):
        portfolio.accrue_share_distribution(
            "zero", **{**facts, "eligible_quantity": Decimal("100")}
        )


@pytest.mark.parametrize("rate", ["0.301", "-1", "NaN", "Infinity", "1E1000000"])
def test_invalid_share_award_never_records_partial_book_state(rate: str) -> None:
    portfolio = Portfolio(EventBus())
    with pytest.raises(ValueError, match="portfolio_share_distribution_"):
        portfolio.accrue_share_distribution(
            "invalid",
            symbol=Symbol("600001"),
            eligible_quantity=Decimal("100"),
            shares_per_share=Decimal(rate),
        )
    assert portfolio.positions == {}
    with pytest.raises(ValueError, match="portfolio_share_distribution_unknown"):
        portfolio.release_share_distribution("invalid")


def test_zero_target_sells_listed_odd_lot_even_below_weight_deadband() -> None:
    bus = EventBus()
    portfolio = Portfolio(bus, initial_cash=Decimal("100000"))
    symbol = Symbol("600001")
    instrument = make_stock(str(symbol), str(symbol))
    portfolio.add_instrument(instrument)
    intents: list[OrderIntentEvent] = []
    bus.subscribe(OrderIntentEvent, intents.append)
    portfolio.accrue_share_distribution(
        "odd-lot",
        symbol=symbol,
        eligible_quantity=Decimal("100"),
        shares_per_share=Decimal("0.3"),
    )
    portfolio.mark_to_market({symbol: Decimal("10")})
    signal = SignalEvent(
        timestamp=datetime(2026, 4, 14, 15),
        strategy_id="exit",
        symbol=symbol,
        target_weight=Decimal("0"),
        price=Decimal("10"),
    )
    bus.publish_and_process(signal)
    bus.drain()
    assert intents == []  # Daily settlement cannot substitute for the listing.
    portfolio.advance_settlement_day()
    bus.publish_and_process(signal)
    bus.drain()
    assert intents == []

    portfolio.release_share_distribution("odd-lot")
    bus.publish_and_process(signal)
    bus.drain()
    assert len(intents) == 1
    assert intents[0].side is OrderSide.SELL
    assert intents[0].quantity == Decimal("30")
    # A non-liquidating rebalance still obeys the existing lot rule.
    assert portfolio._calculate_sell_quantity(
        instrument, Decimal("10"), Decimal("300")
    ) == Decimal("0")
    assert portfolio._calculate_buy_quantity(
        instrument, Decimal("10"), Decimal("300")
    ) == Decimal("0")


def test_zero_target_liquidates_whole_lots_with_the_entire_odd_remainder() -> None:
    bus = EventBus()
    portfolio = Portfolio(bus, initial_cash=Decimal("10000"))
    symbol = Symbol("600001")
    instrument = make_stock(str(symbol), str(symbol))
    portfolio.add_instrument(instrument)
    portfolio.on_fill(
        FillEvent(
            timestamp=datetime(2026, 4, 9, 15),
            fill_id="original-buy",
            order_id="buy",
            symbol=symbol,
            side=OrderSide.BUY,
            fill_price=Decimal("13"),
            fill_quantity=Decimal("100"),
            commission=Decimal("0"),
            slippage=Decimal("0"),
        )
    )
    portfolio.accrue_share_distribution(
        "award",
        symbol=symbol,
        eligible_quantity=Decimal("100"),
        shares_per_share=Decimal("0.3"),
    )
    portfolio.advance_settlement_day()
    assert portfolio._calculate_sell_quantity(
        instrument, Decimal("10"), Decimal("1300"), liquidate=True
    ) == Decimal("100")
    portfolio.release_share_distribution("award")
    assert portfolio._calculate_sell_quantity(
        instrument, Decimal("10"), Decimal("1300"), liquidate=True
    ) == Decimal("130")
    assert portfolio._calculate_sell_quantity(
        instrument, Decimal("10"), Decimal("1300")
    ) == Decimal("100")
