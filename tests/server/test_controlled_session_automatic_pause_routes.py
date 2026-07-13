from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_automatic_pause as route_module
from server.app import create_app
from server.routes.controlled_session_automatic_pause import create_router
from tests.route_assertions import registered_app_routes


class FakeAutomaticPauseService:
    def get_status(self):
        return {
            "automatic_pause_enabled": True,
            "public_pause_endpoint_exposed": False,
            "public_resume_endpoint_exposed": False,
        }

    def list_pause_events(self, *, limit: int):
        return [{"pause_event_id": "a" * 64, "limit": limit}]

    def get_state(self, session_id: str):
        return {"session_id": session_id, "status": "paused"}


class FakeLiveGateService:
    def list_snapshots(self, *, limit: int):
        return [{"snapshot_id": "b" * 64, "limit": limit}]

    def latest(self, session_id: str):
        return {"session_id": session_id, "resolution_status": "current"}


class FakeOrchestratorService:
    def evaluate_authenticated(self, *, session_id: str, session_token: str):
        return {
            "session_id": session_id,
            "status": "clear_no_pause",
            "session_token_echoed": False,
        }


def test_automatic_pause_routes_require_token_for_evaluation(monkeypatch) -> None:
    service = FakeAutomaticPauseService()
    live_gates = FakeLiveGateService()
    orchestrator = FakeOrchestratorService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    monkeypatch.setattr(route_module, "_live_gate_service", lambda: live_gates)
    monkeypatch.setattr(route_module, "_orchestrator_service", lambda: orchestrator)
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)
    prefix = "/api/automation/controlled-sessions/automatic-pause"

    assert client.get(f"{prefix}/status").status_code == 200
    assert client.get(f"{prefix}/events?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/states/session-a").json()["status"] == "paused"
    assert client.get(f"{prefix}/gate-snapshots?limit=5").json()[0]["limit"] == 5
    assert (
        client.get(f"{prefix}/gate-snapshots/{'a' * 64}").json()["resolution_status"]
        == "current"
    )
    evaluated = client.post(
        f"{prefix}/evaluations",
        json={
            "session_id": "a" * 64,
            "session_token": "route-live-gate-token-0000000000000000000001",
        },
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["session_token_echoed"] is False
    assert (
        client.post(
            f"{prefix}/evaluations",
            json={"session_id": "a" * 64},
        ).status_code
        == 422
    )
    assert client.post(f"{prefix}/events", json={}).status_code == 405
    assert client.post(f"{prefix}/states/session-a/resume", json={}).status_code == 404


def test_route_service_wires_persisted_session_and_live_gate_providers(
    monkeypatch,
) -> None:
    fake_state = SimpleNamespace(db=object(), trading_controls=object())
    fake_authority = SimpleNamespace(
        resolve_for_monitoring=lambda session_id: {"session_id": session_id}
    )
    fake_budget = SimpleNamespace(resolve=lambda value: {"reservation_id": value})
    fake_envelope = SimpleNamespace(
        resolve_attestation=lambda value: {"attestation_id": value}
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.controlled_session_runtime_authority._service",
        lambda: fake_authority,
    )
    monkeypatch.setattr(
        "server.routes.controlled_session_budget_reservation._service",
        lambda: fake_budget,
    )
    monkeypatch.setattr(
        "server.routes.controlled_session_envelope._service",
        lambda: fake_envelope,
    )

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._session_provider == fake_authority.resolve_for_monitoring
    assert callable(service._gate_provider)
    assert service.get_status()["automatic_pause_enabled"] is True


def test_create_app_registers_pause_visibility_and_authenticated_evaluation() -> None:
    app = create_app({"live_auto_start": False})
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in registered_app_routes(app)
        if route.path.startswith("/api/automation/controlled-sessions/automatic-pause")
    }

    assert methods_by_path == {
        "/api/automation/controlled-sessions/automatic-pause/status": {"GET"},
        "/api/automation/controlled-sessions/automatic-pause/events": {"GET"},
        "/api/automation/controlled-sessions/automatic-pause/states/{session_id}": {
            "GET"
        },
        "/api/automation/controlled-sessions/automatic-pause/evaluations": {"POST"},
        "/api/automation/controlled-sessions/automatic-pause/gate-snapshots": {"GET"},
        "/api/automation/controlled-sessions/automatic-pause/gate-snapshots/{session_id}": {
            "GET"
        },
    }
