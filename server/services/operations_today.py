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
    shadow = _paper_shadow_summary(
        plan_date=plan_date,
        trading_plan=trading_plan,
        order_facts=orders,
        fill_facts=fills,
    )
    subsystems = [
        _market_subsystem(decision_payload),
        _account_truth_subsystem(decision_payload),
        _strategy_subsystem(decision_payload, daily_operations),
        _risk_subsystem(trading_plan, daily_operations),
        _daily_plan_subsystem(trading_plan),
        _paper_shadow_subsystem(shadow),
        _scheduler_subsystem(daily_operations, plan_date),
        _acceptance_audit_subsystem(daily_operations),
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
        "limitations": [
            "Operations summary is read-only and does not submit broker orders.",
            "Broker integration remains disabled; live-like workflows require manual confirmation.",
        ],
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
    if shadow_status == "not_required":
        status = "skipped"
    elif shadow_status == "within_expectations":
        status = "pass"
    elif shadow_status in {"not_run", "review_required"}:
        status = "manual_action_required"
    elif shadow_status == "diverged":
        status = "blocked"
    else:
        status = "degraded"
    return _subsystem(
        "paper_shadow",
        status,
        target="paper-shadow",
        last_run_at=shadow.get("last_run_at"),
        next_action=shadow.get("next_manual_review_step") or "none",
        limitations=[
            "Paper/shadow results are simulated review evidence, not broker execution."
        ],
        detail_status=shadow_status,
    )


def _scheduler_subsystem(
    daily_operations: DailyOperationsSummary,
    plan_date: str,
) -> dict[str, Any]:
    return _subsystem(
        "scheduler",
        "pass",
        target="scheduler",
        last_run_at=plan_date,
        next_action="none",
        limitations=["Daily scheduler state is summarized from current local records."],
        detail_status=daily_operations.conclusion_status,
    )


def _acceptance_audit_subsystem(
    daily_operations: DailyOperationsSummary,
) -> dict[str, Any]:
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
    }


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
    for status in ("blocked", "manual_action_required", "degraded"):
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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
