"""Read-only daily operations summary aggregation."""

from __future__ import annotations

from typing import Any, Iterable

from server.models import DailyOperationsSummary

_TRUSTED_STATUSES = {
    "attached",
    "complete",
    "confirmed",
    "fresh",
    "live",
    "pass",
    "passed",
}
_BLOCKING_MARKET_STATUSES = {"blocked", "error", "missing", "unavailable"}
_EXCEPTION_ORDER_STATUSES = {"blocked", "canceled", "error", "failed", "rejected"}
_READY_MANUAL_STATUS = "ready_for_manual_confirmation"


def build_daily_operations_summary(
    *,
    decision_summary: dict[str, Any] | None,
    candidates: Iterable[dict[str, Any]],
    pending_manual_orders: Iterable[dict[str, Any]],
    order_facts: Iterable[dict[str, Any]],
    fill_facts: Iterable[dict[str, Any]],
    ledger_review_count: int = 0,
) -> DailyOperationsSummary:
    summary = decision_summary or {}
    candidate_rows = list(candidates)
    pending_orders = list(pending_manual_orders)
    orders = list(order_facts)
    fills = list(fill_facts)

    account_truth_status = _status(
        _nested(summary, "account_truth", "gate_status"),
        default="blocked",
    )
    market_status = _status(
        _nested(summary, "market_data", "source_health"),
        default="unknown",
    )
    account_truth_allows_manual = account_truth_status == "pass"

    candidate_pool_count = _int(summary.get("candidate_count"), len(candidate_rows))
    risk_checked_count = sum(1 for row in candidate_rows if _risk_checked(row))
    risk_passed_count = sum(
        1 for row in candidate_rows if _status(row.get("risk_gate_status")) == "passed"
    )
    risk_blocked_count = max(
        _int(summary.get("risk_blocked_count"), 0),
        sum(
            1
            for row in candidate_rows
            if _status(row.get("risk_gate_status")) == "blocked"
        ),
    )
    manual_ready_count = (
        sum(
            1
            for row in candidate_rows
            if _status(row.get("manual_confirmation_status")) == _READY_MANUAL_STATUS
        )
        if account_truth_allows_manual
        else 0
    )
    summary_manual_ready = _int(summary.get("ready_for_manual_confirmation_count"), 0)
    if account_truth_allows_manual:
        manual_ready_count = max(manual_ready_count, summary_manual_ready)

    execution_exception_count = sum(
        1 for row in orders if _status(row.get("status")) in _EXCEPTION_ORDER_STATUSES
    )
    pending_manual_order_count = len(pending_orders)
    evidence_passed_count = sum(
        1
        for row in candidate_rows
        if _candidate_evidence_passed(row, account_truth_status)
    )
    paper_shadow_review_count = sum(
        1 for row in candidate_rows if _paper_shadow_needs_review(row)
    )

    conclusion_status, primary_target = _conclusion(
        account_truth_status=account_truth_status,
        market_status=market_status,
        execution_exception_count=execution_exception_count,
        pending_manual_order_count=pending_manual_order_count,
        manual_ready_count=manual_ready_count,
        risk_blocked_count=risk_blocked_count,
    )

    return DailyOperationsSummary(
        candidate_pool_count=candidate_pool_count,
        evidence_passed_count=evidence_passed_count,
        risk_checked_count=risk_checked_count,
        risk_passed_count=risk_passed_count,
        risk_blocked_count=risk_blocked_count,
        paper_shadow_review_count=paper_shadow_review_count,
        manual_ready_count=manual_ready_count,
        pending_manual_order_count=pending_manual_order_count,
        execution_record_count=len(orders),
        fill_record_count=len(fills),
        ledger_review_count=max(ledger_review_count, 0),
        execution_exception_count=execution_exception_count,
        default_execution_mode="manual_confirmation",
        broker_bridge_status="disabled",
        conclusion_status=conclusion_status,
        primary_target=primary_target,
        limitations=[
            "Daily operations summary is read-only and does not submit broker orders.",
            "Live-like execution remains manual-confirmation only by default.",
        ],
    )


def _conclusion(
    *,
    account_truth_status: str,
    market_status: str,
    execution_exception_count: int,
    pending_manual_order_count: int,
    manual_ready_count: int,
    risk_blocked_count: int,
) -> tuple[str, str]:
    if account_truth_status == "blocked":
        return "account_truth_blocked", "account-truth"
    if market_status in _BLOCKING_MARKET_STATUSES:
        return "data_unavailable", "market"
    if execution_exception_count > 0:
        return "execution_exception", "trading"
    if pending_manual_order_count > 0 or manual_ready_count > 0:
        return "pending_manual_confirmation", "trading"
    if risk_blocked_count > 0:
        return "risk_blocked", "risk"
    return "no_manual_action", "decision"


def _candidate_evidence_passed(
    row: dict[str, Any],
    account_truth_status: str,
) -> bool:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    return (
        _status(_nested(evidence, "data_freshness", "status")) in _TRUSTED_STATUSES
        and _status(_nested(evidence, "after_cost_oos_validation", "status"))
        in _TRUSTED_STATUSES
        and _status(
            _nested(evidence, "account_truth", "gate_status"),
            account_truth_status,
        )
        == "pass"
    )


def _paper_shadow_needs_review(row: dict[str, Any]) -> bool:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    paper_shadow = (
        evidence.get("paper_shadow")
        if isinstance(evidence.get("paper_shadow"), dict)
        else {}
    )
    return _status(paper_shadow.get("status")) in {
        "review_required",
        "not_evaluated",
        "blocked",
    }


def _risk_checked(row: dict[str, Any]) -> bool:
    status = _status(row.get("risk_gate_status"))
    return status in {"passed", "blocked"} or row.get("risk_gate_passed") is not None


def _nested(value: dict[str, Any], first: str, second: str) -> Any:
    child = value.get(first)
    return child.get(second) if isinstance(child, dict) else None


def _status(value: Any, default: str = "unknown") -> str:
    text = str(value or default).strip().lower()
    return text or default


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback
