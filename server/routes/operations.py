"""Operations center API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from analytics.acceptance_audit_report import build_acceptance_audit_export
from server.routes.decision import (
    _decision_portfolio_context,
    _today_decision_payload,
    _trading_plan_positions,
)
from server.services.broker_adapter_readiness import (
    build_broker_adapter_readiness,
)
from server.services.broker_connector_runtime import build_broker_connectors
from server.services.broker_connector_soak_promotion import (
    BrokerConnectorSoakPromotionService,
)
from server.services.citic_source_follow_up import build_citic_source_follow_up
from server.services.controlled_execution_operator_view import (
    ControlledExecutionOperatorViewService,
)
from server.services.controlled_per_order_pilot_readiness import (
    build_controlled_per_order_pilot_readiness,
)
from server.services.daily_decision_evidence_automation import (
    project_daily_candidate_background_schedule,
)
from server.services.daily_operations import build_daily_operations_summary
from server.services.daily_trading_plan import build_daily_trading_plan
from server.services.operations_today import build_operations_today_summary
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan


class PaperShadowRunReviewRequest(BaseModel):
    reviewed_at: str
    review_status: str = Field(..., min_length=1)
    review_notes: str = Field(..., min_length=1)
    reviewer: str | None = None


async def build_today_operations_payload(state: Any) -> dict[str, Any]:
    """Build the canonical persisted-fact Operations projection."""
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")

    decision_payload, trading_plan = await _current_decision_and_trading_plan(state)
    daily_candidate_schedule = project_daily_candidate_background_schedule(db=state.db)
    pending_manual_orders = _call_list(
        state.db,
        "list_manual_orders_sync",
        status="pending_confirm",
        limit=50,
        offset=0,
    )
    order_facts = _call_list(
        state.db,
        "list_orders_sync",
        limit=100,
        offset=0,
    )
    fill_facts = _call_list(
        state.db,
        "list_fills_sync",
        limit=100,
        offset=0,
    )
    automation_runs = _call_list(
        state.db,
        "list_automation_runs_sync",
        limit=20,
        offset=0,
    )
    execution_reconciliation_open_items = _call_list(
        state.db,
        "list_execution_reconciliation_open_items_sync",
        limit=20,
        offset=0,
    )
    ledger_review_count = len(
        _call_list(
            state.db,
            "get_ledger_entries_sync",
            limit=50,
            offset=0,
        )
    )
    daily_operations = build_daily_operations_summary(
        decision_summary=decision_payload.get("summary"),
        candidates=decision_payload.get("candidates", []),
        pending_manual_orders=pending_manual_orders,
        order_facts=order_facts,
        fill_facts=fill_facts,
        ledger_review_count=ledger_review_count,
    )
    paper_shadow_run = _latest_paper_shadow_run(
        state.db,
        plan_date=str(
            trading_plan.get("plan_date") or decision_payload.get("decision_date") or ""
        ),
    )
    broker_adapter_readiness = build_broker_adapter_readiness(state.db)
    citic_source_follow_up = build_citic_source_follow_up(
        getattr(state.db, "_path", None)
    )
    summary = build_operations_today_summary(
        decision_payload=decision_payload,
        trading_plan=trading_plan,
        daily_operations=daily_operations,
        order_facts=order_facts,
        fill_facts=fill_facts,
        paper_shadow_run=paper_shadow_run,
        automation_runs=automation_runs,
        execution_reconciliation_open_items=execution_reconciliation_open_items,
        acceptance_audit_export=build_acceptance_audit_export(
            selected_audit="operations_runbook",
        ),
        broker_adapter_readiness=broker_adapter_readiness,
        citic_source_follow_up=citic_source_follow_up,
        daily_candidate_schedule=daily_candidate_schedule,
    )
    return {
        **summary,
        "controlled_per_order_pilot_readiness": (
            _build_controlled_per_order_pilot_readiness(
                state,
                broker_adapter_readiness=broker_adapter_readiness,
            )
        ),
    }


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/operations", tags=["operations"])

    @router.get("/today")
    async def today_operations() -> dict[str, Any]:
        from server.dependencies import get_app_state

        return await build_today_operations_payload(get_app_state())

    @router.post("/paper-shadow/run")
    async def run_paper_shadow_daily() -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")

        decision_payload, trading_plan = await _current_decision_and_trading_plan(state)
        return run_paper_shadow_from_trading_plan(
            db=state.db,
            trading_plan=trading_plan,
            generated_at=trading_plan.get("generated_at")
            or decision_payload.get("generated_at"),
        )

    @router.post("/paper-shadow/runs/{run_id}/review")
    async def record_paper_shadow_run_review(
        run_id: str,
        payload: PaperShadowRunReviewRequest,
    ) -> dict[str, Any]:
        from server.dependencies import get_app_state

        state = get_app_state()
        if state.db is None:
            raise HTTPException(status_code=503, detail="Database is not initialized")
        review_status = payload.review_status.strip().lower()
        writer = getattr(state.db, "record_paper_shadow_run_review_sync", None)
        if not callable(writer):
            raise HTTPException(
                status_code=501,
                detail="paper shadow run reviews are not supported by this database",
            )
        try:
            reviewed = writer(
                run_id=run_id,
                reviewed_at=payload.reviewed_at,
                review_status=review_status,
                review_notes=payload.review_notes,
                reviewer=payload.reviewer,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if reviewed is None:
            raise HTTPException(status_code=404, detail="paper shadow run not found")
        return reviewed

    return router


async def _current_decision_and_trading_plan(
    state: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    portfolio_context = _decision_portfolio_context(state)
    decision_payload = await _today_decision_payload(
        state,
        portfolio_context=portfolio_context,
    )
    trading_plan = build_daily_trading_plan(
        decision_payload=decision_payload,
        config=state.config,
        positions=_trading_plan_positions(
            state,
            portfolio_context=portfolio_context,
        ),
    )
    return decision_payload, trading_plan


def _call_list(db: Any, name: str, **kwargs: Any) -> list[dict[str, Any]]:
    reader = getattr(db, name, None)
    if not callable(reader):
        return []
    try:
        rows = reader(**kwargs)
    except TypeError:
        rows = reader()
    return list(rows or [])


def _latest_paper_shadow_run(
    db: Any,
    *,
    plan_date: str,
) -> dict[str, Any] | None:
    reader = getattr(db, "latest_paper_shadow_run_sync", None)
    if not callable(reader):
        return None
    try:
        return reader(plan_date=plan_date) if plan_date else reader()
    except TypeError:
        return reader()


def _build_controlled_per_order_pilot_readiness(
    state: Any,
    *,
    broker_adapter_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose pilot admission evidence without contacting an edge."""

    from server.account_truth_gate import (
        build_latest_account_truth_promotion_evidence,
    )
    from server.routes.controlled_broker_write_release import (
        build_controlled_broker_write_release_service,
    )

    config = getattr(state, "config", None)
    connector_configs = getattr(config, "broker_connectors", []) or []
    trusted_identities = getattr(config, "trusted_operator_identities", []) or []

    def account_truth_reader() -> dict[str, Any]:
        return build_latest_account_truth_promotion_evidence(state)

    adapter = _safe_pilot_source(
        lambda: (
            broker_adapter_readiness
            if broker_adapter_readiness is not None
            else build_broker_adapter_readiness(state.db)
        ),
        schema_version="karkinos.broker_adapter_readiness.v1",
        source_name="broker_adapter_readiness",
    )
    soak = _safe_pilot_source(
        lambda: BrokerConnectorSoakPromotionService(
            db=state.db,
            connectors=build_broker_connectors(connector_configs),
            trusted_operator_identities=trusted_identities,
            account_truth_evidence_provider=account_truth_reader,
        ).get_status(),
        schema_version="karkinos.broker_connector_soak_promotion_status.v1",
        source_name="broker_soak_promotion",
    )
    try:
        write_service = build_controlled_broker_write_release_service(state)
    except Exception as exc:
        write_status = {
            "schema_version": "karkinos.controlled_broker_write_release_status.v1",
            "source_error": f"broker_write_release_status:{type(exc).__name__}",
        }
        write_releases = []
    else:
        write_status = _safe_pilot_source(
            write_service.get_status,
            schema_version="karkinos.controlled_broker_write_release_status.v1",
            source_name="broker_write_release_status",
        )
        write_releases = _safe_pilot_source_list(
            lambda: write_service.list_releases(limit=100),
        )
    operator_view = _safe_pilot_source(
        lambda: ControlledExecutionOperatorViewService(
            db=state.db,
            account_truth_evidence_reader=account_truth_reader,
        ).summary(),
        schema_version="karkinos.controlled_execution_operator_view.v4",
        source_name="controlled_execution_operator_view",
    )
    return build_controlled_per_order_pilot_readiness(
        broker_adapter_readiness=adapter,
        broker_soak_promotion=soak,
        broker_write_release_status=write_status,
        broker_write_releases=write_releases,
        controlled_execution_operator_view=operator_view,
    )


def _safe_pilot_source(
    reader: Any,
    *,
    schema_version: str,
    source_name: str,
) -> dict[str, Any]:
    try:
        value = reader()
    except Exception as exc:
        return {
            "schema_version": schema_version,
            "source_error": f"{source_name}:{type(exc).__name__}",
        }
    if not isinstance(value, dict):
        return {
            "schema_version": schema_version,
            "source_error": f"{source_name}:invalid_payload",
        }
    return value


def _safe_pilot_source_list(reader: Any) -> list[dict[str, Any]]:
    try:
        value = reader()
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]
