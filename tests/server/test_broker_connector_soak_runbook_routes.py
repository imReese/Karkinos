from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_truth.broker_connector import (
    LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerConnectorSourceContract,
    FakeReadOnlyBrokerConnector,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.app import create_app
from server.db import AppDatabase
from server.routes.broker_connector_soak import create_router
from server.services.broker_connector_soak_runbook import (
    BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE,
    BROKER_CONNECTOR_SOAK_RESTART_CHECKPOINT_EVENT_TYPE,
)
from tests.route_assertions import registered_app_routes


class _ContractRequiredReadOnlyConnector(FakeReadOnlyBrokerConnector):
    requires_source_contract = True


def _connector(now: datetime) -> FakeReadOnlyBrokerConnector:
    trading_day = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    return _ContractRequiredReadOnlyConnector(
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
            source_contract=BrokerConnectorSourceContract(
                schema_version=LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
                connector_id="route-runbook-readonly",
                deployment_identity="route-runbook-deployment",
                batch_id="route-runbook-batch-1",
                cursor_previous=0,
                cursor_current=1,
                trading_day=trading_day,
                session_phase="startup",
                heartbeat_at=now.isoformat(),
                cash_complete=True,
                positions_complete=True,
                orders_complete=True,
                fills_complete=True,
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


def test_runbook_routes_accept_sequence_integrity_drill_names(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak-runbook-routes.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_calendar(db, now)
    client = _client(monkeypatch, db, _connector(now))

    responses = [
        client.post(
            "/api/automation/broker-soak/drills",
            json={"drill_type": drill_type},
        )
        for drill_type in ("cursor_gap", "cursor_out_of_order", "partial_batch")
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["drill_status"] == "failed" for response in responses)
    assert all(
        response.json()["broker_submission_enabled"] is False
        and response.json()["does_not_grant_capital_authority"] is True
        for response in responses
    )
    assert (
        len(db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE)) == 3
    )


def test_runbook_routes_require_two_process_instances_for_karkinos_restart(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak-runbook-routes.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_calendar(db, now)
    client = _client(monkeypatch, db, _connector(now))
    monkeypatch.setattr(
        "server.services.broker_connector_soak_runbook._PROCESS_INSTANCE_ID",
        "route-process-before-restart",
    )

    prepared = client.post("/api/automation/broker-soak/restart-checkpoints")
    checkpoint_id = prepared.json()["checkpoint_id"]
    same_process = client.post(
        "/api/automation/broker-soak/restart-checkpoints/complete",
        json={"checkpoint_id": checkpoint_id},
    )
    monkeypatch.setattr(
        "server.services.broker_connector_soak_runbook._PROCESS_INSTANCE_ID",
        "route-process-after-restart",
    )
    completed = client.post(
        "/api/automation/broker-soak/restart-checkpoints/complete",
        json={"checkpoint_id": checkpoint_id},
    )
    checkpoints = client.get("/api/automation/broker-soak/restart-checkpoints")

    assert prepared.status_code == 200
    assert prepared.json()["checkpoint_status"] == "prepared"
    assert same_process.status_code == 200
    assert same_process.json()["drill_status"] == "failed"
    assert "process_instance_unchanged" in same_process.json()["blockers"]
    assert completed.status_code == 200
    assert completed.json()["drill_status"] == "passed"
    assert completed.json()["process_instance_changed"] is True
    assert checkpoints.status_code == 200
    assert [item["checkpoint_id"] for item in checkpoints.json()] == [checkpoint_id]
    assert (
        len(
            db.list_events_sync(
                event_type=BROKER_CONNECTOR_SOAK_RESTART_CHECKPOINT_EVENT_TYPE
            )
        )
        == 1
    )
    assert "private-route-runbook-account-id" not in json.dumps(
        [prepared.json(), same_process.json(), completed.json(), checkpoints.json()]
    )


def test_runbook_restart_completion_rejects_unknown_or_extra_secret_input(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak-runbook-routes.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_calendar(db, now)
    client = _client(monkeypatch, db, _connector(now))

    missing = client.post(
        "/api/automation/broker-soak/restart-checkpoints/complete",
        json={"checkpoint_id": "f" * 64},
    )
    credential = client.post(
        "/api/automation/broker-soak/restart-checkpoints/complete",
        json={
            "checkpoint_id": "f" * 64,
            "broker_password": "must-not-be-accepted",
        },
    )

    assert missing.status_code == 404
    assert credential.status_code == 422
    assert db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_DRILL_EVENT_TYPE) == []


def test_create_app_registers_broker_soak_runbook_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/broker-soak/runs" in paths
    assert "/api/automation/broker-soak/drills" in paths
    assert "/api/automation/broker-soak/restart-checkpoints" in paths
    assert "/api/automation/broker-soak/restart-checkpoints/complete" in paths
