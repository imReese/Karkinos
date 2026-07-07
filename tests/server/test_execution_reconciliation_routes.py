from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes.execution_reconciliation import create_router
from server.services.oms import OmsService


def _client_for_db(monkeypatch, db: AppDatabase) -> TestClient:
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _confirmed_order(db: AppDatabase) -> dict:
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="daily:2026-07-02:600519:buy",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=1688.0,
        source="daily_trading_plan",
        source_ref="shadow:2026-07-02:abc",
    )
    return oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator approved paper/shadow evidence",
        actor="test",
    )


def test_execution_reconciliation_routes_run_list_and_detail(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "execution-reconciliation.db")
    db.init_sync()
    order = _confirmed_order(db)
    client = _client_for_db(monkeypatch, db)

    created = client.post(
        "/api/execution-reconciliation/runs",
        json={"run_date": "2026-07-02"},
    )

    assert created.status_code == 200
    run = created.json()
    assert run["run_id"] == "execution-reconciliation:2026-07-02"
    assert run["status"] == "open_items"
    assert run["open_item_count"] == 1
    assert run["items"][0]["order_id"] == order["order_id"]
    assert run["items"][0]["item_status"] == "gateway_action_missing"

    listed = client.get("/api/execution-reconciliation/runs")
    assert listed.status_code == 200
    assert listed.json()[0]["run_id"] == run["run_id"]

    detail = client.get(f"/api/execution-reconciliation/runs/{run['run_id']}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["run_id"] == run["run_id"]
    assert payload["items"][0]["suggested_action"] == "create_manual_ticket_or_cancel"


def test_execution_reconciliation_detail_route_returns_404(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "execution-reconciliation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.get("/api/execution-reconciliation/runs/missing-run")

    assert response.status_code == 404
