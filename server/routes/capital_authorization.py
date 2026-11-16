"""Fail-closed minimal capital authority status router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/capital-authority",
        tags=["automation", "capital-authority"],
    )

    @router.get("/status")
    async def get_capital_authority_status() -> dict[str, Any]:
        return {
            "schema_version": "karkinos.capital_authority_status.v1",
            "runtime_authority_status": "disabled",
            "execution_authority_enabled": False,
            "broker_submission_enabled": False,
            "live_gateway_implemented": False,
            "status": "disabled",
            "message": "Capital authorization automation is permanently decommissioned and fail closed.",
        }

    return router


__all__ = ["create_router"]
