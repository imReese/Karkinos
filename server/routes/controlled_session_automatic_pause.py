"""Read-only visibility for the default-closed automatic pause controller."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

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
    authority, live_gates, state = _dependencies()
    return ControlledSessionAutomaticPauseService(
        db=state.db,
        session_provider=authority.resolve_for_monitoring,
        gate_provider=live_gates.resolve_gate_snapshot,
    )


def _live_gate_service() -> ControlledSessionLiveGateSnapshotService:
    _, live_gates, _ = _dependencies()
    return live_gates


def _orchestrator_service() -> ControlledSessionAutomaticPauseOrchestratorService:
    authority, live_gates, state = _dependencies()
    return ControlledSessionAutomaticPauseOrchestratorService(
        runtime_authority=authority,
        live_gates=live_gates,
        automatic_pause=ControlledSessionAutomaticPauseService(
            db=state.db,
            session_provider=authority.resolve_for_monitoring,
            gate_provider=live_gates.resolve_gate_snapshot,
        ),
    )


def _dependencies() -> tuple[Any, ControlledSessionLiveGateSnapshotService, Any]:
    from server.app import get_app_state
    from server.routes.controlled_session_budget_reservation import (
        _service as controlled_session_budget_reservation_service,
    )
    from server.routes.controlled_session_envelope import (
        _service as controlled_session_envelope_service,
    )
    from server.routes.controlled_session_runtime_authority import (
        _service as controlled_session_runtime_authority_service,
    )

    state = get_app_state()
    authority = controlled_session_runtime_authority_service()
    live_gates = ControlledSessionLiveGateSnapshotService(
        db=state.db,
        session_monitor_provider=authority.resolve_for_monitoring,
        reservation_provider=controlled_session_budget_reservation_service().resolve,
        attestation_provider=controlled_session_envelope_service().resolve_attestation,
        trading_controls=getattr(state, "trading_controls", None),
    )
    return authority, live_gates, state
