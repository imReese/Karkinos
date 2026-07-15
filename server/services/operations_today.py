"""Read-only operations summary for the current trading workflow."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterable

from server.models import DailyOperationsSummary

_BLOCKING_MARKET_STATUSES = {"blocked", "error", "missing", "unavailable"}
_DEGRADED_MARKET_STATUSES = {"partial", "stale", "estimated", "unknown"}
_BLOCKING_ACCOUNT_STATUSES = {"blocked", "fail", "failed", "missing"}
_PASS_STATUSES = {"pass", "passed", "live", "fresh", "complete", "healthy"}
_PAPER_SHADOW_MODE = "paper_shadow"
_PAPER_SHADOW_SOURCE = "paper_shadow_daily"


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
        _account_truth_subsystem(decision_payload),
        _strategy_subsystem(decision_payload, daily_operations),
        _risk_subsystem(trading_plan, daily_operations),
        _daily_plan_subsystem(trading_plan),
        _paper_shadow_subsystem(shadow),
        _scheduler_subsystem(scheduler),
        _execution_reconciliation_subsystem(execution_reconciliation),
        _acceptance_audit_subsystem(
            daily_operations,
            acceptance_audit_export=acceptance_audit_export,
        ),
        _broker_adapter_readiness_subsystem(broker_adapter_readiness),
    ]
    health = _health_summary(subsystems)
    conclusion_status, primary_target = _conclusion(subsystems)

    return {
        "schema_version": "karkinos.operations_today.v1",
        "operations_date": plan_date,
        "generated_at": generated_at or datetime.now().isoformat(),
        "conclusion_status": conclusion_status,
        "primary_target": primary_target,
        "health": health,
        "subsystems": subsystems,
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
        "limitations": [
            "Operations summary is read-only and does not submit broker orders.",
            "Broker integration remains disabled; live-like workflows require manual confirmation.",
        ],
    }


def _broker_adapter_readiness_subsystem(
    readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    projection = readiness or _broker_adapter_readiness_unavailable()
    return _subsystem(
        "broker_adapter_evidence",
        str(projection.get("subsystem_status") or "skipped"),
        target="account-truth",
        last_run_at=(projection.get("latest_release") or {}).get(
            "collector_updated_at"
        ),
        next_action=projection.get("next_manual_action") or "none",
        limitations=_list(projection.get("limitations")),
        detail_status=str(projection.get("status") or "not_configured"),
    )


def _broker_adapter_readiness_unavailable() -> dict[str, Any]:
    return {
        "schema_version": "karkinos.broker_adapter_readiness.v1",
        "status": "not_configured",
        "subsystem_status": "skipped",
        "evidence_store_status": "unavailable",
        "configured_release_count": 0,
        "accepted_release_count": 0,
        "blocked_release_count": 0,
        "next_manual_action": "await_explicit_real_broker_environment_confirmation",
        "latest_release": None,
        "releases": [],
        "blockers": [],
        "limitations": [
            "Broker adapter evidence was not supplied to this read-only projection."
        ],
        "persisted_facts_only": True,
        "provider_contacted": False,
        "adapter_registered": False,
        "default_registered": False,
        "broker_submission_enabled": False,
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_mutate_risk_state": True,
        "does_not_mutate_kill_switch": True,
        "does_not_mutate_capital_authority": True,
        "authorizes_execution": False,
    }


def _market_subsystem(decision_payload: dict[str, Any]) -> dict[str, Any]:
    market = _nested(decision_payload, "summary", "market_data")
    status = _status(market.get("source_health"))
    if status in _BLOCKING_MARKET_STATUSES:
        operation_status = "blocked"
        next_action = "repair_market_data_source"
    elif status in _DEGRADED_MARKET_STATUSES:
        operation_status = "degraded"
        next_action = "review_market_data_freshness"
    else:
        operation_status = "pass"
        next_action = "none"
    return _subsystem(
        "market_data",
        operation_status,
        target="market",
        last_run_at=market.get("latest_quote_timestamp")
        or decision_payload.get("generated_at"),
        next_action=next_action,
        limitations=_list(market.get("limitations")),
        detail_status=status,
    )


def _account_truth_subsystem(decision_payload: dict[str, Any]) -> dict[str, Any]:
    account_truth = _nested(decision_payload, "summary", "account_truth")
    gate_status = _status(account_truth.get("gate_status"))
    if gate_status in _BLOCKING_ACCOUNT_STATUSES:
        operation_status = "blocked"
        next_action = "resolve_account_truth_mismatch"
    elif gate_status in _PASS_STATUSES:
        operation_status = "pass"
        next_action = "none"
    else:
        operation_status = "degraded"
        next_action = "attach_account_truth_evidence"
    return _subsystem(
        "account_truth",
        operation_status,
        target="account-truth",
        last_run_at=decision_payload.get("generated_at"),
        next_action=next_action,
        limitations=_list(account_truth.get("limitations")),
        detail_status=gate_status,
    )


def _strategy_subsystem(
    decision_payload: dict[str, Any],
    daily_operations: DailyOperationsSummary,
) -> dict[str, Any]:
    candidate_count = _int(_nested(decision_payload, "summary").get("candidate_count"))
    evidence_passed = daily_operations.evidence_passed_count
    if candidate_count == 0:
        status = "skipped"
        next_action = "none"
    elif evidence_passed == 0:
        status = "degraded"
        next_action = "review_strategy_evidence"
    else:
        status = "pass"
        next_action = "none"
    return _subsystem(
        "strategy_candidates",
        status,
        target="decision",
        last_run_at=decision_payload.get("generated_at"),
        next_action=next_action,
        limitations=[],
        detail_status=f"{evidence_passed}/{candidate_count}",
    )


def _risk_subsystem(
    trading_plan: dict[str, Any],
    daily_operations: DailyOperationsSummary,
) -> dict[str, Any]:
    if daily_operations.risk_blocked_count > 0:
        status = "blocked"
        next_action = "review_risk_blocks"
    elif daily_operations.risk_checked_count > 0:
        status = "pass"
        next_action = "none"
    else:
        status = "skipped"
        next_action = "none"
    return _subsystem(
        "risk",
        status,
        target="risk",
        last_run_at=trading_plan.get("generated_at"),
        next_action=next_action,
        limitations=[],
        detail_status=str(daily_operations.risk_blocked_count),
    )


def _daily_plan_subsystem(trading_plan: dict[str, Any]) -> dict[str, Any]:
    manual_ready = _int(trading_plan.get("manual_ready_count"))
    blocked = _int(trading_plan.get("blocked_count"))
    order_intents = _int(trading_plan.get("order_intent_count"))
    if blocked > 0:
        status = "blocked"
        next_action = "resolve_daily_plan_blockers"
    elif manual_ready > 0 or order_intents > 0:
        status = "manual_action_required"
        next_action = "review_manual_order_intents"
    else:
        status = "pass"
        next_action = "none"
    return _subsystem(
        "daily_trading_plan",
        status,
        target="trading",
        last_run_at=trading_plan.get("generated_at"),
        next_action=next_action,
        limitations=_list(trading_plan.get("limitations")),
        detail_status=str(trading_plan.get("conclusion_status") or "unknown"),
    )


def _paper_shadow_subsystem(shadow: dict[str, Any]) -> dict[str, Any]:
    shadow_status = str(shadow.get("status") or "not_run")
    effective_status = str(shadow.get("effective_status") or shadow_status)
    review_status = str(shadow.get("review_status") or "")
    if (
        review_status == "accepted_for_manual_confirmation"
        and _paper_shadow_status_can_accept_manual_handoff(shadow_status)
    ):
        status = "pass"
    elif shadow_status == "not_required":
        status = "skipped"
    elif shadow_status == "within_expectations":
        status = "pass"
    elif shadow_status in {"not_run", "review_required"}:
        status = "manual_action_required"
    elif shadow_status in {"diverged", "failed"}:
        status = "blocked"
    else:
        status = "degraded"
    return _subsystem(
        "paper_shadow",
        status,
        target="paper-shadow",
        last_run_at=shadow.get("last_run_at"),
        next_action=shadow.get("next_manual_review_step") or "none",
        limitations=_dedupe(
            [
                "Paper/shadow results are simulated review evidence, not broker execution."
            ]
            + _list(shadow.get("limitations"))
        ),
        detail_status=effective_status,
    )


def _scheduler_subsystem(summary: dict[str, Any]) -> dict[str, Any]:
    status, next_action = _scheduler_operation_state(str(summary.get("status") or ""))
    return _subsystem(
        "scheduler",
        status,
        target="scheduler",
        last_run_at=summary.get("last_run_at"),
        next_action=next_action,
        limitations=_dedupe(
            _list(summary.get("limitations"))
            + _scheduler_retry_limitations(summary.get("retry_state"))
        ),
        detail_status=str(summary.get("status") or "not_recorded"),
    )


def _execution_reconciliation_subsystem(summary: dict[str, Any]) -> dict[str, Any]:
    return _subsystem(
        "execution_reconciliation",
        str(summary.get("status") or "pass"),
        target="decision",
        last_run_at=summary.get("last_open_item_at"),
        next_action=summary.get("next_review_step") or "none",
        limitations=_list(summary.get("limitations")),
        detail_status=str(summary.get("detail_status") or "0 open items"),
    )


def _execution_reconciliation_summary(
    open_items: Iterable[dict[str, Any]] | None,
) -> dict[str, Any]:
    rows = _list_of_dicts(open_items)
    manual_execution_items = [
        row for row in rows if _manual_execution_evidence_summary(row)
    ]
    controlled_submission_items = [
        row for row in rows if _controlled_submission_evidence_summary(row)
    ]
    unknown_controlled_items = [
        row
        for row in controlled_submission_items
        if "unknown" in str(row.get("item_status") or "")
    ]
    first = rows[0] if rows else None
    next_step = (
        str(first.get("suggested_action") or "review_execution_reconciliation")
        if first
        else "none"
    )
    first_item = _execution_reconciliation_open_item(first) if first else None
    manual_count = len(manual_execution_items)
    return {
        "status": "manual_action_required" if rows else "pass",
        "open_item_count": len(rows),
        "manual_execution_review_count": manual_count,
        "controlled_submission_review_count": len(controlled_submission_items),
        "controlled_submission_unknown_count": len(unknown_controlled_items),
        "next_review_step": next_step,
        "last_open_item_at": _latest_timestamp(rows),
        "detail_status": (
            f"controlled_submission_unknown:{len(unknown_controlled_items)}"
            if unknown_controlled_items
            else (
                f"controlled_submission_review:{len(controlled_submission_items)}"
                if controlled_submission_items
                else (
                    f"manual_execution_recorded:{manual_count}"
                    if manual_count
                    else f"{len(rows)} open items"
                )
            )
        ),
        "first_open_item": first_item,
        "does_not_submit_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "limitations": [
            "Execution reconciliation review is read-only and does not submit broker orders.",
            "Manual execution evidence must be reconciled before any production ledger update is suggested.",
            "A controlled submission that is unknown or not yet reconciled blocks every new controlled order.",
        ],
    }


def _execution_reconciliation_open_item(
    item: dict[str, Any],
) -> dict[str, Any]:
    result = {
        "order_id": item.get("order_id"),
        "item_status": str(item.get("item_status") or "unknown"),
        "suggested_action": str(item.get("suggested_action") or "review_item"),
        "detail": str(item.get("detail") or ""),
        "manual_execution_evidence_summary": _manual_execution_evidence_summary(item),
    }
    controlled = _controlled_submission_evidence_summary(item)
    if controlled:
        result["controlled_submission_evidence_summary"] = controlled
    return result


def _manual_execution_evidence_summary(item: dict[str, Any]) -> dict[str, Any]:
    return _dict(_payload(item).get("manual_execution_evidence_summary"))


def _controlled_submission_evidence_summary(
    item: dict[str, Any],
) -> dict[str, Any]:
    return _dict(_payload(item).get("controlled_submission_evidence_summary"))


def _scheduler_retry_limitations(retry_state: Any) -> list[str]:
    retry = _dict(retry_state)
    if not retry or not bool(retry.get("retryable")):
        return []
    attempt = _int(retry.get("attempt"))
    if attempt <= 1:
        return []
    max_attempts = max(_int(retry.get("max_attempts")), attempt)
    previous_attempts = _int(retry.get("previous_attempts"))
    suffix = f"; previous attempts: {previous_attempts}." if previous_attempts else "."
    return [f"Scheduler retry attempt {attempt} of {max_attempts}{suffix}"]


def _acceptance_audit_subsystem(
    daily_operations: DailyOperationsSummary,
    *,
    acceptance_audit_export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if acceptance_audit_export is not None:
        return _acceptance_audit_export_subsystem(acceptance_audit_export)

    if daily_operations.ledger_review_count > 0:
        status = "manual_action_required"
        next_action = "review_ledger_items"
    else:
        status = "pass"
        next_action = "none"
    return _subsystem(
        "acceptance_audit",
        status,
        target="audit",
        last_run_at=None,
        next_action=next_action,
        limitations=[],
        detail_status=str(daily_operations.ledger_review_count),
    )


def _acceptance_audit_export_subsystem(
    acceptance_audit_export: dict[str, Any],
) -> dict[str, Any]:
    audits = _list_of_dicts(acceptance_audit_export.get("audits"))
    required_count = sum(_int(audit.get("required_count")) for audit in audits)
    completed_count = sum(_int(audit.get("completed_count")) for audit in audits)
    complete_audit_count = sum(1 for audit in audits if bool(audit.get("is_complete")))
    is_complete = (
        bool(acceptance_audit_export.get("overall_is_complete"))
        and required_count > 0
        and completed_count == required_count
    )
    if is_complete:
        status = "pass"
        next_action = "none"
    elif audits:
        status = "manual_action_required"
        next_action = "review_acceptance_audit_gaps"
    else:
        status = "degraded"
        next_action = "export_acceptance_audit"

    return _subsystem(
        "acceptance_audit",
        status,
        target="audit",
        last_run_at=acceptance_audit_export.get("generated_at"),
        next_action=next_action,
        limitations=_dedupe(
            limitation
            for audit in audits
            for limitation in _list(audit.get("limitations"))
        ),
        detail_status=_acceptance_audit_detail_status(
            audits=audits,
            complete_audit_count=complete_audit_count,
            required_count=required_count,
            completed_count=completed_count,
        ),
    )


def _acceptance_audit_detail_status(
    *,
    audits: list[dict[str, Any]],
    complete_audit_count: int,
    required_count: int,
    completed_count: int,
) -> str:
    if len(audits) == 1:
        audit = audits[0]
        key = str(audit.get("key") or "acceptance_audit")
        return f"{key}:{completed_count}/{required_count}"
    if audits:
        return (
            f"{complete_audit_count}/{len(audits)} audits; "
            f"{completed_count}/{required_count} criteria"
        )
    return "0/0 criteria"


def _paper_shadow_summary(
    *,
    plan_date: str,
    trading_plan: dict[str, Any],
    order_facts: list[dict[str, Any]],
    fill_facts: list[dict[str, Any]],
) -> dict[str, Any]:
    order_intent_count = _int(trading_plan.get("order_intent_count"))
    run_id = f"shadow:{plan_date}"
    orders = [
        order
        for order in order_facts
        if _is_daily_shadow_order(order, run_id=run_id, plan_date=plan_date)
    ]
    order_ids = {
        str(order.get("order_id")) for order in orders if order.get("order_id")
    }
    fills = [
        fill
        for fill in fill_facts
        if str(fill.get("execution_mode") or "").lower() == _PAPER_SHADOW_MODE
        or str(fill.get("source") or "").lower() == _PAPER_SHADOW_SOURCE
        or str(fill.get("order_id")) in order_ids
    ]
    divergence_statuses = [
        status
        for order in orders
        if (status := _payload_status(order, "divergence_status")) is not None
    ]
    reviewed_count = len(divergence_statuses)
    if order_intent_count == 0:
        status = "not_required"
        next_step = "none"
    elif not orders:
        status = "not_run"
        next_step = "run_paper_shadow_daily"
    elif reviewed_count < len(orders):
        status = "review_required"
        next_step = "review_shadow_divergence"
    elif all(item == "within_expectations" for item in divergence_statuses):
        status = "within_expectations"
        next_step = "review_manual_confirmation"
    else:
        status = "diverged"
        next_step = "resolve_shadow_divergence"
    return {
        "status": status,
        "effective_status": status,
        "run_id": run_id if orders or order_intent_count > 0 else None,
        "order_intent_count": order_intent_count,
        "simulated_order_count": len(orders),
        "simulated_fill_count": len(fills),
        "divergence_reviewed_count": reviewed_count,
        "divergence_status": status,
        "next_manual_review_step": next_step,
        "last_run_at": _latest_timestamp(orders + fills),
        "orders": [
            {
                "order_id": order.get("order_id"),
                "symbol": order.get("symbol"),
                "status": order.get("status"),
                "divergence_status": _payload_status(order, "divergence_status"),
            }
            for order in orders[:5]
        ],
        "review_queue": [],
        "manual_handoff": _paper_shadow_manual_handoff(
            status=status,
            effective_status=status,
            review_status=None,
            reviewed_at=None,
            reviewer=None,
            next_manual_review_step=next_step,
            review_queue=[],
        ),
    }


def _paper_shadow_run_summary(
    run: dict[str, Any],
    *,
    fallback_order_intent_count: int,
) -> dict[str, Any]:
    payload = _payload(run)
    review = _dict(payload.get("review"))
    orders = _list_of_dicts(payload.get("orders"))
    fills = _list_of_dicts(payload.get("fills"))
    status = str(run.get("status") or "not_run")
    divergence_status = str(run.get("divergence_status") or status)
    review_status = str(
        run.get("review_status") or review.get("review_status") or ""
    ).strip()
    effective_status = _paper_shadow_effective_status(
        status=status,
        review_status=review_status,
    )
    review_queue = _list_of_dicts(payload.get("review_queue"))
    reviewed_count = len(
        [order for order in orders if str(order.get("divergence_status") or "").strip()]
    )
    review_queue = review_queue or _fallback_paper_shadow_review_queue(
        run_id=run.get("run_id"),
        status=status,
        orders=orders,
        divergence_summary=_dict(payload.get("divergence_summary")),
    )
    next_manual_review_step = _paper_shadow_default_next_step(
        status=status,
        value=run.get("next_manual_review_step"),
        review_status=review_status,
    )
    return {
        "status": status,
        "effective_status": effective_status,
        "run_id": run.get("run_id"),
        "input_fingerprint": run.get("input_fingerprint"),
        "input_snapshot": _dict(payload.get("input_snapshot")),
        "evidence_refs": _list(payload.get("evidence_refs")),
        "order_intent_count": _int(
            run.get("order_intent_count"),
            fallback_order_intent_count,
        ),
        "simulated_order_count": _int(
            run.get("simulated_order_count"),
            len(orders),
        ),
        "simulated_fill_count": _int(run.get("simulated_fill_count"), len(fills)),
        "divergence_reviewed_count": reviewed_count,
        "divergence_status": divergence_status,
        "review_status": review_status,
        "reviewed_at": run.get("reviewed_at") or review.get("reviewed_at"),
        "reviewer": run.get("reviewer") or review.get("reviewer"),
        "next_manual_review_step": next_manual_review_step,
        "last_run_at": run.get("updated_at") or run.get("created_at"),
        "limitations": _json_list(run.get("limitations_json")),
        "orders": orders[:5],
        "review_queue": review_queue,
        "divergence_summary": _dict(payload.get("divergence_summary")),
        "manual_handoff": _paper_shadow_manual_handoff(
            status=status,
            effective_status=effective_status,
            review_status=review_status or None,
            reviewed_at=run.get("reviewed_at") or review.get("reviewed_at"),
            reviewer=run.get("reviewer") or review.get("reviewer"),
            next_manual_review_step=next_manual_review_step,
            review_queue=review_queue,
        ),
    }


def _paper_shadow_manual_handoff(
    *,
    status: str,
    effective_status: str,
    review_status: str | None,
    reviewed_at: Any,
    reviewer: Any,
    next_manual_review_step: str,
    review_queue: list[dict[str, Any]],
) -> dict[str, Any]:
    run_status = str(status or "").strip().lower()
    effective = str(effective_status or run_status).strip().lower()
    review = str(review_status or "").strip() or None
    required_actions = _paper_shadow_handoff_required_actions(
        next_manual_review_step=next_manual_review_step,
        review_queue=review_queue,
    )
    ready = False
    handoff_status = "blocked_by_paper_shadow_review"
    blockers: list[str] = []

    if effective == "accepted_for_manual_confirmation":
        ready = True
        handoff_status = "ready_after_accepted_review"
        required_actions = ["review_manual_confirmation"]
    elif run_status == "within_expectations":
        ready = True
        handoff_status = "ready_after_clean_simulation"
        required_actions = ["review_manual_confirmation"]
    elif run_status == "not_required":
        handoff_status = "not_required"
        required_actions = ["none"]
    elif run_status == "not_run":
        handoff_status = "paper_shadow_required"
        blockers = ["paper_shadow_run_not_run"]
    elif run_status == "running":
        handoff_status = "waiting_for_paper_shadow_run"
        blockers = ["paper_shadow_run_running"]
    elif run_status == "failed":
        handoff_status = "blocked_by_failed_run"
        blockers = ["failed_paper_shadow_run"]
    elif review == "needs_rerun":
        handoff_status = "blocked_by_review_requested_rerun"
        blockers = ["paper_shadow_review_requested_rerun"]
    elif run_status in {"diverged", "review_required"}:
        handoff_status = "blocked_by_unresolved_divergence"
        blockers = ["unresolved_paper_shadow_divergence"]

    return {
        "ready": ready,
        "status": handoff_status,
        "blockers": blockers,
        "required_actions": required_actions,
        "review_queue_count": len(review_queue),
        "highest_severity": _paper_shadow_highest_review_severity(review_queue),
        "review_status": review,
        "reviewed_at": reviewed_at,
        "reviewer": reviewer,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _paper_shadow_handoff_required_actions(
    *,
    next_manual_review_step: str,
    review_queue: list[dict[str, Any]],
) -> list[str]:
    actions = [
        str(item.get("required_action") or "").strip()
        for item in review_queue
        if str(item.get("required_action") or "").strip()
    ]
    next_step = str(next_manual_review_step or "").strip()
    if next_step:
        actions.append(next_step)
    return _dedupe(actions) or ["none"]


def _paper_shadow_highest_review_severity(
    review_queue: list[dict[str, Any]],
) -> str | None:
    rank = {"danger": 3, "warning": 2, "info": 1}
    highest: str | None = None
    highest_rank = 0
    for item in review_queue:
        severity = str(item.get("severity") or "").strip().lower()
        severity_rank = rank.get(severity, 0)
        if severity_rank > highest_rank:
            highest = severity
            highest_rank = severity_rank
    return highest


def _fallback_paper_shadow_review_queue(
    *,
    run_id: Any,
    status: str,
    orders: list[dict[str, Any]],
    divergence_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    run_status = str(status or "").strip().lower()
    if run_status in {"not_run", "not_required", "within_expectations"}:
        return []
    queue: list[dict[str, Any]] = []
    for order in orders:
        item = _fallback_paper_shadow_review_item(
            run_id=run_id,
            run_status=run_status,
            order=order,
        )
        if item:
            queue.append(item)
    queue.extend(
        _fallback_missing_simulation_review_items(
            run_id=run_id,
            divergence_summary=divergence_summary,
        )
    )
    return queue


def _fallback_paper_shadow_review_item(
    *,
    run_id: Any,
    run_status: str,
    order: dict[str, Any],
) -> dict[str, Any] | None:
    order_status = str(order.get("status") or "").strip().lower()
    divergence_status = str(order.get("divergence_status") or "").strip().lower()
    if order_status == "filled" and divergence_status == "within_expectations":
        return None

    intent_ref = str(
        _dict(order.get("order_intent")).get("action_ref")
        or order.get("order_intent_ref")
        or ""
    ).strip()
    order_id = str(order.get("order_id") or "").strip()
    required_action, severity, reason = _fallback_paper_shadow_review_action(
        run_status=run_status,
        order_status=order_status,
        divergence_status=divergence_status,
        intent_ref=intent_ref,
        order_id=order_id,
    )
    item = {
        "review_id": f"{run_id}:{_fallback_review_suffix(intent_ref or order_id)}",
        "order_intent_ref": intent_ref,
        "order_id": order_id or None,
        "symbol": order.get("symbol"),
        "status": order_status or "review_required",
        "divergence_status": divergence_status or "review_required",
        "severity": severity,
        "required_action": required_action,
        "reason": reason,
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    transition_evidence = _fallback_paper_shadow_oms_evidence(
        order=order,
        order_id=order_id,
    )
    if transition_evidence:
        item.update(transition_evidence)
        item["evidence_refs"] = _dedupe(
            [intent_ref]
            + ([f"paper_order:{order_id}"] if order_id else [])
            + _list(transition_evidence.get("oms_transition_refs"))
        )
    for key in ("filled_quantity", "remaining_quantity"):
        if order.get(key) is not None:
            item[key] = order.get(key)
    return item


def _fallback_paper_shadow_oms_evidence(
    *,
    order: dict[str, Any],
    order_id: str,
) -> dict[str, Any]:
    transitions = [
        _fallback_paper_shadow_oms_transition(item)
        for item in _list_of_dicts(order.get("oms_transitions"))
    ]
    transitions = [item for item in transitions if item.get("to_status")]
    if not transitions:
        return {}

    transition_refs = [
        f"oms_transition:{order_id}:{item['sequence']}:{item['to_status']}"
        for item in transitions
        if order_id and item.get("sequence") is not None and item.get("to_status")
    ]
    evidence: dict[str, Any] = {
        "oms_status_path": [str(item["to_status"]) for item in transitions],
        "oms_transition_refs": transition_refs,
        "oms_transitions": transitions,
    }
    terminal = _fallback_terminal_oms_transition(
        transitions=transitions,
        status=str(order.get("status") or ""),
    )
    if terminal:
        terminal_status = str(terminal.get("to_status") or "")
        evidence["terminal_status"] = terminal_status
        evidence["terminal_reason"] = str(terminal.get("reason") or "")
        if order_id and terminal.get("sequence") is not None and terminal_status:
            evidence["terminal_oms_transition_ref"] = (
                f"oms_transition:{order_id}:{terminal['sequence']}:{terminal_status}"
            )
    return evidence


def _fallback_paper_shadow_oms_transition(
    transition: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sequence": transition.get("sequence"),
        "from_status": transition.get("from_status"),
        "to_status": transition.get("to_status"),
        "source": transition.get("source"),
        "reason": transition.get("reason") or "",
        "filled_quantity": transition.get("filled_quantity"),
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }


def _fallback_terminal_oms_transition(
    *,
    transitions: list[dict[str, Any]],
    status: str,
) -> dict[str, Any] | None:
    terminal_statuses = {"rejected", "cancelled", "expired", "failed"}
    expected_status = str(status or "").strip().lower()
    if expected_status not in terminal_statuses:
        return None
    return next(
        (
            item
            for item in reversed(transitions)
            if str(item.get("to_status") or "").strip().lower() == expected_status
        ),
        None,
    )


def _fallback_paper_shadow_review_action(
    *,
    run_status: str,
    order_status: str,
    divergence_status: str,
    intent_ref: str,
    order_id: str,
) -> tuple[str, str, str]:
    if (
        run_status == "failed"
        or order_status == "failed"
        or divergence_status == "failed"
    ):
        ref = intent_ref or order_id or "paper/shadow order"
        return (
            "inspect_failed_run",
            "danger",
            f"Paper/shadow simulation failed for {ref}; inspect the failed run before manual confirmation.",
        )
    if run_status == "diverged" or divergence_status == "diverged":
        status = order_status or "unknown"
        return (
            "resolve_shadow_divergence",
            "warning",
            f"Paper/shadow order {status} requires divergence review before manual confirmation.",
        )
    return (
        "review_shadow_divergence",
        "warning",
        "Paper/shadow order requires review before manual confirmation.",
    )


def _fallback_review_suffix(value: str) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.split(":", 1)[1]
    return text or "unknown"


def _fallback_missing_simulation_review_items(
    *,
    run_id: Any,
    divergence_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    execution = _dict(_dict(divergence_summary).get("execution_comparison"))
    missing_refs = _list(execution.get("missing_order_intent_refs"))
    return [
        {
            "review_id": f"{run_id}:{_fallback_review_suffix(intent_ref)}",
            "order_intent_ref": intent_ref,
            "order_id": None,
            "symbol": None,
            "status": "missing_simulation",
            "divergence_status": "review_required",
            "severity": "warning",
            "required_action": "review_shadow_divergence",
            "reason": (
                f"Paper/shadow simulation is missing for {intent_ref}; "
                "review the order intent before manual confirmation."
            ),
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        }
        for intent_ref in missing_refs
    ]


def _paper_shadow_effective_status(
    *,
    status: str,
    review_status: str,
) -> str:
    if (
        review_status == "accepted_for_manual_confirmation"
        and _paper_shadow_status_can_accept_manual_handoff(status)
    ):
        return "accepted_for_manual_confirmation"
    return status


def _paper_shadow_status_can_accept_manual_handoff(status: str) -> bool:
    return str(status or "").strip().lower() in {
        "diverged",
        "review_required",
        "within_expectations",
    }


def _scheduler_summary(
    *,
    automation_runs: Iterable[dict[str, Any]] | None,
    plan_date: str,
    fallback_detail_status: str,
) -> dict[str, Any]:
    latest_run = _latest_automation_run(
        automation_runs=automation_runs,
        plan_date=plan_date,
    )
    if latest_run is None:
        return {
            "status": str(fallback_detail_status or "not_recorded"),
            "run_id": None,
            "run_type": "scheduler",
            "run_date": plan_date,
            "execution_mode": "paper_shadow",
            "last_run_at": plan_date,
            "input_fingerprint": None,
            "idempotency_key": None,
            "input_snapshot": {},
            "retry_state": {},
            "error": {},
            "broker_submission_enabled": False,
            "does_not_submit_broker_order": True,
            "limitations": [
                "Daily scheduler state is summarized from current local records."
            ],
        }

    payload = _payload(latest_run)
    status = str(latest_run.get("status") or "unknown")
    run_type = latest_run.get("run_type")
    execution_mode = latest_run.get("execution_mode") or "paper_shadow"
    retry_state = _dict(payload.get("retry_state"))
    is_failure = _scheduler_run_failed(status)
    return {
        "status": status,
        "run_id": latest_run.get("run_id"),
        "run_type": run_type,
        "run_date": latest_run.get("run_date") or plan_date,
        "execution_mode": execution_mode,
        "last_run_at": latest_run.get("finished_at")
        or latest_run.get("updated_at")
        or latest_run.get("started_at")
        or latest_run.get("created_at"),
        "input_fingerprint": payload.get("input_fingerprint"),
        "idempotency_key": payload.get("idempotency_key"),
        "input_snapshot": _dict(payload.get("input_snapshot")),
        "retry_state": retry_state,
        "error": _dict(payload.get("error")),
        "suggested_action": _scheduler_suggested_action(
            status=status,
            run_type=run_type,
            execution_mode=execution_mode,
        ),
        "requires_manual_review": is_failure,
        "retry_recommended": is_failure and bool(retry_state.get("retryable")),
        "broker_submission_enabled": bool(payload.get("broker_submission_enabled")),
        "does_not_submit_broker_order": payload.get("does_not_submit_broker_order")
        is not False,
        "does_not_mutate_production_ledger": payload.get(
            "does_not_mutate_production_ledger"
        )
        is not False,
        "limitations": _list(payload.get("limitations")),
    }


def _latest_automation_run(
    *,
    automation_runs: Iterable[dict[str, Any]] | None,
    plan_date: str,
) -> dict[str, Any] | None:
    if automation_runs is None:
        return None
    rows = [
        row
        for row in automation_runs
        if isinstance(row, dict)
        and str(row.get("run_type") or "") == "market_session"
        and (not plan_date or str(row.get("run_date") or "") == plan_date)
    ]
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: str(
            row.get("finished_at")
            or row.get("updated_at")
            or row.get("started_at")
            or row.get("created_at")
            or ""
        ),
    )


def _scheduler_operation_state(run_status: str) -> tuple[str, str]:
    status = run_status.strip().lower()
    if status.endswith("_failed") or status in {"failed", "error"}:
        return "blocked", "inspect_scheduler_failure"
    if status == "blocked_by_kill_switch":
        return "blocked", "resolve_kill_switch"
    if status in {"skipped_non_trading_session", "skipped"}:
        return "skipped", "none"
    if status in {"paper_shadow_completed", "completed", "success", "pass"}:
        return "pass", "none"
    if status in {"pending_manual_confirmation", "not_recorded", ""}:
        return "pass", "none"
    return "degraded", "review_scheduler_run"


def _scheduler_run_failed(status: str) -> bool:
    value = str(status or "").strip().lower()
    return value.endswith("_failed") or value in {"failed", "error"}


def _scheduler_suggested_action(
    *,
    status: str,
    run_type: Any,
    execution_mode: Any,
) -> str:
    value = str(status or "").strip().lower()
    if value == "blocked_by_kill_switch":
        return "resolve_kill_switch"
    if value == "paper_shadow_failed" and str(execution_mode or "") == "paper_shadow":
        return "inspect_failed_paper_shadow_run"
    if _scheduler_run_failed(value) and str(run_type or "") == "market_session":
        return "inspect_scheduler_failure"
    if _scheduler_run_failed(value):
        return "inspect_failed_automation_run"
    if value in {"skipped_non_trading_session", "skipped"}:
        return "none"
    if value in {"paper_shadow_completed", "completed", "success", "pass"}:
        return "none"
    if value in {"pending_manual_confirmation", "not_recorded", ""}:
        return "none"
    return "review_scheduler_run"


def _is_daily_shadow_order(
    order: dict[str, Any],
    *,
    run_id: str,
    plan_date: str,
) -> bool:
    if str(order.get("execution_mode") or "").lower() == _PAPER_SHADOW_MODE:
        return True
    if str(order.get("source") or "").lower() == _PAPER_SHADOW_SOURCE:
        return True
    payload = _payload(order)
    if payload.get("run_id") == run_id:
        return True
    return str(order.get("order_id") or "").startswith(f"SHADOW-{plan_date}-")


def _paper_shadow_default_next_step(
    *,
    status: str,
    value: Any,
    review_status: Any = None,
) -> str:
    review = str(review_status or "").strip().lower()
    if (
        review == "accepted_for_manual_confirmation"
        and _paper_shadow_status_can_accept_manual_handoff(status)
    ):
        return "review_manual_confirmation"
    if review == "needs_rerun":
        return "run_paper_shadow_daily"
    if status == "failed":
        return "inspect_failed_run"
    text = str(value or "").strip()
    if text:
        return text
    if status == "running":
        return "wait_for_paper_shadow_run"
    if status == "within_expectations":
        return "review_manual_confirmation"
    if status == "failed":
        return "inspect_failed_run"
    if status == "diverged":
        return "resolve_shadow_divergence"
    if status in {"not_required", "not_run"}:
        return "none" if status == "not_required" else "run_paper_shadow_daily"
    return "review_shadow_divergence"


def _payload_status(order: dict[str, Any], key: str) -> str | None:
    value = _payload(order).get(key)
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload_json") or order.get("payload")
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        return {}
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _subsystem(
    subsystem_id: str,
    status: str,
    *,
    target: str,
    last_run_at: Any,
    next_action: Any,
    limitations: list[str],
    detail_status: str,
) -> dict[str, Any]:
    return {
        "id": subsystem_id,
        "status": status,
        "tone": _tone(status),
        "target": target,
        "last_run_at": last_run_at,
        "next_action": str(next_action or "none"),
        "limitations": limitations,
        "detail_status": detail_status,
    }


def _health_summary(subsystems: list[dict[str, Any]]) -> dict[str, int]:
    statuses = [str(item.get("status") or "unknown") for item in subsystems]
    return {
        "total": len(statuses),
        "pass": statuses.count("pass"),
        "degraded": statuses.count("degraded"),
        "blocked": statuses.count("blocked"),
        "manual_action_required": statuses.count("manual_action_required"),
        "skipped": statuses.count("skipped"),
    }


def _conclusion(subsystems: list[dict[str, Any]]) -> tuple[str, str]:
    blocked = next(
        (item for item in subsystems if item.get("status") == "blocked"),
        None,
    )
    if blocked is not None:
        return "blocked", str(blocked.get("target") or blocked.get("id") or "decision")

    waiting_shadow = next(
        (
            item
            for item in subsystems
            if item.get("id") == "paper_shadow"
            and item.get("status") == "degraded"
            and item.get("next_action") == "wait_for_paper_shadow_run"
        ),
        None,
    )
    if waiting_shadow is not None:
        return "degraded", str(
            waiting_shadow.get("target") or waiting_shadow.get("id") or "decision"
        )

    for status in ("manual_action_required", "degraded"):
        match = None
        if status == "manual_action_required":
            match = next(
                (
                    item
                    for item in subsystems
                    if item.get("id") == "paper_shadow"
                    and item.get("status") == "manual_action_required"
                ),
                None,
            )
        match = match or next(
            (item for item in subsystems if item.get("status") == status),
            None,
        )
        if match is not None:
            return status, str(match.get("target") or match.get("id") or "decision")
    return "healthy", "decision"


def _tone(status: str) -> str:
    if status == "blocked":
        return "danger"
    if status in {"manual_action_required", "degraded"}:
        return "warning"
    return "neutral" if status == "skipped" else "success"


def _latest_timestamp(rows: list[dict[str, Any]]) -> str | None:
    timestamps = [
        str(row.get("updated_at") or row.get("timestamp") or row.get("created_at"))
        for row in rows
        if row.get("updated_at") or row.get("timestamp") or row.get("created_at")
    ]
    return max(timestamps) if timestamps else None


def _nested(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _status(value: Any, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    return text or default


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _json_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return _list(value)
        return _list(parsed)
    return _list(value)


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
