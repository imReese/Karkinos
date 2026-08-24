"""Evidence-bound, human-only post-decision reviews.

The review target is rebuilt exclusively from persisted signal, risk, order,
fill, ledger, and valuation facts.  Recording a review appends audit evidence;
it never mutates those facts or grants trading authority.
"""

from __future__ import annotations

from typing import Any

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.decision_outcome_review import (
    DECISION_OUTCOME_REVIEW_CONFIRMATION,
    DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
    DECISION_OUTCOME_REVIEW_TARGET_VERSION,
    DecisionOutcomeReviewRejected,
    DecisionOutcomeReviewReplay,
    DecisionOutcomeReviewRequest,
    DecisionOutcomeReviewResult,
    DecisionOutcomeReviewTarget,
    DecisionOutcomeReviewTargetDrift,
    StoredDecisionOutcomeReview,
)
from server.contracts.idempotency import IdempotencyConflict
from server.models import AccountStrategyAssignment
from server.persistence.decision_outcome_reviews import DecisionOutcomeReviewStore
from server.services.account_strategy_evidence import (
    fill_metadata,
    linked_strategy_evidence,
    order_source_signal_id,
)
from server.services.strategy_contribution import build_strategy_contribution_report


class DecisionOutcomeReviewService:
    """Preview, record, and revalidate one human post-decision review."""

    def __init__(self, *, db: Any, store: DecisionOutcomeReviewStore, now) -> None:
        self._db = db
        self._store = store
        self._now = now

    def preview(self, signal_id: int) -> DecisionOutcomeReviewTarget:
        return build_decision_outcome_review_target(db=self._db, signal_id=signal_id)

    def review(
        self,
        signal_id: int,
        request: DecisionOutcomeReviewRequest,
    ) -> DecisionOutcomeReviewResult:
        existing = self._store.get_by_idempotency_key(request.idempotency_key)
        target = self.preview(signal_id)
        if existing is not None:
            if (
                existing.signal_id != signal_id
                or existing.request_fingerprint != request.fingerprint
                or existing.target_fingerprint != request.expected_target_fingerprint
            ):
                raise IdempotencyConflict(
                    "decision review idempotency key was reused with different input"
                )
            return self._result(existing, reused=True)
        if request.expected_target_fingerprint != target.fingerprint:
            raise DecisionOutcomeReviewTargetDrift(
                "decision review target changed; preview the persisted evidence again"
            )
        _validate_review_semantics(request=request, target=target)
        review, reused = self._store.record(
            signal_id=signal_id,
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(review, reused=reused)

    def get(self, review_id: str) -> DecisionOutcomeReviewResult:
        return self._result(self._store.get(review_id), reused=True)

    def replay(self, review_id: str) -> DecisionOutcomeReviewReplay:
        return self._store.verify_replay(review_id)

    def _result(
        self,
        review: StoredDecisionOutcomeReview,
        *,
        reused: bool,
    ) -> DecisionOutcomeReviewResult:
        current_target = self.preview(review.signal_id)
        return DecisionOutcomeReviewResult(
            review=review,
            current_target=current_target,
            audit_replay=self._store.verify_replay(review.review_id),
            reused=reused,
        )


def build_decision_outcome_review_target(
    *, db: Any, signal_id: int
) -> DecisionOutcomeReviewTarget:
    journal_entries = db.list_signal_journal_sync(limit=10_000, offset=0)
    entry = next(
        (
            item
            for item in journal_entries
            if int((item.get("signal") or {}).get("id") or 0) == signal_id
        ),
        None,
    )
    if entry is None:
        raise LookupError(f"signal not found: {signal_id}")

    signal = _project_signal(entry["signal"])
    signal_fingerprint = content_fingerprint(signal)
    action_task = _project_action(entry.get("action_task"))
    risk_decision = _project_risk(entry.get("risk_decision"))
    assignment = AccountStrategyAssignment(
        strategy_id=str(signal["strategy_id"]),
        strategy_name=str(signal["strategy_id"]),
        status="research_only",
        scope="symbol",
        symbol=str(signal["symbol"]),
        auto_trade_enabled=False,
        attribution_status="evidence_review",
        limitations=[
            "This symbol-scoped assignment exists only to project persisted review evidence."
        ],
    )
    linked = linked_strategy_evidence(db, assignment)
    contribution = build_strategy_contribution_report(
        db=db,
        assignment=assignment,
        evidence=linked,
    ).model_dump(mode="json")

    risk_decision_id = str((risk_decision or {}).get("decision_id") or "")
    intent_id = str((risk_decision or {}).get("intent_id") or "")
    exact_orders = [
        _project_order(order)
        for order in linked["linked_orders"]
        if order_source_signal_id(order) == signal_id
        or (
            risk_decision_id
            and str(order.get("risk_decision_id") or "") == risk_decision_id
        )
        or (intent_id and str(order.get("intent_id") or "") == intent_id)
    ]
    exact_order_ids = {str(order["order_id"]) for order in exact_orders}
    exact_fills = [
        _project_fill(fill)
        for fill in linked["linked_fills"]
        if str(fill.get("order_id") or "") in exact_order_ids
        or _metadata_signal_id(fill_metadata(fill)) == signal_id
    ]
    execution_status = _execution_status(
        risk_decision=risk_decision,
        orders=exact_orders,
        fills=exact_fills,
    )
    execution_evidence = {
        "status": execution_status,
        "orders": exact_orders,
        "fills": exact_fills,
        "order_count": len(exact_orders),
        "fill_count": len(exact_fills),
    }
    financial_status, blockers = _financial_evidence_status(
        execution_status=execution_status,
        contribution=contribution,
    )
    allowed_outcomes = _allowed_outcomes(
        execution_status=execution_status,
        financial_evidence_status=financial_status,
        risk_decision=risk_decision,
    )
    limitations = (
        "Outcome labels are human conclusions; numeric P/L remains the canonical contribution projection.",
        "The contribution report is strategy-and-symbol scoped and is not silently reallocated to one signal.",
        "A review records audit evidence only and cannot submit, cancel, resume, or authorize capital.",
    )
    identity = {
        "schema_version": DECISION_OUTCOME_REVIEW_TARGET_VERSION,
        "signal_id": signal_id,
        "signal": signal,
        "signal_fingerprint": signal_fingerprint,
        "action_task": action_task,
        "risk_decision": risk_decision,
        "execution_evidence": execution_evidence,
        "strategy_contribution_report": contribution,
        "financial_evidence_status": financial_status,
        "allowed_outcomes": list(allowed_outcomes),
        "blockers": list(blockers),
        "limitations": list(limitations),
    }
    return DecisionOutcomeReviewTarget(
        signal_id=signal_id,
        signal=signal,
        signal_fingerprint=signal_fingerprint,
        action_task=action_task,
        risk_decision=risk_decision,
        execution_evidence=execution_evidence,
        strategy_contribution_report=contribution,
        financial_evidence_status=financial_status,
        allowed_outcomes=allowed_outcomes,
        blockers=blockers,
        limitations=limitations,
        fingerprint=content_fingerprint(identity),
    )


def _validate_review_semantics(
    *,
    request: DecisionOutcomeReviewRequest,
    target: DecisionOutcomeReviewTarget,
) -> None:
    if request.outcome not in target.allowed_outcomes:
        raise DecisionOutcomeReviewRejected(
            f"outcome is not supported by current evidence: {request.outcome}"
        )
    if request.outcome in {"evidence_supported", "evidence_not_supported"}:
        if request.user_decision != "acted":
            raise DecisionOutcomeReviewRejected(
                "evidence outcome requires user_decision=acted"
            )
    elif request.outcome == "risk_gate_validated":
        if request.user_decision not in {"blocked", "ignored"}:
            raise DecisionOutcomeReviewRejected(
                "risk-gate outcome requires a blocked or ignored decision"
            )
    elif request.outcome == "not_executed":
        if request.user_decision not in {"ignored", "deferred", "blocked"}:
            raise DecisionOutcomeReviewRejected(
                "not-executed outcome cannot be recorded as acted"
            )


def _financial_evidence_status(
    *,
    execution_status: str,
    contribution: dict[str, Any],
) -> tuple[str, tuple[str, ...]]:
    if execution_status in {"risk_blocked_no_execution", "not_executed"}:
        return "not_applicable", ()
    if execution_status == "order_recorded_no_fill":
        return "blocked", ("signal_execution_outcome_incomplete",)
    if (
        contribution.get("evidence_binding_status") == "bound"
        and contribution.get("contribution_fingerprint")
        and contribution.get("valuation_snapshot_id")
        and int(contribution.get("ledger_cutoff_id") or 0) > 0
    ):
        return "bound", ()
    blockers = tuple(
        dict.fromkeys(
            [
                "strategy_contribution_not_evidence_bound",
                *(str(item) for item in contribution.get("blockers") or []),
            ]
        )
    )
    return "blocked", blockers


def _allowed_outcomes(
    *,
    execution_status: str,
    financial_evidence_status: str,
    risk_decision: dict[str, Any] | None,
) -> tuple[str, ...]:
    outcomes = ["inconclusive"]
    if execution_status in {"risk_blocked_no_execution", "not_executed"}:
        outcomes.append("not_executed")
    if risk_decision is not None and risk_decision.get("passed") is False:
        outcomes.append("risk_gate_validated")
    if financial_evidence_status == "bound":
        outcomes.extend(["evidence_supported", "evidence_not_supported"])
    return tuple(outcomes)


def _execution_status(
    *,
    risk_decision: dict[str, Any] | None,
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
) -> str:
    if fills:
        return "fills_linked"
    if orders:
        return "order_recorded_no_fill"
    if risk_decision is not None and risk_decision.get("passed") is False:
        return "risk_blocked_no_execution"
    return "not_executed"


def _project_signal(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "id",
            "timestamp",
            "strategy_id",
            "symbol",
            "direction",
            "target_weight",
            "price",
            "asset_class",
        )
    }


def _project_action(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: value.get(key)
        for key in (
            "id",
            "source_signal_id",
            "symbol",
            "direction",
            "target_weight",
            "strategy_id",
            "status",
            "timestamp",
            "updated_at",
        )
    }


def _project_risk(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        key: value.get(key)
        for key in (
            "decision_id",
            "intent_id",
            "timestamp",
            "passed",
            "symbol",
            "side",
            "reasons",
            "resulting_order_id",
            "severity",
        )
    }


def _project_order(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "order_id",
            "intent_id",
            "risk_decision_id",
            "symbol",
            "side",
            "quantity",
            "filled_quantity",
            "status",
            "execution_mode",
            "created_at",
            "updated_at",
        )
    }


def _project_fill(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "fill_id",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "commission",
            "slippage",
            "timestamp",
        )
    }


def _metadata_signal_id(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("source_signal_id") or metadata.get("signal_id")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
