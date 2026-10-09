"""Unified account-plan paper/shadow simulation orchestration.

Coordinates account plan preparation, capital/date constraint checks,
simulation execution, and audit logging across Operations, Trading, and Automation.
Independent research paper books remain strictly decoupled with distinct ledgers.
"""

from __future__ import annotations

from inspect import isawaitable
from typing import Any

from fastapi import HTTPException

from server.services import (
    daily_trading_plan,
    decision_application,
    decision_projection,
    paper_shadow_run,
)


async def orchestrate_account_paper_shadow(
    state: Any,
    *,
    trading_plan: dict[str, Any] | None = None,
    generated_at: str | None = None,
    run_date: str | None = None,
    base_equity: Any | None = None,
    automation_service: Any | None = None,
    broadcast_event: bool = False,
) -> dict[str, Any]:
    """Execute account-plan paper/shadow simulation with canonical constraints."""
    if state.db is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")

    if base_equity is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "caller-supplied shadow base_equity is disabled; "
                "canonical persisted Account Truth must own sizing"
            ),
        )

    plan_generated_at = None
    if trading_plan is None:
        portfolio_context = decision_application.decision_portfolio_context(state)
        decision_payload = await decision_application.today_decision_payload(
            state,
            portfolio_context=portfolio_context,
        )
        decision_payload = (
            decision_projection.suppress_unverified_daily_scan_candidates(
                decision_payload
            )
        )
        trading_plan = daily_trading_plan.build_daily_trading_plan(
            decision_payload=decision_payload,
            config=getattr(state, "config", None),
            positions=decision_application.trading_plan_positions(
                state,
                portfolio_context=portfolio_context,
            ),
        )
        plan_generated_at = decision_payload.get("generated_at")

    plan_date = str(trading_plan.get("plan_date") or "")
    if run_date is not None and run_date != plan_date:
        raise HTTPException(
            status_code=409,
            detail=(
                "requested shadow run_date does not match the canonical "
                f"persisted plan date: {plan_date or 'missing'}"
            ),
        )

    effective_generated_at = (
        generated_at or trading_plan.get("generated_at") or plan_generated_at
    )

    shadow_run = paper_shadow_run.run_paper_shadow_from_trading_plan(
        db=state.db,
        trading_plan=trading_plan,
        generated_at=effective_generated_at,
    )

    if broadcast_event:
        hub = getattr(state, "hub", None)
        if hub is not None and hasattr(hub, "broadcast"):
            result = hub.broadcast(
                {"event_type": "DailyShadowRunRecorded", "payload": shadow_run}
            )
            if isawaitable(result):
                await result

    if automation_service is not None:
        automation_run = automation_service.record_paper_shadow_run(
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

    return shadow_run
