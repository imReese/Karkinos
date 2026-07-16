from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_broker_submission as route_module
from server.app import create_app
from server.routes.controlled_broker_submission import create_router
from tests.route_assertions import registered_app_routes


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

    def preview_recovery(self, **kwargs):
        return {
            **kwargs,
            "review_status": "ready_for_final_signature",
            "review_ready": True,
            "recovery_fingerprint": "6" * 64,
            "provider_contact_performed": False,
            "broker_query_performed": False,
        }

    def list_intents(self, *, limit: int):
        return [{"submit_intent_id": "1" * 64, "limit": limit}]

    def get_intent(self, submit_intent_id: str):
        return {"submit_intent_id": submit_intent_id, "status": "submitted"}


class FakeControlledSubmissionClearanceService:
    def get_status(self):
        return {
            "contract_status": "signed_terminal_outcome_clearance_available",
            "partial_fill_terminal_cancel_clearance_enabled": True,
            "open_partial_fill_clearance_enabled": False,
        }

    def preview(self, **kwargs):
        return {
            **kwargs,
            "clearance_fingerprint": "4" * 64,
            "review_ready": True,
            "production_ledger_mutated": False,
        }

    def record(self, **kwargs):
        return {
            **kwargs,
            "status": "cleared",
            "interlock_released": True,
            "production_ledger_mutated": False,
        }

    def list_clearances(self, *, limit: int):
        return [{"clearance_id": "5" * 64, "limit": limit}]

    def get_clearance(self, clearance_id: str):
        return {"clearance_id": clearance_id, "status": "cleared"}


class FakeManualBrokerCancellationEvidenceService:
    def preview(self, **kwargs):
        return {
            **kwargs,
            "status": "ready_for_manual_broker_action",
            "ticket_fingerprint": "8" * 64,
            "ready": True,
            "safety": {
                "provider_contact_performed": False,
                "broker_cancel_performed": False,
                "oms_mutated": False,
            },
        }

    def export(self, **kwargs):
        return {
            **kwargs,
            "status": "export_ready",
            "content": "{}",
            "safety": {
                "provider_contact_performed": False,
                "broker_cancel_performed": False,
                "oms_mutated": False,
            },
        }


def _client(monkeypatch):
    service = FakeControlledBrokerSubmissionService()
    clearance_service = FakeControlledSubmissionClearanceService()
    cancellation_service = FakeManualBrokerCancellationEvidenceService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    monkeypatch.setattr(route_module, "_clearance_service", lambda: clearance_service)
    monkeypatch.setattr(
        route_module,
        "_manual_cancellation_service",
        lambda: cancellation_service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service, clearance_service, cancellation_service


def test_routes_require_strict_final_signature_and_expose_query_recovery(
    monkeypatch,
) -> None:
    client, _, _, _ = _client(monkeypatch)
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
    recovery_preview = client.post(f"{prefix}/intents/{intent_id}/recovery/preview")
    assert recovery_preview.status_code == 200
    assert recovery_preview.json()["provider_contact_performed"] is False
    recovered = client.post(
        f"{prefix}/intents/{intent_id}/recoveries",
        json={
            "recovery_fingerprint": "6" * 64,
            "operator_approval_id": "7" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": ("query_exact_unknown_submission_once_without_resubmit"),
        },
    )
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


def test_clearance_routes_require_separate_signature_and_forbid_credentials(
    monkeypatch,
) -> None:
    client, _, _, _ = _client(monkeypatch)
    prefix = "/api/automation/controlled-broker-submission"
    intent_id = "1" * 64
    run_id = "reconciliation-run-1"

    status = client.get(f"{prefix}/reconciliation-clearance/status")
    assert status.status_code == 200
    assert status.json()["partial_fill_terminal_cancel_clearance_enabled"] is True
    assert status.json()["open_partial_fill_clearance_enabled"] is False
    preview = client.post(
        f"{prefix}/intents/{intent_id}/reconciliation-clearance/preview",
        json={"reconciliation_run_id": run_id},
    )
    assert preview.status_code == 200
    assert preview.json()["production_ledger_mutated"] is False
    cleared = client.post(
        f"{prefix}/intents/{intent_id}/reconciliation-clearances",
        json={
            "reconciliation_run_id": run_id,
            "clearance_fingerprint": "4" * 64,
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "clear_exact_terminal_outcome_without_automatic_ledger_mutation"
            ),
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["interlock_released"] is True
    assert cleared.json()["production_ledger_mutated"] is False
    assert (
        client.get(f"{prefix}/reconciliation-clearances?limit=9").json()[0]["limit"]
        == 9
    )
    clearance_id = "5" * 64
    assert (
        client.get(f"{prefix}/reconciliation-clearances/{clearance_id}").status_code
        == 200
    )

    missing_signature = client.post(
        f"{prefix}/intents/{intent_id}/reconciliation-clearances",
        json={
            "reconciliation_run_id": run_id,
            "clearance_fingerprint": "4" * 64,
            "operator_approval_id": "3" * 64,
            "acknowledgement": (
                "clear_exact_terminal_outcome_without_automatic_ledger_mutation"
            ),
        },
    )
    assert missing_signature.status_code == 422
    credential = client.post(
        f"{prefix}/intents/{intent_id}/reconciliation-clearances",
        json={
            "reconciliation_run_id": run_id,
            "clearance_fingerprint": "4" * 64,
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "clear_exact_terminal_outcome_without_automatic_ledger_mutation"
            ),
            "broker_password": "must-not-be-accepted",
        },
    )
    assert credential.status_code == 422


def test_manual_cancellation_ticket_routes_never_expose_broker_cancel(
    monkeypatch,
) -> None:
    client, _, _, _ = _client(monkeypatch)
    prefix = "/api/automation/controlled-broker-submission"
    intent_id = "1" * 64

    preview = client.post(
        f"{prefix}/intents/{intent_id}/manual-cancellation-ticket/preview"
    )
    assert preview.status_code == 200
    assert preview.json()["safety"] == {
        "provider_contact_performed": False,
        "broker_cancel_performed": False,
        "oms_mutated": False,
    }
    exported = client.post(
        f"{prefix}/intents/{intent_id}/manual-cancellation-ticket/export",
        json={
            "ticket_fingerprint": "8" * 64,
            "acknowledgement": (
                "prepare_manual_broker_cancellation_ticket_without_broker_contact"
            ),
        },
    )
    assert exported.status_code == 200
    assert exported.json()["status"] == "export_ready"
    assert exported.json()["safety"]["broker_cancel_performed"] is False
    missing_acknowledgement = client.post(
        f"{prefix}/intents/{intent_id}/manual-cancellation-ticket/export",
        json={"ticket_fingerprint": "8" * 64},
    )
    assert missing_acknowledgement.status_code == 422
    unknown_field = client.post(
        f"{prefix}/intents/{intent_id}/manual-cancellation-ticket/export",
        json={
            "ticket_fingerprint": "8" * 64,
            "acknowledgement": (
                "prepare_manual_broker_cancellation_ticket_without_broker_contact"
            ),
            "broker_password": "must-not-be-accepted",
        },
    )
    assert unknown_field.status_code == 422


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
    for route in registered_app_routes(app):
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
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/recovery/preview": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/recoveries": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents": {"GET"},
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}": {
            "GET"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/manual-cancellation-ticket/preview": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/manual-cancellation-ticket/export": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/reconciliation-clearance/status": {
            "GET"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/reconciliation-clearance/preview": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/intents/{submit_intent_id}/reconciliation-clearances": {
            "POST"
        },
        "/api/automation/controlled-broker-submission/reconciliation-clearances": {
            "GET"
        },
        "/api/automation/controlled-broker-submission/reconciliation-clearances/{clearance_id}": {
            "GET"
        },
    }
    assert all("strategy" not in path for path in methods_by_path)
