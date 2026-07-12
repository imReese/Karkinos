from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_runtime_authority as route_module
from server.app import create_app
from server.routes.controlled_session_runtime_authority import create_router


class FakeRuntimeAuthorityService:
    def get_status(self):
        return {
            "contract_status": "signed_runtime_session_authority_ready_non_broker",
            "session_resume_endpoint_exposed": False,
            "broker_submission_enabled": False,
        }

    def preview_issuance(self, *, reservation_id: str):
        return {
            "reservation_id": reservation_id,
            "issuance_fingerprint": "b" * 64,
            "ready": True,
        }

    def issue(self, **kwargs):
        return {
            "session_id": "c" * 64,
            "session_token": "token-shown-once",
            "session_token_issued": True,
            "broker_submission_enabled": False,
            **kwargs,
        }

    def list_sessions(self, *, limit: int):
        return [{"session_id": "c" * 64, "limit": limit, "session_token": ""}]

    def resolve_current(self, session_id: str):
        return {"session_id": session_id, "status": "current_enabled_bounded_session"}

    def preview_replacement(
        self,
        *,
        predecessor_session_id: str,
        reservation_id: str,
    ):
        return {
            "predecessor_session_id": predecessor_session_id,
            "replacement_reservation_id": reservation_id,
            "replacement_fingerprint": "9" * 64,
            "ready": True,
            "broker_submission_enabled": False,
        }

    def replace_paused(self, **kwargs):
        return {
            "status": "enabled",
            "session_id": "8" * 64,
            "session_token": "replacement-token-shown-once",
            "session_token_issued": True,
            "broker_submission_enabled": False,
            **kwargs,
        }

    def list_replacements(self, *, limit: int):
        return [{"status": "replaced", "limit": limit, "session_token": ""}]

    def preview_revocation(self, *, session_id: str, reason_code: str):
        return {
            "session_id": session_id,
            "reason_code": reason_code,
            "revocation_fingerprint": "d" * 64,
        }

    def revoke(self, **kwargs):
        return {"status": "revoked", **kwargs}

    def list_revocations(self, *, limit: int):
        return [{"status": "revoked", "limit": limit}]


def _client(monkeypatch):
    service = FakeRuntimeAuthorityService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_runtime_authority_routes_require_exact_models_and_expose_no_resume(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)
    prefix = "/api/automation/controlled-sessions/runtime-authority"
    reservation_id = "a" * 64
    session_id = "c" * 64

    assert client.get(f"{prefix}/status").status_code == 200
    assert (
        client.post(
            f"{prefix}/issuance/preview",
            json={"reservation_id": reservation_id},
        ).status_code
        == 200
    )
    issued = client.post(
        f"{prefix}/sessions",
        json={
            "reservation_id": reservation_id,
            "issuance_fingerprint": "b" * 64,
            "operator_approval_id": "e" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "issue_exact_expiring_non_broker_controlled_session",
        },
    )
    assert issued.status_code == 200
    assert issued.json()["session_token_issued"] is True
    assert issued.json()["broker_submission_enabled"] is False
    assert client.get(f"{prefix}/sessions?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/sessions/{session_id}").status_code == 200

    replacement_preview = client.post(
        f"{prefix}/sessions/{session_id}/replacement/preview",
        json={"reservation_id": "7" * 64},
    )
    assert replacement_preview.status_code == 200
    replaced = client.post(
        f"{prefix}/sessions/{session_id}/replacements",
        json={
            "reservation_id": "7" * 64,
            "replacement_fingerprint": "9" * 64,
            "operator_approval_id": "6" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "replace_paused_session_with_equal_or_narrower_fresh_authority"
            ),
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["session_token_issued"] is True
    assert replaced.json()["broker_submission_enabled"] is False
    assert client.get(f"{prefix}/replacements?limit=5").json()[0]["limit"] == 5

    preview = client.post(
        f"{prefix}/sessions/{session_id}/revocation/preview",
        json={"reason_code": "manual_operator_stop"},
    )
    assert preview.status_code == 200
    revoked = client.post(
        f"{prefix}/sessions/{session_id}/revocations",
        json={
            "reason_code": "manual_operator_stop",
            "revocation_fingerprint": "d" * 64,
            "operator_approval_id": "f" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "revoke_exact_controlled_session_no_auto_resume",
        },
    )
    assert revoked.status_code == 200
    assert client.get(f"{prefix}/revocations?limit=9").json()[0]["limit"] == 9
    assert (
        client.post(f"{prefix}/sessions/{session_id}/resume", json={}).status_code
        == 404
    )
    assert (
        client.post(f"{prefix}/sessions/{session_id}/renew", json={}).status_code == 404
    )

    rejected_secret = client.post(
        f"{prefix}/sessions",
        json={
            "reservation_id": reservation_id,
            "issuance_fingerprint": "b" * 64,
            "operator_approval_id": "e" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "issue_exact_expiring_non_broker_controlled_session",
            "broker_password": "must-not-be-accepted",
        },
    )
    assert rejected_secret.status_code == 422
    rejected_replacement_secret = client.post(
        f"{prefix}/sessions/{session_id}/replacements",
        json={
            "reservation_id": "7" * 64,
            "replacement_fingerprint": "9" * 64,
            "operator_approval_id": "6" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "replace_paused_session_with_equal_or_narrower_fresh_authority"
            ),
            "broker_password": "must-not-be-accepted",
        },
    )
    assert rejected_replacement_secret.status_code == 422


def test_route_service_wires_exact_evidence_providers_without_gateway(
    monkeypatch,
) -> None:
    fake_state = SimpleNamespace(
        db=object(),
        config=SimpleNamespace(trusted_operator_identities=[]),
    )
    fake_budget = SimpleNamespace(resolve=lambda value: {"reservation_id": value})
    fake_envelope = SimpleNamespace(
        resolve_attestation=lambda value: {"attestation_id": value}
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.controlled_session_budget_reservation._service",
        lambda: fake_budget,
    )
    monkeypatch.setattr(
        "server.routes.controlled_session_envelope._service",
        lambda: fake_envelope,
    )

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._reservation_provider == fake_budget.resolve
    assert service._attestation_provider == fake_envelope.resolve_attestation
    assert service.get_status()["broker_submission_enabled"] is False


def test_create_app_registers_runtime_authority_without_resume_or_broker_routes() -> (
    None
):
    app = create_app({"live_auto_start": False})
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        if route.path.startswith(
            "/api/automation/controlled-sessions/runtime-authority"
        ):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path == {
        "/api/automation/controlled-sessions/runtime-authority/status": {"GET"},
        "/api/automation/controlled-sessions/runtime-authority/issuance/preview": {
            "POST"
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions": {
            "GET",
            "POST",
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions/{session_id}": {
            "GET"
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/replacement/preview": {
            "POST"
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/replacements": {
            "POST"
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/revocation/preview": {
            "POST"
        },
        "/api/automation/controlled-sessions/runtime-authority/sessions/{session_id}/revocations": {
            "POST"
        },
        "/api/automation/controlled-sessions/runtime-authority/revocations": {"GET"},
        "/api/automation/controlled-sessions/runtime-authority/replacements": {"GET"},
    }
