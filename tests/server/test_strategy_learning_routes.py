from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.routes.strategy_learning import create_router
from tests.route_assertions import registered_app_routes


class FakeLearningService:
    def __init__(self) -> None:
        self.limits: list[int] = []

    def build(self, *, limit: int = 100) -> dict:
        self.limits.append(limit)
        return {
            "schema_version": "karkinos.strategy_learning_review.v1",
            "status": "not_configured",
            "items": [],
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
            "financial_recalculation_performed": False,
            "ai_invoked": False,
            "memory_created": False,
            "strategy_changed": False,
            "authorizes_execution": False,
            "capital_authority_changed": False,
        }


def test_strategy_learning_queue_route_is_read_only(monkeypatch) -> None:
    fake = FakeLearningService()
    monkeypatch.setattr(
        "server.routes.strategy_learning.build_strategy_learning_review_service",
        lambda state: fake,
    )
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    response = client.get("/api/strategy-learning/review-queue?limit=37")

    assert response.status_code == 200
    assert fake.limits == [37]
    assert response.json()["provider_contacted"] is False
    assert response.json()["database_writes_performed"] is False
    assert response.json()["ai_invoked"] is False
    assert response.json()["authorizes_execution"] is False
    assert all(
        route.methods == {"GET"}
        for route in registered_app_routes(app)
        if route.path.startswith("/api/strategy-learning")
    )


def test_create_app_registers_strategy_learning_route() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/strategy-learning/review-queue" in paths
