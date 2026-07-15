from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_promoted_analysis_memory_retrieval import (
    ExternalPromotedAnalysisMemoryRetrievalRejected,
)
from server.routes.ai_external_promoted_analysis_memory_retrievals import (
    create_router,
)


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
                "retrieval_id": "ai-external-promoted-analysis-retrieval-fixture",
                "retrieval_eligible": True,
                "automatic_recall_enabled": False,
                "phase_1_8_retrieval_modified": False,
                "phase_1_13_retrieval_modified": False,
                "external_model_consumption_enabled": False,
                "network_io_used": False,
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
        "server.routes.ai_external_promoted_analysis_memory_retrievals."
        "build_human_external_promoted_analysis_memory_retrieval_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "external-promoted-analysis-retrieval-route-001",
        "requested_by": "human:reese",
        "purpose": "Rebind reviewed historical research to current evidence.",
        "current_context_snapshot_id": "ai-context-fixture",
        "promotion_ids": ["ai-external-promoted-analysis-memory-fixture"],
        "confirmation": (
            "retrieve_promoted_external_analysis_memory_with_current_canonical_"
            "evidence_as_non_authoritative_research_input"
        ),
    }


@pytest.mark.unit
def test_route_requires_exact_human_confirmation(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)
    payload = _payload()
    payload["confirmation"] = "wrong"

    response = client.post(
        "/api/ai/external-promoted-analysis-memory-retrievals",
        json=payload,
    )

    assert response.status_code == 422
    assert service.calls == []
    assert initialize_calls == []


@pytest.mark.unit
def test_routes_are_explicit_read_only_and_initialize_only_on_post(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    started = client.post(
        "/api/ai/external-promoted-analysis-memory-retrievals",
        json=_payload(),
    )
    listed = client.get(
        "/api/ai/external-promoted-analysis-memory-retrievals",
        params={"limit": 10},
    )
    fetched = client.get(
        "/api/ai/external-promoted-analysis-memory-retrievals/retrieval"
    )
    replayed = client.get(
        "/api/ai/external-promoted-analysis-memory-retrievals/retrieval/replay"
    )

    assert started.status_code == 200
    assert listed.status_code == fetched.status_code == replayed.status_code == 200
    assert started.json()["retrieval_eligible"] is True
    assert started.json()["automatic_recall_enabled"] is False
    assert started.json()["phase_1_8_retrieval_modified"] is False
    assert started.json()["phase_1_13_retrieval_modified"] is False
    assert started.json()["external_model_consumption_enabled"] is False
    assert started.json()["network_io_used"] is False
    assert started.json()["external_model_invocation_count"] == 0
    assert started.json()["decision_handoff_enabled"] is False
    assert started.json()["authority_effect"] == "none"
    assert listed.json()["explicit_human_start_required"] is True
    assert listed.json()["automatic_recall_enabled"] is False
    assert listed.json()["provider_tool_registered"] is False
    assert listed.json()["network_io_used"] is False
    assert initialize_calls == [True, False, False, False]


@pytest.mark.unit
def test_route_maps_gate_rejection_without_retry(monkeypatch):
    service = FixtureService(
        error=ExternalPromotedAnalysisMemoryRetrievalRejected(
            "current evidence is incomplete"
        )
    )
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/external-promoted-analysis-memory-retrievals",
        json=_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "current evidence is incomplete"
    assert initialize_calls == [True]
    assert len(service.calls) == 1
