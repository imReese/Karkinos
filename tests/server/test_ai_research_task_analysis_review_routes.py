from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.analysis_reviews import AnalysisReviewRejected
from server.app import create_app
from server.routes.ai_research_task_analysis_reviews import create_router
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
                "review_id": "ai-analysis-review-fixture",
                "analysis_id": "ai-task-analysis-fixture",
                "decision": "accept_as_reviewed_memory",
                "effective_status": "reviewed_memory",
                "memory_recall_eligible": True,
                "research_output_is_account_fact": False,
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
        "server.routes.ai_research_task_analysis_reviews."
        "build_human_analysis_review_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _payload():
    return {
        "idempotency_key": "analysis-review-route-001",
        "reviewed_by": "human:reese",
        "decision": "accept_as_reviewed_memory",
        "note": "Reviewed exact persisted evidence and limitations.",
        "confirmation": (
            "record_fixture_analysis_review_without_decision_or_execution_authority"
        ),
    }


@pytest.mark.unit
def test_analysis_review_route_requires_explicit_confirmation(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post(
        "/api/ai/research-task-analyses/ai-task-analysis-fixture/reviews",
        json=payload,
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_analysis_review_route_is_human_only_and_non_authoritative(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/research-task-analyses/ai-task-analysis-fixture/reviews",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["memory_recall_eligible"] is True
    assert response.json()["research_output_is_account_fact"] is False
    assert response.json()["decision_handoff_enabled"] is False
    assert response.json()["authority_effect"] == "none"
    assert initialize_calls == [True]


@pytest.mark.unit
def test_analysis_review_get_routes_do_not_initialize_schema(monkeypatch):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    listed = client.get(
        "/api/ai/research-task-analysis-reviews"
        "?analysis_id=ai-task-analysis-fixture&limit=20"
    )
    fetched = client.get(
        "/api/ai/research-task-analysis-reviews/ai-analysis-review-fixture"
    )
    replayed = client.get(
        "/api/ai/research-task-analysis-reviews/" "ai-analysis-review-fixture/replay"
    )

    assert listed.status_code == 200
    assert fetched.status_code == 200
    assert replayed.status_code == 200
    assert initialize_calls == [False, False, False]


@pytest.mark.unit
def test_analysis_review_route_maps_gate_rejection(monkeypatch):
    client, _ = _client(
        monkeypatch,
        FixtureService(error=AnalysisReviewRejected("analysis evidence drifted")),
    )

    response = client.post(
        "/api/ai/research-task-analyses/ai-task-analysis-fixture/reviews",
        json=_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "analysis evidence drifted"


@pytest.mark.unit
def test_main_app_registers_human_analysis_review_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert (
        "/api/ai/research-task-analyses/{analysis_id}/reviews",
        "POST",
    ) in routes
    assert ("/api/ai/research-task-analysis-reviews", "GET") in routes
    assert (
        "/api/ai/research-task-analysis-reviews/{review_id}/replay",
        "GET",
    ) in routes
