from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_automatic_pause as route_module
from server.app import create_app
from server.routes.controlled_session_automatic_pause import create_router


class FakeAutomaticPauseService:
    def get_status(self):
        return {
            "automatic_pause_enabled": False,
            "public_pause_endpoint_exposed": False,
            "public_resume_endpoint_exposed": False,
        }

    def list_pause_events(self, *, limit: int):
        return [{"pause_event_id": "a" * 64, "limit": limit}]

    def get_state(self, session_id: str):
        return {"session_id": session_id, "status": "paused"}


def test_automatic_pause_routes_are_read_only(monkeypatch) -> None:
    service = FakeAutomaticPauseService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)
    prefix = "/api/automation/controlled-sessions/automatic-pause"

    assert client.get(f"{prefix}/status").status_code == 200
    assert client.get(f"{prefix}/events?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/states/session-a").json()["status"] == "paused"
    assert client.post(f"{prefix}/events", json={}).status_code == 405
    assert client.post(f"{prefix}/states/session-a/resume", json={}).status_code == 404


def test_route_service_wires_session_identity_but_keeps_gate_provider_closed(
    monkeypatch,
) -> None:
    fake_state = SimpleNamespace(db=object())
    fake_authority = SimpleNamespace(
        resolve_current=lambda session_id: {"session_id": session_id}
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.controlled_session_runtime_authority._service",
        lambda: fake_authority,
    )

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._session_provider == fake_authority.resolve_current
    assert service._gate_provider is None
    assert service.get_status()["automatic_pause_enabled"] is False


def test_create_app_registers_only_pause_visibility_routes() -> None:
    app = create_app({"live_auto_start": False})
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in app.routes
        if route.path.startswith("/api/automation/controlled-sessions/automatic-pause")
    }

    assert methods_by_path == {
        "/api/automation/controlled-sessions/automatic-pause/status": {"GET"},
        "/api/automation/controlled-sessions/automatic-pause/events": {"GET"},
        "/api/automation/controlled-sessions/automatic-pause/states/{session_id}": {
            "GET"
        },
    }
