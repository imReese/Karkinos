"""Controlled automation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.services.automation_control import AutomationControlService
from server.services.broker_connector_runtime import build_broker_connectors


class AutomationPolicyRequest(BaseModel):
    default_execution_mode: str | None = None
    manual_confirmation_required: bool | None = None
    broker_submission_enabled: bool | None = None
    allowed_execution_modes: list[str] | None = None
    updated_by: str | None = None


class DailyPaperShadowRunRequest(BaseModel):
    trading_plan: dict[str, Any] | None = Field(default=None)
    generated_at: str | None = None


class MarketSessionRunRequest(BaseModel):
    trading_plan: dict[str, Any] | None = Field(default=None)
    now: str | None = None


class AlertAckRequest(BaseModel):
    actor: str | None = None


class AlertScanRequest(BaseModel):
    connector_health: list[dict[str, Any]] | None = None
    trading_plan: dict[str, Any] | None = None
    market_health: dict[str, Any] | None = None
    account_truth: dict[str, Any] | None = None
    paper_shadow_run: dict[str, Any] | None = None


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/automation", tags=["automation"])

    @r.get("/status")
    async def get_automation_status() -> dict[str, Any]:
        service = _service()
        return service.get_status()

    @r.get("/cockpit")
    async def get_automation_cockpit() -> dict[str, Any]:
        from server.account_truth_gate import (
            build_latest_account_truth_promotion_evidence,
        )
        from server.app import get_app_state
        from server.services.automation_cockpit import AutomationCockpitService
        from server.services.current_per_order_dossier_factory import (
            build_current_per_order_dossier_service,
        )

        state = get_app_state()
        current_per_order_dossiers = build_current_per_order_dossier_service(state)
        return AutomationCockpitService(
            db=state.db,
            trading_controls=getattr(state, "trading_controls", None),
            broker_connectors=_broker_connectors(state),
            account_truth_evidence_reader=(
                lambda: build_latest_account_truth_promotion_evidence(state)
            ),
            current_per_order_dossier_reader=(
                lambda: current_per_order_dossiers.list_candidates(limit=20)
            ),
        ).summary()

    @r.get("/policies")
    async def list_automation_policies() -> list[dict[str, Any]]:
        service = _service()
        return [service.get_default_policy()]

    @r.put("/policies/default")
    async def update_default_policy(
        request: AutomationPolicyRequest,
    ) -> dict[str, Any]:
        service = _service()
        patch = request.model_dump(exclude_none=True)
        updated_by = patch.pop("updated_by", None)
        try:
            return service.update_default_policy(patch, updated_by=updated_by)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @r.post("/run/daily-paper-shadow")
    async def run_daily_paper_shadow(
        request: DailyPaperShadowRunRequest,
    ) -> dict[str, Any]:
        from server.app import get_app_state
        from server.routes.operations import _current_decision_and_trading_plan
        from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

        state = get_app_state()
        trading_plan = request.trading_plan
        if trading_plan is None:
            _, trading_plan = await _current_decision_and_trading_plan(state)
        generated_at = request.generated_at or trading_plan.get("generated_at")
        shadow_run = run_paper_shadow_from_trading_plan(
            db=state.db,
            trading_plan=trading_plan,
            generated_at=generated_at,
        )
        automation_run = _service().record_paper_shadow_run(
            run_date=trading_plan.get("plan_date"),
            source_ref=shadow_run.get("run_id"),
            paper_shadow_run=shadow_run,
        )
        return {
            "automation_run": automation_run,
            "paper_shadow_run": shadow_run,
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
        }

    @r.post("/run/market-session")
    async def run_market_session(
        request: MarketSessionRunRequest,
    ) -> dict[str, Any]:
        from server.app import get_app_state
        from server.routes.operations import _current_decision_and_trading_plan
        from server.services.market_session_automation import (
            MarketSessionAutomationService,
        )

        state = get_app_state()
        trading_plan = request.trading_plan
        if trading_plan is None:
            _, trading_plan = await _current_decision_and_trading_plan(state)
        now = datetime.fromisoformat(request.now) if request.now else None
        return MarketSessionAutomationService(
            db=state.db,
            trading_controls=getattr(state, "trading_controls", None),
        ).run_session(trading_plan=trading_plan, now=now)

    @r.get("/alerts")
    async def list_alerts(status: str | None = None) -> list[dict[str, Any]]:
        from server.app import get_app_state
        from server.services.automation_alerts import AutomationAlertService

        state = get_app_state()
        return AutomationAlertService(
            db=state.db,
            trading_controls=getattr(state, "trading_controls", None),
        ).list_alerts(status=status)

    @r.post("/alerts/scan")
    async def scan_alerts(
        request: AlertScanRequest | None = None,
    ) -> dict[str, Any]:
        from server.app import get_app_state
        from server.services.automation_alerts import AutomationAlertService

        state = get_app_state()
        return AutomationAlertService(
            db=state.db,
            trading_controls=getattr(state, "trading_controls", None),
            broker_connectors=_broker_connectors(state),
            connector_health=(
                request.connector_health if request is not None else None
            ),
            trading_plan=request.trading_plan if request is not None else None,
            market_health=request.market_health if request is not None else None,
            account_truth=request.account_truth if request is not None else None,
            paper_shadow_run=(
                request.paper_shadow_run if request is not None else None
            ),
        ).scan()

    @r.post("/alerts/{alert_id}/ack")
    async def acknowledge_alert(
        alert_id: int,
        request: AlertAckRequest,
    ) -> dict[str, Any]:
        from server.app import get_app_state
        from server.services.automation_alerts import AutomationAlertService

        state = get_app_state()
        try:
            return AutomationAlertService(
                db=state.db,
                trading_controls=getattr(state, "trading_controls", None),
            ).acknowledge(alert_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return r


def _service() -> AutomationControlService:
    from server.app import get_app_state

    state = get_app_state()
    return AutomationControlService(
        db=state.db,
        trading_controls=getattr(state, "trading_controls", None),
    )


def _broker_connectors(state: Any) -> list[Any]:
    config = getattr(state, "config", None)
    connectors = getattr(config, "broker_connectors", [])
    return build_broker_connectors(connectors or [])
