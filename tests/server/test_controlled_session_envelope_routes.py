from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_envelope as route_module
from server.app import create_app
from server.routes.controlled_session_envelope import create_router
from server.services.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    ControlledSessionAttestationRejected,
)
from tests.route_assertions import registered_app_routes

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


class FakeControlledSessionEnvelopeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "proposal_only_non_executing",
            "runtime_session_authority": "separate_signed_service_required",
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
        "execution_gateway_verification_fingerprints": {
            "OMS-1": "7" * 64,
            "OMS-2": "8" * 64,
        },
        "session_start_account_truth_fingerprint": "5" * 64,
        "per_symbol_runtime_limits": {
            "159915.SZ": "6000",
            "510300.SH": "6000",
        },
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
    assert status.json()["runtime_session_authority"] == (
        "separate_signed_service_required"
    )
    assert preview.status_code == 200
    assert preview.json()["runtime_session_status"] == "not_issued"
    assert attestation.status_code == 200
    assert attestation.json()["status"] == "recorded_verified_identity"
    assert attestation.json()["operator_identity_verified"] is True
    assert attestation.json()["authorizes_execution"] is False
    assert listing.status_code == 200
    assert listing.json()[0]["runtime_session_status"] == "not_issued"
    assert service.calls[1][1]["per_symbol_runtime_limits"] == {
        "159915.SZ": 6000,
        "510300.SH": 6000,
    }
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
    missing_gateway_verifications_payload = _preview_payload()
    missing_gateway_verifications_payload.pop(
        "execution_gateway_verification_fingerprints"
    )
    missing_gateway_verifications = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=missing_gateway_verifications_payload,
    )
    invalid_gateway_verifications_payload = _preview_payload()
    invalid_gateway_verifications_payload[
        "execution_gateway_verification_fingerprints"
    ]["OMS-1"] = "not-a-fingerprint"
    invalid_gateway_verifications = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=invalid_gateway_verifications_payload,
    )
    missing_account_truth_payload = _preview_payload()
    missing_account_truth_payload.pop("session_start_account_truth_fingerprint")
    missing_account_truth = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=missing_account_truth_payload,
    )
    missing_symbol_limits_payload = _preview_payload()
    missing_symbol_limits_payload.pop("per_symbol_runtime_limits")
    missing_symbol_limits = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json=missing_symbol_limits_payload,
    )
    overprecise_symbol_limits = client.post(
        "/api/automation/controlled-sessions/envelopes/preview",
        json={
            **_preview_payload(),
            "per_symbol_runtime_limits": {"510300.SH": "0.00001"},
        },
    )

    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert missing_batch.status_code == 422
    assert missing_approval.status_code == 422
    assert missing_gateway_verifications.status_code == 422
    assert invalid_gateway_verifications.status_code == 422
    assert missing_account_truth.status_code == 422
    assert missing_symbol_limits.status_code == 422
    assert overprecise_symbol_limits.status_code == 422
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
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/controlled-sessions/status" in paths
    assert "/api/automation/controlled-sessions/envelopes/preview" in paths
    assert "/api/automation/controlled-sessions/attestations" in paths


def test_controlled_session_route_service_wires_current_runtime_sources(
    monkeypatch,
) -> None:
    connector = object()
    gateway = object()
    fake_state = SimpleNamespace(
        db=object(),
        config=SimpleNamespace(
            broker_connectors=[object()],
            trusted_operator_identities=[object()],
        ),
        trading_controls=object(),
        execution_gateways=[gateway],
    )
    captured: dict[str, object] = {}

    class FakeGatewayVerificationService:
        def __init__(self, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def resolve(self, fingerprint: str) -> dict:
            captured["fingerprint"] = fingerprint
            return {"status": "blocked", "verification_fingerprint": fingerprint}

    class FakeSessionStartAccountTruthService:
        def __init__(self, **kwargs) -> None:
            captured["account_truth_kwargs"] = kwargs

        def resolve(self, fingerprint: str) -> dict:
            captured["account_truth_fingerprint"] = fingerprint
            return {
                "status": "blocked",
                "account_truth_fingerprint": fingerprint,
            }

    def fake_account_truth_source(state, *, max_age_seconds: int):
        captured["account_truth_state"] = state
        captured["account_truth_max_age_seconds"] = max_age_seconds
        return {"status": "blocked"}

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        route_module,
        "build_broker_connectors",
        lambda config: [connector],
    )
    monkeypatch.setattr(
        route_module,
        "ExecutionGatewayVerificationService",
        FakeGatewayVerificationService,
    )
    monkeypatch.setattr(
        route_module,
        "SessionStartAccountTruthService",
        FakeSessionStartAccountTruthService,
    )
    monkeypatch.setattr(
        route_module,
        "build_latest_account_truth_promotion_evidence",
        fake_account_truth_source,
    )

    service = route_module._service()
    resolution = service._execution_gateway_verification_provider("7" * 64)
    account_truth_resolution = service._session_start_account_truth_provider("5" * 64)
    account_truth_source = captured["account_truth_kwargs"]["account_truth_provider"]()

    assert captured["kwargs"] == {
        "db": fake_state.db,
        "gateways": fake_state.execution_gateways,
    }
    assert captured["fingerprint"] == "7" * 64
    assert resolution == {
        "status": "blocked",
        "verification_fingerprint": "7" * 64,
    }
    assert captured["account_truth_kwargs"]["db"] is fake_state.db
    assert captured["account_truth_fingerprint"] == "5" * 64
    assert account_truth_resolution == {
        "status": "blocked",
        "account_truth_fingerprint": "5" * 64,
    }
    assert account_truth_source == {"status": "blocked"}
    assert captured["account_truth_state"] is fake_state
    assert captured["account_truth_max_age_seconds"] == 120
