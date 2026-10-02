"""Cash-dividend accounting through real next-bar backtest execution."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.cash_dividends import CashDividend, cash_dividends_from_evidence
from backtest.engine import BacktestEngine, BacktestExecutionConfig
from core.event_bus import EventBus
from core.events import MarketEvent, SignalEvent
from core.types import ZERO, OrderSide, Symbol
from data.handler import DataHandler
from domain.instrument import make_stock
from execution.commission import StockACommission
from execution.slippage import FixedSlippage
from strategy.base import Strategy

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYMBOL = Symbol("600001")
DAYS = [date(2026, 4, day) for day in (7, 8, 9, 10, 13, 14)]


def _close(day: date) -> datetime:
    return datetime.combine(day, time(15), SHANGHAI)


def _dividend(**changes) -> CashDividend:
    return replace(
        CashDividend(
            action_id="frozen-dividend-1",
            symbol=SYMBOL,
            record_date=date(2026, 4, 9),
            ex_date=date(2026, 4, 10),
            pay_date=date(2026, 4, 14),
            cash_per_share=Decimal("0.5"),
            available_at=_close(date(2026, 4, 7)),
        ),
        **changes,
    )


class DayTargets(Strategy):
    def __init__(self, targets: dict[date, Decimal]):
        super().__init__("dated_targets", EventBus())
        self.targets = targets
        self.initialized = False
        self.observed_dates: list[date] = []

    def on_init(self, symbols: list[Symbol]) -> None:
        self.initialized = True

    def on_data(self, event: MarketEvent) -> None:
        day = event.timestamp.astimezone(SHANGHAI).date()
        self.observed_dates.append(day)
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


def _engine(
    *, targets=None, days=None, distributions=None, observed=False, tz=SHANGHAI
):
    rows = []
    for day in DAYS if days is None else days:
        timestamp = _close(day).astimezone(tz)
        price = Decimal("10") if day < date(2026, 4, 10) else Decimal("9.5")
        rows.append(
            {
                "timestamp": timestamp,
                "available_at": timestamp,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 10000,
            }
        )
    strategy = DayTargets(targets or {})
    return BacktestEngine(
        strategy=strategy,
        instruments={SYMBOL: make_stock(str(SYMBOL), "synthetic stock")},
        data_handlers={SYMBOL: DataHandler(pd.DataFrame(rows), SYMBOL)},
        initial_cash=Decimal("1000"),
        commission_calc=StockACommission(
            commission_rate=ZERO,
            min_commission=ZERO,
            stamp_tax_rate=ZERO,
            transfer_fee_rate=ZERO,
        ),
        slippage_model=FixedSlippage(ZERO),
        execution_config=BacktestExecutionConfig(
            availability_mode="observed" if observed else "historical_snapshot"
        ),
        cash_dividends=(_dividend(),) if distributions is None else distributions,
    )


def _book_states(engine):
    states = {}

    def observe(event):
        portfolio = engine.portfolio
        states[event.timestamp.astimezone(SHANGHAI).date()] = (
            portfolio.cash,
            portfolio.dividend_receivable,
        )

    engine.event_bus.subscribe(MarketEvent, observe)
    return states


def test_record_date_buy_earns_receivable_then_payment_without_double_return():
    engine = _engine(targets={date(2026, 4, 8): Decimal("1")})
    states = _book_states(engine)

    result = engine.run()

    assert len(result.fills) == 1
    assert result.fills[0].timestamp == _close(date(2026, 4, 9))
    assert result.fills[0].fill_quantity == Decimal("100")
    assert states[date(2026, 4, 9)] == (ZERO, ZERO)
    assert states[date(2026, 4, 10)] == (ZERO, Decimal("50"))
    assert states[date(2026, 4, 13)] == (ZERO, Decimal("50"))
    assert states[date(2026, 4, 14)] == (Decimal("50"), ZERO)
    assert all(value == Decimal("1000") for _, value in result.equity_curve)
    assert result.total_return == ZERO
    evidence = result.cash_dividend_accounting
    assert (
        Decimal(evidence["gross_income"])
        == Decimal(evidence["cash_paid"])
        == Decimal("50")
    )
    assert evidence["taxes_modeled"] is evidence["coverage_verified"] is False
    assert evidence["historical_availability_verified"] is False
    assert evidence["distributions"][0]["eligible_quantity"] == "100"


def test_record_date_sale_removes_eligibility():
    engine = _engine(targets={date(2026, 4, 7): Decimal("1"), date(2026, 4, 8): ZERO})

    result = engine.run()

    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert result.fills[-1].timestamp == _close(date(2026, 4, 9))
    assert result.positions[SYMBOL].quantity == ZERO
    assert engine.portfolio.dividend_income == ZERO
    assert result.final_equity == Decimal("1000")
    assert (
        result.cash_dividend_accounting["distributions"][0]["eligible_quantity"] == "0"
    )


def test_sale_before_payment_preserves_entitlement_even_after_position_closes():
    engine = _engine(targets={date(2026, 4, 8): Decimal("1"), date(2026, 4, 10): ZERO})
    states = _book_states(engine)

    result = engine.run()

    assert [fill.side for fill in result.fills] == [OrderSide.BUY, OrderSide.SELL]
    assert result.fills[-1].timestamp == _close(date(2026, 4, 13))
    assert result.positions[SYMBOL].quantity == ZERO
    assert states[date(2026, 4, 13)] == (Decimal("950"), Decimal("50"))
    assert states[date(2026, 4, 14)] == (Decimal("1000"), ZERO)
    assert all(value == Decimal("1000") for _, value in result.equity_curve)
    assert result.positions[SYMBOL].realized_pnl == Decimal("-50")
    assert engine.portfolio.dividend_income == Decimal("50")


def test_payment_after_last_bar_leaves_receivable_in_final_equity():
    engine = _engine(targets={date(2026, 4, 8): Decimal("1")}, days=DAYS[:-1])

    result = engine.run()

    assert engine.portfolio.cash == ZERO
    assert engine.portfolio.dividend_receivable == Decimal("50")
    assert result.final_equity == result.equity_curve[-1][1] == Decimal("1000")
    assert result.cash_dividend_accounting["distributions"][0]["paid"] is False
    assert Decimal(result.cash_dividend_accounting["cash_paid"]) == ZERO


@pytest.mark.parametrize("missing", [date(2026, 4, 9), date(2026, 4, 10)])
def test_missing_required_bar_rejects_before_strategy_callbacks(missing):
    engine = _engine(days=[day for day in DAYS if day != missing])

    with pytest.raises(ValueError, match="cash_dividend_required_session_missing"):
        engine.run()

    assert engine.strategy.initialized is False
    assert engine.strategy.observed_dates == []
    assert engine.portfolio.dividend_income == ZERO


def test_duplicate_daily_bar_rejects_before_strategy_callbacks():
    engine = _engine(days=[*DAYS, date(2026, 4, 9)])

    with pytest.raises(ValueError, match="cash_dividend_daily_close_required"):
        engine.run()

    assert engine.strategy.initialized is False
    assert engine.strategy.observed_dates == []


def test_duplicate_action_identity_is_rejected():
    with pytest.raises(ValueError, match="cash_dividend_duplicate_action"):
        _engine(distributions=(_dividend(), _dividend()))


def test_changed_action_identity_cannot_duplicate_the_same_distribution():
    with pytest.raises(ValueError, match="cash_dividend_conflicting_implementation"):
        _engine(
            distributions=(
                _dividend(),
                _dividend(
                    action_id="different-revision", cash_per_share=Decimal("0.7")
                ),
            )
        )


def test_ex_date_order_is_blocked_without_a_verified_limit_reference():
    engine = _engine(
        targets={
            date(2026, 4, 8): Decimal("1"),
            date(2026, 4, 9): ZERO,
            date(2026, 4, 10): ZERO,
        }
    )

    result = engine.run()

    assert [fill.timestamp for fill in result.fills] == [
        _close(date(2026, 4, 9)),
        _close(date(2026, 4, 13)),
    ]
    assert result.cash_dividend_accounting["ex_date_execution_blocked_count"] == 1
    assert engine.portfolio.dividend_income == Decimal("50")


def test_observed_mode_rejects_late_dividend_before_any_strategy_callback():
    engine = _engine(
        distributions=(
            _dividend(available_at=_close(date(2026, 4, 10)) + timedelta(seconds=1)),
        ),
        observed=True,
    )

    with pytest.raises(
        ValueError, match="cash_dividend_historical_availability_unverified"
    ):
        engine.run()

    assert engine.strategy.initialized is False
    assert engine.strategy.observed_dates == []
    assert engine.fills == []


def test_equivalent_aware_timestamps_use_the_shanghai_entitlement_day():
    engine = _engine(
        targets={date(2026, 4, 8): Decimal("1")},
        tz=timezone(timedelta(hours=-12)),
    )

    result = engine.run()

    assert len(result.fills) == 1
    assert engine.portfolio.dividend_income == Decimal("50")
    assert engine.portfolio.cash == Decimal("50")
    assert result.final_equity == Decimal("1000")


def _evidence():
    event = {
        "symbol": str(SYMBOL),
        "instrument_type": "stock",
        "div_proc": "实施",
        "end_date": "2025-12-31",
        "ann_date": "2026-03-01",
        "imp_ann_date": "2026-04-01",
        "record_date": "2026-04-09",
        "ex_date": "2026-04-10",
        "pay_date": "2026-04-14",
        "cash_div_tax": "0.5",
        "cash_div": "0.4",
        "stk_div": "0",
        "stk_bo_rate": "0",
        "stk_co_rate": "0",
        "available_at": _close(date(2026, 4, 7)).isoformat(),
        "source_revision_id": "sha256:" + "a" * 64,
    }
    return {
        "schema_version": "karkinos.corporate_action_evidence.v1",
        "status": "observed",
        "coverage_status": "provider_reported_only",
        "undated_event_count": 0,
        "events": [event],
    }


def test_evidence_adapter_uses_before_tax_amount_without_claiming_tax_coverage():
    evidence = _evidence()
    event = evidence["events"][0]
    distributions = cash_dividends_from_evidence(evidence)
    assert distributions[0].cash_per_share == Decimal("0.5")
    result = _engine(
        targets={date(2026, 4, 8): Decimal("1")}, distributions=distributions
    ).run()
    assert Decimal(result.cash_dividend_accounting["gross_income"]) == Decimal("50")
    assert result.cash_dividend_accounting["taxes_modeled"] is False
    with pytest.raises(ValueError, match="cash_dividend_gross_amount_missing"):
        cash_dividends_from_evidence(
            {**evidence, "events": [{**event, "cash_div_tax": None}]}
        )


def test_evidence_adapter_rejects_conflicting_revisions_of_one_distribution():
    evidence = _evidence()
    event = evidence["events"][0]
    evidence["events"].append(
        {**event, "ann_date": "2026-03-10", "cash_div_tax": "0.7"}
    )

    with pytest.raises(ValueError, match="cash_dividend_conflicting_implementation"):
        cash_dividends_from_evidence(evidence)


def test_explicit_zero_total_share_ratio_allows_missing_component_breakdown():
    evidence = _evidence()
    event = evidence["events"][0]
    event.update(stk_bo_rate=None, stk_co_rate=None)
    distributions = cash_dividends_from_evidence(evidence)

    result = _engine(
        targets={date(2026, 4, 8): Decimal("1")}, distributions=distributions
    ).run()

    assert Decimal(result.cash_dividend_accounting["gross_income"]) == Decimal("50")
    with pytest.raises(ValueError, match="cash_dividend_share_terms_missing"):
        cash_dividends_from_evidence(
            {**evidence, "events": [{**event, "stk_div": None}]}
        )
    with pytest.raises(
        ValueError, match="cash_dividend_share_distribution_unsupported"
    ):
        cash_dividends_from_evidence(
            {**evidence, "events": [{**event, "stk_bo_rate": "0.1"}]}
        )
