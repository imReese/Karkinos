from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import ValidationError

from server.config import ServerConfig
from server.contracts.http.settings_models import SettingsResponse
from server.routes.settings import create_router


def _methods_by_path(router: APIRouter) -> dict[str, set[str]]:
    return {
        route.path: set(route.methods or set())
        for route in router.routes
        if hasattr(route, "methods")
    }


def test_live_scheduler_settings_surface_is_read_only() -> None:
    methods = _methods_by_path(create_router())

    assert methods["/api/settings/live/status"] == {"GET"}
    assert "/api/settings/live/start" not in methods
    assert "/api/settings/live/stop" not in methods


def test_settings_schema_has_no_live_scheduler_switch() -> None:
    assert "live_auto_start" not in SettingsResponse.model_fields
    with pytest.raises(ValidationError, match="live_auto_start"):
        SettingsResponse.model_validate({"live_auto_start": False})

    from server.routes import settings as settings_routes

    state = SimpleNamespace(config=ServerConfig(), db=None)
    response = settings_routes._settings_response(state)

    assert "live_auto_start" not in response.model_dump()


def test_live_status_distinguishes_liveness_readiness_and_activation_guard(
    monkeypatch,
) -> None:
    router = create_router()
    endpoint = next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/api/settings/live/status"
    )
    state = SimpleNamespace(
        scheduler=SimpleNamespace(
            is_running=True,
            is_initialized=False,
            activation_guarded=True,
            scheduler_activation_guarded=lambda: False,
            completed_iterations=3,
            is_market_open=False,
        )
    )
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: state)

    response = asyncio.run(endpoint())

    assert response.model_dump() == {
        "running": True,
        "initialized": False,
        "activation_guarded": True,
        "scheduler_activation_guarded": False,
        "completed_iterations": 3,
        "market_open": False,
    }
