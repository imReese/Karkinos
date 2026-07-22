"""Signed operator routes for provider-neutral broker adapter release reviews."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
)
from server.services.signed_broker_adapter_release_review import (
    SignedBrokerAdapterReleaseReviewRejected,
    SignedBrokerAdapterReleaseReviewService,
)


class SignedBrokerAdapterReleaseReviewDossierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    source_name: str = Field(default="operator-reviewed-manifest.json", max_length=255)
    review_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    decision: Literal["accepted", "rejected", "revoked"]
    reviewed_at: str = Field(min_length=20, max_length=64)
    reason_ref: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


class SignedBrokerAdapterReleaseReviewRequest(
    SignedBrokerAdapterReleaseReviewDossierRequest
):
    dossier_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_proof_signature_base64: str = Field(min_length=80, max_length=128)
    acknowledgement: Literal[
        "review_broker_adapter_release_without_registration_or_execution_authority"
    ] = BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/broker-adapter-release-review",
        tags=["automation", "broker-adapter", "operator-review"],
    )

    @router.get("/status")
    async def get_signed_broker_adapter_release_review_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/releases")
    async def list_signed_broker_adapter_release_reviews(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_releases(limit=limit)

    @router.post("/dossiers/preview")
    async def preview_signed_broker_adapter_release_review(
        request: SignedBrokerAdapterReleaseReviewDossierRequest,
    ) -> dict[str, Any]:
        return _service().preview_dossier(**request.model_dump())

    @router.post("/reviews")
    async def record_signed_broker_adapter_release_review(
        request: SignedBrokerAdapterReleaseReviewRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record_review(**request.model_dump())
        except SignedBrokerAdapterReleaseReviewRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    return router


def build_signed_broker_adapter_release_review_service(
    state: Any,
) -> SignedBrokerAdapterReleaseReviewService:
    config = getattr(state, "config", None)
    return SignedBrokerAdapterReleaseReviewService(
        db=state.db,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
    )


def _service() -> SignedBrokerAdapterReleaseReviewService:
    from server.app import get_app_state

    return build_signed_broker_adapter_release_review_service(get_app_state())


__all__ = [
    "SignedBrokerAdapterReleaseReviewDossierRequest",
    "SignedBrokerAdapterReleaseReviewRequest",
    "build_signed_broker_adapter_release_review_service",
    "create_router",
]
