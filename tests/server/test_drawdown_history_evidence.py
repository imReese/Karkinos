"""Replay a historical valuation gap followed by a later capital deposit."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.http.portfolio_endpoints import analysis, snapshot
from server.models import (
    EquityPoint,
    EquitySeriesPoint,
    LiveHoldingsResponse,
    PortfolioSnapshot,
)
from server.projections.portfolio_views.historical_series import (
    cash_flow_adjusted_equity_points_from_series,
)
from server.routes import portfolio


def _state():
    rows = [
        {
            "id": 1,
            "entry_type": "cash_deposit",
            "timestamp": "2026-01-01T09:00:00+08:00",
            "amount": 100,
        },
        {
            "id": 2,
            "entry_type": "cash_deposit",
            "timestamp": "2026-01-03T09:00:00+08:00",
            "amount": 900,
        },
    ]
    return SimpleNamespace(
        db=SimpleNamespace(
            get_ledger_entries_sync=lambda limit=500, offset=0: rows[
                offset : offset + limit
            ]
        ),
        config=SimpleNamespace(initial_cash=0),
        scheduler=None,
    )


def _series(middle=None):
    return [
        EquitySeriesPoint(
            timestamp=f"2026-01-0{day}T15:00:00+08:00",
            total=total,
            stocks=total,
            funds=0,
            others=0,
            cash=0,
            missing_price_symbols=["TEST"] if total is None else [],
            valuation_snapshot_id="current" if day == 3 else None,
        )
        for day, total in [(1, 100), (2, middle), (3, 990)]
    ]


def test_cash_flow_adjustment_does_not_bridge_unknown_valuations():
    # Production incident shape, with invented dates, amounts, and instrument.
    # Dropping day 2 used to produce a synthetic currency peak above all raw points.
    assert cash_flow_adjusted_equity_points_from_series(_state(), _series()) == []


@pytest.mark.parametrize("endpoint", ["overview", "risk-workspace"])
@pytest.mark.parametrize(
    "history", ["gap", "empty", "single", "mismatched", "complete"]
)
def test_drawdown_consumers_preserve_history_blockers(monkeypatch, endpoint, history):
    state = _state()
    points = _series(110 if history != "gap" else None)
    if history == "empty":
        points = []
    elif history == "single":
        points = points[-1:]
    elif history == "mismatched":
        points[-1] = points[-1].model_copy(update={"valuation_snapshot_id": "other"})
    current = PortfolioSnapshot(
        cash=990,
        total_equity=990,
        positions=[],
        allocation=[],
        valuation_status="complete",
        valuation_snapshot_id="current",
        valuation_as_of="2026-01-03T15:00:00+08:00",
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    monkeypatch.setattr(
        portfolio, "build_portfolio_snapshot", AsyncMock(return_value=current)
    )
    monkeypatch.setattr(portfolio, "_collect_latest_quote_timestamps", lambda state: {})
    monkeypatch.setattr(
        portfolio,
        "_build_live_holdings_response",
        lambda state: LiveHoldingsResponse(groups=[], valuation_snapshot_id="current"),
    )
    monkeypatch.setattr(
        portfolio, "_overview_daily_operations_summary", lambda state: None
    )
    performance = SimpleNamespace(
        get_equity_curve_series=AsyncMock(return_value=points),
        get_equity_curve=AsyncMock(
            return_value=[
                EquityPoint(
                    timestamp=points[-1].timestamp if points else "2026-01-03",
                    equity=990,
                )
            ]
        ),
    )
    dependencies = portfolio.build_portfolio_endpoint_dependencies()
    snapshots = snapshot.create_router(dependencies.snapshot, performance)
    router = (
        snapshots.router
        if endpoint == "overview"
        else analysis.create_router(
            dependencies.analysis, snapshots.operations, performance
        )
    )
    handler = next(
        route.endpoint
        for route in router.routes
        if route.path == f"/api/portfolio/{endpoint}"
    )
    result = asyncio.run(handler())

    if history == "complete":
        drawdown = (
            result.current_drawdown
            if endpoint == "overview"
            else result.drawdown.current_drawdown
        )
        assert drawdown == pytest.approx(1 - 0.9 / 1.1)
    elif endpoint == "overview":
        assert result.current_drawdown is None
        assert result.current_drawdown_amount is None
        assert result.drawdown_peak_equity is None
        assert result.drawdown_peak_timestamp is None
        assert result.drawdown_blockers == ["drawdown_history_unavailable"]
        assert result.total_equity == 990
    else:
        assert result.status == "partial"
        assert result.drawdown is None
        assert result.drawdown_series == []
        assert result.blockers == ["drawdown_history_unavailable"]
        assert {item.key for item in result.metrics} == {
            "gross_exposure",
            "cash_ratio",
            "largest_weight",
            "top3_weight",
        }
        assert result.exposure_buckets[0].value == 990
    performance.get_equity_curve.assert_not_awaited()
