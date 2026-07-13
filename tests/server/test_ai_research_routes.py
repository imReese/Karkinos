from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.capture import CaptureSelectionError
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.store import IdempotencyConflict
from server.app import create_app
from server.routes.ai_research import create_router
from tests.route_assertions import registered_app_routes


class FixtureResult:
    def to_dict(self) -> dict:
        return {
            "schema_version": "karkinos.ai.context_capture_result.v1",
            "capture_status": "completed",
            "persisted_facts_only": True,
            "provider_fetch_used": False,
            "model_invocation_count": 0,
            "workflow_started": False,
            "authority_effect": "none",
        }


class FixtureService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests = []

    async def capture(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return FixtureResult()


def _client(monkeypatch, service: FixtureService) -> TestClient:
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )
    monkeypatch.setattr(
        "server.routes.ai_research.build_human_context_capture_service",
        lambda state: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _payload() -> dict:
    return {
        "idempotency_key": "route-capture-001",
        "requested_by": "human:reese",
        "research_question": "Review the exact persisted portfolio facts",
        "account_alias": "primary",
        "evidence_types": ["portfolio", "account_state"],
        "confirmation": "capture_read_only_research_context",
    }


@pytest.mark.unit
def test_capture_route_requires_explicit_confirmation(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post("/api/ai/research-contexts/capture", json=payload)

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
def test_capture_route_starts_only_a_model_free_read_only_capture(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)

    response = client.post("/api/ai/research-contexts/capture", json=_payload())

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "karkinos.ai.context_capture_result.v1",
        "capture_status": "completed",
        "persisted_facts_only": True,
        "provider_fetch_used": False,
        "model_invocation_count": 0,
        "workflow_started": False,
        "authority_effect": "none",
    }
    assert len(service.requests) == 1
    assert service.requests[0].requested_tools == (
        "portfolio_projection.read",
        "account_state_projection.read",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (IdempotencyConflict("conflict"), 409),
        (EvidenceIdentityMismatch("identity drift"), 409),
        (LookupError("persisted row missing"), 404),
        (CaptureSelectionError("selection invalid"), 422),
    ],
)
def test_capture_route_maps_fail_closed_domain_errors(
    monkeypatch,
    error,
    status_code,
):
    client = _client(monkeypatch, FixtureService(error=error))

    response = client.post("/api/ai/research-contexts/capture", json=_payload())

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


@pytest.mark.unit
def test_main_app_registers_explicit_capture_route():
    app = create_app({"live_auto_start": False})

    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert ("/api/ai/research-contexts/capture", "POST") in routes
