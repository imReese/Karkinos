"""Execution reconciliation routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.services.execution_reconciliation import ExecutionReconciliationService


class ExecutionReconciliationRunRequest(BaseModel):
    run_date: str | None = None


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

    return r


def _service() -> ExecutionReconciliationService:
    from server.app import get_app_state

    return ExecutionReconciliationService(db=get_app_state().db)
