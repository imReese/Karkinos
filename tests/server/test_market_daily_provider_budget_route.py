"""The operator can inspect the durable allowance without making provider calls."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from data.providers.baostock import BAOSTOCK_DAILY_BAR_DESCRIPTOR
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.persistence.jobs import SQLiteJobStore
from server.persistence.market_daily_call_budget import (
    DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT,
    reserve_market_daily_provider_call,
)
from server.routes import market


def test_daily_provider_budget_route_reads_shared_reservations(tmp_path, monkeypatch):
    now = datetime(2026, 9, 29, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "server.http.market_endpoints.health.datetime",
        SimpleNamespace(now=lambda tz: now),
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = SQLiteJobStore(db.path)
    store.enqueue("market_daily_collection", {"sample": 1}, now=now)
    job = store.claim("market_daily_collection", "test-worker", now=now)
    assert job is not None
    reserve_market_daily_provider_call(
        db.path, job.lease, BAOSTOCK_DAILY_BAR_DESCRIPTOR, now=now
    )

    state = AppState()
    state.db = db
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(market.create_router())
    with TestClient(app) as client:
        response = client.get("/api/market/daily-provider-budget")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "karkinos.market_daily_provider_budget.v1"
    assert payload["scope"] == "managed_daily_market_jobs"
    assert payload["shanghai_date"] == "2026-09-29"
    assert payload["groups"]["baostock"] == {
        "used": 1,
        "limit": DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT,
        "remaining": DEFAULT_DAILY_PROVIDER_ATTEMPT_LIMIT - 1,
    }
    assert payload["groups"]["tencent"]["used"] == 0


def test_daily_provider_budget_route_fails_closed_on_unreadable_usage(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = AppState()
    state.db = db
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(market.create_router())

    def unreadable(*args, **kwargs):
        raise OSError("unreadable")

    monkeypatch.setattr(
        "server.http.market_endpoints.health.market_daily_provider_call_budget_status",
        unreadable,
    )

    with TestClient(app) as client:
        response = client.get("/api/market/daily-provider-budget")

    assert response.status_code == 503
    assert response.json()["detail"] == "market_daily_provider_budget_unavailable"
