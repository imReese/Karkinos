"""Evidence-only per-order confirmation dossier routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_connector_soak_promotion import (
    BrokerConnectorSoakPromotionService,
)
from server.services.current_per_order_dossier import (
    CurrentPerOrderDossierService,
    resolve_persisted_execution_gateway_verification,
)
from server.services.execution_gateway_verification import (
    ExecutionGatewayVerificationService,
)
from server.services.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PerOrderConfirmationRejected,
    PerOrderConfirmationService,
)


class PerOrderDossierPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital_evaluation_input_fingerprint: str = Field(default="", max_length=64)
    prior_batch_reconciliation_fingerprint: str = Field(
        default="",
        max_length=64,
        pattern=r"^$|^[a-f0-9]{64}$",
    )
    execution_gateway_verification_fingerprint: str = Field(
        default="",
        max_length=64,
        pattern=r"^$|^[a-f0-9]{64}$",
    )


class PerOrderConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital_evaluation_input_fingerprint: str = Field(min_length=64, max_length=64)
    prior_batch_reconciliation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    execution_gateway_verification_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    dossier_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(min_length=1, max_length=128)
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal["confirm_exact_non_submitting_dossier_for_review"] = (
        PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT
    )


class CurrentPerOrderConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dossier_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(min_length=1, max_length=128)
    operator_approval_id: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    acknowledgement: Literal["confirm_exact_non_submitting_dossier_for_review"] = (
        PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT
    )


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/controlled-bridge",
        tags=["automation", "controlled-bridge", "per-order-confirmation"],
    )

    @router.get("/status")
    async def get_per_order_confirmation_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/dossiers/current")
    async def list_current_per_order_dossier_candidates(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        return _current_dossier_service().list_candidates(limit=limit)

    @router.post("/orders/{order_id}/dossier/current/preview")
    async def preview_current_per_order_confirmation_dossier(
        order_id: str,
    ) -> dict[str, Any]:
        try:
            return _current_dossier_service().preview_current(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/orders/{order_id}/dossier/current/confirmations")
    async def record_current_per_order_confirmation(
        order_id: str,
        request: CurrentPerOrderConfirmationRequest,
    ) -> dict[str, Any]:
        try:
            return _current_dossier_service().record_current_confirmation(
                order_id,
                dossier_fingerprint=request.dossier_fingerprint,
                operator_label=request.operator_label,
                operator_approval_id=request.operator_approval_id,
                acknowledgement=request.acknowledgement,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PerOrderConfirmationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.post("/orders/{order_id}/dossier/preview")
    async def preview_per_order_confirmation_dossier(
        order_id: str,
        request: PerOrderDossierPreviewRequest | None = None,
    ) -> dict[str, Any]:
        fingerprint = request.capital_evaluation_input_fingerprint if request else ""
        prior_batch_fingerprint = (
            request.prior_batch_reconciliation_fingerprint if request else ""
        )
        gateway_verification_fingerprint = (
            request.execution_gateway_verification_fingerprint if request else ""
        )
        try:
            return _service().preview_dossier(
                order_id,
                capital_evaluation_input_fingerprint=fingerprint,
                prior_batch_reconciliation_fingerprint=prior_batch_fingerprint,
                execution_gateway_verification_fingerprint=(
                    gateway_verification_fingerprint
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/orders/{order_id}/confirmations")
    async def record_per_order_confirmation(
        order_id: str,
        request: PerOrderConfirmationRequest,
    ) -> dict[str, Any]:
        try:
            return _service().record_confirmation(
                order_id,
                capital_evaluation_input_fingerprint=(
                    request.capital_evaluation_input_fingerprint
                ),
                prior_batch_reconciliation_fingerprint=(
                    request.prior_batch_reconciliation_fingerprint
                ),
                execution_gateway_verification_fingerprint=(
                    request.execution_gateway_verification_fingerprint
                ),
                dossier_fingerprint=request.dossier_fingerprint,
                operator_label=request.operator_label,
                operator_approval_id=request.operator_approval_id,
                acknowledgement=request.acknowledgement,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PerOrderConfirmationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/orders/{order_id}/confirmations")
    async def list_per_order_confirmations(
        order_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_confirmations(order_id, limit=limit)

    return router


def _service() -> PerOrderConfirmationService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    trusted_operator_identities = (
        getattr(config, "trusted_operator_identities", []) or []
    )
    return PerOrderConfirmationService(
        db=state.db,
        connectors=connectors,
        trusted_operator_identities=trusted_operator_identities,
        trading_controls=getattr(state, "trading_controls", None),
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: BrokerConnectorSoakPromotionService(
                db=state.db,
                connectors=connectors,
                trusted_operator_identities=trusted_operator_identities,
                account_truth_evidence_provider=(
                    lambda: build_latest_account_truth_promotion_evidence(state)
                ),
            ).preview_dossier(connector_id)
        ),
        execution_gateway_verification_provider=(
            ExecutionGatewayVerificationService(
                db=state.db,
                gateways=getattr(state, "execution_gateways", []) or [],
            ).resolve
        ),
    )


def _current_dossier_service() -> CurrentPerOrderDossierService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    trusted_operator_identities = (
        getattr(config, "trusted_operator_identities", []) or []
    )
    dossier_service = PerOrderConfirmationService(
        db=state.db,
        connectors=connectors,
        trusted_operator_identities=trusted_operator_identities,
        trading_controls=getattr(state, "trading_controls", None),
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: BrokerConnectorSoakPromotionService(
                db=state.db,
                connectors=connectors,
                trusted_operator_identities=trusted_operator_identities,
                account_truth_evidence_provider=(
                    lambda: build_latest_account_truth_promotion_evidence(state)
                ),
            ).preview_dossier(connector_id)
        ),
        execution_gateway_verification_provider=(
            lambda fingerprint: resolve_persisted_execution_gateway_verification(
                state.db,
                fingerprint,
            )
        ),
    )
    return CurrentPerOrderDossierService(
        db=state.db,
        dossier_service=dossier_service,
    )
