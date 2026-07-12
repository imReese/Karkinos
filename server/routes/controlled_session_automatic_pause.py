"""Read-only visibility for the default-closed automatic pause controller."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-sessions/automatic-pause",
        tags=["automation", "controlled-session", "automatic-pause"],
    )

    @router.get("/status")
    async def get_controlled_session_automatic_pause_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/events")
    async def list_controlled_session_automatic_pause_events(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_pause_events(limit=limit)

    @router.get("/states/{session_id}")
    async def get_controlled_session_automatic_pause_state(
        session_id: str,
    ) -> dict[str, Any]:
        return _service().get_state(session_id)

    return router


def _service() -> ControlledSessionAutomaticPauseService:
    from server.app import get_app_state
    from server.routes.controlled_session_runtime_authority import (
        _service as controlled_session_runtime_authority_service,
    )

    state = get_app_state()
    return ControlledSessionAutomaticPauseService(
        db=state.db,
        session_provider=controlled_session_runtime_authority_service().resolve_current,
        gate_provider=None,
    )
