"""Read-only broker connector soak routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.account_truth_gate import build_latest_account_truth_promotion_evidence
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_connector_soak import BrokerConnectorSoakService
from server.services.broker_connector_soak_promotion import (
    BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT,
    BrokerConnectorSoakPromotionRejected,
    BrokerConnectorSoakPromotionService,
)
from server.services.broker_connector_soak_runbook import (
    BrokerConnectorSoakRunbookService,
)


class BrokerConnectorSoakCaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_snapshot_age_seconds: int = Field(default=900, ge=60, le=86400)


class BrokerConnectorSoakRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["startup", "intraday", "end_of_day"]
    max_snapshot_age_seconds: int = Field(default=900, ge=60, le=86400)


class BrokerConnectorSoakDrillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_type: Literal[
        "disconnect",
        "schema_drift",
        "stale_data",
        "duplicate_evidence",
        "restart_recovery",
    ]
    max_snapshot_age_seconds: int = Field(default=900, ge=60, le=86400)


class BrokerConnectorSoakPromotionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


class BrokerConnectorSoakPromotionAcceptanceRequest(
    BrokerConnectorSoakPromotionPreviewRequest
):
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
    acknowledgement: Literal[
        "accept_exact_readonly_soak_and_account_truth_promotion_without_execution_authority"
    ] = BROKER_SOAK_PROMOTION_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/automation/broker-soak",
        tags=["automation", "broker-soak"],
    )

    @router.get("/status")
    async def get_broker_connector_soak_status() -> dict[str, Any]:
        return _service().get_status()

    @router.get("/observations")
    async def list_broker_connector_soak_observations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _service().list_observations(limit=limit)

    @router.post("/capture")
    async def capture_broker_connector_soak_observation(
        request: BrokerConnectorSoakCaptureRequest | None = None,
    ) -> dict[str, Any]:
        max_age = request.max_snapshot_age_seconds if request is not None else 900
        return _service().capture(max_snapshot_age_seconds=max_age)

    @router.post("/runs")
    async def run_broker_connector_soak_phase(
        request: BrokerConnectorSoakRunRequest,
    ) -> dict[str, Any]:
        return _runbook_service().run_phase(
            phase=request.phase,
            max_snapshot_age_seconds=request.max_snapshot_age_seconds,
        )

    @router.get("/runs")
    async def list_broker_connector_soak_runs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _runbook_service().list_runs(limit=limit)

    @router.post("/drills")
    async def run_broker_connector_soak_drill(
        request: BrokerConnectorSoakDrillRequest,
    ) -> dict[str, Any]:
        return _runbook_service().run_drill(
            drill_type=request.drill_type,
            max_snapshot_age_seconds=request.max_snapshot_age_seconds,
        )

    @router.get("/drills")
    async def list_broker_connector_soak_drills(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _runbook_service().list_drills(limit=limit)

    @router.get("/promotion/status")
    async def get_broker_connector_soak_promotion_status() -> dict[str, Any]:
        return _promotion_service().get_status()

    @router.post("/promotion/dossiers/preview")
    async def preview_broker_connector_soak_promotion_dossier(
        request: BrokerConnectorSoakPromotionPreviewRequest,
    ) -> dict[str, Any]:
        return _promotion_service().preview_dossier(request.connector_id)

    @router.post("/promotion/acceptances")
    async def record_broker_connector_soak_promotion_acceptance(
        request: BrokerConnectorSoakPromotionAcceptanceRequest,
    ) -> dict[str, Any]:
        try:
            return _promotion_service().record_acceptance(
                connector_id=request.connector_id,
                dossier_fingerprint=request.dossier_fingerprint,
                operator_label=request.operator_label,
                operator_approval_id=request.operator_approval_id,
                acknowledgement=request.acknowledgement,
            )
        except BrokerConnectorSoakPromotionRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @router.get("/promotion/acceptances")
    async def list_broker_connector_soak_promotion_acceptances(
        connector_id: str = Query(default="", max_length=128),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _promotion_service().list_acceptances(
            connector_id=connector_id,
            limit=limit,
        )

    return router


def _service() -> BrokerConnectorSoakService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    return BrokerConnectorSoakService(db=state.db, connectors=connectors)


def _runbook_service() -> BrokerConnectorSoakRunbookService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    return BrokerConnectorSoakRunbookService(db=state.db, connectors=connectors)


def _promotion_service() -> BrokerConnectorSoakPromotionService:
    from server.app import get_app_state

    state = get_app_state()
    config = getattr(state, "config", None)
    connectors = build_broker_connectors(getattr(config, "broker_connectors", []) or [])
    return BrokerConnectorSoakPromotionService(
        db=state.db,
        connectors=connectors,
        trusted_operator_identities=(
            getattr(config, "trusted_operator_identities", []) or []
        ),
        account_truth_evidence_provider=(
            lambda: build_latest_account_truth_promotion_evidence(state)
        ),
    )
