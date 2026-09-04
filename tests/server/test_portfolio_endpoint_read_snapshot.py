"""Real portfolio endpoints share one immutable persisted-fact snapshot."""

from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.config import ServerConfig
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.routes import portfolio as portfolio_routes


def _build_etf_state(tmp_path) -> AppState:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-01T09:00:00+08:00",
        amount=10_000.0,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-01T10:00:00+08:00",
        symbol="510300",
        direction="buy",
        quantity=100.0,
        price=4.0,
        asset_class="etf",
    )
    db.save_daily_close_snapshot_sync(
        symbol="510300",
        asset_class="etf",
        trade_date="2026-09-03",
        close_price=4.0,
        source="endpoint_snapshot_fixture",
    )
    db.save_quote_snapshot_sync(
        symbol="510300",
        asset_class="etf",
        price=4.1,
        volume=1_000.0,
        timestamp="2026-09-04T15:00:00+08:00",
        quote_source="endpoint_snapshot_fixture",
        provider_name="fixture",
        quote_status="confirmed",
    )
    db.publish_current_valuation_snapshot_sync()

    state = AppState()
    state.db = db
    state.config = ServerConfig(
        assets=[
            {
                "symbol": "510300",
                "asset_class": "etf",
                "display_name": "沪深300ETF",
            }
        ]
    )
    return state


def _test_app(state: AppState) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(portfolio_routes.create_router())
    return app


def _fail_independent_read(method_name: str):
    def fail(*args, **kwargs):
        raise AssertionError(f"independent financial read: {method_name}")

    return fail


def test_overview_uses_one_snapshot_across_portfolio_live_risk_and_equity(
    monkeypatch,
    tmp_path,
) -> None:
    from server.projections import portfolio_read_snapshot_persistence as persistence

    state = _build_etf_state(tmp_path)
    db = state.require_database()
    counts = {"identity": 0, "ledger": 0, "matrix": 0}

    resolve_identity = persistence._resolve_read_identity
    read_ledger = db.get_all_ledger_entries_sync
    read_matrix = db.get_historical_price_matrix_sync

    def counted_identity(*args, **kwargs):
        counts["identity"] += 1
        return resolve_identity(*args, **kwargs)

    def counted_ledger(*args, **kwargs):
        counts["ledger"] += 1
        return read_ledger(*args, **kwargs)

    def counted_matrix(*args, **kwargs):
        counts["matrix"] += 1
        return read_matrix(*args, **kwargs)

    monkeypatch.setattr(persistence, "_resolve_read_identity", counted_identity)
    monkeypatch.setattr(db, "get_all_ledger_entries_sync", counted_ledger)
    monkeypatch.setattr(db, "get_historical_price_matrix_sync", counted_matrix)
    for method_name in (
        "get_latest_market_bar_before_date_sync",
        "get_latest_daily_close_before_sync",
        "get_latest_quote_before_date_sync",
        "get_market_bar_on_date_sync",
        "get_recent_quote_snapshots_sync",
    ):
        monkeypatch.setattr(
            db,
            method_name,
            _fail_independent_read(method_name),
        )

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["valuation_snapshot_id"]
    assert payload["ledger_cutoff_id"] == 2
    assert counts == {"identity": 1, "ledger": 1, "matrix": 1}


def test_intraday_equity_uses_snapshot_quote_history_not_per_symbol_reads(
    monkeypatch,
    tmp_path,
) -> None:
    state = _build_etf_state(tmp_path)
    db = state.require_database()
    monkeypatch.setattr(
        db,
        "get_recent_quote_snapshots_sync",
        _fail_independent_read("get_recent_quote_snapshots_sync"),
    )

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/series?range=1d")

    assert response.status_code == 200, response.text
    assert response.json()


def test_live_holding_rejects_tampered_published_valuation(
    monkeypatch,
    tmp_path,
) -> None:
    state = _build_etf_state(tmp_path)
    database_path = tmp_path / "app.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TRIGGER valuation_snapshots_update_guard")
        connection.execute("DROP TRIGGER valuation_snapshots_delete_guard")
        row = connection.execute("""
            SELECT snapshots.snapshot_id, snapshots.quotes_json
            FROM runtime_controls AS controls
            JOIN valuation_snapshots AS snapshots
              ON snapshots.snapshot_id = json_extract(
                  controls.value_json,
                  '$.snapshot_id'
              )
            WHERE controls.key = 'valuation_snapshot_publication'
            """).fetchone()
        assert row is not None
        quotes = json.loads(str(row[1]))
        for key in (
            "previous_close",
            "previous_close_date",
            "previous_close_source",
            "valuation_baseline_status",
        ):
            quotes[0].pop(key, None)
        connection.execute(
            "UPDATE valuation_snapshots SET quotes_json = ? WHERE snapshot_id = ?",
            (json.dumps(quotes), str(row[0])),
        )

    db = state.require_database()
    for method_name in (
        "get_latest_market_bar_before_date_sync",
        "get_latest_daily_close_before_sync",
        "get_latest_quote_before_date_sync",
    ):
        monkeypatch.setattr(db, method_name, _fail_independent_read(method_name))

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/live-holdings")

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "published valuation snapshot is invalid"


def test_portfolio_endpoint_preserves_explicit_etf_identity_from_legacy_ledger(
    tmp_path,
) -> None:
    state = _build_etf_state(tmp_path)

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["positions"][0]["symbol"] == "510300"
    assert payload["positions"][0]["instrument_type"] == "etf"
    assert payload["positions"][0]["market_value"] == 410.0
