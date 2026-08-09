from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.routes.service_health import (
    SERVICE_HEALTH_SCHEMA_VERSION,
    create_router,
)
from tests.route_assertions import registered_app_routes


def test_service_health_is_process_liveness_only_and_non_authorizing() -> None:
    app = FastAPI()
    app.include_router(create_router())
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": SERVICE_HEALTH_SCHEMA_VERSION,
        "service": "karkinos",
        "status": "alive",
        "scope": "process_liveness_only",
        "financial_readiness_claimed": False,
        "provider_contacted": False,
        "database_reads_performed": False,
        "database_writes_performed": False,
        "production_ledger_mutated": False,
        "broker_submission_enabled": False,
        "broker_cancellation_enabled": False,
        "capital_authority_changed": False,
        "authorizes_execution": False,
    }
    assert [
        route.methods
        for route in registered_app_routes(app)
        if route.path == "/api/health"
    ] == [{"GET"}]


def test_create_app_registers_service_health_before_static_fallback() -> None:
    app = create_app({"live_auto_start": False})
    paths = [route.path for route in registered_app_routes(app)]

    assert "/api/health" in paths
    assert paths.index("/api/health") < paths.index("")
