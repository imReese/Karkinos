"""Read-only visibility for the default-closed automatic pause controller."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.composition.controlled_execution_services import (
    build_controlled_session_automatic_pause_orchestrator_service,
    build_controlled_session_automatic_pause_service,
    build_controlled_session_live_gate_service,
)
from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_live_gates import (
    ControlledSessionAutomaticPauseOrchestratorService,
    ControlledSessionLiveGateRejected,
    ControlledSessionLiveGateSnapshotService,
)


class ControlledSessionPauseEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    session_token: str = Field(
        min_length=32,
        max_length=256,
        pattern=r"^[A-Za-z0-9_-]{32,256}$",
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

    @router.post("/evaluations")
    async def evaluate_controlled_session_automatic_pause(
        request: ControlledSessionPauseEvaluationRequest,
    ) -> dict[str, Any]:
        try:
            return _orchestrator_service().evaluate_authenticated(
                session_id=request.session_id,
                session_token=request.session_token,
            )
        except ControlledSessionLiveGateRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/gate-snapshots")
    async def list_controlled_session_gate_snapshots(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _live_gate_service().list_snapshots(limit=limit)

    @router.get("/gate-snapshots/{session_id}")
    async def get_controlled_session_gate_snapshot(
        session_id: str,
    ) -> dict[str, Any]:
        return _live_gate_service().latest(session_id)

    return router


def _service() -> ControlledSessionAutomaticPauseService:
    from server.dependencies import get_app_state

    return build_controlled_session_automatic_pause_service(get_app_state())


def _live_gate_service() -> ControlledSessionLiveGateSnapshotService:
    from server.dependencies import get_app_state

    return build_controlled_session_live_gate_service(get_app_state())


def _orchestrator_service() -> ControlledSessionAutomaticPauseOrchestratorService:
    from server.dependencies import get_app_state

    return build_controlled_session_automatic_pause_orchestrator_service(
        get_app_state()
    )
