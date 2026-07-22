"""Operator routes for an exact, expiring broker write-edge release."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.controlled_broker_write_release import (
    CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT,
    ControlledBrokerWriteReleaseRejected,
    ControlledBrokerWriteReleaseService,
)


class ControlledBrokerWriteReleaseDossierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_edge_manifest: dict[str, Any]
    readonly_release_evidence_ref: str = Field(min_length=1, max_length=256)
    soak_acceptance_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    effective_at: str = Field(min_length=20, max_length=64)
    expires_at: str = Field(min_length=20, max_length=64)
    owner_review_refs: dict[str, str]


class ControlledBrokerWriteReleaseRequest(ControlledBrokerWriteReleaseDossierRequest):
    dossier_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
    )
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_proof_signature_base64: str = Field(min_length=80, max_length=128)
    acknowledgement: Literal[
        "issue_exact_expiring_manual_each_order_write_release_without_order_or_capital_authority"
    ] = CONTROLLED_BROKER_WRITE_RELEASE_ACKNOWLEDGEMENT


class ControlledBrokerWriteReleaseRevocationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_code: Literal[
        "adapter_or_deployment_changed",
        "incident_or_anomaly",
        "owner_disabled",
        "provider_scope_changed",
        "regulatory_or_permission_change",
        "scheduled_expiry_superseded",
    ]


class ControlledBrokerWriteReleaseRevocationRequest(
    ControlledBrokerWriteReleaseRevocationPreviewRequest
):
    revocation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
    )
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_proof_signature_base64: str = Field(min_length=80, max_length=128)
    acknowledgement: Literal[
        "revoke_exact_broker_write_release_without_resume_or_broker_action"
    ] = CONTROLLED_BROKER_WRITE_RELEASE_REVOCATION_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-broker-write-release",
        tags=["automation", "controlled-bridge", "broker-write-release"],
    )

    @router.get("/status")
    async def get_controlled_broker_write_release_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/dossiers/preview")
    async def preview_controlled_broker_write_release(
        request: ControlledBrokerWriteReleaseDossierRequest,
    ) -> dict[str, Any]:
        return _service().preview_dossier(**request.model_dump())

    @router.post("/releases")
    async def record_controlled_broker_write_release(
        request: ControlledBrokerWriteReleaseRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record_release(**request.model_dump())
        except ControlledBrokerWriteReleaseRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/releases")
    async def list_controlled_broker_write_releases(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_releases(limit=limit)

    @router.get("/releases/{release_evidence_id}")
    async def get_controlled_broker_write_release(
        release_evidence_id: str,
    ) -> dict[str, Any]:
        return _service().get_release(release_evidence_id)

    @router.post("/releases/{release_evidence_id}/revocation/preview")
    async def preview_controlled_broker_write_release_revocation(
        release_evidence_id: str,
        request: ControlledBrokerWriteReleaseRevocationPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview_revocation(
            release_evidence_id=release_evidence_id,
            reason_code=request.reason_code,
        )

    @router.post("/releases/{release_evidence_id}/revocations")
    async def revoke_controlled_broker_write_release(
        release_evidence_id: str,
        request: ControlledBrokerWriteReleaseRevocationRequest,
    ) -> dict[str, Any]:
        try:
            return _service().revoke_release(
                release_evidence_id=release_evidence_id,
                **request.model_dump(),
            )
        except ControlledBrokerWriteReleaseRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    return router


def build_controlled_broker_write_release_service(
    state: Any,
) -> ControlledBrokerWriteReleaseService:
    from server.routes.broker_connector_soak import _promotion_service

    config = getattr(state, "config", None)
    return ControlledBrokerWriteReleaseService(
        db=state.db,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        soak_promotion_provider=(
            lambda connector_id: _promotion_service().preview_dossier(connector_id)
        ),
    )


def _service() -> ControlledBrokerWriteReleaseService:
    from server.app import get_app_state

    return build_controlled_broker_write_release_service(get_app_state())


__all__ = [
    "ControlledBrokerWriteReleaseDossierRequest",
    "ControlledBrokerWriteReleaseRequest",
    "ControlledBrokerWriteReleaseRevocationPreviewRequest",
    "ControlledBrokerWriteReleaseRevocationRequest",
    "build_controlled_broker_write_release_service",
    "create_router",
]
