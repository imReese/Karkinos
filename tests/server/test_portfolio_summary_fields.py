"""Portfolio summaries preserve missing marks and session boundaries."""

import pytest

from server.models import PositionResponse
from server.projections.portfolio_snapshot_projection import _portfolio_summary_fields


def position(**changes) -> PositionResponse:
    return PositionResponse(
        **{
            "symbol": "600001",
            "asset_class": "stock",
            "quantity": 10,
            "available_qty": 10,
            "frozen_qty": 0,
            "avg_cost": 100,
            "market_value": 1200,
            "unrealized_pnl": 200,
            "realized_pnl": 0,
            "commission_paid": 0,
            "today_change": 20,
            "performance_session_date": "2026-10-08",
            **changes,
        }
    )


def summarize(positions, total_equity=1700):
    return _portfolio_summary_fields(
        positions,
        total_equity=total_equity,
        cash=500,
        expected_session_date="2026-10-08",
    )


def test_summary_consumes_canonical_position_marks_and_cost_basis():
    values = summarize([position()])
    assert values["total_market_value"] == 1200
    assert values["total_today_change"] == 20
    assert values["total_unrealized_pnl"] == 200
    assert values["total_unrealized_pnl_pct"] == pytest.approx(0.2)
    assert values["performance_session_date"] == "2026-10-08"


def test_unavailable_valuation_does_not_turn_partial_marks_into_totals():
    values = summarize(
        [position(), position(symbol="600002", market_value=None, unrealized_pnl=None)],
        total_equity=None,
    )
    assert all(value is None for value in values.values())


def test_missing_daily_baseline_preserves_valuation_and_unrealized_pnl():
    values = summarize([position(today_change=None)])
    assert values["total_market_value"] == 1200
    assert values["total_unrealized_pnl"] == 200
    assert values["total_today_change"] is None
    assert values["performance_session_date"] is None


@pytest.mark.parametrize("session_date", [None, "2026-10-07"])
def test_mixed_or_unverified_session_marks_are_not_aggregated(session_date):
    values = summarize(
        [position(), position(symbol="600002", performance_session_date=session_date)],
        total_equity=2900,
    )
    assert values["total_market_value"] == 2400
    assert values["total_unrealized_pnl"] == 400
    assert values["total_today_change"] is None
    assert values["performance_session_date"] is None


def test_empty_book_has_zero_holdings_and_no_return_denominator():
    values = summarize([], total_equity=500)
    assert values["total_market_value"] == 0
    assert values["total_unrealized_pnl"] == 0
    assert values["total_unrealized_pnl_pct"] is None
    assert values["total_today_change"] == 0
