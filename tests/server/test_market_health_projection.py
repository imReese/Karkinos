from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey
from server.db import AppDatabase
from server.routes.market import create_router
from server.services.market_views import health_projection
from server.services.market_views.health_inputs import extract_runtime_portfolio

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 4, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture(autouse=True)
def fixed_market_time(monkeypatch):
    monkeypatch.setattr(health_projection, "_shanghai_now", lambda: _NOW)
    monkeypatch.setattr(health_projection, "is_cn_trading_session", lambda: True)


def _asset(symbol, instrument_type):
    return {
        "symbol": symbol,
        "instrument_type": instrument_type,
        "asset_class": "fund"
        if instrument_type == "open_end_fund"
        else instrument_type,
    }


def _state(db, assets, *, runtime_quotes=None):
    return SimpleNamespace(
        db=db,
        config=SimpleNamespace(assets=assets, data_source="akshare"),
        scheduler=SimpleNamespace(latest_quotes=runtime_quotes or {}),
    )


def _quote(symbol="600001", price=10.0):
    return {
        "symbol": symbol,
        "asset_class": "stock",
        "price": price,
        "timestamp": _NOW.isoformat(),
        "quote_source": "fixture",
        "quote_status": "live",
    }


def _save_quote(db, asset, price):
    db.upsert_latest_quote_sync(
        symbol=asset["symbol"],
        asset_type=asset["instrument_type"],
        price=price,
        quote_timestamp=_NOW.isoformat(),
        quote_source="fixture",
        quote_status="live",
    )


def test_health_reads_current_quotes_once_and_preserves_exact_identities(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    assets = [
        _asset("000001", "stock"),
        _asset("000001", "index"),
        _asset("019999", "etf"),
        _asset("019999", "open_end_fund"),
    ]
    prices = (12.5, 3500.0, 1.25, 2.5)
    for asset, price in zip(assets, prices, strict=True):
        _save_quote(db, asset, price)
    calls = {"list": 0, "get": 0}
    real_list = db.list_latest_quotes_sync
    real_get = db.get_latest_quotes_sync

    def list_quotes():
        calls["list"] += 1
        return real_list()

    def get_quotes():
        calls["get"] += 1
        return real_get()

    monkeypatch.setattr(db, "list_latest_quotes_sync", list_quotes)
    monkeypatch.setattr(db, "get_latest_quotes_sync", get_quotes)

    response = health_projection.build_market_data_health_response(
        _state(db, assets), assets
    )

    assert calls == {"list": 1, "get": 0}
    assert {
        InstrumentKey.from_values(quote.symbol, quote.instrument_type): quote.price
        for quote in response.quotes
    } == {
        InstrumentKey.from_values(asset["symbol"], asset["instrument_type"]): price
        for asset, price in zip(assets, prices, strict=True)
    }
    assert response.has_persistent_cache is True
    assert response.real_data_available is True


@pytest.mark.parametrize("legacy_has_quote", [False, True])
def test_empty_current_quotes_never_use_other_reader_or_runtime(
    tmp_path, monkeypatch, legacy_has_quote
):
    db = AppDatabase(tmp_path / "empty.db")
    db.init_sync()
    assets = [_asset("600001", "stock")]
    calls = {"list": 0, "get": 0}
    real_list = db.list_latest_quotes_sync

    def list_quotes():
        calls["list"] += 1
        return real_list()

    def get_quotes():
        calls["get"] += 1
        return [_quote(price=9.0)] if legacy_has_quote else []

    monkeypatch.setattr(db, "list_latest_quotes_sync", list_quotes)
    monkeypatch.setattr(db, "get_latest_quotes_sync", get_quotes)
    state = _state(db, assets, runtime_quotes={"600001": _quote(price=8.0)})

    response = health_projection.build_market_data_health_response(state, assets)

    assert response.quotes[0].price is None
    assert response.quotes[0].quote_status == "missing"
    assert response.quotes[0].stale_reason == "no_real_data_available"
    assert response.source_health == "missing"
    assert response.has_persistent_cache is False
    assert response.real_data_available is False
    assert response.persistent_cache_status == "missing"
    assert response.latest_persistent_quote_timestamp is None
    assert calls == {"list": 1, "get": 0}


@pytest.mark.parametrize("current_has_quote", [False, True])
def test_runtime_quote_projection_reads_only_current_reader(
    tmp_path, monkeypatch, current_has_quote
):
    db = AppDatabase(tmp_path / "runtime.db")
    db.init_sync()
    assets = [_asset("600001", "stock")]
    if current_has_quote:
        _save_quote(db, assets[0], 10.0)
    calls = {"list": 0, "get": 0}
    real_list = db.list_latest_quotes_sync

    def list_quotes():
        calls["list"] += 1
        return real_list()

    def get_quotes():
        calls["get"] += 1
        return [_quote(price=9.0)]

    monkeypatch.setattr(db, "list_latest_quotes_sync", list_quotes)
    monkeypatch.setattr(db, "get_latest_quotes_sync", get_quotes)
    state = _state(db, assets, runtime_quotes={"600001": _quote(price=8.0)})

    _, _, _, quotes = extract_runtime_portfolio(state)

    assert {symbol: row["price"] for symbol, row in quotes.items()} == (
        {"600001": 10.0} if current_has_quote else {}
    )
    assert calls == {"list": 1, "get": 0}


def test_health_http_empty_current_quotes_cannot_revive_legacy_or_runtime(
    tmp_path, monkeypatch
):
    db = AppDatabase(tmp_path / "http.db")
    db.init_sync()
    assets = [_asset("600001", "stock")]
    calls = {"list": 0, "get": 0}
    real_list = db.list_latest_quotes_sync

    def list_quotes():
        calls["list"] += 1
        return real_list()

    def get_quotes():
        calls["get"] += 1
        return [_quote(price=9.0)]

    monkeypatch.setattr(db, "list_latest_quotes_sync", list_quotes)
    monkeypatch.setattr(db, "get_latest_quotes_sync", get_quotes)
    state = _state(db, assets, runtime_quotes={"600001": _quote(price=8.0)})
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/data-health")

    assert response.status_code == 200
    payload = response.json()
    stock = next(quote for quote in payload["quotes"] if quote["symbol"] == "600001")
    assert stock["price"] is None
    assert stock["quote_status"] == "missing"
    assert payload["real_data_available"] is False
    assert payload["has_persistent_cache"] is False
    assert calls == {"list": 2, "get": 0}


def test_health_uses_legacy_reader_only_when_current_reader_is_absent(tmp_path):
    db = AppDatabase(tmp_path / "legacy.db")
    db.init_sync()
    assets = [_asset("600001", "stock")]
    _save_quote(db, assets[0], 10.0)
    calls = []

    def get_quotes():
        calls.append("get")
        return db.get_latest_quotes_sync()

    state = _state(
        SimpleNamespace(get_latest_quotes_sync=get_quotes),
        assets,
        runtime_quotes={"600001": _quote(price=8.0)},
    )

    response = health_projection.build_market_data_health_response(state, assets)

    assert calls == ["get"]
    assert response.quotes[0].price == 10.0
    assert response.quotes[0].instrument_type == "stock"
    assert response.has_persistent_cache is True
    assert response.latest_persistent_quote_timestamp == _NOW.isoformat()

    calls.clear()
    _, _, _, quotes = extract_runtime_portfolio(state)
    assert calls == ["get"]
    assert quotes["600001"]["price"] == 10.0
