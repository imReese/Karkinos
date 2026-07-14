from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.memory_retrieval import ReviewedMemoryRetrievalRejected
from server.app import create_app
from server.routes.ai_reviewed_memory_retrievals import create_router
from tests.route_assertions import registered_app_routes


class FixtureValue:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class FixtureService:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def _result(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return FixtureValue(
            {
                "retrieval_id": "ai-memory-retrieval-fixture",
                "retrieval_eligible": True,
                "selected_memory_count": 1,
                "automatic_recall_enabled": False,
                "provider_tool_registered": False,
                "memory_is_account_fact": False,
                "decision_handoff_enabled": False,
                "authority_effect": "none",
            }
        )

    def start(self, request):
        return self._result("start", request)

    def list(self, *, limit):
        self.calls.append(("list", limit))
        if self.error is not None:
            raise self.error
        return (self._result("listed"),)

    def get(self, retrieval_id):
        return self._result("get", retrieval_id)

    def replay(self, retrieval_id):
        return self._result("replay", retrieval_id)


def _client(monkeypatch, service):
    initialize_calls = []
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )

    def build(state, *, initialize):
        initialize_calls.append(initialize)
        return service

    monkeypatch.setattr(
        "server.routes.ai_reviewed_memory_retrievals."
        "build_human_reviewed_memory_retrieval_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "reviewed-memory-retrieval-route-001",
        "requested_by": "human:reese",
        "purpose": "Compare reviewed memory with current persisted evidence.",
        "current_context_snapshot_id": "ai-context-current-fixture",
        "review_ids": ["ai-analysis-review-fixture"],
        "confirmation": (
            "retrieve_reviewed_memory_as_non_authoritative_research_input"
        ),
    }


@pytest.mark.unit
def test_retrieval_route_requires_explicit_confirmation(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post("/api/ai/reviewed-memory-retrievals", json=payload)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_retrieval_route_is_explicit_read_only_and_non_authoritative(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/reviewed-memory-retrievals",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["retrieval_eligible"] is True
    assert response.json()["automatic_recall_enabled"] is False
    assert response.json()["provider_tool_registered"] is False
    assert response.json()["memory_is_account_fact"] is False
    assert response.json()["decision_handoff_enabled"] is False
    assert response.json()["authority_effect"] == "none"
    assert initialize_calls == [True]


@pytest.mark.unit
def test_retrieval_get_routes_do_not_initialize_schema(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    listed = client.get("/api/ai/reviewed-memory-retrievals?limit=20")
    fetched = client.get(
        "/api/ai/reviewed-memory-retrievals/ai-memory-retrieval-fixture"
    )
    replayed = client.get(
        "/api/ai/reviewed-memory-retrievals/" "ai-memory-retrieval-fixture/replay"
    )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert replayed.status_code == 200
    assert initialize_calls == [False, False, False]


@pytest.mark.unit
def test_retrieval_route_maps_gate_rejection(monkeypatch):
    client, _ = _client(
        monkeypatch,
        FixtureService(
            error=ReviewedMemoryRetrievalRejected("current evidence drifted")
        ),
    )

    response = client.post(
        "/api/ai/reviewed-memory-retrievals",
        json=_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "current evidence drifted"


@pytest.mark.unit
def test_main_app_registers_reviewed_memory_retrieval_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert ("/api/ai/reviewed-memory-retrievals", "POST") in routes
    assert ("/api/ai/reviewed-memory-retrievals", "GET") in routes
    assert (
        "/api/ai/reviewed-memory-retrievals/{retrieval_id}/replay",
        "GET",
    ) in routes
