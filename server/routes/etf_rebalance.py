"""HTTP routes for automated ETF rotation rebalance execution — /api/trading/etf-rebalance/*."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from server.services.etf_rotation_automation import EtfRotationAutomationService


class RebalanceEvaluationRequest(BaseModel):
    total_equity: float | None = Field(
        default=None, description="Total account equity in CNY"
    )
    current_holdings: dict[str, int] | None = Field(
        default=None, description="Current holding shares mapping by symbol"
    )
    strategy_params: dict[str, Any] | None = Field(
        default=None, description="Optional override strategy parameters"
    )


class ExecuteOrdersRequest(BaseModel):
    operator: str = Field(
        default="user", description="Operator identity authorizing the trade"
    )
    note: str = Field(default="", description="Optional operator note")
    broker_mode: str = Field(
        default="auto", description="Execution broker mode (auto, qmt, sim)"
    )


def create_router(
    service: EtfRotationAutomationService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/trading/etf-rebalance", tags=["etf-rebalance"])
    svc = service or EtfRotationAutomationService()

    @router.get("/dashboard")
    async def get_dashboard() -> dict[str, Any]:
        """Get full strategy backtest performance, today's actionable orders, and execution status."""
        return svc.get_dashboard_view()

    @router.post("/execute")
    async def execute_rebalance_orders(
        request: ExecuteOrdersRequest | None = None,
    ) -> dict[str, Any]:
        """Perform actual order placement based on the verified strategy yield and recommendations."""
        req = request or ExecuteOrdersRequest()
        return svc.execute_orders(
            operator=req.operator,
            note=req.note,
            broker_mode=req.broker_mode,
        )

    @router.get("/plan")
    async def get_rebalance_plan() -> dict[str, Any]:
        """Get the latest actionable ETF rebalance plan with Chinese names and order details."""
        summary = svc.get_latest_plan_summary()
        if summary is None:
            try:
                summary = svc.evaluate_rebalance()
            except Exception as exc:
                raise HTTPException(
                    status_code=500, detail=f"Failed to evaluate ETF rebalance: {exc}"
                ) from exc
        return summary

    @router.post("/run")
    async def run_rebalance_evaluation(
        request: RebalanceEvaluationRequest | None = None,
    ) -> dict[str, Any]:
        """Trigger an on-demand rebalance calculation and update the active rebalance plan."""
        req = request or RebalanceEvaluationRequest()
        try:
            return svc.evaluate_rebalance(
                total_equity=req.total_equity,
                current_holdings=req.current_holdings,
                strategy_params=req.strategy_params,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to evaluate ETF rebalance: {exc}"
            ) from exc

    @router.get("/csv", response_class=PlainTextResponse)
    async def export_rebalance_csv() -> PlainTextResponse:
        """Download broker-ready CSV (证券代码, 证券名称, 买卖方向, 委托数量, 委托价格, 预估金额, 调仓说明)."""
        summary = svc.get_latest_plan_summary()
        if summary is None:
            summary = svc.evaluate_rebalance()
        csv_text = summary.get("csv_content", "")
        return PlainTextResponse(
            content=csv_text,
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="etf_rebalance_orders.csv"'
            },
        )

    @router.get("/script", response_class=PlainTextResponse)
    async def export_miniqmt_script() -> PlainTextResponse:
        """Download standalone MiniQMT (xtquant) Python execution script."""
        summary = svc.get_latest_plan_summary()
        if summary is None:
            summary = svc.evaluate_rebalance()
        script_text = summary.get("miniqmt_script", "")
        return PlainTextResponse(
            content=script_text,
            media_type="text/x-python",
            headers={
                "Content-Disposition": 'attachment; filename="execute_rebalance_miniqmt.py"'
            },
        )

    return router
