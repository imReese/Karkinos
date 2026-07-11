from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.session_start_account_truth as route_module
from server.app import create_app
from server.routes.session_start_account_truth import create_router
from server.services.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    SessionStartAccountTruthRejected,
)


class FakeSessionStartAccountTruthService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "short_lived_non_authorizing_account_truth",
            "runtime_session_authority": "disabled",
            "broker_submission_enabled": False,
        }

    def preview(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {
            "review_status": "ready_to_record",
            "account_truth_fingerprint": "a" * 64,
            "authorizes_execution": False,
        }

    def record(self, **kwargs):
        self.calls.append(("record", kwargs))
        if kwargs["account_truth_fingerprint"] == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["account_truth_fingerprint_mismatch"],
                "authorizes_execution": False,
            }
            raise SessionStartAccountTruthRejected(
                "stale Account Truth",
                evidence=evidence,
            )
        return {
            "status": "recorded_clear",
            "account_truth_fingerprint": kwargs["account_truth_fingerprint"],
            "runtime_session_authority": "disabled",
            "authorizes_execution": False,
        }

    def resolve(self, fingerprint: str):
        self.calls.append(("resolve", fingerprint))
        return {
            "status": "clear",
            "account_truth_fingerprint": fingerprint,
            "runtime_session_authority": "disabled",
            "authorizes_execution": False,
        }

    def list_records(self, *, limit: int):
        self.calls.append(("list", limit))
        return [{"status": "recorded_clear", "authorizes_execution": False}]


def _client(monkeypatch) -> tuple[TestClient, FakeSessionStartAccountTruthService]:
    service = FakeSessionStartAccountTruthService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def _preview_payload() -> dict:
    return {
        "evidence_connector_id": "qmt-readonly-session",
        "account_alias": "qmt-session-review",
    }


def test_session_start_account_truth_routes_full_non_authorizing_flow(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    status = client.get("/api/automation/session-start-account-truth/status")
    preview = client.post(
        "/api/automation/session-start-account-truth/preview",
        json=_preview_payload(),
    )
    record = client.post(
        "/api/automation/session-start-account-truth/records",
        json={
            **_preview_payload(),
            "account_truth_fingerprint": "a" * 64,
            "acknowledgement": SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
        },
    )
    resolve = client.post(
        "/api/automation/session-start-account-truth/resolve",
        json={"account_truth_fingerprint": "a" * 64},
    )
    listing = client.get("/api/automation/session-start-account-truth/records?limit=10")

    assert status.status_code == 200
    assert status.json()["runtime_session_authority"] == "disabled"
    assert preview.status_code == 200
    assert preview.json()["authorizes_execution"] is False
    assert record.status_code == 200
    assert record.json()["status"] == "recorded_clear"
    assert resolve.status_code == 200
    assert resolve.json()["runtime_session_authority"] == "disabled"
    assert listing.status_code == 200
    assert ("list", 10) in service.calls


def test_session_start_account_truth_route_maps_audited_rejection(monkeypatch) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/session-start-account-truth/records",
        json={
            **_preview_payload(),
            "account_truth_fingerprint": "0" * 64,
            "acknowledgement": SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "rejected"
    assert response.json()["detail"]["authorizes_execution"] is False


def test_session_start_account_truth_routes_reject_credentials_and_bad_input(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    credential = client.post(
        "/api/automation/session-start-account-truth/records",
        json={
            **_preview_payload(),
            "account_truth_fingerprint": "a" * 64,
            "acknowledgement": SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
            "broker_password": "must-not-be-accepted",
        },
    )
    bad_ack = client.post(
        "/api/automation/session-start-account-truth/records",
        json={
            **_preview_payload(),
            "account_truth_fingerprint": "a" * 64,
            "acknowledgement": "issue_session_now",
        },
    )
    bad_fingerprint = client.post(
        "/api/automation/session-start-account-truth/resolve",
        json={"account_truth_fingerprint": "invalid"},
    )
    nested_credentials = client.post(
        "/api/automation/session-start-account-truth/preview",
        json={**_preview_payload(), "credentials": {"token": "must-not-leak"}},
    )

    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert bad_fingerprint.status_code == 422
    assert nested_credentials.status_code == 422
    assert not any(call[0] == "record" for call in service.calls)


def test_session_start_account_truth_route_service_wires_current_source(
    monkeypatch,
) -> None:
    fake_state = SimpleNamespace(db=object())
    captured: dict[str, object] = {}

    def fake_provider(state, *, max_age_seconds: int):
        captured["state"] = state
        captured["max_age_seconds"] = max_age_seconds
        return {"status": "blocked"}

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        route_module,
        "build_latest_account_truth_promotion_evidence",
        fake_provider,
    )

    service = route_module._service()
    source = service._account_truth_provider()

    assert source == {"status": "blocked"}
    assert captured["state"] is fake_state
    assert captured["max_age_seconds"] == 120


def test_create_app_registers_session_start_account_truth_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/session-start-account-truth/status" in paths
    assert "/api/automation/session-start-account-truth/preview" in paths
    assert "/api/automation/session-start-account-truth/records" in paths
    assert "/api/automation/session-start-account-truth/resolve" in paths
