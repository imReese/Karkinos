from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_broker_submission as submission_route_module
import server.routes.controlled_broker_write_release as route_module
from server.app import create_app
from server.routes.controlled_broker_write_release import create_router
from tests.route_assertions import registered_app_routes


class FakeControlledBrokerWriteReleaseService:
    def get_status(self):
        return {
            "contract_status": "default_closed_waiting_for_signed_write_release",
            "active_release_count": 0,
            "gateway_registered": False,
        }

    def preview_dossier(self, **kwargs):
        return {
            **kwargs,
            "dossier_fingerprint": "1" * 64,
            "review_ready": True,
            "broker_submission_performed": False,
        }

    def record_release(self, **kwargs):
        return {
            **kwargs,
            "release_evidence_id": "2" * 64,
            "status": "recorded_expiring_manual_each_order_release",
            "adapter_registered": False,
            "broker_submission_performed": False,
        }

    def list_releases(self, *, limit):
        return [{"release_evidence_id": "2" * 64, "limit": limit}]

    def get_release(self, release_evidence_id):
        return {
            "release_evidence_id": release_evidence_id,
            "status": "current_clear_signed_release",
        }

    def preview_revocation(self, **kwargs):
        return {
            **kwargs,
            "revocation_fingerprint": "3" * 64,
            "ready": True,
            "broker_contact_performed": False,
        }

    def revoke_release(self, **kwargs):
        return {
            **kwargs,
            "status": "revoked",
            "resume_enabled": False,
            "broker_contact_performed": False,
        }


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        route_module,
        "_service",
        lambda: FakeControlledBrokerWriteReleaseService(),
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _dossier_request() -> dict:
    return {
        "execution_edge_manifest": {"schema_version": "fixture"},
        "readonly_release_evidence_ref": "fixture-readonly-release",
        "soak_acceptance_id": "4" * 64,
        "effective_at": "2026-07-18T02:15:00+00:00",
        "expires_at": "2026-07-18T10:15:00+00:00",
        "owner_review_refs": {"broker_agreement_review": "review:v1"},
    }


def test_routes_require_exact_signature_and_expose_one_way_revocation(
    monkeypatch,
) -> None:
    client = _client(monkeypatch)
    prefix = "/api/automation/controlled-broker-write-release"
    request = _dossier_request()

    status = client.get(f"{prefix}/status")
    preview = client.post(f"{prefix}/dossiers/preview", json=request)
    recorded = client.post(
        f"{prefix}/releases",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "5" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
            ),
        },
    )
    release_id = "2" * 64
    revocation_preview = client.post(
        f"{prefix}/releases/{release_id}/revocation/preview",
        json={"reason_code": "incident_or_anomaly"},
    )
    revoked = client.post(
        f"{prefix}/releases/{release_id}/revocations",
        json={
            "reason_code": "incident_or_anomaly",
            "revocation_fingerprint": "3" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "6" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "revoke_exact_broker_write_release_without_resume_or_broker_action"
            ),
        },
    )

    assert status.status_code == 200
    assert status.json()["active_release_count"] == 0
    assert preview.status_code == 200
    assert preview.json()["broker_submission_performed"] is False
    assert recorded.status_code == 200
    assert recorded.json()["adapter_registered"] is False
    assert client.get(f"{prefix}/releases?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/releases/{release_id}").status_code == 200
    assert revocation_preview.json()["broker_contact_performed"] is False
    assert revoked.json()["resume_enabled"] is False

    missing_proof = client.post(
        f"{prefix}/releases",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "5" * 64,
            "acknowledgement": (
                "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
            ),
        },
    )
    credentials = client.post(
        f"{prefix}/releases",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "5" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
            ),
            "broker_password": "must-not-be-accepted",
        },
    )
    assert missing_proof.status_code == 422
    assert credentials.status_code == 422


def test_create_app_registers_write_release_without_strategy_or_ai_endpoint() -> None:
    prefix = "/api/automation/controlled-broker-write-release"
    routes: dict[str, set[str]] = {}
    for route in registered_app_routes(create_app()):
        if route.path.startswith(prefix):
            routes.setdefault(route.path, set()).update(route.methods or set())

    assert routes[f"{prefix}/status"] == {"GET"}
    assert routes[f"{prefix}/dossiers/preview"] == {"POST"}
    assert routes[f"{prefix}/releases"] == {"GET", "POST"}
    assert routes[f"{prefix}/releases/{{release_evidence_id}}"] == {"GET"}
    assert routes[f"{prefix}/releases/{{release_evidence_id}}/revocation/preview"] == {
        "POST"
    }
    assert routes[f"{prefix}/releases/{{release_evidence_id}}/revocations"] == {"POST"}
    assert all("strategy" not in path for path in routes if path.startswith(prefix))
    assert all("ai" not in path for path in routes if path.startswith(prefix))


def test_submission_factories_only_consume_a_current_persisted_release_provider(
    monkeypatch,
) -> None:
    class PersistedProvider:
        def __init__(self, active_count: int):
            self.active_count = active_count

        def __call__(self, release_evidence_id: str):
            return {"release_evidence_id": release_evidence_id}

        def get_status(self):
            return {"active_release_count": self.active_count}

    active = PersistedProvider(1)
    inactive = PersistedProvider(0)
    state = type("State", (), {"controlled_broker_release_evidence_provider": None})()
    monkeypatch.setattr(
        route_module,
        "build_controlled_broker_write_release_service",
        lambda _: active,
    )
    assert submission_route_module._release_evidence_provider(state) is active

    monkeypatch.setattr(
        route_module,
        "build_controlled_broker_write_release_service",
        lambda _: inactive,
    )
    assert submission_route_module._release_evidence_provider(state) is None

    def injected(release_id: str):
        return {"release_evidence_id": release_id}

    state.controlled_broker_release_evidence_provider = injected
    assert submission_route_module._release_evidence_provider(state) is injected
