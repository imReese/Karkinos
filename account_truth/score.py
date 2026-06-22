"""Account Truth Score derived from reconciliation and manual review evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from account_truth.manual_review import ManualReviewDecision
from account_truth.reconciliation import ReconciliationItem, ReconciliationReport

ACCOUNT_TRUTH_SCORE_SCHEMA_VERSION = "karkinos.account_truth.score.v1"

AccountTruthGateStatus = Literal["pass", "degraded", "blocked"]
DataFreshnessStatus = Literal["fresh", "stale", "missing"]

_RESOLVED_REVIEW_STATUSES = {"accepted", "ignored", "known_difference"}
_CATEGORY_STATUS_FIELDS = {
    "cash": "cash_status",
    "position": "position_status",
    "fee": "fee_status",
    "tax": "fee_status",
    "transfer_fee": "fee_status",
    "cost_basis": "cost_basis_status",
}


@dataclass(frozen=True)
class AccountTruthScore:
    schema_version: str
    score: int
    gate_status: AccountTruthGateStatus
    cash_status: str
    position_status: str
    fee_status: str
    cost_basis_status: str
    data_freshness_status: DataFreshnessStatus
    unresolved_mismatch_count: int
    resolved_review_count: int
    required_actions: list[str]
    blocking_reasons: list[str]
    limitations: list[str]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "score": self.score,
            "gate_status": self.gate_status,
            "cash_status": self.cash_status,
            "position_status": self.position_status,
            "fee_status": self.fee_status,
            "cost_basis_status": self.cost_basis_status,
            "data_freshness_status": self.data_freshness_status,
            "unresolved_mismatch_count": self.unresolved_mismatch_count,
            "resolved_review_count": self.resolved_review_count,
            "required_actions": list(self.required_actions),
            "blocking_reasons": list(self.blocking_reasons),
            "limitations": list(self.limitations),
        }


def build_account_truth_score(
    *,
    report: ReconciliationReport,
    review_decisions: list[ManualReviewDecision],
    data_freshness_status: str,
) -> AccountTruthScore:
    """Build a deterministic account-truth score for gates and reports."""

    freshness = _freshness_status(data_freshness_status)
    review_by_item = {decision.item_key: decision for decision in review_decisions}
    unresolved_items = [
        item
        for item in report.items
        if item.status != "pass" and not _is_resolved(item, review_by_item)
    ]
    resolved_review_count = sum(
        1
        for item in report.items
        if item.status != "pass" and _is_resolved(item, review_by_item)
    )
    blocking_reasons = _blocking_reasons(
        report=report,
        unresolved_items=unresolved_items,
        data_freshness_status=freshness,
    )
    score = _score(
        report=report,
        unresolved_items=unresolved_items,
        data_freshness_status=freshness,
    )
    return AccountTruthScore(
        schema_version=ACCOUNT_TRUTH_SCORE_SCHEMA_VERSION,
        score=score,
        gate_status=_gate_status(score=score, blocking_reasons=blocking_reasons),
        cash_status=_category_status(report.items, "cash"),
        position_status=_category_status(report.items, "position"),
        fee_status=_combined_status(report.items, ["fee", "tax", "transfer_fee"]),
        cost_basis_status=_category_status(report.items, "cost_basis"),
        data_freshness_status=freshness,
        unresolved_mismatch_count=len(unresolved_items),
        resolved_review_count=resolved_review_count,
        required_actions=_required_actions(unresolved_items),
        blocking_reasons=blocking_reasons,
        limitations=_limitations(
            unresolved_items=unresolved_items,
            data_freshness_status=freshness,
        ),
    )


def _score(
    *,
    report: ReconciliationReport,
    unresolved_items: list[ReconciliationItem],
    data_freshness_status: DataFreshnessStatus,
) -> int:
    if report.status == "blocked":
        return 0

    value = 100
    if report.status == "warning":
        value -= 15
    if report.status == "mismatch":
        value -= 40
    if data_freshness_status == "stale":
        value -= 20
    if data_freshness_status == "missing":
        value -= 35
    value -= 10 * sum(1 for item in unresolved_items if item.status == "mismatch")
    return max(0, min(100, value))


def _gate_status(
    *,
    score: int,
    blocking_reasons: list[str],
) -> AccountTruthGateStatus:
    if blocking_reasons or score < 60:
        return "blocked"
    if score < 90:
        return "degraded"
    return "pass"


def _blocking_reasons(
    *,
    report: ReconciliationReport,
    unresolved_items: list[ReconciliationItem],
    data_freshness_status: DataFreshnessStatus,
) -> list[str]:
    reasons: list[str] = []
    if report.status == "blocked":
        reasons.append("blocked_reconciliation_report")
    if data_freshness_status == "missing":
        reasons.append("missing_account_or_market_evidence")
    for item in unresolved_items:
        if item.status == "mismatch" or report.status == "blocked":
            reason = f"unresolved_{item.category}_difference"
            if reason not in reasons:
                reasons.append(reason)
    return reasons


def _limitations(
    *,
    unresolved_items: list[ReconciliationItem],
    data_freshness_status: DataFreshnessStatus,
) -> list[str]:
    limitations: list[str] = []
    if data_freshness_status in {"stale", "missing"}:
        limitations.append(
            "Account truth is degraded by stale account or market evidence."
        )
    if unresolved_items:
        limitations.append(
            "Unresolved reconciliation items require review before trusted use."
        )
    return limitations


def _required_actions(items: list[ReconciliationItem]) -> list[str]:
    actions: list[str] = []
    for item in items:
        if item.suggested_review_action and item.suggested_review_action not in actions:
            actions.append(item.suggested_review_action)
    return actions


def _is_resolved(
    item: ReconciliationItem,
    review_by_item: dict[str, ManualReviewDecision],
) -> bool:
    decision = review_by_item.get(_item_key(item))
    return bool(decision and decision.review_status in _RESOLVED_REVIEW_STATUSES)


def _item_key(item: ReconciliationItem) -> str:
    if item.symbol:
        return f"{item.category}:{item.symbol}"
    return item.category


def _category_status(items: list[ReconciliationItem], category: str) -> str:
    category_items = [item for item in items if item.category == category]
    if not category_items:
        return "pass"
    return _worst_status([item.status for item in category_items])


def _combined_status(items: list[ReconciliationItem], categories: list[str]) -> str:
    statuses = [item.status for item in items if item.category in categories]
    if not statuses:
        return "pass"
    return _worst_status(statuses)


def _worst_status(statuses: list[str]) -> str:
    priority = {"pass": 0, "warning": 1, "mismatch": 2, "blocked": 3}
    return max(statuses, key=lambda status: priority.get(status, 0))


def _freshness_status(value: str) -> DataFreshnessStatus:
    if value not in {"fresh", "stale", "missing"}:
        raise ValueError(f"unsupported data freshness status: {value}")
    return value  # type: ignore[return-value]
