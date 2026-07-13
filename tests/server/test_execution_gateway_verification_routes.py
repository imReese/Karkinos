from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.execution_gateway_verification as route_module
from server.app import create_app
from server.routes.execution_gateway_verification import create_router
from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    ExecutionGatewayVerificationRejected,
)
from tests.route_assertions import registered_app_routes


class FakeExecutionGatewayVerificationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "runtime_gateway_available": False,
            "runtime_execution_authority": "disabled",
            "broker_submission_enabled": False,
        }

    def preview(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {
            "verification_fingerprint": "d" * 64,
            "review_status": "ready_to_record",
            "broker_submission_enabled": False,
            "authorizes_execution": False,
        }

    def record(self, **kwargs):
        self.calls.append(("record", kwargs))
        if kwargs["verification_fingerprint"] == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["verification_fingerprint_mismatch"],
                "authorizes_execution": False,
            }
            raise ExecutionGatewayVerificationRejected(
                "stale verification",
                evidence=evidence,
            )
        return {
            "status": "recorded_non_submitting_runtime_verification",
            "verification_id": "e" * 64,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
        }

    def resolve(self, verification_fingerprint: str):
        self.calls.append(("resolve", verification_fingerprint))
        return {
            "status": "clear",
            "verification_fingerprint": verification_fingerprint,
            "runtime_gateway_verified": True,
            "broker_submission_enabled": False,
            "authorizes_execution": False,
        }

    def list_verifications(self, *, limit: int):
        self.calls.append(("list", limit))
        return [{"verification_id": "e" * 64, "authorizes_execution": False}]


def _payload() -> dict:
    return {
        "gateway_id": "qmt-execution-1",
        "evidence_connector_id": "qmt-readonly-1",
        "account_alias": "primary-review",
        "order_id": "OMS-1",
        "order_fingerprint": "a" * 64,
        "order_contract": {
            "symbol": "510300.SH",
            "side": "buy",
            "asset_class": "fund",
            "quantity": "100",
            "order_type": "limit",
            "limit_price": "4",
        },
    }


def _client(monkeypatch):
    service = FakeExecutionGatewayVerificationService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_execution_gateway_verification_routes_cover_full_evidence_flow(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    payload = _payload()

    status = client.get("/api/automation/execution-gateway-verification/status")
    preview = client.post(
        "/api/automation/execution-gateway-verification/preview",
        json=payload,
    )
    record = client.post(
        "/api/automation/execution-gateway-verification/records",
        json={
            **payload,
            "verification_fingerprint": "d" * 64,
            "acknowledgement": EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
        },
    )
    resolve = client.post(
        "/api/automation/execution-gateway-verification/resolve",
        json={"verification_fingerprint": "d" * 64},
    )
    listing = client.get(
        "/api/automation/execution-gateway-verification/records?limit=10"
    )

    assert status.status_code == 200
    assert status.json()["runtime_execution_authority"] == "disabled"
    assert preview.status_code == 200
    assert preview.json()["broker_submission_enabled"] is False
    assert record.status_code == 200
    assert record.json()["authorizes_execution"] is False
    assert resolve.status_code == 200
    assert resolve.json()["runtime_gateway_verified"] is True
    assert resolve.json()["authorizes_execution"] is False
    assert listing.status_code == 200
    assert listing.json()[0]["authorizes_execution"] is False
    assert ("list", 10) in service.calls


def test_execution_gateway_verification_routes_reject_credentials_and_bad_ack(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    payload = _payload()
    credential = client.post(
        "/api/automation/execution-gateway-verification/preview",
        json={**payload, "broker_password": "must-not-be-accepted"},
    )
    nested_credential_payload = _payload()
    nested_credential_payload["order_contract"]["api_token"] = "must-not-leak"
    nested_credential = client.post(
        "/api/automation/execution-gateway-verification/preview",
        json=nested_credential_payload,
    )
    bad_ack = client.post(
        "/api/automation/execution-gateway-verification/records",
        json={
            **payload,
            "verification_fingerprint": "d" * 64,
            "acknowledgement": "submit_now",
        },
    )

    assert credential.status_code == 422
    assert nested_credential.status_code == 422
    assert bad_ack.status_code == 422
    assert not any(call[0] in {"preview", "record"} for call in service.calls)


def test_execution_gateway_verification_route_maps_rejection_to_conflict(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/execution-gateway-verification/records",
        json={
            **_payload(),
            "verification_fingerprint": "0" * 64,
            "acknowledgement": EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "rejected"
    assert response.json()["detail"]["authorizes_execution"] is False


def test_execution_gateway_verification_service_uses_runtime_registry(
    monkeypatch,
) -> None:
    gateway = object()
    fake_state = SimpleNamespace(db=object(), execution_gateways=[gateway])
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._gateways == [gateway]


def test_create_app_registers_execution_gateway_verification_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/execution-gateway-verification/status" in paths
    assert "/api/automation/execution-gateway-verification/preview" in paths
    assert "/api/automation/execution-gateway-verification/records" in paths
    assert "/api/automation/execution-gateway-verification/resolve" in paths
