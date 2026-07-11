"""Atomic, non-authorizing controlled-session budget reservation routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_session_budget_reservation import (
    CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    ControlledSessionBudgetReservationRejected,
    ControlledSessionBudgetReservationService,
)


class ControlledSessionBudgetPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attestation_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


class ControlledSessionBudgetRecordRequest(ControlledSessionBudgetPreviewRequest):
    reservation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal[
        "reserve_exact_non_authorizing_controlled_session_budget"
    ] = CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-sessions/budget-reservations",
        tags=["automation", "controlled-session", "budget-reservation"],
    )

    @router.get("/status")
    async def get_controlled_session_budget_reservation_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/preview")
    async def preview_controlled_session_budget_reservation(
        request: ControlledSessionBudgetPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(attestation_id=request.attestation_id)

    @router.post("/records")
    async def record_controlled_session_budget_reservation(
        request: ControlledSessionBudgetRecordRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record(
                attestation_id=request.attestation_id,
                reservation_fingerprint=request.reservation_fingerprint,
                acknowledgement=request.acknowledgement,
            )
        except ControlledSessionBudgetReservationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/records")
    async def list_controlled_session_budget_reservations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_reservations(limit=limit)

    @router.get("/records/{reservation_id}")
    async def resolve_controlled_session_budget_reservation(
        reservation_id: str,
    ) -> dict[str, Any]:
        return _service().resolve(reservation_id)

    return router


def _service() -> ControlledSessionBudgetReservationService:
    from server.app import get_app_state
    from server.routes.controlled_session_envelope import (
        _service as controlled_session_envelope_service,
    )

    state = get_app_state()
    return ControlledSessionBudgetReservationService(
        db=state.db,
        attestation_provider=(
            controlled_session_envelope_service().resolve_attestation
        ),
    )
