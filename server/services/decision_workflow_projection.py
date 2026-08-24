"""Decision summary and operator-workflow projections."""

from __future__ import annotations

from typing import Any

from server.services.decision_contracts import TRUSTED_DATA_STATUSES
from server.services.decision_portfolio_projection import (
    market_data_summary,
    portfolio_state_summary,
)


def decision_summary(
    state: Any,
    *,
    actions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    journal_by_signal: dict[int, dict[str, Any]],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    portfolio_context: dict[str, Any],
) -> dict[str, Any]:
    risk_blocked_count = sum(
        1 for candidate in candidates if candidate["risk_gate_status"] == "blocked"
    )
    ready_for_manual_confirmation_count = sum(
        1
        for candidate in candidates
        if candidate["manual_confirmation_status"] == "ready_for_manual_confirmation"
    )
    market_data = market_data_summary(
        state,
        actions,
        portfolio_context=portfolio_context,
    )
    action_tasks = action_task_summary(actions)
    audit = audit_summary(actions, candidates, journal_by_signal)
    return {
        "candidate_count": len(candidates),
        "risk_blocked_count": risk_blocked_count,
        "ready_for_manual_confirmation_count": ready_for_manual_confirmation_count,
        "portfolio": portfolio_state_summary(
            state,
            portfolio_context=portfolio_context,
        ),
        "market_data": market_data,
        "account_truth": account_truth,
        "strategy_attribution": strategy_attribution,
        "action_tasks": action_tasks,
        "audit": audit,
        "workflow_tasks": workflow_tasks(
            market_data=market_data,
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            action_tasks=action_tasks,
            audit=audit,
            candidate_count=len(candidates),
            ready_for_manual_confirmation_count=ready_for_manual_confirmation_count,
        ),
    }


def action_task_summary(actions: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(action.get("status") or "unknown") for action in actions]
    return {
        "total_count": len(actions),
        "pending_count": statuses.count("pending"),
        "deferred_count": statuses.count("deferred"),
        "symbols": [
            str(action.get("symbol")) for action in actions if action.get("symbol")
        ],
    }


def audit_summary(
    actions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    journal_by_signal: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "signal_count": len(
            {
                action.get("source_signal_id")
                for action in actions
                if action.get("source_signal_id") is not None
            }
        ),
        "journal_entry_count": len(journal_by_signal),
        "risk_checked_count": sum(
            1
            for action in actions
            if action.get("risk_gate_status") in {"passed", "blocked"}
            or action.get("risk_gate_passed") is not None
        ),
        "risk_blocked_count": sum(
            1 for candidate in candidates if candidate["risk_gate_status"] == "blocked"
        ),
    }


def workflow_tasks(
    *,
    market_data: dict[str, Any],
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    action_tasks: dict[str, Any],
    audit: dict[str, Any],
    candidate_count: int,
    ready_for_manual_confirmation_count: int,
) -> list[dict[str, Any]]:
    return [
        data_refresh_workflow_task(market_data),
        account_truth_workflow_task(account_truth),
        risk_review_workflow_task(action_tasks, audit),
        strategy_evidence_workflow_task(strategy_attribution, candidate_count),
        paper_shadow_workflow_task(candidate_count),
        manual_confirmation_workflow_task(
            account_truth=account_truth,
            strategy_attribution=strategy_attribution,
            audit=audit,
            candidate_count=candidate_count,
            ready_for_manual_confirmation_count=ready_for_manual_confirmation_count,
        ),
    ]


def data_refresh_workflow_task(market_data: dict[str, Any]) -> dict[str, Any]:
    source_health = str(market_data.get("source_health") or "unknown")
    if source_health in TRUSTED_DATA_STATUSES:
        status = "pass"
        required_actions: list[str] = []
        blocking_reasons: list[str] = []
        description = "Market data is trusted for the decision universe."
    elif source_health == "missing":
        status = "blocked"
        required_actions = ["refresh_market_data"]
        blocking_reasons = ["market_data_missing"]
        description = "Decision data is missing for the selected universe."
    else:
        status = "blocked"
        required_actions = ["refresh_or_confirm_market_data"]
        blocking_reasons = ["market_data_not_fully_live"]
        description = (
            "Decision risk writes are blocked while quotes are stale, cached, "
            "estimated, or only partially available."
        )
    return workflow_task(
        task_id="data_refresh",
        priority=10,
        status=status,
        title="Data refresh",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "source_health": source_health,
            "quote_count": market_data.get("quote_count"),
            "missing_symbols": list(market_data.get("missing_symbols") or []),
            "latest_quote_timestamp": market_data.get("latest_quote_timestamp"),
        },
    )


def account_truth_workflow_task(account_truth: dict[str, Any]) -> dict[str, Any]:
    gate_status = str(account_truth.get("gate_status") or "blocked")
    if gate_status == "pass":
        status = "pass"
    elif gate_status == "degraded":
        status = "degraded"
    else:
        status = "blocked"
    return workflow_task(
        task_id="account_truth",
        priority=20,
        status=status,
        title="Account truth",
        description="Broker evidence and local account facts are checked before action review.",
        required_actions=list(account_truth.get("required_actions") or []),
        blocking_reasons=list(account_truth.get("blocking_reasons") or []),
        evidence={
            "gate_status": gate_status,
            "score": account_truth.get("score"),
            "has_evidence": bool(account_truth.get("has_evidence")),
            "unresolved_mismatch_count": account_truth.get("unresolved_mismatch_count"),
        },
    )


def risk_review_workflow_task(
    action_tasks: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    total_count = int(action_tasks.get("total_count") or 0)
    risk_checked_count = int(audit.get("risk_checked_count") or 0)
    risk_blocked_count = int(audit.get("risk_blocked_count") or 0)
    if risk_blocked_count:
        status = "blocked"
        required_actions = ["review_risk_blockers"]
        blocking_reasons = ["risk_gate_blocked"]
        description = "At least one candidate is blocked by the pre-trade risk gate."
    elif total_count and risk_checked_count < total_count:
        status = "review_required"
        required_actions = ["run_pre_trade_risk_gate"]
        blocking_reasons = ["risk_gate_not_checked"]
        description = "Some candidate actions still need risk-gate evidence."
    else:
        status = "pass"
        required_actions = []
        blocking_reasons = []
        description = "Risk-gate evidence is present for the current candidates."
    return workflow_task(
        task_id="risk_review",
        priority=30,
        status=status,
        title="Risk review",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "total_action_count": total_count,
            "risk_checked_count": risk_checked_count,
            "risk_blocked_count": risk_blocked_count,
        },
    )


def strategy_evidence_workflow_task(
    strategy_attribution: dict[str, Any],
    candidate_count: int,
) -> dict[str, Any]:
    gate_status = str(strategy_attribution.get("gate_status") or "pass")
    if gate_status == "pass":
        status = "pass"
    elif gate_status == "degraded":
        status = "degraded"
    else:
        status = "blocked"
    return workflow_task(
        task_id="strategy_evidence",
        priority=40,
        status=status,
        title="Strategy evidence",
        description="Strategy candidates are reviewed only after data and account facts.",
        required_actions=list(strategy_attribution.get("required_actions") or []),
        blocking_reasons=list(strategy_attribution.get("blocking_reasons") or []),
        evidence={
            "candidate_count": candidate_count,
            "gate_status": gate_status,
            "strategy_id": strategy_attribution.get("strategy_id"),
            "has_evidence": bool(strategy_attribution.get("has_evidence")),
        },
    )


def paper_shadow_workflow_task(candidate_count: int) -> dict[str, Any]:
    if candidate_count:
        status = "review_required"
        required_actions = ["review_paper_shadow_evidence"]
        description = (
            "Candidate actions should be compared against paper/shadow evidence."
        )
    else:
        status = "pass"
        required_actions = []
        description = "No candidate actions require paper/shadow review."
    return workflow_task(
        task_id="paper_shadow_review",
        priority=50,
        status=status,
        title="Paper/shadow review",
        description=description,
        required_actions=required_actions,
        blocking_reasons=[],
        evidence={"candidate_count": candidate_count},
    )


def manual_confirmation_workflow_task(
    *,
    account_truth: dict[str, Any],
    strategy_attribution: dict[str, Any],
    audit: dict[str, Any],
    candidate_count: int,
    ready_for_manual_confirmation_count: int,
) -> dict[str, Any]:
    account_truth_status = str(account_truth.get("gate_status") or "blocked")
    strategy_status = str(strategy_attribution.get("gate_status") or "pass")
    risk_blocked_count = int(audit.get("risk_blocked_count") or 0)
    if not candidate_count:
        status = "pass"
        required_actions: list[str] = []
        blocking_reasons: list[str] = []
        description = "No candidate actions require manual confirmation."
    elif (
        account_truth_status == "pass"
        and strategy_status == "pass"
        and risk_blocked_count == 0
        and ready_for_manual_confirmation_count
    ):
        status = "review_required"
        required_actions = ["manual_confirm_candidate_actions"]
        blocking_reasons = []
        description = "Candidate actions are ready for explicit human review."
    else:
        status = "blocked"
        required_actions = ["resolve_upstream_workflow_blockers"]
        blocking_reasons = ["upstream_workflow_blockers"]
        description = (
            "Manual confirmation is blocked until upstream evidence is resolved."
        )
    return workflow_task(
        task_id="manual_confirmation",
        priority=60,
        status=status,
        title="Manual confirmation",
        description=description,
        required_actions=required_actions,
        blocking_reasons=blocking_reasons,
        evidence={
            "candidate_count": candidate_count,
            "ready_for_manual_confirmation_count": (
                ready_for_manual_confirmation_count
            ),
            "account_truth_gate_status": account_truth_status,
            "strategy_attribution_gate_status": strategy_status,
            "risk_blocked_count": risk_blocked_count,
        },
    )


def workflow_task(
    *,
    task_id: str,
    priority: int,
    status: str,
    title: str,
    description: str,
    required_actions: list[str],
    blocking_reasons: list[str],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": task_id,
        "priority": priority,
        "status": status,
        "title": title,
        "description": description,
        "required_actions": required_actions,
        "blocking_reasons": blocking_reasons,
        "evidence": evidence,
    }
