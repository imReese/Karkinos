"""Real portfolio endpoints share one immutable persisted-fact snapshot."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pytest
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
    monkeypatch,
) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["positions"][0]["symbol"] == "510300"
    assert payload["positions"][0]["instrument_type"] == "etf"
    assert payload["positions"][0]["market_value"] == 410.0


def test_portfolio_state_endpoint_supports_etag_and_304(
    tmp_path,
    monkeypatch,
) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)

    async def operations(_state):
        return {"daily_plan": {}, "generated_at": now.isoformat()}

    monkeypatch.setattr(
        "server.projections.account_state.build_today_operations_payload", operations
    )

    with TestClient(_test_app(state)) as client:
        # First request: 200 OK with ETag
        response = client.get("/api/portfolio/state")
        assert response.status_code == 200, response.text
        etag = response.headers.get("etag")
        assert etag is not None
        assert response.headers.get("cache-control") == "no-cache"
        assert etag.startswith('"') and etag.endswith('"')

        # Second request with matching If-None-Match: 304 Not Modified
        conditional_response = client.get(
            "/api/portfolio/state",
            headers={"If-None-Match": etag},
        )
        assert conditional_response.status_code == 304
        assert conditional_response.text == ""
        assert conditional_response.headers.get("etag") == etag

        # Weak ETag format is also accepted
        weak_response = client.get(
            "/api/portfolio/state",
            headers={"If-None-Match": f"W/{etag}"},
        )
        assert weak_response.status_code == 304

        # Non-matching ETag returns 200
        mismatch_response = client.get(
            "/api/portfolio/state",
            headers={"If-None-Match": '"different-snapshot-id"'},
        )
        assert mismatch_response.status_code == 200


def test_portfolio_equity_curve_series_endpoint_supports_etag_and_304(
    tmp_path,
    monkeypatch,
) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)

    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/equity-curve/series?range=all")
        assert response.status_code == 200, response.text
        etag = response.headers.get("etag")
        assert etag is not None
        assert etag.startswith('"') and etag.endswith('"')

        conditional_response = client.get(
            "/api/portfolio/equity-curve/series?range=all",
            headers={"If-None-Match": etag},
        )
        assert conditional_response.status_code == 304
        assert conditional_response.text == ""

        # Different range has different etag and returns 200
        diff_range_response = client.get(
            "/api/portfolio/equity-curve/series?range=1m",
            headers={"If-None-Match": etag},
        )
        assert diff_range_response.status_code == 200


def _tamper_published_valuation(database_path) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TRIGGER valuation_snapshots_update_guard")
        row = connection.execute("""
            SELECT snapshots.snapshot_id, snapshots.quotes_json
            FROM runtime_controls AS controls
            JOIN valuation_snapshots AS snapshots
              ON snapshots.snapshot_id = json_extract(
                  controls.value_json, '$.snapshot_id'
              )
            WHERE controls.key = 'valuation_snapshot_publication'
            """).fetchone()
        assert row is not None
        quotes = json.loads(row[1])
        quotes[0].pop("previous_close", None)
        connection.execute(
            "UPDATE valuation_snapshots SET quotes_json = ? WHERE snapshot_id = ?",
            (json.dumps(quotes), row[0]),
        )


@pytest.mark.parametrize(
    "path",
    ["/api/portfolio/state", "/api/portfolio/equity-curve/series?range=all"],
)
def test_conditional_portfolio_read_validates_published_valuation(
    tmp_path, monkeypatch, path
) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)

    with TestClient(_test_app(state)) as client:
        first = client.get(path)
        assert first.status_code == 200, first.text
        _tamper_published_valuation(tmp_path / "app.db")
        conditional = client.get(path, headers={"If-None-Match": first.headers["etag"]})

    assert conditional.status_code == 503, conditional.text
    assert conditional.json()["detail"] == "published valuation snapshot is invalid"


@pytest.mark.parametrize("changed_projection", ["session", "refresh", "operations"])
def test_account_etag_changes_with_independent_overview_state(
    tmp_path, monkeypatch, changed_projection
) -> None:
    from server.contracts.http.portfolio_models import OverviewRefreshHealth
    from server.projections import account_state

    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    session = {"status": "pre_open", "calendar_verified": True}
    refresh = {"status": "healthy"}
    operations = {"daily_plan": {"blocked_count": 0}}

    async def read_operations(_state):
        return operations

    monkeypatch.setattr(account_state, "project_market_session", lambda *_: session)
    monkeypatch.setattr(
        account_state,
        "read_overview_refresh_health",
        lambda *_: OverviewRefreshHealth(**refresh),
    )
    monkeypatch.setattr(
        account_state, "build_today_operations_payload", read_operations
    )

    with TestClient(_test_app(state)) as client:
        first = client.get("/api/portfolio/state")
        assert first.status_code == 200, first.text
        if changed_projection == "session":
            session["status"] = "open"
        elif changed_projection == "refresh":
            refresh["status"] = "degraded"
        else:
            operations["daily_plan"]["blocked_count"] = 1
        second = client.get(
            "/api/portfolio/state", headers={"If-None-Match": first.headers["etag"]}
        )

    assert second.status_code == 200, second.text
    assert second.headers["etag"] != first.headers["etag"]
    assert (
        second.json()["snapshot"]["valuation_snapshot_id"]
        == first.json()["snapshot"]["valuation_snapshot_id"]
    )
    if changed_projection == "session":
        assert second.json()["overview"]["market_session"]["status"] == "open"
    elif changed_projection == "refresh":
        assert second.json()["overview"]["refresh_health"]["status"] == "degraded"
    else:
        assert second.json()["overview"]["decision_readiness"] == "blocked"


def _complete_history(state, close_price=4.0) -> None:
    for trade_date in ("2026-09-01", "2026-09-02", "2026-09-03"):
        state.require_database().save_daily_close_snapshot_sync(
            symbol="510300",
            asset_class="etf",
            trade_date=trade_date,
            close_price=close_price,
            source="historical_revision_fixture",
        )


def _historical_total(response, trade_date="2026-09-03") -> float:
    assert response.status_code == 200, response.text
    return next(
        point["total"]
        for point in response.json()
        if point["timestamp"].startswith(trade_date)
    )


def test_historical_revision_updates_series_drawdown_and_etags(
    tmp_path, monkeypatch
) -> None:
    state = _build_etf_state(tmp_path)
    _complete_history(state)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    path = "/api/portfolio/equity-curve/series?range=all"

    with TestClient(_test_app(state)) as client:
        first = client.get(path)
        first_account = client.get("/api/portfolio/state")
        assert _historical_total(first) == 10_000
        assert first_account.status_code == 200, first_account.text
        assert first_account.json()["summary"]["current_drawdown"] == 0
        state.require_database().save_daily_close_snapshot_sync(
            symbol="510300",
            asset_class="etf",
            trade_date="2026-09-03",
            close_price=9.0,
            source="historical_revision_fixture",
        )
        revised = client.get(path)
        revised_account = client.get("/api/portfolio/state")
        conditional = client.get(path, headers={"If-None-Match": first.headers["etag"]})

    assert _historical_total(revised) == 10_500
    assert conditional.status_code == 200, conditional.text
    assert revised.headers["etag"] != first.headers["etag"]
    assert revised_account.status_code == 200, revised_account.text
    before = first_account.json()
    after = revised_account.json()
    assert (
        after["snapshot"]["valuation_snapshot_id"]
        == before["snapshot"]["valuation_snapshot_id"]
    )
    assert after["summary"]["current_drawdown"] > 0
    assert after["summary"]["drawdown_peak_equity"] == pytest.approx(10_500)


def test_history_and_drawdown_are_isolated_between_app_states(
    tmp_path, monkeypatch
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first_state = _build_etf_state(first_root)
    _complete_history(first_state)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    first_state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    with sqlite3.connect(first_root / "app.db") as source:
        with sqlite3.connect(second_root / "app.db") as destination:
            source.backup(destination)
    second_state = AppState()
    second_state.db = AppDatabase(second_root / "app.db")
    second_state.config = first_state.config
    _complete_history(second_state, close_price=9.0)
    path = "/api/portfolio/equity-curve/series?range=all"

    with TestClient(_test_app(first_state)) as first_client:
        first = first_client.get(path)
        first_account = first_client.get("/api/portfolio/state")
    with TestClient(_test_app(second_state)) as second_client:
        second = second_client.get(path)
        second_account = second_client.get("/api/portfolio/state")

    assert _historical_total(first) == 10_000
    assert _historical_total(second) == 10_500
    before = first_account.json()
    after = second_account.json()
    assert (
        after["snapshot"]["valuation_snapshot_id"]
        == before["snapshot"]["valuation_snapshot_id"]
    )
    assert before["summary"]["current_drawdown"] == 0
    assert after["summary"]["current_drawdown"] > 0


def test_intraday_equity_etag_covers_its_response(tmp_path, monkeypatch) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    state.require_database().publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    path = "/api/portfolio/equity-curve/series?range=1d"
    with TestClient(_test_app(state)) as client:
        first = client.get(path)
        assert first.status_code == 200, first.text
        assert first.headers.get("etag")
        second = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304, second.text


def test_conditional_equity_read_reuses_the_validated_input_snapshot(
    tmp_path, monkeypatch
) -> None:
    state = _build_etf_state(tmp_path)
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    database = state.require_database()
    database.publish_current_valuation_snapshot_sync(now=now)
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    counts = {"ledger": 0, "matrix": 0}
    read_ledger = database.get_all_ledger_entries_sync
    read_matrix = database.get_historical_price_matrix_sync

    def ledger(*args, **kwargs):
        counts["ledger"] += 1
        return read_ledger(*args, **kwargs)

    def matrix(*args, **kwargs):
        counts["matrix"] += 1
        return read_matrix(*args, **kwargs)

    monkeypatch.setattr(database, "get_all_ledger_entries_sync", ledger)
    monkeypatch.setattr(database, "get_historical_price_matrix_sync", matrix)
    path = "/api/portfolio/equity-curve/series?range=all"
    with TestClient(_test_app(state)) as client:
        first = client.get(path)
        assert first.status_code == 200, first.text
        assert counts == {"ledger": 1, "matrix": 1}
        second = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert second.status_code == 304, second.text
    assert counts == {"ledger": 1, "matrix": 1}


@pytest.mark.parametrize(
    "holding_kind, task_kind, attaches",
    [
        ("stock", "stock", True),
        ("etf", "fund", True),
        ("open_end_fund", "fund", True),
        ("stock", "fund", False),
        ("open_end_fund", "stock", False),
        ("stock", "", False),
        ("stock", "unknown", False),
        ("stock", "missing", False),
    ],
)
def test_cockpit_links_tasks_only_to_the_same_asset_class(
    tmp_path, monkeypatch, holding_kind, task_kind, attaches
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    symbol = "000001"
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-01T09:00:00+08:00",
        amount=10_000,
        asset_class="cash",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-01T10:00:00+08:00",
        symbol=symbol,
        direction="buy",
        quantity=100,
        price=1,
        asset_class=holding_kind,
    )
    db.save_daily_close_snapshot_sync(
        symbol=symbol,
        asset_class=holding_kind,
        trade_date="2026-09-03",
        close_price=1,
        source="cockpit_identity_fixture",
    )
    db.save_quote_snapshot_sync(
        symbol=symbol,
        asset_class=holding_kind,
        price=1.1,
        volume=1_000,
        timestamp="2026-09-04T15:00:00+08:00",
        quote_source="cockpit_identity_fixture",
        provider_name="fixture",
        quote_status="confirmed",
    )
    now = datetime.fromisoformat("2026-09-04T16:00:00+08:00")
    valuation = db.publish_current_valuation_snapshot_sync(now=now)
    persisted_kind = "stock" if task_kind == "missing" else task_kind
    signal_id = db.save_signal_sync(
        timestamp="2026-09-04T09:40:00+08:00",
        strategy_id="cockpit_identity_fixture",
        symbol=symbol,
        direction="sell",
        target_weight=0,
        price=12.5,
        asset_class=persisted_kind,
    )
    action_id = db.upsert_action_task_sync(
        source_signal_id=signal_id,
        symbol=symbol,
        title="Synthetic exit candidate",
        detail="Synthetic identity fixture",
        direction="sell",
        urgency="medium",
        target_weight=0,
        price=12.5,
        strategy_id="cockpit_identity_fixture",
        timestamp="2026-09-04T09:40:00+08:00",
        asset_class=persisted_kind,
    )
    if task_kind == "missing":
        read_tasks = db.get_action_tasks

        async def missing_task_identity(*args, **kwargs):
            rows = await read_tasks(*args, **kwargs)
            return [
                {key: value for key, value in row.items() if key != "asset_class"}
                for row in rows
            ]

        monkeypatch.setattr(db, "get_action_tasks", missing_task_identity)

    state = AppState()
    state.db = db
    state.config = ServerConfig(
        assets=[{"symbol": symbol, "asset_class": holding_kind}]
    )
    monkeypatch.setattr(portfolio_routes, "get_shanghai_now", lambda: now)
    ledger_before = db.get_ledger_entries_sync()
    valuation_before = db.get_valuation_snapshot_sync(valuation["snapshot_id"])
    with TestClient(_test_app(state)) as client:
        response = client.get("/api/portfolio/cockpit")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["valuation_snapshot_id"] == valuation["snapshot_id"]
    assert len(payload["action_queue"]) == 1
    assert payload["action_queue"][0]["id"] == action_id
    position = payload["positions"][0]
    assert position["asset_class"] == (
        "fund" if holding_kind == "open_end_fund" else holding_kind
    )
    if attaches:
        assert position["action_task"]["id"] == action_id
        assert position["target_weight"] == 0
        assert position["drift"] == pytest.approx(-position["actual_weight"])
        recommendation = payload["construction_recommendations"][0]
        assert recommendation["source_action_task_id"] == action_id
        assert recommendation["asset_class"] == position["asset_class"]
        assert recommendation["direction"] == "sell"
        assert recommendation["target_weight"] == 0
        assert recommendation["actionable"] is False
        assert recommendation["account_truth_gate_status"] == "blocked"
        assert recommendation["risk_gate_status"] == "not_checked"
    else:
        assert position["action_task"] is None
        assert position["target_weight"] == position["actual_weight"]
        assert position["drift"] == 0
        assert payload["construction_recommendations"] == []
    assert db.get_ledger_entries_sync() == ledger_before
    assert db.get_valuation_snapshot_sync(valuation["snapshot_id"]) == valuation_before
    with sqlite3.connect(db._path) as connection:
        for table in ("risk_decisions", "oms_orders", "fills"):
            assert (
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            )
