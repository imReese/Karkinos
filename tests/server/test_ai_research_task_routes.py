from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.tasks import ResearchTaskRejected
from server.app import create_app
from server.routes.ai_research_tasks import create_router
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
                "task_id": "ai-research-task-fixture",
                "model_execution_enabled": False,
                "workflow_started": False,
                "authority_effect": "none",
            }
        )

    def create(self, request):
        return self._result("create", request)

    def list(self, *, limit):
        self.calls.append(("list", limit))
        if self.error is not None:
            raise self.error
        return (self._result("listed-task"),)

    def get(self, task_id):
        return self._result("get", task_id)

    def review(self, task_id, request):
        return self._result("review", task_id, request)

    def replay(self, task_id):
        return self._result("replay", task_id)


def _client(monkeypatch, service):
    monkeypatch.setattr(
        "server.app.get_app_state", lambda: SimpleNamespace(db=object())
    )
    monkeypatch.setattr(
        "server.routes.ai_research_tasks.build_human_research_task_service",
        lambda state, *, initialize: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _task_payload():
    return {
        "idempotency_key": "route-research-task-001",
        "capture_id": "ai-capture-fixture",
        "created_by": "human:reese",
        "title": "Review frozen account evidence",
        "research_question": "Which claims are supported?",
        "confirmation": "record_human_research_task_without_model_execution",
    }


@pytest.mark.unit
def test_task_route_requires_explicit_model_free_confirmation(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _task_payload()
    payload.pop("confirmation")

    response = client.post("/api/ai/research-tasks", json=payload)

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.unit
def test_task_and_review_routes_never_start_model_or_authority(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)

    created = client.post("/api/ai/research-tasks", json=_task_payload())
    reviewed = client.post(
        "/api/ai/research-tasks/ai-research-task-fixture/reviews",
        json={
            "idempotency_key": "route-research-review-001",
            "reviewed_by": "human:reese",
            "decision": "context_accepted",
            "note": "Human accepted the frozen evidence context only.",
            "confirmation": "record_human_research_review_without_model_execution",
        },
    )

    for response in (created, reviewed):
        assert response.status_code == 200
        assert response.json()["model_execution_enabled"] is False
        assert response.json()["workflow_started"] is False
        assert response.json()["authority_effect"] == "none"


@pytest.mark.unit
def test_task_route_maps_fail_closed_domain_error(monkeypatch):
    client = _client(
        monkeypatch,
        FixtureService(error=ResearchTaskRejected("evidence is not complete")),
    )

    response = client.post("/api/ai/research-tasks", json=_task_payload())

    assert response.status_code == 409
    assert response.json()["detail"] == "evidence is not complete"


@pytest.mark.unit
def test_main_app_registers_human_research_task_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }
    assert ("/api/ai/research-tasks", "POST") in routes
    assert ("/api/ai/research-tasks", "GET") in routes
    assert ("/api/ai/research-tasks/{task_id}/reviews", "POST") in routes
    assert ("/api/ai/research-tasks/{task_id}/replay", "GET") in routes
