from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_broker_submission as route_module
from server.app import create_app
from server.routes.controlled_broker_submission import create_router


class FakeControlledBrokerSubmissionService:
    def get_status(self):
        return {
            "contract_status": "disabled_waiting_for_explicit_write_gateway",
            "default_broker_submission_enabled": False,
        }

    def preview(self, **kwargs):
        return {
            **kwargs,
            "submit_intent_id": "1" * 64,
            "submit_fingerprint": "2" * 64,
            "ready": True,
            "submitted_to_broker": False,
        }

    def submit(self, **kwargs):
        return {
            **kwargs,
            "submit_intent_id": "1" * 64,
            "status": "submitted",
            "submitted_to_broker": True,
            "production_ledger_mutated": False,
        }

    def recover(self, **kwargs):
        return {
            **kwargs,
            "status": "submission_unknown",
            "recovery_resubmission_enabled": False,
        }

    def list_intents(self, *, limit: int):
        return [{"submit_intent_id": "1" * 64, "limit": limit}]

    def get_intent(self, submit_intent_id: str):
        return {"submit_intent_id": submit_intent_id, "status": "submitted"}


def _client(monkeypatch):
    service = FakeControlledBrokerSubmissionService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_routes_require_strict_final_signature_and_expose_query_recovery(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)
    prefix = "/api/automation/controlled-broker-submission"
    order_id = "OMS-1"
    confirmation_id = "c" * 64
    release_id = "f" * 64
    intent_id = "1" * 64

    status = client.get(f"{prefix}/status")
    assert status.status_code == 200
    assert status.json()["default_broker_submission_enabled"] is False
    preview = client.post(
        f"{prefix}/orders/{order_id}/submission/preview",
        json={
            "confirmation_id": confirmation_id,
            "release_evidence_id": release_id,
        },
    )
    assert preview.status_code == 200
    submitted = client.post(
        f"{prefix}/orders/{order_id}/submissions",
        json={
            "confirmation_id": confirmation_id,
            "release_evidence_id": release_id,
            "submit_fingerprint": "2" * 64,
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "submit_one_exact_manually_confirmed_order_once",
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["submitted_to_broker"] is True
    assert submitted.json()["production_ledger_mutated"] is False
    recovered = client.post(f"{prefix}/intents/{intent_id}/recover")
    assert recovered.status_code == 200
    assert recovered.json()["recovery_resubmission_enabled"] is False
    assert client.get(f"{prefix}/intents?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/intents/{intent_id}").status_code == 200

    missing_signature = client.post(
        f"{prefix}/orders/{order_id}/submissions",
        json={
            "confirmation_id": confirmation_id,
            "release_evidence_id": release_id,
            "submit_fingerprint": "2" * 64,
            "operator_approval_id": "3" * 64,
            "acknowledgement": "submit_one_exact_manually_confirmed_order_once",
        },
    )
    assert missing_signature.status_code == 422
    credential = client.post(
        f"{prefix}/orders/{order_id}/submissions",
        json={
            "confirmation_id": confirmation_id,
            "release_evidence_id": release_id,
            "submit_fingerprint": "2" * 64,
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "submit_one_exact_manually_confirmed_order_once",
            "broker_password": "must-not-be-accepted",
        },
    )
    assert credential.status_code == 422


def test_route_service_is_default_closed_without_injected_release_provider(
    monkeypatch,
) -> None:
    gateway = object()
    per_order = SimpleNamespace(resolve_confirmation=lambda value: {})
    state = SimpleNamespace(
        db=object(),
        config=SimpleNamespace(trusted_operator_identities=[]),
        execution_gateways=[gateway],
        trading_controls=object(),
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    monkeypatch.setattr(
        "server.routes.per_order_confirmation._service",
        lambda: per_order,
    )

    service = route_module._service()

    assert service._db is state.db
    assert service._gateways == [gateway]
    assert service._confirmation_provider == per_order.resolve_confirmation
    assert service._release_evidence_provider is None
    assert service.get_status()["default_broker_submission_enabled"] is False
    assert service.get_status()["contract_status"].startswith("disabled_waiting")


def test_create_app_registers_controlled_submission_without_strategy_endpoint() -> None:
    app = create_app({"live_auto_start": False})
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        if route.path.startswith("/api/automation/controlled-broker-submission"):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path == {
        "/api/automation/controlled-broker-submission/status": {"GET"},
        "/api/automation/controlled-broker-submission/orders/{order_id}/submission/preview": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/orders/{order_id}/submissions": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/recover": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents": {"GET"},
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}": {
            "GET"
        },
    }
    assert all("strategy" not in path for path in methods_by_path)
