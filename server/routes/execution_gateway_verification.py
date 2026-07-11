"""Non-submitting runtime execution-gateway verification routes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    ExecutionGatewayVerificationRejected,
    ExecutionGatewayVerificationService,
)


class ExecutionGatewayOrderContractPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=64)
    side: Literal["buy", "sell"]
    asset_class: str = Field(min_length=1, max_length=32)
    quantity: Decimal = Field(gt=0)
    order_type: Literal["limit"]
    limit_price: Decimal = Field(gt=0)


class ExecutionGatewayVerificationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_id: str = Field(min_length=1, max_length=128)
    evidence_connector_id: str = Field(min_length=1, max_length=128)
    account_alias: str = Field(min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    order_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    order_contract: ExecutionGatewayOrderContractPayload


class ExecutionGatewayVerificationRecordRequest(
    ExecutionGatewayVerificationPreviewRequest
):
    verification_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal["record_non_submitting_execution_gateway_verification"] = (
        EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT
    )


class ExecutionGatewayVerificationResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/execution-gateway-verification",
        tags=["automation", "execution-gateway", "runtime-verification"],
    )

    @router.get("/status")
    async def get_execution_gateway_verification_status() -> dict[str, Any]:
        return _service().get_status()

    @router.post("/preview")
    async def preview_execution_gateway_verification(
        request: ExecutionGatewayVerificationPreviewRequest,
    ) -> dict[str, Any]:
        return _service().preview(
            gateway_id=request.gateway_id,
            evidence_connector_id=request.evidence_connector_id,
            account_alias=request.account_alias,
            order_id=request.order_id,
            order_fingerprint=request.order_fingerprint,
            order_contract=request.order_contract.model_dump(mode="json"),
        )

    @router.post("/records")
    async def record_execution_gateway_verification(
        request: ExecutionGatewayVerificationRecordRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record(
                gateway_id=request.gateway_id,
                evidence_connector_id=request.evidence_connector_id,
                account_alias=request.account_alias,
                order_id=request.order_id,
                order_fingerprint=request.order_fingerprint,
                order_contract=request.order_contract.model_dump(mode="json"),
                verification_fingerprint=request.verification_fingerprint,
                acknowledgement=request.acknowledgement,
            )
        except ExecutionGatewayVerificationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.post("/resolve")
    async def resolve_execution_gateway_verification(
        request: ExecutionGatewayVerificationResolveRequest,
    ) -> dict[str, Any]:
        return _service().resolve(request.verification_fingerprint)

    @router.get("/records")
    async def list_execution_gateway_verifications(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_verifications(limit=limit)

    return router


def _service() -> ExecutionGatewayVerificationService:
    from server.app import get_app_state

    state = get_app_state()
    return ExecutionGatewayVerificationService(
        db=state.db,
        gateways=getattr(state, "execution_gateways", []) or [],
    )
