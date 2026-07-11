from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.routes.controlled_session_envelope import create_router
from server.services.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    ControlledSessionAttestationRejected,
)

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


class FakeControlledSessionEnvelopeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "proposal_only_non_executing",
            "runtime_session_authority": "disabled",
            "broker_submission_enabled": False,
        }

    def preview_envelope(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {
            "envelope_fingerprint": "e" * 64,
            "review_status": "review_ready_non_executing",
            "runtime_session_status": "not_issued",
            "submission_status": "blocked",
            "authorizes_execution": False,
        }

    def record_attestation(self, **kwargs):
        self.calls.append(("attest", kwargs))
        if kwargs["envelope_fingerprint"] == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["envelope_fingerprint_mismatch"],
                "runtime_session_status": "not_issued",
                "authorizes_execution": False,
            }
            raise ControlledSessionAttestationRejected(
                "stale envelope",
                evidence=evidence,
            )
        return {
            "status": "recorded_verified_identity",
            "runtime_session_status": "not_issued",
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
        }

    def list_attestations(self, *, limit: int):
        self.calls.append(("list", limit))
        return [
            {
                "status": "recorded_verified_identity",
                "runtime_session_status": "not_issued",
                "authorizes_execution": False,
            }
        ]


def _client(monkeypatch) -> tuple[TestClient, FakeControlledSessionEnvelopeService]:
    service = FakeControlledSessionEnvelopeService()
    monkeypatch.setattr(
        "server.routes.controlled_session_envelope._service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def _preview_payload() -> dict:
    return {
        "capital_evaluation_input_fingerprint": "a" * 64,
        "prior_batch_reconciliation_fingerprint": "b" * 64,
        "order_ids": ["OMS-1", "OMS-2"],
        "requested_start_at": NOW.isoformat(),
        "requested_expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }


def test_controlled_session_routes_status_preview_attest_and_list(monkeypatch) -> None:
    client, service = _client(monkeypatch)

    status = client.get("/api/automation/controlled-sessions/status")
    preview = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=_preview_payload(),
    )
    attestation = client.post(
        "/api/automation/controlled-sessions/attestations",
        json={
            **_preview_payload(),
            "envelope_fingerprint": "e" * 64,
            "operator_label": "local-session-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        },
    )
    listing = client.get("/api/automation/controlled-sessions/attestations?limit=10")

    assert status.status_code == 200
    assert status.json()["runtime_session_authority"] == "disabled"
    assert preview.status_code == 200
    assert preview.json()["runtime_session_status"] == "not_issued"
    assert attestation.status_code == 200
    assert attestation.json()["status"] == "recorded_verified_identity"
    assert attestation.json()["operator_identity_verified"] is True
    assert attestation.json()["authorizes_execution"] is False
    assert listing.status_code == 200
    assert listing.json()[0]["runtime_session_status"] == "not_issued"
    assert ("list", 10) in service.calls


def test_controlled_session_route_maps_rejected_attestation_to_conflict(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/controlled-sessions/attestations",
        json={
            **_preview_payload(),
            "envelope_fingerprint": "0" * 64,
            "operator_label": "local-session-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "rejected"
    assert response.json()["detail"]["runtime_session_status"] == "not_issued"


def test_controlled_session_routes_reject_credentials_and_bad_acknowledgement(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    credential = client.post(
        "/api/automation/controlled-sessions/attestations",
        json={
            **_preview_payload(),
            "envelope_fingerprint": "e" * 64,
            "operator_label": "local-session-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
            "broker_password": "must-not-be-accepted",
        },
    )
    bad_ack = client.post(
        "/api/automation/controlled-sessions/attestations",
        json={
            **_preview_payload(),
            "envelope_fingerprint": "e" * 64,
            "operator_label": "local-session-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": "enable_session_now",
        },
    )
    missing_batch_payload = _preview_payload()
    missing_batch_payload.pop("prior_batch_reconciliation_fingerprint")
    missing_batch = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=missing_batch_payload,
    )
    missing_approval = client.post(
        "/api/automation/controlled-sessions/attestations",
        json={
            **_preview_payload(),
            "envelope_fingerprint": "e" * 64,
            "operator_label": "local-session-owner",
            "acknowledgement": CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        },
    )

    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert missing_batch.status_code == 422
    assert missing_approval.status_code == 422
    assert not any(call[0] == "attest" for call in service.calls)
    assert not any(call[0] == "preview" for call in service.calls)


def test_controlled_session_preview_request_rejects_empty_order_set(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    response = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json={**_preview_payload(), "order_ids": []},
    )

    assert response.status_code == 422
    assert not any(call[0] == "preview" for call in service.calls)


def test_create_app_registers_controlled_session_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/controlled-sessions/status" in paths
    assert "/api/automation/controlled-sessions/envelopes/preview" in paths
    assert "/api/automation/controlled-sessions/attestations" in paths
