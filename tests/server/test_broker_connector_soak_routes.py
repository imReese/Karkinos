from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from account_truth.broker_connector import (
    LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.app import create_app
from server.config import BrokerConnectorConfig
from server.db import AppDatabase
from server.routes.broker_connector_soak import create_router
from server.services.broker_connector_soak import BROKER_CONNECTOR_SOAK_EVENT_TYPE
from server.services.broker_connector_soak_promotion import (
    BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    BrokerConnectorSoakPromotionRejected,
)
from tests.route_assertions import registered_app_routes


class FakeBrokerConnectorSoakPromotionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "promotion_ready": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
        }

    def preview_dossier(self, connector_id: str):
        self.calls.append(("preview", connector_id))
        return {
            "connector_id": connector_id,
            "dossier_fingerprint": "d" * 64,
            "review_status": "ready_for_signed_owner_acceptance",
            "promotion_ready": False,
            "broker_submission_enabled": False,
        }

    def record_acceptance(self, **kwargs):
        self.calls.append(("accept", kwargs))
        if kwargs["dossier_fingerprint"] == "0" * 64:
            raise BrokerConnectorSoakPromotionRejected(
                "stale promotion dossier",
                evidence={
                    "status": "rejected",
                    "rejection_reasons": ["dossier_fingerprint_mismatch"],
                    "authorizes_execution": False,
                },
            )
        return {
            "status": "recorded_verified_owner_acceptance",
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
        }

    def list_acceptances(self, *, connector_id: str, limit: int):
        self.calls.append(("list", (connector_id, limit)))
        return [
            {
                "connector_id": connector_id,
                "status": "recorded_verified_owner_acceptance",
                "authorizes_execution": False,
            }
        ]


def _client_for_db(monkeypatch, db: AppDatabase, connector: object) -> TestClient:
    fake_state = SimpleNamespace(
        db=db,
        config=SimpleNamespace(broker_connectors=[connector]),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _connector() -> FakeReadOnlyBrokerConnector:
    now = datetime.now(timezone.utc)
    return FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="route-readonly",
            source_name="route readonly fixture",
            account_id="private-route-account-id",
            account_alias="route-primary",
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


def _seed_today_calendar(db: AppDatabase, now: datetime) -> None:
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


def test_broker_soak_capture_status_and_list_are_readonly(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    now = datetime.now(timezone.utc)
    _seed_today_calendar(db, now)
    client = _client_for_db(monkeypatch, db, _connector())

    capture = client.post("/api/automation/broker-soak/capture", json={})
    status = client.get("/api/automation/broker-soak/status")
    listing = client.get("/api/automation/broker-soak/observations")

    assert capture.status_code == 200
    assert capture.json()["observations"][0]["soak_status"] == "healthy"
    assert capture.json()["broker_submission_enabled"] is False
    assert status.status_code == 200
    assert status.json()["promotion_ready"] is False
    assert status.json()["broker_submission_enabled"] is False
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert "private-route-account-id" not in json.dumps(listing.json())


def test_broker_soak_capture_supports_sanitized_local_broker_export(
    tmp_path,
    monkeypatch,
) -> None:
    connector_type = "local_export_readonly"
    now = datetime.now(timezone.utc)
    snapshot_path = tmp_path / f"{connector_type}.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "schema_version": LOCAL_JSON_SNAPSHOT_SCHEMA_VERSION,
                "captured_at": now.isoformat(),
                "source_name": f"{connector_type} local export",
                "account_id": "private-local-export-account",
                "health": {
                    "status": "healthy",
                    "checked_at": now.isoformat(),
                },
                "cash": {
                    "currency": "CNY",
                    "balance": "100000",
                    "available": "90000",
                },
                "positions": [],
                "orders": [],
                "fills": [],
            }
        ),
        encoding="utf-8",
    )
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    _seed_today_calendar(db, now)
    config = BrokerConnectorConfig(
        connector_id=f"{connector_type}-soak",
        connector_type=connector_type,
        enabled=True,
        client_path=str(snapshot_path),
        account_alias="sanitized-local-account",
    )
    client = _client_for_db(monkeypatch, db, config)

    response = client.post("/api/automation/broker-soak/capture", json={})

    assert response.status_code == 200
    observation = response.json()["observations"][0]
    assert observation["soak_status"] == "healthy"
    assert observation["connector_id"] == f"{connector_type}-soak"
    assert observation["account_alias"] == "sanitized-local-account"
    assert "private-local-export-account" not in json.dumps(observation)
    assert observation["broker_submission_enabled"] is False


def test_broker_soak_capture_rejects_undeclared_credential_fields(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "broker-soak.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db, _connector())

    response = client.post(
        "/api/automation/broker-soak/capture",
        json={"broker_password": "must-not-be-accepted"},
    )

    assert response.status_code == 422
    assert db.list_events_sync(event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE) == []


def test_broker_soak_promotion_routes_preview_accept_list_and_status(
    monkeypatch,
) -> None:
    service = FakeBrokerConnectorSoakPromotionService()
    monkeypatch.setattr(
        "server.routes.broker_connector_soak._promotion_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    status = client.get("/api/automation/broker-soak/promotion/status")
    preview = client.post(
        "/api/automation/broker-soak/promotion/dossiers/preview",
        json={"connector_id": "fixture-readonly-promotion"},
    )
    acceptance = client.post(
        "/api/automation/broker-soak/promotion/acceptances",
        json={
            "connector_id": "fixture-readonly-promotion",
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "a" * 64,
            "acknowledgement": BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
        },
    )
    listing = client.get(
        "/api/automation/broker-soak/promotion/acceptances"
        "?connector_id=fixture-readonly-promotion&limit=10"
    )

    assert status.status_code == 200
    assert status.json()["runtime_execution_authority"] == "disabled"
    assert preview.status_code == 200
    assert preview.json()["promotion_ready"] is False
    assert acceptance.status_code == 200
    assert acceptance.json()["status"] == "recorded_verified_owner_acceptance"
    assert acceptance.json()["operator_identity_verified"] is True
    assert acceptance.json()["authorizes_execution"] is False
    assert listing.status_code == 200
    assert listing.json()[0]["authorizes_execution"] is False
    assert ("list", ("fixture-readonly-promotion", 10)) in service.calls


def test_broker_soak_promotion_routes_fail_closed_on_stale_or_credential_input(
    monkeypatch,
) -> None:
    service = FakeBrokerConnectorSoakPromotionService()
    monkeypatch.setattr(
        "server.routes.broker_connector_soak._promotion_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)
    base = {
        "connector_id": "fixture-readonly-promotion",
        "dossier_fingerprint": "d" * 64,
        "operator_label": "local-owner",
        "operator_approval_id": "a" * 64,
        "acknowledgement": BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    }

    credential = client.post(
        "/api/automation/broker-soak/promotion/acceptances",
        json={**base, "broker_password": "must-not-be-accepted"},
    )
    missing_approval = client.post(
        "/api/automation/broker-soak/promotion/acceptances",
        json={
            key: value for key, value in base.items() if key != "operator_approval_id"
        },
    )
    bad_ack = client.post(
        "/api/automation/broker-soak/promotion/acceptances",
        json={**base, "acknowledgement": "enable_broker_now"},
    )
    stale = client.post(
        "/api/automation/broker-soak/promotion/acceptances",
        json={**base, "dossier_fingerprint": "0" * 64},
    )

    assert credential.status_code == 422
    assert missing_approval.status_code == 422
    assert bad_ack.status_code == 422
    assert stale.status_code == 409
    assert stale.json()["detail"]["rejection_reasons"] == [
        "dossier_fingerprint_mismatch"
    ]


def test_create_app_registers_broker_soak_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/broker-soak/status" in paths
    assert "/api/automation/broker-soak/observations" in paths
    assert "/api/automation/broker-soak/capture" in paths
    assert "/api/automation/broker-soak/promotion/status" in paths
    assert "/api/automation/broker-soak/promotion/dossiers/preview" in paths
    assert "/api/automation/broker-soak/promotion/acceptances" in paths
