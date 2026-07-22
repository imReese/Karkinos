"""Persisted-only strategy learning queue derived from human outcome reviews.

The projection revalidates canonical post-decision reviews and translates only
their reviewed disposition into safe human next actions. It does not infer P/L,
invoke AI, create research tasks, or grant trading/capital authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.services.decision_outcome_review import (
    DecisionOutcomeReviewResult,
    DecisionOutcomeReviewService,
    DecisionOutcomeReviewStore,
    StoredDecisionOutcomeReview,
)

STRATEGY_LEARNING_REVIEW_SCHEMA_VERSION = "karkinos.strategy_learning_review.v1"

_PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}


class StrategyLearningReviewService:
    """Build a deterministic, non-authorizing learning queue from stored reviews."""

    def __init__(
        self,
        *,
        review_store: DecisionOutcomeReviewStore,
        review_service: DecisionOutcomeReviewService,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._review_store = review_store
        self._review_service = review_service
        self._now = now or (lambda: datetime.now(UTC).isoformat())

    def build(self, *, limit: int = 100) -> dict[str, Any]:
        stored_reviews = self._review_store.list_latest_by_signal(limit=limit)
        items: list[dict[str, Any]] = []
        for stored in stored_reviews:
            try:
                items.append(self._item(self._review_service.get(stored.review_id)))
            except Exception:
                items.append(_blocked_revalidation_item(stored))

        items.sort(
            key=lambda item: (
                _PRIORITY_RANK.get(str(item["priority"]), 99),
                str(item["strategy_id"]),
                -int(item["signal_id"]),
            )
        )
        action_items = [item for item in items if item["safe_next_action"] != "none"]
        critical_count = sum(item["priority"] == "critical" for item in items)
        status = (
            "not_configured"
            if not items
            else (
                "blocked"
                if critical_count
                else "review_required" if action_items else "clear"
            )
        )
        core = {
            "schema_version": STRATEGY_LEARNING_REVIEW_SCHEMA_VERSION,
            "status": status,
            "reviewed_signal_count": len(items),
            "action_item_count": len(action_items),
            "critical_item_count": critical_count,
            "outcome_counts": _outcome_counts(items),
            "strategy_summaries": _strategy_summaries(items),
            "items": items,
            "limitations": [
                "Only the latest persisted human outcome review per signal is projected; unreviewed signals are not silently classified.",
                "Historical review labels are learning evidence, not current account facts or automatic strategy changes.",
                "Research handoffs are copy-only and require a separate human-started evidence capture and research task.",
            ],
            **_safety_flags(),
        }
        return {
            **core,
            "queue_fingerprint": content_fingerprint(core),
            "generated_at": self._now(),
        }

    def _item(self, result: DecisionOutcomeReviewResult) -> dict[str, Any]:
        stored = result.review
        stored_target = stored.target
        current_target = result.current_target
        signal = _mapping(stored_target.get("signal"))
        strategy_id = str(signal.get("strategy_id") or "unknown")
        symbol = str(signal.get("symbol") or "")
        outcome = str(stored.request.get("outcome") or "unknown")
        user_decision = str(stored.request.get("user_decision") or "unknown")
        integrity_valid = result.audit_replay.valid
        target_binding_valid = (
            integrity_valid and stored.target_fingerprint == current_target.fingerprint
        )
        learning_status, priority, next_action = _learning_action(
            integrity_valid=integrity_valid,
            target_binding_valid=target_binding_valid,
            outcome=outcome,
        )
        blockers = (
            list(result.audit_replay.errors)
            if not integrity_valid
            else (
                [
                    "decision_outcome_review_target_drift",
                    *[str(item) for item in current_target.blockers],
                ]
                if not target_binding_valid
                else []
            )
        )
        evidence_refs = _evidence_refs(
            stored=stored,
            current_target_fingerprint=current_target.fingerprint,
        )
        item = {
            "review_id": stored.review_id,
            "signal_id": stored.signal_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "reviewed_at": stored.created_at,
            "user_decision": user_decision,
            "outcome": outcome,
            "learning_status": learning_status,
            "priority": priority,
            "safe_next_action": next_action,
            "stored_target_fingerprint": stored.target_fingerprint,
            "current_target_fingerprint": current_target.fingerprint,
            "target_binding_valid": target_binding_valid,
            "audit_integrity_valid": integrity_valid,
            "valuation_snapshot_id": _stored_target_value(
                stored_target,
                "valuation_snapshot_id",
            ),
            "ledger_cutoff_id": int(
                _stored_target_value(stored_target, "ledger_cutoff_id") or 0
            ),
            "contribution_fingerprint": _stored_target_value(
                stored_target,
                "contribution_fingerprint",
            ),
            "blockers": list(dict.fromkeys(blockers)),
            "evidence_refs": evidence_refs,
            "research_handoff": _research_handoff(
                strategy_id=strategy_id,
                symbol=symbol,
                review_id=stored.review_id,
                signal_id=stored.signal_id,
                outcome=outcome,
                evidence_refs=evidence_refs,
                eligible=(
                    learning_status == "strategy_research_required"
                    and integrity_valid
                    and target_binding_valid
                ),
            ),
            **_safety_flags(),
        }
        return {
            **item,
            "item_fingerprint": content_fingerprint(item),
        }


def _learning_action(
    *,
    integrity_valid: bool,
    target_binding_valid: bool,
    outcome: str,
) -> tuple[str, str, str]:
    if not integrity_valid:
        return (
            "audit_integrity_blocked",
            "critical",
            "repair_post_decision_review_integrity_before_learning",
        )
    if not target_binding_valid:
        return (
            "evidence_refresh_required",
            "high",
            "re_preview_post_decision_review_against_current_evidence",
        )
    if outcome == "evidence_not_supported":
        return (
            "strategy_research_required",
            "high",
            "open_human_strategy_research_task",
        )
    if outcome == "inconclusive":
        return (
            "outcome_evidence_review_required",
            "medium",
            "resolve_or_wait_for_canonical_outcome_evidence",
        )
    if outcome == "not_executed":
        return (
            "decision_process_review",
            "medium",
            "review_why_the_signal_was_not_executed",
        )
    return "no_action", "none", "none"


def _research_handoff(
    *,
    strategy_id: str,
    symbol: str,
    review_id: str,
    signal_id: int,
    outcome: str,
    evidence_refs: list[str],
    eligible: bool,
) -> dict[str, Any] | None:
    if not eligible:
        return None
    return {
        "schema_version": "karkinos.strategy_learning_research_handoff.v1",
        "kind": "copy_only_human_started_research",
        "research_question": (
            f"Re-evaluate strategy {strategy_id} for {symbol or 'its reviewed scope'} "
            f"after outcome {outcome} on signal {signal_id}; test the hypothesis "
            "against current canonical evidence before proposing any change."
        ),
        "review_id": review_id,
        "evidence_refs": evidence_refs,
        "historical_review_is_current_fact": False,
        "requires_human_started_capture": True,
        "requires_human_started_research_task": True,
        "invokes_ai": False,
        "creates_memory": False,
        "authorizes_strategy_change": False,
        "authorizes_execution": False,
    }


def _blocked_revalidation_item(
    stored: StoredDecisionOutcomeReview,
) -> dict[str, Any]:
    signal = _mapping(stored.target.get("signal"))
    item = {
        "review_id": stored.review_id,
        "signal_id": stored.signal_id,
        "strategy_id": str(signal.get("strategy_id") or "unknown"),
        "symbol": str(signal.get("symbol") or ""),
        "reviewed_at": stored.created_at,
        "user_decision": str(stored.request.get("user_decision") or "unknown"),
        "outcome": str(stored.request.get("outcome") or "unknown"),
        "learning_status": "audit_integrity_blocked",
        "priority": "critical",
        "safe_next_action": "repair_post_decision_review_integrity_before_learning",
        "stored_target_fingerprint": stored.target_fingerprint,
        "current_target_fingerprint": "",
        "target_binding_valid": False,
        "audit_integrity_valid": False,
        "valuation_snapshot_id": None,
        "ledger_cutoff_id": 0,
        "contribution_fingerprint": None,
        "blockers": ["decision_outcome_review_revalidation_failed"],
        "evidence_refs": [f"decision_outcome_review:{stored.review_id}"],
        "research_handoff": None,
        **_safety_flags(),
    }
    return {**item, "item_fingerprint": content_fingerprint(item)}


def _evidence_refs(
    *,
    stored: StoredDecisionOutcomeReview,
    current_target_fingerprint: str,
) -> list[str]:
    refs = [
        f"decision_outcome_review:{stored.review_id}",
        f"signal:{stored.signal_id}",
        f"decision_outcome_review_target:{stored.target_fingerprint}",
        f"current_decision_outcome_target:{current_target_fingerprint}",
    ]
    valuation_snapshot_id = _stored_target_value(
        stored.target,
        "valuation_snapshot_id",
    )
    ledger_cutoff_id = int(_stored_target_value(stored.target, "ledger_cutoff_id") or 0)
    contribution_fingerprint = _stored_target_value(
        stored.target,
        "contribution_fingerprint",
    )
    if valuation_snapshot_id:
        refs.append(f"valuation_snapshot:{valuation_snapshot_id}")
    if ledger_cutoff_id > 0:
        refs.append(f"ledger_cutoff:{ledger_cutoff_id}")
    if contribution_fingerprint:
        refs.append(f"strategy_contribution:{contribution_fingerprint}")
    return refs


def _strategy_summaries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        strategy_id = str(item["strategy_id"])
        summary = grouped.setdefault(
            strategy_id,
            {
                "strategy_id": strategy_id,
                "reviewed_signal_count": 0,
                "action_item_count": 0,
                "highest_priority": "none",
                "outcome_counts": {},
            },
        )
        summary["reviewed_signal_count"] += 1
        if item["safe_next_action"] != "none":
            summary["action_item_count"] += 1
        if _PRIORITY_RANK.get(str(item["priority"]), 99) < _PRIORITY_RANK.get(
            str(summary["highest_priority"]),
            99,
        ):
            summary["highest_priority"] = item["priority"]
        outcome = str(item["outcome"])
        summary["outcome_counts"][outcome] = (
            int(summary["outcome_counts"].get(outcome, 0)) + 1
        )
    return [grouped[key] for key in sorted(grouped)]


def _outcome_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        outcome = str(item["outcome"])
        counts[outcome] = counts.get(outcome, 0) + 1
    return dict(sorted(counts.items()))


def _stored_target_value(target: Mapping[str, Any], key: str) -> Any:
    direct = target.get(key)
    if direct is not None:
        return direct
    return _mapping(target.get("strategy_contribution_report")).get(key)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safety_flags() -> dict[str, bool]:
    return {
        "persisted_facts_only": True,
        "provider_contacted": False,
        "database_writes_performed": False,
        "financial_recalculation_performed": False,
        "ai_invoked": False,
        "memory_created": False,
        "strategy_changed": False,
        "authorizes_execution": False,
        "capital_authority_changed": False,
    }


__all__ = [
    "STRATEGY_LEARNING_REVIEW_SCHEMA_VERSION",
    "StrategyLearningReviewService",
]
