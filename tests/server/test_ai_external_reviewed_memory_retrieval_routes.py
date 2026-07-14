from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_reviewed_memory_retrieval import (
    ExternalReviewedMemoryRetrievalRejected,
)
from server.app import create_app
from server.routes.ai_external_reviewed_memory_retrievals import create_router
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
                "retrieval_id": "ai-external-memory-retrieval-fixture",
                "retrieval_eligible": True,
                "automatic_recall_enabled": False,
                "legacy_retrieval_v1_modified": False,
                "external_model_consumption_enabled": False,
                "external_model_invocation_count": 0,
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
        "server.routes.ai_external_reviewed_memory_retrievals."
        "build_human_external_reviewed_memory_retrieval_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "external-reviewed-memory-retrieval-route-001",
        "requested_by": "human:reese",
        "purpose": "Rebind an exact reviewed precedent to current evidence.",
        "current_context_snapshot_id": "ai-context-current",
        "promotion_ids": ["ai-external-memory-promotion-fixture"],
        "confirmation": (
            "retrieve_promoted_external_reviewed_memory_with_current_canonical_"
            "evidence_as_non_authoritative_research_input"
        ),
    }


@pytest.mark.unit
def test_external_reviewed_memory_retrieval_requires_exact_confirmation(
    monkeypatch,
):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload["confirmation"] = "wrong"

    response = client.post(
        "/api/ai/external-reviewed-memory-retrievals",
        json=payload,
    )
    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_external_reviewed_memory_retrieval_is_explicit_local_and_read_lazy(
    monkeypatch,
):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    started = client.post(
        "/api/ai/external-reviewed-memory-retrievals",
        json=_payload(),
    )
    listed = client.get(
        "/api/ai/external-reviewed-memory-retrievals",
        params={"limit": 10},
    )
    fetched = client.get("/api/ai/external-reviewed-memory-retrievals/ai-retrieval")
    replayed = client.get(
        "/api/ai/external-reviewed-memory-retrievals/ai-retrieval/replay"
    )

    assert started.status_code == 200
    assert started.json()["retrieval_eligible"] is True
    assert started.json()["automatic_recall_enabled"] is False
    assert started.json()["legacy_retrieval_v1_modified"] is False
    assert started.json()["external_model_consumption_enabled"] is False
    assert listed.status_code == fetched.status_code == replayed.status_code == 200
    assert listed.json()["automatic_recall_enabled"] is False
    assert listed.json()["network_io_used"] is False
    assert listed.json()["external_model_invocation_count"] == 0
    assert listed.json()["authority_effect"] == "none"
    assert initialize_calls == [True, False, False, False]


@pytest.mark.unit
def test_external_reviewed_memory_retrieval_maps_domain_errors(monkeypatch):
    service = FixtureService(
        error=ExternalReviewedMemoryRetrievalRejected("current evidence is partial")
    )
    client, _ = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/external-reviewed-memory-retrievals",
        json=_payload(),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "current evidence is partial"


@pytest.mark.unit
def test_main_app_registers_external_reviewed_memory_retrieval_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }

    assert ("/api/ai/external-reviewed-memory-retrievals", "POST") in routes
    assert ("/api/ai/external-reviewed-memory-retrievals", "GET") in routes
    assert (
        "/api/ai/external-reviewed-memory-retrievals/{retrieval_id}",
        "GET",
    ) in routes
    assert (
        "/api/ai/external-reviewed-memory-retrievals/{retrieval_id}/replay",
        "GET",
    ) in routes
