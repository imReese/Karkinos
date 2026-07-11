from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes.execution_reconciliation import create_router
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
)
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


def test_execution_batch_reconciliation_routes_preview_record_resolve_and_list(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "execution-reconciliation.db")
    db.init_sync()
    db.upsert_oms_order_sync(
        {
            "order_id": "prior-order-1",
            "intent_key": "intent-prior-order-1",
            "symbol": "510300",
            "side": "buy",
            "asset_class": "etf",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 6.0,
            "status": "cancelled",
            "broker_submission_enabled": False,
            "source": "route-test",
            "payload": {"execution_mode": "manual"},
        }
    )
    run_id = "execution-reconciliation:2026-07-10"
    db.upsert_execution_reconciliation_run_sync(
        run_id=run_id,
        run_date="2026-07-10",
        status="clear",
        item_count=1,
        open_item_count=0,
        payload={"schema_version": "karkinos.execution_reconciliation.v1"},
        items=[
            {
                "order_id": "prior-order-1",
                "item_status": "cancelled",
                "suggested_action": "no_action",
                "detail": "route test clear prior batch",
                "payload": {
                    "oms_status": "cancelled",
                    "execution_mode": "manual",
                },
            }
        ],
    )
    client = _client_for_db(monkeypatch, db)
    request = {
        "batch_id": "prior-batch-1",
        "order_ids": ["prior-order-1"],
        "reconciliation_run_id": run_id,
    }

    status = client.get("/api/execution-reconciliation/batch-evidence/status")
    preview = client.post(
        "/api/execution-reconciliation/batch-evidence/preview",
        json=request,
    )
    fingerprint = preview.json()["batch_reconciliation_fingerprint"]
    recorded = client.post(
        "/api/execution-reconciliation/batch-evidence/records",
        json={
            **request,
            "batch_reconciliation_fingerprint": fingerprint,
            "operator_label": "local-owner",
            "acknowledgement": (EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT),
        },
    )
    resolved = client.get(
        f"/api/execution-reconciliation/batch-evidence/records/{fingerprint}"
    )
    listed = client.get("/api/execution-reconciliation/batch-evidence/records?limit=10")

    assert status.status_code == 200
    assert status.json()["broker_submission_enabled"] is False
    assert preview.status_code == 200
    assert preview.json()["status"] == "clear"
    assert recorded.status_code == 200
    assert recorded.json()["record_status"] == "recorded_clear"
    assert recorded.json()["authorizes_next_batch"] is False
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "pass"
    assert listed.status_code == 200
    assert listed.json()[0]["batch_id"] == "prior-batch-1"


def test_execution_batch_reconciliation_route_rejects_credentials_and_stale_hash(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "execution-reconciliation.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    payload = {
        "batch_id": "prior-batch-1",
        "order_ids": ["prior-order-1"],
        "reconciliation_run_id": "execution-reconciliation:2026-07-10",
        "batch_reconciliation_fingerprint": "0" * 64,
        "operator_label": "local-owner",
        "acknowledgement": EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    }

    credential = client.post(
        "/api/execution-reconciliation/batch-evidence/records",
        json={**payload, "broker_password": "must-not-be-accepted"},
    )
    stale = client.post(
        "/api/execution-reconciliation/batch-evidence/records",
        json=payload,
    )

    assert credential.status_code == 422
    assert stale.status_code == 409
    assert stale.json()["detail"]["record_status"] == "rejected"
    assert stale.json()["detail"]["authorizes_next_batch"] is False
