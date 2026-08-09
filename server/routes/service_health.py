"""Process-liveness route with no financial or provider side effects."""

from __future__ import annotations

from fastapi import APIRouter

SERVICE_HEALTH_SCHEMA_VERSION = "karkinos.service_health.v1"


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/health", tags=["service-health"])

    @router.get("")
    async def get_service_health() -> dict[str, object]:
        return {
            "schema_version": SERVICE_HEALTH_SCHEMA_VERSION,
            "service": "karkinos",
            "status": "alive",
            "scope": "process_liveness_only",
            "financial_readiness_claimed": False,
            "provider_contacted": False,
            "database_reads_performed": False,
            "database_writes_performed": False,
            "production_ledger_mutated": False,
            "broker_submission_enabled": False,
            "broker_cancellation_enabled": False,
            "capital_authority_changed": False,
            "authorizes_execution": False,
        }

    return router
