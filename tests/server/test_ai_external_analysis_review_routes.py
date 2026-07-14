from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisReviewRejected,
)
from server.app import create_app
from server.routes.ai_external_analysis_reviews import create_router
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
                "review_id": "ai-external-review-fixture",
                "analysis_id": "ai-external-memory-fixture",
                "effective_status": "reviewed_research",
                "reviewed_research_eligible": True,
                "quality_evidence": {"status": "complete"},
                "cost_evidence": {"status": "unpriced"},
                "review_external_model_invocation_count": 0,
                "memory_recall_eligible": False,
                "provider_promotion_eligible": False,
                "decision_handoff_enabled": False,
                "authority_effect": "none",
            }
        )

    def review(self, analysis_id, request):
        return self._result("review", analysis_id, request)

    def list(self, *, analysis_id, limit):
        self.calls.append(("list", analysis_id, limit))
        if self.error is not None:
            raise self.error
        return (self._result("listed"),)

    def get(self, review_id):
        return self._result("get", review_id)

    def replay(self, review_id):
        return self._result("replay", review_id)


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
        "server.routes.ai_external_analysis_reviews."
        "build_human_external_analysis_review_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "external-analysis-review-route-001",
        "reviewed_by": "human:reese",
        "decision": "accept_as_reviewed_research",
        "note": "逐项复核证据、反方观点、局限和成本状态。",
        "quality_rubric": {
            "evidence_grounding": 5,
            "contradiction_handling": 4,
            "uncertainty_calibration": 4,
            "decision_usefulness": 4,
        },
        "factual_error_count": 0,
        "unsupported_claim_count": 0,
        "pricing_snapshot": None,
        "pricing_unavailable_reason": "provider pricing not yet reviewed",
        "confirmation": (
            "record_external_analysis_review_without_memory_decision_or_trade_"
            "authority"
        ),
    }


@pytest.mark.unit
def test_external_analysis_review_route_requires_exact_confirmation(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload["confirmation"] = "wrong"

    response = client.post(
        "/api/ai/external-memory-informed-analyses/"
        "ai-external-memory-fixture/reviews",
        json=payload,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_external_analysis_review_route_records_no_authority_disposition(
    monkeypatch,
):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/external-memory-informed-analyses/"
        "ai-external-memory-fixture/reviews",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["reviewed_research_eligible"] is True
    assert response.json()["review_external_model_invocation_count"] == 0
    assert response.json()["memory_recall_eligible"] is False
    assert response.json()["provider_promotion_eligible"] is False
    assert response.json()["decision_handoff_enabled"] is False
    assert response.json()["authority_effect"] == "none"
    assert initialize_calls == [True]


@pytest.mark.unit
def test_external_analysis_review_get_routes_are_read_only(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    listed = client.get(
        "/api/ai/external-analysis-reviews"
        "?analysis_id=ai-external-memory-fixture&limit=20"
    )
    fetched = client.get("/api/ai/external-analysis-reviews/ai-external-review-fixture")
    replayed = client.get(
        "/api/ai/external-analysis-reviews/" "ai-external-review-fixture/replay"
    )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert replayed.status_code == 200
    assert listed.json()["human_review_only"] is True
    assert listed.json()["review_external_model_invocation_count"] == 0
    assert listed.json()["memory_recall_eligible"] is False
    assert initialize_calls == [False, False, False]


@pytest.mark.unit
def test_external_analysis_review_route_maps_gate_rejection(monkeypatch):
    client, _ = _client(
        monkeypatch,
        FixtureService(error=ExternalAnalysisReviewRejected("analysis replay invalid")),
    )

    response = client.post(
        "/api/ai/external-memory-informed-analyses/"
        "ai-external-memory-fixture/reviews",
        json=_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "analysis replay invalid"


@pytest.mark.unit
def test_main_app_registers_external_analysis_review_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert (
        "/api/ai/external-memory-informed-analyses/{analysis_id}/reviews",
        "POST",
    ) in routes
    assert ("/api/ai/external-analysis-reviews", "GET") in routes
    assert (
        "/api/ai/external-analysis-reviews/{review_id}/replay",
        "GET",
    ) in routes
