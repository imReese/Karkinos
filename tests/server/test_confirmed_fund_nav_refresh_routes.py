from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from core.types import Symbol
from server.db import AppDatabase


class DeterministicConfirmedFundNavSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_confirmed_fund_nav(self, symbol: Symbol) -> dict:
        self.calls.append(str(symbol))
        return {
            "price": 2.75,
            "timestamp": "2026-06-17T15:00:00+08:00",
            "nav_date": "2026-06-17",
            "quote_source": "eastmoney_fund_page",
            "provider_name": "deterministic_fixture",
            "provider_symbol": str(symbol),
        }


class DeterministicEstimateOnlySource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_latest(self, symbol: Symbol, _asset_class) -> dict:
        self.calls.append(str(symbol))
        return {
            "price": 2.74,
            "timestamp": "2026-06-17T14:48:00+08:00",
            "nav_date": "2026-06-16",
            "quote_source": "eastmoney_fund_estimate",
            "provider_name": "deterministic_fixture",
        }


def _route_endpoint():
    from server.routes import market as market_routes

    router = market_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == "/api/market/fund-nav/confirmed/refresh"
        and "POST" in route.methods
    )


def _state(db: AppDatabase, *, asset_class: str = "fund") -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            data_source="deterministic_fixture",
            tushare_token="",
            assets=[
                {
                    "symbol": "FUND-A",
                    "asset_class": asset_class,
                    "display_name": "确定性基金",
                }
            ],
        ),
        db=db,
        scheduler=None,
    )


@pytest.fixture
def inline_market_fetch(monkeypatch):
    from server.routes import market as market_routes

    async def inline_fetch(func, *args):
        return func(*args)

    monkeypatch.setattr(market_routes, "_run_blocking_fetch", inline_fetch)
    monkeypatch.setattr(
        market_routes,
        "_shanghai_now",
        lambda: datetime(2026, 6, 17, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def test_confirmed_fund_nav_refresh_persists_audited_evidence_only(
    monkeypatch,
    tmp_path,
    inline_market_fetch,
):
    from server.routes.market import ConfirmedFundNavRefreshRequest
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = DeterministicConfirmedFundNavSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {
            "deterministic_fixture": source,
            "akshare": source,
        },
    )
    state = _state(db)
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    ledger_before = db.get_ledger_entries_sync(limit=100)
    request_id = "confirmed-nav-route-0001"

    response = asyncio.run(
        _route_endpoint()(
            ConfirmedFundNavRefreshRequest(
                symbols=["FUND-A"],
                request_id=request_id,
            )
        )
    )

    latest = db.get_latest_quote_sync("FUND-A", asset_type="fund")
    assert source.calls == ["FUND-A"]
    assert response.status == "success"
    assert response.request_id == request_id
    assert response.idempotent_replay is False
    assert response.requested_symbols == ["FUND-A"]
    assert response.refreshed_symbols == ["FUND-A"]
    assert response.failed_symbols == {}
    assert response.run.trigger == "fund_nav_sync"
    assert response.run.metadata["confirmation_only"] is True
    assert response.valuation_snapshot_id
    assert response.provider_contact_performed is True
    assert response.writes_market_data_only is True
    assert response.does_not_mutate_oms is True
    assert response.does_not_mutate_production_ledger is True
    assert response.does_not_mutate_risk is True
    assert response.does_not_mutate_kill_switch is True
    assert response.does_not_change_capital_authority is True
    assert response.authorizes_execution is False
    assert latest is not None
    assert latest["quote_source"] == "eastmoney_fund_page"
    assert latest["nav_date"] == "2026-06-17"
    assert latest["fetch_run_id"] == response.run.run_id
    assert db.get_ledger_entries_sync(limit=100) == ledger_before


def test_confirmed_fund_nav_refresh_replays_same_request_without_provider_contact(
    monkeypatch,
    tmp_path,
    inline_market_fetch,
):
    from server.routes.market import ConfirmedFundNavRefreshRequest
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = DeterministicConfirmedFundNavSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {
            "deterministic_fixture": source,
            "akshare": source,
        },
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: _state(db))
    request = ConfirmedFundNavRefreshRequest(
        symbols=["FUND-A"],
        request_id="confirmed-nav-route-replay-0001",
    )

    first = asyncio.run(_route_endpoint()(request))
    replay = asyncio.run(_route_endpoint()(request))

    assert source.calls == ["FUND-A"]
    assert replay.request_id == request.request_id
    assert replay.run.run_id == first.run.run_id
    assert replay.status == "success"
    assert replay.refreshed_symbols == ["FUND-A"]
    assert replay.idempotent_replay is True
    assert replay.provider_contact_performed is False
    assert len(db.list_quote_fetch_runs(trigger="fund_nav_sync")) == 1
    assert len(db.get_recent_quote_snapshots_sync("FUND-A", limit=10)) == 1


def test_confirmed_fund_nav_refresh_maps_request_payload_drift_to_conflict(
    monkeypatch,
    tmp_path,
    inline_market_fetch,
):
    from server.routes.market import ConfirmedFundNavRefreshRequest
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    monkeypatch.setattr("server.app.get_app_state", lambda: _state(db))

    def reject_payload_drift(*args, **kwargs):
        raise fund_nav_sync.FundNavSyncIdempotencyConflict("payload drift")

    monkeypatch.setattr(
        fund_nav_sync,
        "refresh_fund_nav_quotes",
        reject_payload_drift,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _route_endpoint()(
                ConfirmedFundNavRefreshRequest(
                    symbols=["FUND-A"],
                    request_id="confirmed-nav-conflict-route-0001",
                )
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "confirmed fund NAV request id payload conflict"
    assert db.list_quote_fetch_runs() == []


def test_confirmed_fund_nav_refresh_rejects_estimate_and_keeps_review_open(
    monkeypatch,
    tmp_path,
    inline_market_fetch,
):
    from server.routes.market import ConfirmedFundNavRefreshRequest
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = DeterministicEstimateOnlySource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {
            "deterministic_fixture": source,
        },
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: _state(db))

    response = asyncio.run(
        _route_endpoint()(ConfirmedFundNavRefreshRequest(symbols=["FUND-A"]))
    )

    assert source.calls == ["FUND-A"]
    assert response.status == "failed"
    assert response.refreshed_symbols == []
    assert "FUND-A" in response.failed_symbols
    assert response.next_manual_action == "wait_for_confirmed_nav_then_retry"
    assert response.run.metadata["confirmation_only"] is True
    assert db.get_latest_quote_sync("FUND-A", asset_type="fund") is None
    assert db.get_ledger_entries_sync(limit=100) == []


def test_confirmed_fund_nav_refresh_rejects_non_fund_before_provider_contact(
    monkeypatch,
    tmp_path,
    inline_market_fetch,
):
    from server.routes.market import ConfirmedFundNavRefreshRequest
    from server.services import fund_nav_sync

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    source = DeterministicConfirmedFundNavSource()
    monkeypatch.setattr(
        fund_nav_sync,
        "build_sources",
        lambda data_source, tushare_token: {
            "deterministic_fixture": source,
        },
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: _state(db, asset_class="stock"),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _route_endpoint()(ConfirmedFundNavRefreshRequest(symbols=["FUND-A"]))
        )

    assert exc_info.value.status_code == 422
    assert source.calls == []
    assert db.list_quote_fetch_runs() == []
    assert db.get_ledger_entries_sync(limit=100) == []
