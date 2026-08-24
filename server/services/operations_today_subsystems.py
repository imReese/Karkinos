"""Subsystem health projections for Operations Today."""

from __future__ import annotations

from typing import Any, Iterable

from server.models import DailyOperationsSummary
from server.services.operations_today_contracts import (
    BLOCKING_ACCOUNT_STATUSES as _BLOCKING_ACCOUNT_STATUSES,
)
from server.services.operations_today_contracts import (
    BLOCKING_MARKET_STATUSES as _BLOCKING_MARKET_STATUSES,
)
from server.services.operations_today_contracts import (
    DEGRADED_MARKET_STATUSES as _DEGRADED_MARKET_STATUSES,
)
from server.services.operations_today_contracts import PASS_STATUSES as _PASS_STATUSES
from server.services.operations_today_contracts import (
    STALE_ONLY_ACCOUNT_TRUTH_BLOCKERS as _STALE_ONLY_ACCOUNT_TRUTH_BLOCKERS,
)
from server.services.operations_today_scheduler import (
    scheduler_operation_state as _scheduler_operation_state,
)
from server.services.operations_today_values import dedupe as _dedupe
from server.services.operations_today_values import dict_value as _dict
from server.services.operations_today_values import int_value as _int
from server.services.operations_today_values import (
    latest_timestamp as _latest_timestamp,
)
from server.services.operations_today_values import list_of_dicts as _list_of_dicts
from server.services.operations_today_values import list_value as _list
from server.services.operations_today_values import nested as _nested
from server.services.operations_today_values import (
    paper_shadow_status_can_accept_manual_handoff as _paper_shadow_status_can_accept_manual_handoff,
)
from server.services.operations_today_values import payload as _payload
from server.services.operations_today_values import status as _status
from server.services.operations_today_values import subsystem as _subsystem


def _citic_source_follow_up_attention(
    projection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": "citic_source_follow_up",
        "status": str(projection.get("subsystem_status") or "blocked"),
        "target": "account-truth",
        "last_run_at": projection.get("latest_reviewed_at"),
        "next_action": str(projection.get("next_manual_action") or "none"),
        "detail_status": str(projection.get("status") or "unknown"),
        "evidence_fingerprint": str(projection.get("evidence_fingerprint") or ""),
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
        operation_status = "blocked"
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


def _account_truth_subsystem(
    decision_payload: dict[str, Any],
    *,
    daily_candidate_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    account_truth = _nested(decision_payload, "summary", "account_truth")
    gate_status = _status(account_truth.get("gate_status"))
    stale_only = _account_truth_is_stale_only(account_truth)
    if gate_status in _BLOCKING_ACCOUNT_STATUSES:
        if stale_only and _is_non_trading_day(daily_candidate_schedule):
            operation_status = "skipped"
            next_action = "none"
            detail_status = "stale_non_trading_day"
        elif stale_only:
            operation_status = "blocked"
            next_action = "refresh_account_truth_snapshot"
            detail_status = "stale"
        else:
            operation_status = "blocked"
            next_action = "resolve_account_truth_mismatch"
            detail_status = gate_status
    elif gate_status in _PASS_STATUSES:
        operation_status = "pass"
        next_action = "none"
        detail_status = gate_status
    else:
        operation_status = "degraded"
        next_action = "attach_account_truth_evidence"
        detail_status = gate_status
    return _subsystem(
        "account_truth",
        operation_status,
        target="account-truth",
        last_run_at=account_truth.get("captured_at")
        or decision_payload.get("generated_at"),
        next_action=next_action,
        limitations=_list(account_truth.get("limitations")),
        detail_status=detail_status,
    )


def _account_truth_is_stale_only(account_truth: dict[str, Any]) -> bool:
    blockers = set(_list(account_truth.get("blocking_reasons")))
    return bool(blockers) and (
        _status(account_truth.get("data_freshness_status")) == "stale"
        and blockers <= _STALE_ONLY_ACCOUNT_TRUTH_BLOCKERS
        and account_truth.get("has_evidence") is True
        and account_truth.get("unresolved_mismatch_count") == 0
        and _status(account_truth.get("reconciliation_status")) in _PASS_STATUSES
        and _status(_nested(account_truth, "ledger_coverage").get("status"))
        == "covered"
    )


def _is_non_trading_day(schedule: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(schedule, dict)
        and _status(schedule.get("status")) == "not_trading_day"
        and schedule.get("due") is False
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


def _scheduler_subsystem(
    summary: dict[str, Any],
    *,
    daily_candidate_schedule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if _is_non_trading_day(daily_candidate_schedule) and str(
        summary.get("run_date") or ""
    ) != str(daily_candidate_schedule.get("run_date") or ""):
        return _subsystem(
            "scheduler",
            "skipped",
            target="scheduler",
            last_run_at=summary.get("last_run_at"),
            next_action="none",
            limitations=_list(summary.get("limitations")),
            detail_status="not_trading_day",
        )
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


citic_source_follow_up_attention = _citic_source_follow_up_attention
broker_adapter_readiness_subsystem = _broker_adapter_readiness_subsystem
broker_adapter_readiness_unavailable = _broker_adapter_readiness_unavailable
market_subsystem = _market_subsystem
account_truth_subsystem = _account_truth_subsystem
account_truth_is_stale_only = _account_truth_is_stale_only
is_non_trading_day = _is_non_trading_day
strategy_subsystem = _strategy_subsystem
risk_subsystem = _risk_subsystem
daily_plan_subsystem = _daily_plan_subsystem
paper_shadow_subsystem = _paper_shadow_subsystem
scheduler_subsystem = _scheduler_subsystem
execution_reconciliation_subsystem = _execution_reconciliation_subsystem
execution_reconciliation_summary = _execution_reconciliation_summary
execution_reconciliation_open_item = _execution_reconciliation_open_item
manual_execution_evidence_summary = _manual_execution_evidence_summary
controlled_submission_evidence_summary = _controlled_submission_evidence_summary
scheduler_retry_limitations = _scheduler_retry_limitations
acceptance_audit_subsystem = _acceptance_audit_subsystem
acceptance_audit_export_subsystem = _acceptance_audit_export_subsystem
acceptance_audit_detail_status = _acceptance_audit_detail_status
