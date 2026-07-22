from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.signed_broker_adapter_release_review as route_module
from server.app import create_app
from server.routes.signed_broker_adapter_release_review import create_router
from tests.route_assertions import registered_app_routes


class FakeSignedBrokerAdapterReleaseReviewService:
    def get_status(self):
        return {
            "contract_status": "signed_provider_neutral_adapter_review",
            "recorded_review_count": 0,
            "adapter_registered": False,
        }

    def list_releases(self, *, limit):
        return [{"release_evidence_ref": "fixture-release-v1", "limit": limit}]

    def preview_dossier(self, **kwargs):
        return {
            **kwargs,
            "dossier_fingerprint": "1" * 64,
            "review_ready": True,
            "adapter_registered": False,
        }

    def record_review(self, **kwargs):
        return {
            **kwargs,
            "status": kwargs["decision"],
            "review_fingerprint": "2" * 64,
            "adapter_registered": False,
            "authorizes_execution": False,
        }


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        route_module,
        "_service",
        lambda: FakeSignedBrokerAdapterReleaseReviewService(),
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _request() -> dict:
    return {
        "manifest": {"schema_version": "fixture"},
        "source_name": "reviewed-adapter-release.json",
        "review_id": "signed-review-v1",
        "decision": "accepted",
        "reviewed_at": "2026-07-18T03:00:00+00:00",
        "reason_ref": "owner-reviewed-provider-boundary-v1",
    }


def test_routes_are_strict_signed_and_non_authorizing(monkeypatch) -> None:
    client = _client(monkeypatch)
    prefix = "/api/automation/broker-adapter-release-review"
    request = _request()

    status = client.get(f"{prefix}/status")
    releases = client.get(f"{prefix}/releases?limit=7")
    preview = client.post(f"{prefix}/dossiers/preview", json=request)
    recorded = client.post(
        f"{prefix}/reviews",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "review_broker_adapter_release_without_registration_or_execution_authority"
            ),
        },
    )

    assert status.status_code == 200
    assert status.json()["adapter_registered"] is False
    assert releases.json()[0]["limit"] == 7
    assert preview.status_code == 200
    assert preview.json()["adapter_registered"] is False
    assert recorded.status_code == 200
    assert recorded.json()["authorizes_execution"] is False

    missing_proof = client.post(
        f"{prefix}/reviews",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "3" * 64,
            "acknowledgement": (
                "review_broker_adapter_release_without_registration_or_execution_authority"
            ),
        },
    )
    credentials = client.post(
        f"{prefix}/reviews",
        json={
            **request,
            "dossier_fingerprint": "1" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "3" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": (
                "review_broker_adapter_release_without_registration_or_execution_authority"
            ),
            "broker_password": "must-not-be-accepted",
        },
    )
    assert missing_proof.status_code == 422
    assert credentials.status_code == 422


def test_create_app_registers_only_operator_review_routes() -> None:
    prefix = "/api/automation/broker-adapter-release-review"
    routes: dict[str, set[str]] = {}
    for route in registered_app_routes(create_app()):
        if route.path.startswith(prefix):
            routes.setdefault(route.path, set()).update(route.methods or set())

    assert routes == {
        f"{prefix}/status": {"GET"},
        f"{prefix}/releases": {"GET"},
        f"{prefix}/dossiers/preview": {"POST"},
        f"{prefix}/reviews": {"POST"},
    }
    assert all("submit" not in path and "cancel" not in path for path in routes)
