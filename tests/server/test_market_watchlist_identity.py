from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import AssetClass, InstrumentType, Symbol
from domain.instrument import make_etf, make_open_end_fund
from domain.position import Position
from server.db import AppDatabase
from server.routes.market import create_router

pytestmark = pytest.mark.unit


@pytest.fixture
def watchlist_state(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    state = SimpleNamespace(
        db=db,
        scheduler=None,
        config=SimpleNamespace(assets=[], initial_cash=0, data_source="akshare"),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    return state


@pytest.mark.parametrize(
    "symbol, held_kind, watched_kind",
    [
        ("000001", "stock", "index"),
        ("019999", "etf", "open_end_fund"),
        ("019999", "open_end_fund", "etf"),
    ],
    ids=["stock-index", "etf-fund", "fund-etf"],
)
@pytest.mark.parametrize("quotes", ["held", "watched", "both", "missing"])
def test_watchlist_joins_holdings_and_snapshots_by_exact_identity(
    watchlist_state, symbol, held_kind, watched_kind, quotes
):
    db = watchlist_state.db
    db.upsert_watchlist_asset_sync(
        symbol=symbol,
        asset_class=watched_kind,
        instrument_type=watched_kind,
        display_name=f"synthetic {watched_kind}",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-10-15T09:00:00+08:00",
        amount=10000,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-10-15T10:00:00+08:00",
        symbol=symbol,
        direction="buy",
        quantity=100,
        price=10,
        asset_class=held_kind,
    )
    timestamps = {
        held_kind: "2026-10-16T14:00:00+08:00",
        watched_kind: "2026-10-16T15:00:00+08:00",
    }
    for lane, kind in [("held", held_kind), ("watched", watched_kind)]:
        if quotes in {lane, "both"}:
            db.upsert_latest_quote_sync(
                symbol=symbol,
                asset_type=kind,
                price=12.5 if lane == "held" else 3500,
                quote_timestamp=timestamps[kind],
                quote_source="synthetic",
                quote_status="confirmed",
            )
    ledger_before = db.get_ledger_entries_sync()
    quotes_before = db.list_latest_quotes_sync()
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/watchlist")

    assert response.status_code == 200
    items = {item["instrument_type"]: item for item in response.json()}
    assert set(items) == {held_kind, watched_kind}
    holding = items[held_kind]
    assert holding["is_holding"] is True
    assert holding["quantity"] == 100
    assert holding["avg_cost"] == 10
    assert holding["realized_pnl"] == 0
    # Missing or ambiguous valuation remains unavailable in the canonical book.
    assert holding["market_value"] == (1250 if quotes == "held" else 0)
    other = items[watched_kind]
    assert other["is_holding"] is False
    for field in (
        "quantity",
        "avg_cost",
        "market_value",
        "unrealized_pnl",
        "realized_pnl",
    ):
        assert other[field] is None
    for lane, kind in [("held", held_kind), ("watched", watched_kind)]:
        # The symbol-only runtime projection excludes multiple quote namespaces.
        expected = timestamps[kind] if quotes == lane else None
        assert items[kind]["last_snapshot_at"] == expected
    assert db.get_ledger_entries_sync() == ledger_before
    assert db.list_latest_quotes_sync() == quotes_before


@pytest.mark.parametrize("held_kind", ["etf", "open_end_fund"])
@pytest.mark.parametrize("runtime_identity", ["canonical", "missing", "unknown"])
def test_watchlist_runtime_fund_grouping_does_not_replace_exact_identity(
    monkeypatch, held_kind, runtime_identity
):
    symbol = "019999"
    other_kind = "open_end_fund" if held_kind == "etf" else "etf"
    instrument = (
        make_etf(symbol, "synthetic ETF")
        if held_kind == "etf"
        else make_open_end_fund(symbol, "synthetic fund")
    )
    assert instrument.asset_class is AssetClass.FUND
    if runtime_identity == "unknown":
        instrument = replace(instrument, instrument_type=InstrumentType.UNKNOWN)
    position = Position(Symbol(symbol))
    position.update_on_fill("buy", Decimal("100"), Decimal("10"))
    timestamp = "2026-10-16T15:00:00+08:00"
    state = SimpleNamespace(
        db=None,
        config=SimpleNamespace(
            assets=[
                {"symbol": symbol, "instrument_type": kind}
                for kind in (held_kind, other_kind)
            ],
        ),
        scheduler=SimpleNamespace(
            portfolio=SimpleNamespace(positions={Symbol(symbol): position}),
            instruments=(
                {} if runtime_identity == "missing" else {Symbol(symbol): instrument}
            ),
            latest_quotes={
                symbol: {
                    "instrument_type": held_kind,
                    "asset_class": "fund",
                    "timestamp": timestamp,
                    "price": 12.5,
                }
            },
        ),
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/watchlist")

    assert response.status_code == 200
    items = {item["instrument_type"]: item for item in response.json()}
    assert items[held_kind]["is_holding"] is (runtime_identity == "canonical")
    assert items[held_kind]["quantity"] == (
        100 if runtime_identity == "canonical" else None
    )
    assert items[other_kind]["is_holding"] is False
    assert items[other_kind]["quantity"] is None
    assert items[held_kind]["last_snapshot_at"] == timestamp
    assert items[other_kind]["last_snapshot_at"] is None


def test_research_board_does_not_inherit_other_instrument_holdings(watchlist_state):
    db = watchlist_state.db
    db.upsert_watchlist_asset_sync(
        symbol="000001", asset_class="index", instrument_type="index"
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-10-15T10:00:00+08:00",
        symbol="000001",
        direction="buy",
        quantity=100,
        price=10,
        asset_class="stock",
    )
    app = FastAPI()
    app.include_router(create_router())

    with TestClient(app) as client:
        response = client.get("/api/market/research-board")

    assert response.status_code == 200
    items = {item["asset_class"]: item for item in response.json()["items"]}
    assert items["stock"]["is_holding"] is True
    assert items["stock"]["quantity"] == 100
    assert items["index"]["is_holding"] is False
    assert items["index"]["quantity"] is None
    assert items["index"]["market_value"] is None
