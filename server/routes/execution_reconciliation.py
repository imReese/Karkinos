"""Execution reconciliation routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    ExecutionBatchReconciliationRejected,
    ExecutionBatchReconciliationService,
)
from server.services.execution_reconciliation import ExecutionReconciliationService


class ExecutionReconciliationRunRequest(BaseModel):
    run_date: str | None = None


class ExecutionBatchReconciliationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )
    order_ids: list[str] = Field(min_length=1, max_length=100)
    reconciliation_run_id: str = Field(min_length=1, max_length=256)


class ExecutionBatchReconciliationRecordRequest(
    ExecutionBatchReconciliationPreviewRequest
):
    batch_reconciliation_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[a-f0-9]{64}$",
    )
    operator_label: str = Field(min_length=1, max_length=128)
    acknowledgement: Literal[
        "record_exact_batch_reconciliation_without_authority_change"
    ] = EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT


def create_router() -> APIRouter:
    r = APIRouter(
        prefix="/api/execution-reconciliation",
        tags=["execution-reconciliation"],
    )

    @r.post("/runs")
    async def run_execution_reconciliation(
        request: ExecutionReconciliationRunRequest,
    ) -> dict[str, Any]:
        return _service().run_reconciliation(run_date=request.run_date)

    @r.get("/runs")
    async def list_execution_reconciliation_runs(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        from server.app import get_app_state

        return get_app_state().db.list_execution_reconciliation_runs_sync(
            limit=limit,
            offset=offset,
        )

    @r.get("/runs/{run_id}")
    async def get_execution_reconciliation_run(run_id: str) -> dict[str, Any]:
        from server.app import get_app_state

        db = get_app_state().db
        run = db.get_execution_reconciliation_run_sync(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail=f"execution reconciliation run not found: {run_id}",
            )
        return {
            **run,
            "items": db.list_execution_reconciliation_items_sync(run_id),
        }

    @r.get("/batch-evidence/status")
    async def get_execution_batch_reconciliation_status() -> dict[str, Any]:
        return _batch_service().get_status()

    @r.post("/batch-evidence/preview")
    async def preview_execution_batch_reconciliation(
        request: ExecutionBatchReconciliationPreviewRequest,
    ) -> dict[str, Any]:
        return _batch_service().preview(
            batch_id=request.batch_id,
            order_ids=request.order_ids,
            reconciliation_run_id=request.reconciliation_run_id,
        )

    @r.post("/batch-evidence/records")
    async def record_execution_batch_reconciliation(
        request: ExecutionBatchReconciliationRecordRequest,
    ) -> dict[str, Any]:
        try:
            return _batch_service().record(
                batch_id=request.batch_id,
                order_ids=request.order_ids,
                reconciliation_run_id=request.reconciliation_run_id,
                batch_reconciliation_fingerprint=(
                    request.batch_reconciliation_fingerprint
                ),
                operator_label=request.operator_label,
                acknowledgement=request.acknowledgement,
            )
        except ExecutionBatchReconciliationRejected as exc:
            raise HTTPException(status_code=409, detail=exc.evidence) from exc

    @r.get("/batch-evidence/records")
    async def list_execution_batch_reconciliations(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return _batch_service().list_records(limit=limit)

    @r.get("/batch-evidence/records/{fingerprint}")
    async def resolve_execution_batch_reconciliation(
        fingerprint: str,
    ) -> dict[str, Any]:
        return _batch_service().resolve_recorded(fingerprint)

    return r


def _service() -> ExecutionReconciliationService:
    from server.app import get_app_state

    return ExecutionReconciliationService(db=get_app_state().db)


def _batch_service() -> ExecutionBatchReconciliationService:
    from server.app import get_app_state

    return ExecutionBatchReconciliationService(db=get_app_state().db)
