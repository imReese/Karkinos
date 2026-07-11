from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.app import create_app
from server.db import AppDatabase
from server.routes.broker_connector_soak import create_router
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
)


def _connector(now: datetime) -> FakeReadOnlyBrokerConnector:
    return FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="route-runbook-readonly",
            source_name="route runbook readonly fixture",
            account_id="private-route-runbook-account-id",
            account_alias="route-runbook",
            captured_at=now.isoformat(),
            health=BrokerConnectorHealth(
                status="healthy",
                checked_at=now.isoformat(),
            ),
            cash=BrokerCashFact(
                currency="CNY",
                balance=Decimal("100000"),
                available=Decimal("90000"),
            ),
        )
    )


def _client(monkeypatch, db: AppDatabase, connector: object) -> TestClient:
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(broker_connectors=[connector]),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _seed_calendar(db: AppDatabase, now: datetime) -> None:
    shanghai_now = now.astimezone(timezone(timedelta(hours=8)))
    db.upsert_market_calendar_snapshot_sync(
        build_static_market_calendar_snapshot(
            exchange="SSE",
            year=shanghai_now.year,
            provider="synthetic_test_calendar",
            open_dates=[shanghai_now.date().isoformat()],
            fetched_at=shanghai_now.isoformat(),
        )
    )


def test_runbook_routes_record_and_list_readonly_run_and_drill_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak-runbook-routes.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_calendar(db, now)
    client = _client(monkeypatch, db, _connector(now))

    startup = client.post(
        "/api/automation/broker-soak/runs",
        json={"phase": "startup"},
    )
    end_of_day = client.post(
        "/api/automation/broker-soak/runs",
        json={"phase": "end_of_day"},
    )
    drill = client.post(
        "/api/automation/broker-soak/drills",
        json={"drill_type": "duplicate_evidence"},
    )
    runs = client.get("/api/automation/broker-soak/runs")
    drills = client.get("/api/automation/broker-soak/drills")

    assert startup.status_code == 200
    assert startup.json()["run_status"] == "passed"
    assert startup.json()["broker_submission_enabled"] is False
    assert end_of_day.status_code == 200
    assert end_of_day.json()["run_status"] == "blocked"
    assert drill.status_code == 200
    assert drill.json()["drill_status"] == "passed"
    assert drill.json()["does_not_grant_capital_authority"] is True
    assert runs.status_code == 200
    assert len(runs.json()) == 2
    assert drills.status_code == 200
    assert len(drills.json()) == 1
    assert "private-route-runbook-account-id" not in json.dumps(
        [startup.json(), end_of_day.json(), drill.json(), runs.json(), drills.json()]
    )


def test_runbook_routes_reject_credentials_and_invalid_scenarios(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak-runbook-routes.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_calendar(db, now)
    client = _client(monkeypatch, db, _connector(now))

    credential = client.post(
        "/api/automation/broker-soak/drills",
        json={
            "drill_type": "duplicate_evidence",
            "broker_password": "must-not-be-accepted",
        },
    )
    invalid = client.post(
        "/api/automation/broker-soak/drills",
        json={"drill_type": "submit_order"},
    )

    assert credential.status_code == 422
    assert invalid.status_code == 422
    assert db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE) == []


def test_create_app_registers_broker_soak_runbook_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/broker-soak/runs" in paths
    assert "/api/automation/broker-soak/drills" in paths
