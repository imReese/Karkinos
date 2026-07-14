from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.provider_connectivity import (
    CONNECTIVITY_CONFIRMATION,
    ConnectivityCheckResult,
    ConnectivityConfigurationError,
    ConnectivityStatus,
)
from server.ai_runtime.store import IdempotencyConflict
from server.app import create_app
from server.routes.ai_provider_connectivity import create_router
from tests.route_assertions import registered_app_routes


def _result(status: ConnectivityStatus = ConnectivityStatus.PASSED):
    return ConnectivityCheckResult(
        check_id="ai-connectivity-fixture",
        idempotency_key="connectivity-route-001",
        requested_by="human:reese",
        provider_id="fixture-provider",
        model_id="fixture-provider:fixture-model",
        model_name="fixture-model",
        adapter_kind="openai_compatible_https",
        endpoint_origin="https://ai.example.test",
        status=status,
        request_fingerprint="request-fingerprint",
        request_payload_fingerprint=(
            "payload-fingerprint" if status == ConnectivityStatus.PASSED else None
        ),
        response_fingerprint=(
            "response-fingerprint" if status == ConnectivityStatus.PASSED else None
        ),
        response_model="fixture-model" if status == ConnectivityStatus.PASSED else None,
        usage={"total_tokens": 8} if status == ConnectivityStatus.PASSED else {},
        http_status=200 if status == ConnectivityStatus.PASSED else 401,
        error_code=(
            None
            if status == ConnectivityStatus.PASSED
            else "provider_authentication_failed"
        ),
        credential_source="test-only",
        started_at="2026-07-14T04:00:00.000+00:00",
        finished_at="2026-07-14T04:00:00.010+00:00",
        latency_ms=10,
    )


class FixtureService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result or _result()
        self.error = error
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _payload() -> dict:
    return {
        "idempotency_key": "connectivity-route-001",
        "requested_by": "human:reese",
        "confirmation": CONNECTIVITY_CONFIRMATION,
    }


def _client(monkeypatch, service: FixtureService) -> TestClient:
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )
    monkeypatch.setattr(
        "server.routes.ai_provider_connectivity.build_provider_connectivity_service",
        lambda state: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


@pytest.mark.unit
def test_connectivity_route_requires_exact_human_confirmation(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post("/api/ai/provider-connectivity/checks", json=payload)

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
def test_connectivity_route_returns_only_redacted_non_authoritative_result(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)

    response = client.post("/api/ai/provider-connectivity/checks", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "passed"
    assert body["probe_verified"] is True
    assert body["financial_context_sent"] is False
    assert body["tool_calls_allowed"] is False
    assert body["authority_effect"] == "none"
    assert body["broker_action_count"] == 0
    assert "api_key" not in body
    assert len(service.requests) == 1


@pytest.mark.unit
def test_connectivity_route_surfaces_audited_provider_failure(monkeypatch):
    failed = replace(_result(), status=ConnectivityStatus.FAILED)
    service = FixtureService(result=failed)
    client = _client(monkeypatch, service)

    response = client.post("/api/ai/provider-connectivity/checks", json=_payload())

    assert response.status_code == 502
    assert response.json()["status"] == "failed"
    assert response.json()["probe_verified"] is False


@pytest.mark.unit
def test_connectivity_route_reports_inflight_duplicate_as_accepted(monkeypatch):
    running = replace(_result(), status=ConnectivityStatus.RUNNING)
    client = _client(monkeypatch, FixtureService(result=running))

    response = client.post("/api/ai/provider-connectivity/checks", json=_payload())

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert response.json()["probe_verified"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (IdempotencyConflict("conflict"), 409),
        (ConnectivityConfigurationError("not configured"), 503),
        (ValueError("invalid"), 422),
    ],
)
def test_connectivity_route_maps_fail_closed_errors(
    monkeypatch,
    error,
    status_code,
):
    client = _client(monkeypatch, FixtureService(error=error))

    response = client.post("/api/ai/provider-connectivity/checks", json=_payload())

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


@pytest.mark.unit
def test_main_app_registers_only_explicit_connectivity_post_route():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }

    assert ("/api/ai/provider-connectivity/checks", "POST") in routes
    assert ("/api/ai/provider-connectivity/checks", "GET") not in routes
