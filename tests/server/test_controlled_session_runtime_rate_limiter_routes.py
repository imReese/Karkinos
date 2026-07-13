from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_runtime_rate_limiter as route_module
from server.app import create_app
from server.routes.controlled_session_runtime_rate_limiter import create_router
from tests.route_assertions import registered_app_routes


class FakeRuntimeRateLimiterService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "runtime_admission_ready_internal_only",
            "runtime_admission_enabled": True,
            "public_admission_endpoint_exposed": False,
            "broker_submission_enabled": False,
        }

    def list_admissions(self, *, limit: int):
        self.calls.append(("list", limit))
        return [
            {
                "status": "admitted",
                "runtime_admission_granted": True,
                "authorizes_broker_submission": False,
            }
        ]


def _client(monkeypatch):
    service = FakeRuntimeRateLimiterService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_runtime_rate_limit_routes_are_read_only(monkeypatch) -> None:
    client, service = _client(monkeypatch)
    prefix = "/api/automation/controlled-sessions/runtime-rate-limit"

    status = client.get(f"{prefix}/status")
    admissions = client.get(f"{prefix}/admissions?limit=10")
    forbidden_admit = client.post(
        f"{prefix}/admissions",
        json={
            "session_id": "session-a",
            "order_id": "OMS-1",
            "request_id": "1" * 64,
            "broker_password": "must-not-be-accepted",
        },
    )

    assert status.status_code == 200
    assert status.json()["runtime_admission_enabled"] is True
    assert status.json()["public_admission_endpoint_exposed"] is False
    assert admissions.status_code == 200
    assert admissions.json()[0]["authorizes_broker_submission"] is False
    assert forbidden_admit.status_code == 405
    assert ("list", 10) in service.calls


def test_route_service_wires_persistent_authentication_but_keeps_api_read_only(
    monkeypatch,
) -> None:
    fake_state = SimpleNamespace(db=object())
    fake_authority = SimpleNamespace(
        authenticate=lambda session_id, session_token: {"session_id": session_id}
    )
    fake_live_gates = SimpleNamespace(
        latest=lambda session_id: {"session_id": session_id}
    )
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.controlled_session_runtime_authority._service",
        lambda: fake_authority,
    )
    monkeypatch.setattr(
        "server.routes.controlled_session_automatic_pause._live_gate_service",
        lambda: fake_live_gates,
    )

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._session_provider == fake_authority.authenticate
    assert service._gate_snapshot_provider == fake_live_gates.latest
    assert service.get_status()["runtime_admission_enabled"] is True
    assert service.get_status()["public_admission_endpoint_exposed"] is False


def test_create_app_registers_only_rate_limit_status_and_history() -> None:
    app = create_app({"live_auto_start": False})
    methods_by_path = {
        route.path: set(route.methods or set())
        for route in registered_app_routes(app)
        if route.path.startswith(
            "/api/automation/controlled-sessions/runtime-rate-limit"
        )
    }

    assert methods_by_path == {
        "/api/automation/controlled-sessions/runtime-rate-limit/status": {"GET"},
        "/api/automation/controlled-sessions/runtime-rate-limit/admissions": {"GET"},
    }
