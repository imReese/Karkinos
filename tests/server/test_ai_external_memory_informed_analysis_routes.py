from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_memory_informed_analysis import (
    ExternalMemoryAnalysisRejected,
)
from server.ai_runtime.provider_connectivity import ConnectivityConfigurationError
from server.app import create_app
from server.routes.ai_external_memory_informed_analyses import create_router
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
                "analysis_id": "ai-external-memory-fixture",
                "retrieval_id": "ai-memory-retrieval-fixture",
                "workflow_status": "completed",
                "binding_validity": "valid",
                "current_evidence_reads_complete": True,
                "external_model_invocation_count": 3,
                "model_reasoning_mode_preserved": True,
                "reasoning_content_persisted": False,
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
        "server.routes.ai_external_memory_informed_analyses."
        "build_human_external_memory_analysis_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "external-memory-route-001",
        "requested_by": "human:reese",
        "research_question": "历史判断与当前持久化证据是否仍然一致？",
        "confirmation": (
            "send_reviewed_memory_and_current_canonical_evidence_to_configured_"
            "external_model_for_claim_debate_report_without_trade_authority"
        ),
    }


@pytest.mark.unit
def test_external_memory_route_requires_exact_export_confirmation(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload["confirmation"] = "wrong"

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/external-analyses",
        json=payload,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_external_memory_route_is_explicit_reasoning_preserving_and_no_authority(
    monkeypatch,
):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/external-analyses",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["current_evidence_reads_complete"] is True
    assert response.json()["external_model_invocation_count"] == 3
    assert response.json()["model_reasoning_mode_preserved"] is True
    assert response.json()["reasoning_content_persisted"] is False
    assert response.json()["decision_handoff_enabled"] is False
    assert response.json()["authority_effect"] == "none"
    assert initialize_calls == [True]


@pytest.mark.unit
def test_external_memory_get_routes_do_not_initialize_or_load_provider(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    listed = client.get("/api/ai/external-memory-informed-analyses?limit=20")
    fetched = client.get(
        "/api/ai/external-memory-informed-analyses/ai-external-memory-fixture"
    )
    replayed = client.get(
        "/api/ai/external-memory-informed-analyses/" "ai-external-memory-fixture/replay"
    )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert replayed.status_code == 200
    assert listed.json()["explicit_human_start_required"] is True
    assert listed.json()["provider_side_tools_enabled"] is False
    assert initialize_calls == [False, False, False]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ExternalMemoryAnalysisRejected("evidence drifted"), 409),
        (ConnectivityConfigurationError("provider disabled"), 503),
    ],
)
def test_external_memory_route_maps_gate_and_configuration_errors(
    monkeypatch,
    error,
    expected_status,
):
    client, _ = _client(monkeypatch, FixtureService(error=error))

    response = client.post(
        "/api/ai/reviewed-memory-retrievals/"
        "ai-memory-retrieval-fixture/external-analyses",
        json=_payload(),
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == str(error)


@pytest.mark.unit
def test_main_app_registers_external_memory_routes_without_new_app_wiring():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert (
        "/api/ai/reviewed-memory-retrievals/{retrieval_id}/external-analyses",
        "POST",
    ) in routes
    assert ("/api/ai/external-memory-informed-analyses", "GET") in routes
    assert (
        "/api/ai/external-memory-informed-analyses/{analysis_id}/replay",
        "GET",
    ) in routes
