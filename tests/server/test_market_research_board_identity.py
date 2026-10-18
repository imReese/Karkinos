from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import InstrumentKey
from server.db import AppDatabase
from server.routes import market as market_routes
from server.routes.market import create_router

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "symbol, kinds, prices",
    [
        ("000001", ("stock", "index"), (None, 3500.0)),
        ("000001", ("stock", "index"), (12.5, 3500.0)),
        ("019999", ("etf", "open_end_fund"), (1.25, 2.5)),
        ("019999", ("etf", "open_end_fund"), (None, 2.5)),
        ("019999", ("etf", "open_end_fund"), (1.25, None)),
    ],
    ids=[
        "stock-missing",
        "stock-and-index",
        "etf-and-fund",
        "etf-missing",
        "fund-missing",
    ],
)
def test_research_board_prices_join_exact_persisted_identity(
    tmp_path, monkeypatch, symbol, kinds, prices
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    # Market indices are added by the real endpoint, alongside the stock watchlist.
    configured_kinds = kinds[:1] if kinds[1] == "index" else kinds
    assets = [
        {
            "symbol": symbol,
            "instrument_type": kind,
            "display_name": f"synthetic {kind}",
        }
        for kind in configured_kinds
    ]
    for kind, price in zip(kinds, prices, strict=True):
        if price is not None:
            db.upsert_latest_quote_sync(
                symbol=symbol,
                asset_type=kind,
                price=price,
                quote_timestamp="2026-10-16T15:00:00+08:00",
                quote_source="synthetic",
                quote_status="confirmed",
            )
    state = SimpleNamespace(
        db=db,
        scheduler=None,
        config=SimpleNamespace(assets=assets, data_source="akshare"),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/research-board")

    assert response.status_code == 200
    payload = response.json()
    health_quotes = {
        InstrumentKey.from_values(quote["symbol"], quote["instrument_type"]): quote
        for quote in payload["health"]["quotes"]
    }
    for kind, price in zip(kinds, prices, strict=True):
        quote = health_quotes[InstrumentKey.from_values(symbol, kind)]
        assert quote["price"] == price
        if price is None:
            assert quote["quote_status"] == "missing"
    assert [(item["asset_class"], item["price"]) for item in payload["items"]] == [
        ("fund" if kind == "open_end_fund" else kind, prices[index])
        for index, kind in enumerate(configured_kinds)
    ]


@pytest.mark.parametrize("identity", [None, "unsupported"])
@pytest.mark.parametrize("side", ["watchlist", "health"])
def test_research_board_never_joins_unresolved_identity(
    tmp_path, monkeypatch, identity, side
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_latest_quote_sync(
        symbol="600001",
        asset_type="stock",
        price=12.5,
        quote_timestamp="2026-10-16T15:00:00+08:00",
        quote_source="synthetic",
        quote_status="confirmed",
    )
    asset = {"symbol": "600001", "asset_class": "stock", "instrument_type": "stock"}
    state = SimpleNamespace(
        db=db,
        scheduler=None,
        config=SimpleNamespace(assets=[asset], data_source="akshare"),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    if side == "watchlist":
        monkeypatch.setattr(
            market_routes,
            "_merged_watchlist_assets",
            lambda state: [{**asset, "instrument_type": identity}],
        )
    else:
        build_health = market_routes._build_market_data_health_response

        def health_with_unresolved_identity(*args):
            health = build_health(*args)
            return health.model_copy(
                update={
                    "quotes": [
                        quote.model_copy(update={"instrument_type": identity})
                        if quote.symbol == "600001"
                        else quote
                        for quote in health.quotes
                    ]
                }
            )

        monkeypatch.setattr(
            market_routes,
            "_build_market_data_health_response",
            health_with_unresolved_identity,
        )
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/research-board")

    assert response.status_code == 200
    assert response.json()["items"][0]["price"] is None
