"""Missing prices never become authoritative return or risk facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from core.types import Symbol
from domain.instrument import make_open_end_fund, make_stock
from server.ledger.models import LedgerEntry
from server.models import EquityPoint, PortfolioSnapshot, PositionResponse
from server.projections.portfolio_projection_values import quote_price
from server.projections.portfolio_snapshot_projection import (
    PortfolioSnapshotProjectionPorts,
    build_portfolio_snapshot_sync,
)
from server.projections.portfolio_views.explainability import build_timeline
from server.projections.portfolio_views.intraday_series import (
    build_intraday_equity_curve_series,
    current_equity_series_point,
)
from server.projections.portfolio_views.live_holdings import (
    build_live_holdings_response,
)
from server.projections.service import (
    build_equity_series_from_entries,
    build_portfolio_projection,
)
from server.services.account_state import build_account_state_projection
from server.services.risk_engine import build_risk_summary
from server.services.risk_workspace import build_risk_workspace


def _open_position() -> LedgerEntry:
    return LedgerEntry(
        entry_type="trade_buy",
        timestamp="2026-08-28T09:30:00+08:00",
        symbol="600519",
        direction="buy",
        quantity=10,
        price=100,
        asset_class="stock",
    )


def test_quote_price_does_not_fall_back_to_cost_basis() -> None:
    assert quote_price("600519", Decimal("100"), {}) is None
    assert (
        quote_price(
            "600519",
            Decimal("100"),
            {"600519": {"price": 0}},
        )
        is None
    )


def test_projection_blocks_total_equity_when_open_position_has_no_price() -> None:
    projection = build_portfolio_projection([_open_position()], latest_quotes={})

    assert projection.total_equity is None
    assert projection.valuation_status == "blocked"
    assert projection.missing_price_symbols == ["600519"]
    assert projection.positions["600519"].valuation_available is False
    assert projection.positions["600519"].market_value == Decimal("0")


def test_account_and_risk_results_are_unavailable_not_cost_valued() -> None:
    position = PositionResponse(
        symbol="600519",
        asset_class="stock",
        instrument_type="stock",
        quantity=10,
        available_qty=10,
        frozen_qty=0,
        avg_cost=100,
        latest_price=None,
        market_value=None,
        unrealized_pnl=None,
        realized_pnl=0,
        commission_paid=0,
        quote_status="missing",
        valuation_available=False,
        valuation_blockers=["missing_market_price:600519"],
    )
    snapshot = PortfolioSnapshot(
        cash=500,
        total_equity=None,
        positions=[position],
        allocation=[],
        valuation_status="blocked",
        missing_price_symbols=["600519"],
        valuation_blockers=["missing_market_price:600519"],
    )

    risks = build_risk_summary(snapshot, {})
    account = build_account_state_projection(snapshot, risks)
    workspace = build_risk_workspace(snapshot, [])

    assert account.summary.total_equity is None
    assert account.summary.unrealized_pnl is None
    assert account.summary.cash_ratio is None
    assert account.next_step == "补齐并复核市场数据证据"
    assert [item.title for item in risks] == ["权威风险结果不可用"]
    assert all(item.title != "当前风险可控" for item in risks)
    assert workspace.status == "blocked"
    assert workspace.drawdown is None
    assert workspace.metrics == []
    assert workspace.blockers == ["missing_market_price:600519"]


def test_confirmed_nav_missing_blocks_aggregate_account_and_risk_projections() -> None:
    quote = {
        "symbol": "019999",
        "asset_type": "fund",
        "asset_class": "fund",
        "price": 2.25,
        "quote_timestamp": "2026-08-28T14:57:00+08:00",
        "timestamp": "2026-08-28T14:57:00+08:00",
        "quote_status": "confirmed_nav_missing",
        "valuation_baseline_status": "complete",
    }
    entries = [
        LedgerEntry(
            entry_type="cash_deposit",
            timestamp="2026-08-28T09:00:00+08:00",
            amount=5000,
            asset_class="cash",
        ),
        LedgerEntry(
            entry_type="trade_buy",
            timestamp="2026-08-28T09:30:00+08:00",
            symbol="019999",
            direction="buy",
            quantity=1000,
            price=2,
            asset_class="fund",
        ),
    ]
    portfolio = build_portfolio_projection(
        entries,
        latest_quotes={"019999": quote},
    )
    valuation = {
        "snapshot_id": "valuation-fund-estimate",
        "as_of": "2026-08-28T14:57:00+08:00",
        "trade_date": "2026-08-28",
        "valuation_policy": "karkinos.persisted_valuation.v4",
        "ledger_cutoff_id": 2,
        "ledger_fingerprint": "ledger-fingerprint",
        "quote_set_fingerprint": "quote-fingerprint",
        "status": "degraded",
        "valuation_lanes": [
            {
                "asset_class": "fund",
                "status": "degraded",
                "quote_count": 1,
                "complete_quote_count": 0,
                "review_required_quote_count": 1,
                "blocker_statuses": ["confirmed_nav_missing"],
            }
        ],
        "quotes": [quote],
    }
    state = SimpleNamespace(
        scheduler=SimpleNamespace(watchlist=[]),
        config=SimpleNamespace(assets=[]),
        db=None,
    )
    result = build_portfolio_snapshot_sync(
        state,
        ports=PortfolioSnapshotProjectionPorts(
            current_valuation_snapshot=lambda _state: valuation,
            position_quote_presentation=lambda *_args, **_kwargs: (
                "confirmed_nav_missing",
                "confirmed_fund_nav_missing_estimate_only",
            ),
            read_daily_ledger_entries=lambda _state: [],
            resolve_position_today_change=lambda *_args, **_kwargs: (
                None,
                None,
                None,
                None,
                "unavailable",
            ),
            resolve_projection_sources=lambda *_args, **_kwargs: (portfolio, {}),
        ),
    )
    snapshot = result.snapshot
    risks = build_risk_summary(snapshot, {})
    account = build_account_state_projection(snapshot, risks)
    workspace = build_risk_workspace(snapshot, [])

    assert snapshot.total_equity is None
    assert snapshot.valuation_status == "degraded"
    assert snapshot.positions[0].latest_price == 2.25
    assert snapshot.positions[0].market_value is None
    assert snapshot.positions[0].valuation_blockers == ["confirmed_nav_missing:019999"]
    assert account.summary.total_equity is None
    assert account.summary.unrealized_pnl is None
    assert account.summary.cash_ratio is None
    assert [item.title for item in risks] == ["权威风险结果不可用"]
    assert workspace.status == "blocked"
    assert "confirmed_nav_missing:019999" in workspace.blockers


def test_degraded_fund_lane_preserves_independent_stock_projections(
    monkeypatch,
) -> None:
    fixed_now = datetime(
        2026,
        9,
        4,
        10,
        0,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    monkeypatch.setattr(
        "server.projections.portfolio_views.intraday_series.get_shanghai_now",
        lambda now=None: fixed_now,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_quotes.get_shanghai_now",
        lambda now=None: fixed_now,
    )
    stock_quote = {
        "symbol": "600519",
        "asset_type": "stock",
        "asset_class": "stock",
        "price": 110.0,
        "timestamp": fixed_now.isoformat(),
        "quote_timestamp": fixed_now.isoformat(),
        "quote_status": "confirmed",
        "previous_close": 100.0,
        "previous_close_date": "2026-09-03",
        "valuation_baseline_status": "complete",
    }
    fund_quote = {
        "symbol": "019999",
        "asset_type": "fund",
        "asset_class": "fund",
        "price": 2.2,
        "timestamp": fixed_now.isoformat(),
        "quote_timestamp": fixed_now.isoformat(),
        "quote_source": "sina_fund_estimate",
        "quote_status": "confirmed_nav_missing",
        "previous_close": 2.0,
        "previous_close_date": "2026-09-03",
        "valuation_baseline_status": "complete",
    }
    quotes = {"600519": stock_quote, "019999": fund_quote}
    entries = [
        LedgerEntry(
            entry_type="cash_deposit",
            timestamp="2026-09-03T09:00:00+08:00",
            amount=5000,
            asset_class="cash",
        ),
        LedgerEntry(
            entry_type="trade_buy",
            timestamp="2026-09-03T09:30:00+08:00",
            symbol="600519",
            direction="buy",
            quantity=10,
            price=100,
            asset_class="stock",
        ),
        LedgerEntry(
            entry_type="trade_buy",
            timestamp="2026-09-03T09:31:00+08:00",
            symbol="019999",
            direction="buy",
            quantity=100,
            price=2,
            asset_class="fund",
        ),
    ]
    portfolio = build_portfolio_projection(entries, latest_quotes=quotes)
    valuation = {
        "snapshot_id": "valuation-mixed-lanes",
        "as_of": fixed_now.isoformat(),
        "trade_date": "2026-09-04",
        "valuation_policy": "karkinos.persisted_valuation.v5",
        "ledger_cutoff_id": 3,
        "ledger_fingerprint": "ledger-fingerprint",
        "quote_set_fingerprint": "quote-fingerprint",
        "status": "degraded",
        "valuation_lanes": [
            {"asset_class": "stock", "status": "complete"},
            {"asset_class": "fund", "status": "degraded"},
        ],
        "quotes": [stock_quote, fund_quote],
    }
    state = SimpleNamespace(
        scheduler=SimpleNamespace(
            portfolio=portfolio,
            instruments={
                Symbol("600519"): make_stock("600519", "synthetic stock"),
                Symbol("019999"): make_open_end_fund(
                    "019999",
                    "synthetic fund",
                ),
            },
            watchlist=[],
        ),
        config=SimpleNamespace(assets=[], data_source="fixture"),
        db=None,
    )

    live = build_live_holdings_response(state, valuation, now=fixed_now)
    groups = {group.asset_class: group for group in live.groups}
    stock = groups["stock"].items[0]
    fund = groups["fund"].items[0]

    assert stock.market_value == 1100
    assert stock.today_change == 100
    assert stock.valuation_available is True
    assert fund.latest_price == 2.2
    assert fund.market_value is None
    assert fund.today_change is None
    assert fund.valuation_available is False
    assert live.missing_price_symbols == ["019999"]
    assert live.valuation_status == "blocked"

    current = current_equity_series_point(state, portfolio, {}, quotes)
    assert current is not None
    assert current.stocks == 1100
    assert current.funds is None
    assert current.total is None
    assert current.unrealized_pnl is None
    assert current.missing_price_symbols == ["019999"]

    raw_intraday = build_intraday_equity_curve_series(
        state,
        portfolio,
        {},
        quotes,
    )
    last = raw_intraday[-1]
    assert last["stocks"] == 1100
    assert last["stocks_daily_change"] == 100
    assert last["funds"] is None
    assert last["funds_daily_change"] is None
    assert last["total"] is None
    assert last["total_daily_change"] is None
    assert last["missing_price_symbols"] == ["019999"]


def test_legacy_equity_series_fallback_never_emits_partial_total() -> None:
    points = build_equity_series_from_entries(
        [_open_position()],
        latest_quotes={},
    )

    assert len(points) == 1
    assert points[0]["cash"] == Decimal("-1000")
    assert points[0]["total"] is None
    assert points[0]["stocks"] is None
    assert points[0]["funds"] == Decimal("0")
    assert points[0]["others"] == Decimal("0")
    assert points[0]["missing_price_symbols"] == ["600519"]


def test_explainability_preserves_confirmed_nav_missing_gap_reason() -> None:
    timeline = build_timeline(
        [
            EquityPoint(timestamp="2026-08-27T15:00:00+08:00", equity=1000),
            EquityPoint(timestamp="2026-08-28T15:00:00+08:00", equity=1010),
        ],
        [],
        valuation_status_by_date={
            "2026-08-27": "live",
            "2026-08-28": "confirmed_nav_missing",
        },
        missing_price_symbols_by_date={"2026-08-28": ["019999"]},
    )

    assert timeline[-1].valuation_status == "confirmed_nav_missing"
    assert timeline[-1].market_pnl == 0
    assert timeline[-1].missing_price_symbols == ["019999"]
