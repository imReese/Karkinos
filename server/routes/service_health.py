"""Process-liveness route with no financial or provider side effects."""

from __future__ import annotations

from fastapi import APIRouter  # pyright: ignore[reportMissingImports]

from server import __version__


def _release_identity() -> dict[str, str]:
    """Expose only non-sensitive immutable release identity for probes."""
    import os

    identity: dict[str, str] = {}
    release_sha = os.environ.get("KARKINOS_RELEASE_SHA", "").strip()
    artifact_fingerprint = os.environ.get("KARKINOS_ARTIFACT_FINGERPRINT", "").strip()
    if release_sha:
        identity["release_sha"] = release_sha
    if artifact_fingerprint:
        identity["artifact_fingerprint"] = artifact_fingerprint
    return identity


SERVICE_HEALTH_SCHEMA_VERSION = "karkinos.service_health.v1"


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/health", tags=["service-health"])

    @router.get("/readiness")
    def get_system_readiness() -> dict[str, object]:
        from server.dependencies import get_app_state
        from server.projections.system_readiness import build_system_readiness

        state = get_app_state()
        database = getattr(state, "db", None)
        return build_system_readiness(
            getattr(database, "path", None),
            api_observed=True,
            data_worker_enabled=getattr(
                state.config, "market_calendar_auto_sync", None
            ),
        )

    @router.get("")
    async def get_service_health() -> dict[str, object]:
        return {
            "schema_version": SERVICE_HEALTH_SCHEMA_VERSION,
            "service": "karkinos",
            "version": __version__,
            **_release_identity(),
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
