"""Actual publications drive a restartable, isolated modeled paper book."""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from backtest.distributions import StockDistribution
from backtest.engine import BacktestExecutionConfig
from backtest.paper_replay import PublishedPaperTarget, replay_paper_book
from core.events import MarketEvent
from core.types import ZERO, Symbol
from domain.instrument import make_stock
from domain.portfolio import Portfolio
from execution.commission import StockACommission
from execution.slippage import FixedSlippage

SH = ZoneInfo("Asia/Shanghai")
SYMBOL = Symbol("600000")
DAYS = [date(2026, 4, day) for day in (6, 7, 8, 9, 10, 13)]


def _at(day, hour=15, minute=0):
    return datetime.combine(day, time(hour, minute), SH)


def _bar(day, price="10", *, symbol=SYMBOL, volume="10000"):
    value = Decimal(price)
    return MarketEvent(
        timestamp=_at(day),
        symbol=symbol,
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(volume),
        available_at=_at(day, 16),
    )


def _target(day_index, weight="1", *, identity=None, weights=None):
    return PublishedPaperTarget(
        id=identity or f"publication-{day_index}",
        published_at=_at(DAYS[day_index - 1], 16),
        reference_session=DAYS[day_index],
        target_weights=weights or {str(SYMBOL): Decimal(weight)},
    )


def _cost(*, minimum="0", slip="0"):
    return BacktestExecutionConfig(
        commission_calc=StockACommission(
            commission_rate=ZERO,
            min_commission=Decimal(minimum),
            stamp_tax_rate=ZERO,
            transfer_fee_rate=ZERO,
        ),
        slippage_model=FixedSlippage(Decimal(slip)),
    )


def _replay(bars, publications, **changes):
    args = {
        "book_id": "independent-book",
        "initial_cash": Decimal("10000"),
        "instruments": {SYMBOL: make_stock(str(SYMBOL), "fixture")},
        "bars": bars,
        "publications": publications,
        "evaluation_start": DAYS[1],
        "through_session": max(bar.timestamp.date() for bar in bars),
        "cost_config": _cost(),
    }
    return replay_paper_book(**{**args, **changes})


def test_published_targets_replay_stably_with_future_close_t1_and_no_warmup_nav():
    publications = [_target(1), _target(2, "0")]
    first = _replay([_bar(day) for day in DAYS[:2]], publications)
    complete = _replay([_bar(day) for day in DAYS[:3]], publications)
    assert complete == _replay([_bar(day) for day in DAYS[:3]], publications)
    assert complete["sessions"][:1] == first["sessions"]
    assert [row["session"] for row in complete["sessions"]] == [
        day.isoformat() for day in DAYS[1:3]
    ]
    assert [fill["side"] for fill in complete["fills"]] == ["buy", "sell"]
    assert complete["fills"][0]["timestamp"] == _at(DAYS[1]).isoformat()
    assert complete["sessions"][0]["positions"][SYMBOL]["frozen_qty"] == "1000"
    assert complete["sessions"][1]["positions"][SYMBOL]["quantity"] == "0"
    assert complete["sessions"][1]["cash"] == "10000"
    assert first["pending_targets"] == [
        {
            "publication_id": "publication-2",
            "reference_session": DAYS[2].isoformat(),
        }
    ]
    other = _replay([_bar(day) for day in DAYS[:3]], publications, book_id="other")
    assert other["fills"][0]["fill_id"] != complete["fills"][0]["fill_id"]


@pytest.mark.parametrize("hour,minute", [(9, 30), (15, 0), (16, 0)])
def test_target_published_at_or_after_reference_open_cannot_fill(hour, minute):
    target = PublishedPaperTarget(
        "late", _at(DAYS[1], hour, minute), DAYS[1], {str(SYMBOL): Decimal(1)}
    )
    with pytest.raises(ValueError, match="paper_replay_publication_too_late"):
        _replay([_bar(day) for day in DAYS[:2]], [target])


@pytest.mark.parametrize(
    "price,volume,reason",
    [
        ("11", "10000", "limit"),
        ("10", "0", "suspension"),
    ],
)
def test_blocked_target_is_attempted_once_and_not_retried(price, volume, reason):
    result = _replay(
        [
            _bar(DAYS[0]),
            _bar(DAYS[1], price, volume=volume),
            _bar(DAYS[2], "10.5"),
        ],
        [_target(1)],
    )
    assert result["fills"] == []
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["reason"] == reason
    assert result["attempts"][0]["status"] == "blocked"


def test_actual_fee_and_slippage_resize_buy_and_preserve_decimal_accounting():
    result = _replay(
        [_bar(day) for day in DAYS[:2]],
        [_target(1)],
        initial_cash=Decimal("2050"),
        cost_config=_cost(minimum="5", slip="1"),
    )
    fill = result["fills"][0]
    row = result["sessions"][0]
    assert fill["fill_price"] == "11"
    assert fill["fill_quantity"] == "100"
    assert fill["commission"] == "5"
    assert fill["slippage"] == "100"
    assert row["cash"] == "945"
    assert row["equity"] == "1945"
    assert row["positions"][SYMBOL]["avg_cost"] == "11.05"


def test_cash_and_share_distribution_uses_record_holdings_and_listing_day():
    distribution = StockDistribution(
        action_id="distribution-1",
        symbol=SYMBOL,
        record_date=DAYS[1],
        ex_date=DAYS[2],
        pay_date=DAYS[4],
        cash_per_share=Decimal("1"),
        available_at=_at(DAYS[0]),
        bonus_per_share=Decimal("0.1"),
        listing_date=DAYS[4],
    )
    bars = [_bar(day, "10" if day < DAYS[2] else "8") for day in DAYS[:5]]
    result = _replay(
        bars,
        [_target(1), _target(2, "0"), _target(4, "0")],
        distributions=[distribution],
    )
    ex = result["sessions"][1]
    assert ex["cash"] == "0"
    assert ex["dividend_receivable"] == "1000"
    assert ex["positions"][SYMBOL]["quantity"] == "1100"
    assert ex["positions"][SYMBOL]["unlisted_qty"] == "100"
    assert (
        ex["attempts"][0]["reason"] == "corporate_action_price_limit_reference_missing"
    )
    paid = result["sessions"][-1]
    assert paid["dividend_receivable"] == "0"
    assert paid["cash"] == "9800"
    assert paid["positions"][SYMBOL]["quantity"] == "0"
    assert paid["corporate_actions"][0]["paid"] is True
    assert paid["corporate_actions"][0]["shares_listed"] is True


def test_future_distribution_does_not_rewrite_financial_prefix_before_ex_date():
    bars = [_bar(day) for day in DAYS[:3]]
    publications = [_target(1)]
    before = _replay(bars, publications)
    distribution = StockDistribution(
        action_id="known-later",
        symbol=SYMBOL,
        record_date=DAYS[1],
        ex_date=DAYS[3],
        pay_date=DAYS[4],
        cash_per_share=Decimal("0.1"),
        available_at=_at(DAYS[2]),
    )
    after = _replay(bars, publications, distributions=[distribution])
    assert before["sessions"] == after["sessions"]


def test_zero_entitlement_does_not_change_decimal_text_or_financial_prefix():
    bars = [_bar(day) for day in DAYS[:4]]
    before = _replay(bars, [])
    distribution = StockDistribution(
        action_id="no-holding",
        symbol=SYMBOL,
        record_date=DAYS[1],
        ex_date=DAYS[2],
        pay_date=DAYS[3],
        cash_per_share=Decimal("0.10"),
        available_at=_at(DAYS[0]),
    )
    after = _replay(bars, [], distributions=[distribution])
    assert before["sessions"] == after["sessions"]


def test_missing_target_session_or_warmup_price_fails_instead_of_later_fill():
    with pytest.raises(ValueError, match="paper_replay_session_bars_missing"):
        _replay([_bar(DAYS[1])], [_target(1)])
    with pytest.raises(ValueError, match="paper_replay_target_close_missing"):
        _replay([_bar(DAYS[0]), _bar(DAYS[1]), _bar(DAYS[3])], [_target(2)])


def test_empty_ca_tuple_still_marks_all_symbols_before_target_sizing():
    other = Symbol("600001")
    instruments = {
        SYMBOL: make_stock(str(SYMBOL), "first", limit_pct=ZERO),
        other: make_stock(str(other), "second", limit_pct=ZERO),
    }
    weights = {str(SYMBOL): Decimal("0.5"), str(other): Decimal("0.5")}
    bars = [_bar(day, symbol=symbol) for day in DAYS[:2] for symbol in instruments] + [
        _bar(DAYS[2], "5"),
        _bar(DAYS[2], "15", symbol=other),
    ]
    result = _replay(
        bars,
        [_target(1, weights=weights), _target(2, weights=weights)],
        instruments=instruments,
    )
    # First symbol cannot buy before second symbol's sell. Both marks already
    # value the book at 10000, so the second symbol sells 100, not 200 shares.
    final = result["sessions"][-1]
    assert final["fills"][0]["symbol"] == other
    assert final["fills"][0]["fill_quantity"] == "100"
    assert final["cash"] == "1500"
    assert final["equity"] == "10000"


def test_accounting_handler_exception_aborts_paper_replay(monkeypatch):
    def fail(self, event):
        raise ValueError("synthetic_accounting_failure")

    monkeypatch.setattr(Portfolio, "on_fill", fail)
    with pytest.raises(ValueError, match="synthetic_accounting_failure"):
        _replay([_bar(day) for day in DAYS[:2]], [_target(1)])
