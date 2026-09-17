"""Overview keeps one financial snapshot and separates its independent states."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from server.contracts.http.portfolio_models import (
    ClosedPositionResponse,
    OverviewRefreshHealth,
    PortfolioSnapshot,
    PositionResponse,
)
from server.projections.account_state import (
    build_overview_account_state_response as build_account_state_response,
)
from server.projections.portfolio_application import (
    build_account_state_response as build_base_account_state,
)
from server.services.account_state import build_overview_state

NOW = datetime(2026, 9, 12, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
SESSION = {
    "status": "non_trading_day",
    "calendar_verified": True,
    "latest_completed_trade_date": "2026-09-11",
    "expected_quote_date": "2026-09-11",
    "next_trading_date": "2026-09-14",
    "blockers": [],
}


def portfolio_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash=500,
        total_equity=1600,
        total_deposits=1480,
        realized_pnl_total=20,
        valuation_snapshot_id="snapshot-friday",
        valuation_as_of="2026-09-11T17:00:00+08:00",
        valuation_trade_date="2026-09-11",
        valuation_status="complete",
        valuation_policy="confirmed-close",
        ledger_cutoff_id=3,
        ledger_fingerprint="ledger-fixture",
        quote_set_fingerprint="quotes-fixture",
        allocation=[],
        positions=[
            PositionResponse(
                symbol="fixture-stock",
                asset_class="stock",
                instrument_type="stock",
                quantity=10,
                available_qty=10,
                frozen_qty=0,
                avg_cost=100,
                latest_price=110,
                market_value=1100,
                unrealized_pnl=100,
                realized_pnl=0,
                commission_paid=0,
                today_change=-10,
                quote_timestamp="2026-09-11T15:00:00+08:00",
                quote_status="live",
                pricing_kind="session_close",
                pricing_as_of="2026-09-11",
                pricing_authority="authoritative",
            )
        ],
    )


@pytest.fixture
def projection_sources(monkeypatch):
    calls = []
    snapshot = portfolio_snapshot()

    async def read_snapshot(state, *, now):
        assert now == NOW
        calls.append("portfolio")
        return snapshot

    async def read_operations(state):
        calls.append("operations")
        return {"attention_items": [], "daily_plan": {"blocked_count": 0}}

    monkeypatch.setattr(
        "server.projections.portfolio_application.build_portfolio_snapshot",
        read_snapshot,
    )
    monkeypatch.setattr(
        "server.projections.portfolio_application.collect_latest_quote_timestamps",
        lambda state: {},
    )
    monkeypatch.setattr(
        "server.projections.account_state.project_market_session",
        lambda db, now: SESSION,
    )
    monkeypatch.setattr(
        "server.projections.account_state.build_today_operations_payload",
        read_operations,
    )
    db = SimpleNamespace(
        list_quote_fetch_runs=lambda **kwargs: [
            {
                "status": "failed",
                "updated_at": NOW.isoformat(),
                "blockers": ["refresh_transport_failed"],
            }
        ]
    )
    return SimpleNamespace(db=db), snapshot, calls


@pytest.mark.asyncio
async def test_valid_snapshot_and_later_failed_refresh_are_independent(
    projection_sources,
):
    state, snapshot, calls = projection_sources
    response = await build_account_state_response(state, now=NOW)

    assert calls == ["portfolio", "operations"]
    assert response.snapshot is snapshot
    assert response.summary.valuation_snapshot_id == snapshot.valuation_snapshot_id
    assert response.summary.total_equity == 1600
    assert response.summary.cumulative_pnl == 120
    assert response.summary.cumulative_return is None
    assert response.summary.today_pnl == -10
    assert response.summary.latest_session_date == "2026-09-11"
    assert response.overview.valuation_usability == "usable"
    assert response.overview.pricing_as_of == "2026-09-11"
    assert response.overview.refresh_health.status == "degraded"
    assert response.overview.user_attention == []
    assert response.overview.decision_readiness == "unknown"


@pytest.mark.asyncio
async def test_missing_daily_baseline_does_not_invalidate_current_valuation(
    projection_sources,
):
    state, snapshot, _ = projection_sources
    snapshot.positions[0].today_change = None
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl is None
    assert response.summary.total_equity == 1600
    assert response.summary.quote_status != "missing"
    assert response.overview.valuation_usability == "usable"


@pytest.mark.asyncio
async def test_daily_pnl_includes_canonical_closed_position_attribution(
    projection_sources,
):
    state, snapshot, _ = projection_sources
    snapshot.closed_positions = [
        ClosedPositionResponse(
            **{
                **snapshot.positions[0].model_dump(),
                "symbol": "closed-fixture",
                "quantity": 0,
                "today_change": 7,
            },
            closed_at="2026-09-11T14:00:00+08:00",
        )
    ]
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl == -3


@pytest.mark.asyncio
async def test_closed_position_from_an_older_session_does_not_erase_session_pnl(
    projection_sources,
):
    state, snapshot, _ = projection_sources
    snapshot.closed_positions = [
        ClosedPositionResponse(
            **{
                **snapshot.positions[0].model_dump(),
                "symbol": "older-closed-fixture",
                "quantity": 0,
                "today_change": 70,
                "performance_session_date": "2026-09-10",
                "pricing_as_of": "2026-09-10",
            },
            closed_at="2026-09-10T14:00:00+08:00",
        )
    ]
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl == -10
    assert response.summary.latest_session_date == "2026-09-11"
    assert [item.symbol for item in response.summary.today_contributors] == [
        "fixture-stock"
    ]


@pytest.mark.asyncio
async def test_performance_session_date_takes_priority_over_publication_timestamp(
    projection_sources,
):
    state, snapshot, _ = projection_sources
    position = snapshot.positions[0]
    position.performance_session_date = "2026-09-10"
    position.pricing_as_of = "2026-09-11"
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl == -10
    assert response.summary.latest_session_date == "2026-09-10"


@pytest.mark.asyncio
async def test_attention_failure_preserves_financial_canvas(
    monkeypatch, projection_sources
):
    state, _, _ = projection_sources

    async def fail_operations(state):
        raise RuntimeError("fixture unavailable")

    monkeypatch.setattr(
        "server.projections.account_state.build_today_operations_payload",
        fail_operations,
    )
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.total_equity == 1600
    assert response.overview.valuation_usability == "usable"
    assert response.overview.attention_status == "unavailable"
    assert response.overview.decision_readiness == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["history", "refresh", "attention_items"])
async def test_secondary_projection_failure_preserves_usable_financial_state(
    monkeypatch, projection_sources, failure
):
    state, snapshot, _ = projection_sources

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture secondary projection unavailable")

    target = {
        "history": "build_daily_equity_series_from_ledger_history",
        "refresh": "read_overview_refresh_health",
        "attention_items": "build_overview_attention_items",
    }[failure]
    monkeypatch.setattr(f"server.projections.account_state.{target}", unavailable)
    if failure == "attention_items":

        async def blocked_operations(state):
            return {"daily_plan": {"blocked_count": 1}, "attention_items": []}

        monkeypatch.setattr(
            "server.projections.account_state.build_today_operations_payload",
            blocked_operations,
        )
    response = await build_account_state_response(state, now=NOW)

    assert response.snapshot is snapshot
    assert response.summary.total_equity == 1600
    assert response.summary.today_pnl == -10
    assert response.summary.cumulative_pnl == 120
    assert response.overview.valuation_usability == "usable"
    if failure == "history":
        assert response.summary.current_drawdown is None
        assert response.summary.drawdown_blockers == ["drawdown_history_unavailable"]
    elif failure == "refresh":
        assert response.overview.refresh_health.blockers == [
            "refresh_history_unavailable"
        ]
    else:
        assert response.overview.attention_status == "unavailable"
        assert response.overview.decision_readiness == "blocked"


@pytest.mark.asyncio
async def test_stale_holding_blocks_valuation_and_decision(projection_sources):
    state, snapshot, _ = projection_sources
    snapshot.total_equity = None
    snapshot.valuation_status = "blocked"
    snapshot.valuation_blockers = ["market_evidence_stale:fixture-stock"]
    position = snapshot.positions[0]
    position.valuation_available = False
    position.valuation_blockers = snapshot.valuation_blockers
    position.quote_status = "stale"
    position.today_change = None
    position.market_value = None
    position.unrealized_pnl = None
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.total_equity is None
    assert response.summary.cumulative_pnl is None
    assert response.overview.valuation_usability == "degraded"
    assert response.overview.decision_readiness == "blocked"
    assert len(response.overview.user_attention) == 1


@pytest.mark.asyncio
async def test_non_overview_consumer_does_not_fetch_operational_state(
    projection_sources,
):
    state, snapshot, calls = projection_sources
    response = await build_base_account_state(state, snapshot=snapshot, now=NOW)
    assert calls == []
    assert response.overview is None
    assert response.summary.total_equity == 1600


@pytest.mark.parametrize("gate_status", ["blocked", "degraded", "missing"])
def test_manual_ready_count_cannot_override_required_decision_gates(gate_status):
    overview = build_overview_state(
        portfolio_snapshot(),
        market_session=SESSION,
        refresh_health=OverviewRefreshHealth(status="healthy"),
        operations={
            "daily_plan": {"manual_ready_count": 1, "blocked_count": 0},
            "subsystems": [
                {"id": key, "status": gate_status if key == "risk" else "pass"}
                for key in ("market_data", "account_truth", "risk", "paper_shadow")
            ],
        },
        user_attention=[],
    )
    assert overview.valuation_usability == "usable"
    assert overview.decision_readiness != "ready"


@pytest.mark.asyncio
async def test_mixed_nav_and_stock_dates_do_not_claim_one_session_pnl(
    projection_sources,
):
    state, snapshot, _ = projection_sources
    snapshot.positions.append(
        snapshot.positions[0].model_copy(
            update={
                "symbol": "fixture-fund",
                "instrument_type": "open_end_fund",
                "asset_class": "fund",
                "pricing_kind": "published_nav",
                "pricing_as_of": "2026-09-10",
                "nav_date": "2026-09-10",
                "today_change": 5,
            }
        )
    )
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl is None
    assert response.summary.latest_session_date is None
    assert response.overview.valuation_usability == "usable"


@pytest.mark.asyncio
async def test_daily_pnl_date_comes_from_marks_not_wall_clock(
    monkeypatch, projection_sources
):
    state, _, _ = projection_sources
    monkeypatch.setattr(
        "server.projections.account_state.project_market_session",
        lambda db, now: {
            **SESSION,
            "status": "open",
            "expected_quote_date": "2026-09-14",
        },
    )
    response = await build_account_state_response(state, now=NOW)
    assert response.summary.today_pnl == -10
    assert response.summary.latest_session_date == "2026-09-11"


@pytest.mark.asyncio
async def test_persisted_overview_keeps_friday_valuation_after_failed_weekend_refresh(
    tmp_path, monkeypatch
):
    from server.config import ServerConfig
    from server.db import AppDatabase
    from server.dependencies import AppState
    from server.projections.account_state import build_overview_account_state_response
    from tests.server.test_market_pricing_semantics import _calendar

    def no_provider(*args, **kwargs):
        pytest.fail("ordinary Overview read must not construct external providers")

    monkeypatch.setattr("data.manager.build_sources", no_provider)
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    calendar = _calendar()
    db.upsert_market_calendar_snapshot_sync(
        {**calendar, "provider": "fixture", "status": "available", "limitations": []}
    )
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="fixture",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-10T09:00:00+08:00",
        amount=1000.0,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-10T10:00:00+08:00",
        symbol="019999",
        direction="buy",
        quantity=100.0,
        price=1.0,
        asset_class="fund",
    )
    db.save_daily_close_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        trade_date="2026-09-10",
        close_price=1.2,
        source="fixture",
    )
    db.save_quote_snapshot_sync(
        symbol="019999",
        asset_class="fund",
        price=1.1,
        volume=None,
        timestamp="2026-09-11T15:00:00+08:00",
        quote_source="eastmoney_fund_page",
        quote_status="confirmed",
        nav_date="2026-09-11",
    )
    valuation = db.publish_current_valuation_snapshot_sync(now=NOW)
    db.create_quote_fetch_run(
        run_id="failed-later-refresh",
        started_at="2026-09-12T16:59:00+08:00",
        trigger="manual",
        provider="fixture",
        asset_type="fund",
        status="failed",
        symbol_count=1,
        metadata={"requested_symbols": ["019999"]},
    )
    state = AppState()
    state.db = db
    state.config = ServerConfig()

    response = await build_overview_account_state_response(state, now=NOW)

    assert response.snapshot.valuation_snapshot_id == valuation["snapshot_id"]
    assert response.summary.valuation_snapshot_id == valuation["snapshot_id"]
    assert response.summary.total_equity == 1010.0
    assert response.summary.current_drawdown == pytest.approx(1 - 1010 / 1020)
    assert response.summary.current_drawdown_amount == pytest.approx(10)
    assert response.summary.drawdown_peak_equity == pytest.approx(1020)
    assert response.summary.drawdown_latest_equity == pytest.approx(1010)
    assert response.summary.drawdown_blockers == []
    assert response.overview.valuation_usability == "usable"
    assert response.overview.market_session.status == "non_trading_day"
    assert response.overview.pricing_as_of == "2026-09-11"
    assert response.overview.refresh_health.status == "degraded"
    assert response.overview.attention_status == "available"
    assert response.overview.user_attention == []
    assert response.overview.decision_readiness != "ready"
    assert (
        db.get_runtime_control_sync("valuation_snapshot_publication")["snapshot_id"]
        == valuation["snapshot_id"]
    )
