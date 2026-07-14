from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.memory_informed_analysis import (
    MemoryInformedAnalysisRejected,
)
from server.app import create_app
from server.routes.ai_memory_informed_analyses import create_router
from tests.route_assertions import registered_app_routes


class FixtureValue:
    def __init__(self, payload, *, status="completed"):
        self.payload = payload
        self.workflow = SimpleNamespace(status=SimpleNamespace(value=status))

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
                "analysis_id": "ai-memory-analysis-fixture",
                "retrieval_id": "ai-memory-retrieval-fixture",
                "workflow_status": "completed",
                "binding_validity": "valid",
                "current_evidence_reads_complete": True,
                "memory_input_is_current_fact": False,
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

    def get(self, analysis_id):
        return self._result("get", analysis_id)

    def replay(self, analysis_id):
        return self._result("replay", analysis_id)


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
        "server.routes.ai_memory_informed_analyses."
        "build_human_memory_informed_analysis_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "memory-informed-route-001",
        "requested_by": "human:reese",
        "research_question": "Which old assumptions still require review?",
        "confirmation": (
            "run_offline_memory_informed_fixture_with_current_evidence_"
            "without_trade_authority"
        ),
    }


@pytest.mark.unit
def test_memory_informed_route_requires_explicit_confirmation(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/fixture-analyses",
        json=payload,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_memory_informed_route_is_explicit_offline_and_non_authoritative(
    monkeypatch,
):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/fixture-analyses",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["current_evidence_reads_complete"] is True
    assert response.json()["memory_input_is_current_fact"] is False
    assert response.json()["external_model_invocation_count"] == 0
    assert response.json()["decision_handoff_enabled"] is False
    assert response.json()["authority_effect"] == "none"
    assert initialize_calls == [True]


@pytest.mark.unit
def test_memory_informed_get_routes_do_not_initialize_schema(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    listed = client.get("/api/ai/memory-informed-fixture-analyses?limit=20")
    fetched = client.get(
        "/api/ai/memory-informed-fixture-analyses/ai-memory-analysis-fixture"
    )
    replayed = client.get(
        "/api/ai/memory-informed-fixture-analyses/" "ai-memory-analysis-fixture/replay"
    )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert replayed.status_code == 200
    assert initialize_calls == [False, False, False]


@pytest.mark.unit
def test_memory_informed_route_maps_gate_rejection(monkeypatch):
    client, _ = _client(
        monkeypatch,
        FixtureService(error=MemoryInformedAnalysisRejected("retrieval drifted")),
    )

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/fixture-analyses",
        json=_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "retrieval drifted"


@pytest.mark.unit
def test_main_app_registers_memory_informed_fixture_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert (
        "/api/ai/reviewed-memory-retrievals/{retrieval_id}/fixture-analyses",
        "POST",
    ) in routes
    assert ("/api/ai/memory-informed-fixture-analyses", "GET") in routes
    assert (
        "/api/ai/memory-informed-fixture-analyses/{analysis_id}/replay",
        "GET",
    ) in routes
