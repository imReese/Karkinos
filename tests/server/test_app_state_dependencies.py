import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.config import ServerConfig
from server.dependencies import (
    AppState,
    AppStateContextMiddleware,
    get_app_state,
)


def _state_probe_app(label: str) -> FastAPI:
    app = FastAPI()
    state = AppState()
    state.config = label
    app.state.app_state = state
    app.add_middleware(AppStateContextMiddleware, app_state=state)

    @app.get("/state")
    async def read_state() -> dict[str, str]:
        return {"label": get_app_state().config}

    return app


def test_request_context_keeps_application_states_isolated() -> None:
    first_app = _state_probe_app("first")
    second_app = _state_probe_app("second")

    assert first_app.state.app_state is not second_app.state.app_state
    assert TestClient(first_app).get("/state").json() == {"label": "first"}
    assert TestClient(second_app).get("/state").json() == {"label": "second"}


def test_create_app_owns_a_fresh_state_instance() -> None:
    from server.app import create_app

    runtime_config = ServerConfig(live_auto_start=False)
    first_app = create_app(runtime_config=runtime_config)
    second_app = create_app(runtime_config=runtime_config)

    assert first_app.state.app_state is not second_app.state.app_state


def test_missing_application_context_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="outside a bound request"):
        get_app_state()


def test_scheduler_callback_binds_only_its_owning_application_state(
    monkeypatch,
) -> None:
    from server.app import _evaluate_controlled_session_pauses

    state = AppState()

    class Orchestrator:
        @staticmethod
        def evaluate_all() -> dict[str, bool]:
            assert get_app_state() is state
            return {"evaluated": True}

    monkeypatch.setattr(
        "server.composition.controlled_execution_services."
        "build_controlled_session_automatic_pause_orchestrator_service",
        lambda bound_state: (
            Orchestrator()
            if bound_state is state
            else pytest.fail("scheduler bound an unrelated application state")
        ),
    )

    assert _evaluate_controlled_session_pauses(state) == {"evaluated": True}
    with pytest.raises(RuntimeError, match="outside a bound request"):
        get_app_state()


def test_production_routes_do_not_import_application_bootstrap() -> None:
    violations: list[str] = []
    for source_path in sorted(Path("server/routes").rglob("*.py")):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "server.app":
                violations.append(f"{source_path}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "server.app":
                        violations.append(f"{source_path}:{node.lineno}")

    assert violations == []
