"""Read-only visibility for the default-closed runtime rate limiter."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from server.services.controlled_session_runtime_rate_limiter import (
    ControlledSessionRuntimeRateLimiterService,
)


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-sessions/runtime-rate-limit",
        tags=["automation", "controlled-session", "runtime-rate-limit"],
    )

    @router.get("/status")
    async def get_controlled_session_runtime_rate_limit_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/admissions")
    async def list_controlled_session_runtime_rate_admissions(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_admissions(limit=limit)

    return router


def _service() -> ControlledSessionRuntimeRateLimiterService:
    from server.app import get_app_state
    from server.routes.controlled_session_automatic_pause import (
        _live_gate_service as controlled_session_live_gate_service,
    )
    from server.routes.controlled_session_runtime_authority import (
        _service as controlled_session_runtime_authority_service,
    )

    state = get_app_state()
    return ControlledSessionRuntimeRateLimiterService(
        db=state.db,
        session_provider=controlled_session_runtime_authority_service().authenticate,
        gate_snapshot_provider=controlled_session_live_gate_service().latest,
    )
