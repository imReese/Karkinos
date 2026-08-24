"""Read-only operations summary for the current trading workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from server.models import DailyOperationsSummary
from server.services.citic_source_follow_up import build_citic_source_follow_up
from server.services.operations_today_paper_shadow import (
    paper_shadow_run_summary as _paper_shadow_run_summary,
)
from server.services.operations_today_paper_shadow import (
    paper_shadow_summary as _paper_shadow_summary,
)
from server.services.operations_today_scheduler import (
    scheduler_summary as _scheduler_summary,
)
from server.services.operations_today_subsystems import (
    acceptance_audit_subsystem as _acceptance_audit_subsystem,
)
from server.services.operations_today_subsystems import (
    account_truth_subsystem as _account_truth_subsystem,
)
from server.services.operations_today_subsystems import (
    broker_adapter_readiness_subsystem as _broker_adapter_readiness_subsystem,
)
from server.services.operations_today_subsystems import (
    broker_adapter_readiness_unavailable as _broker_adapter_readiness_unavailable,
)
from server.services.operations_today_subsystems import (
    citic_source_follow_up_attention as _citic_source_follow_up_attention,
)
from server.services.operations_today_subsystems import (
    daily_plan_subsystem as _daily_plan_subsystem,
)
from server.services.operations_today_subsystems import (
    execution_reconciliation_subsystem as _execution_reconciliation_subsystem,
)
from server.services.operations_today_subsystems import (
    execution_reconciliation_summary as _execution_reconciliation_summary,
)
from server.services.operations_today_subsystems import (
    market_subsystem as _market_subsystem,
)
from server.services.operations_today_subsystems import (
    paper_shadow_subsystem as _paper_shadow_subsystem,
)
from server.services.operations_today_subsystems import (
    risk_subsystem as _risk_subsystem,
)
from server.services.operations_today_subsystems import (
    scheduler_subsystem as _scheduler_subsystem,
)
from server.services.operations_today_subsystems import (
    strategy_subsystem as _strategy_subsystem,
)
from server.services.operations_today_values import attention_items as _attention_items
from server.services.operations_today_values import conclusion as _conclusion
from server.services.operations_today_values import health_summary as _health_summary
from server.services.operations_today_values import int_value as _int
from server.services.operations_today_values import list_of_dicts as _list_of_dicts


def build_operations_today_summary(
    *,
    decision_payload: dict[str, Any],
    trading_plan: dict[str, Any],
    daily_operations: DailyOperationsSummary,
    order_facts: Iterable[dict[str, Any]],
    fill_facts: Iterable[dict[str, Any]],
    paper_shadow_run: dict[str, Any] | None = None,
    automation_runs: Iterable[dict[str, Any]] | None = None,
    execution_reconciliation_open_items: Iterable[dict[str, Any]] | None = None,
    acceptance_audit_export: dict[str, Any] | None = None,
    broker_adapter_readiness: dict[str, Any] | None = None,
    citic_source_follow_up: dict[str, Any] | None = None,
    daily_candidate_schedule: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a UI-facing operations summary without mutating trading state."""
    orders = list(order_facts)
    fills = list(fill_facts)
    plan_date = str(
        trading_plan.get("plan_date")
        or decision_payload.get("decision_date")
        or datetime.now().date().isoformat()
    )
    shadow = (
        _paper_shadow_run_summary(
            paper_shadow_run,
            fallback_order_intent_count=_int(trading_plan.get("order_intent_count")),
        )
        if paper_shadow_run is not None
        else _paper_shadow_summary(
            plan_date=plan_date,
            trading_plan=trading_plan,
            order_facts=orders,
            fill_facts=fills,
        )
    )
    scheduler = _scheduler_summary(
        automation_runs=automation_runs,
        plan_date=plan_date,
        fallback_detail_status=daily_operations.conclusion_status,
    )
    execution_reconciliation = _execution_reconciliation_summary(
        execution_reconciliation_open_items
    )
    subsystems = [
        _market_subsystem(decision_payload),
        _account_truth_subsystem(
            decision_payload,
            daily_candidate_schedule=daily_candidate_schedule,
        ),
        _strategy_subsystem(decision_payload, daily_operations),
        _risk_subsystem(trading_plan, daily_operations),
        _daily_plan_subsystem(trading_plan),
        _paper_shadow_subsystem(shadow),
        _scheduler_subsystem(
            scheduler,
            daily_candidate_schedule=daily_candidate_schedule,
        ),
        _execution_reconciliation_subsystem(execution_reconciliation),
        _acceptance_audit_subsystem(
            daily_operations,
            acceptance_audit_export=acceptance_audit_export,
        ),
        _broker_adapter_readiness_subsystem(broker_adapter_readiness),
    ]
    health = _health_summary(subsystems)
    conclusion_status, primary_target = _conclusion(subsystems)
    attention_items = _attention_items(subsystems)
    source_follow_up = citic_source_follow_up or build_citic_source_follow_up(None)
    attention_items.extend(
        _attention_items([_citic_source_follow_up_attention(source_follow_up)])
    )

    return {
        "schema_version": "karkinos.operations_today.v1",
        "operations_date": plan_date,
        "generated_at": generated_at or datetime.now().isoformat(),
        "conclusion_status": conclusion_status,
        "primary_target": primary_target,
        "health": health,
        "subsystems": subsystems,
        "attention_items": attention_items,
        "daily_operations": daily_operations.model_dump(),
        "daily_plan": {
            "candidate_pool_count": _int(trading_plan.get("candidate_pool_count")),
            "manual_ready_count": _int(trading_plan.get("manual_ready_count")),
            "blocked_count": _int(trading_plan.get("blocked_count")),
            "blocker_summary": _list_of_dicts(trading_plan.get("blocker_summary")),
            "order_intent_count": _int(trading_plan.get("order_intent_count")),
            "conclusion_status": str(
                trading_plan.get("conclusion_status") or "unknown"
            ),
        },
        "paper_shadow": shadow,
        "scheduler": scheduler,
        "execution_reconciliation": execution_reconciliation,
        "broker_adapter_readiness": broker_adapter_readiness
        or _broker_adapter_readiness_unavailable(),
        "citic_source_follow_up": source_follow_up,
        "limitations": [
            "Operations summary is read-only and does not submit broker orders.",
            "Broker integration remains disabled; live-like workflows require manual confirmation.",
        ],
    }
