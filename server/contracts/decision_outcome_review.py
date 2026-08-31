"""Stable decision-outcome review contracts without transport or storage concerns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.contracts.content_identity import content_fingerprint

DECISION_OUTCOME_REVIEW_CONTRACT_VERSION = "karkinos.decision_outcome_review.v1"

DECISION_OUTCOME_REVIEW_REQUEST_VERSION = "karkinos.decision_outcome_review_request.v1"

DECISION_OUTCOME_REVIEW_TARGET_VERSION = "karkinos.decision_outcome_review_target.v1"

DECISION_OUTCOME_REVIEW_CONFIRMATION = (
    "record_evidence_bound_decision_review_without_trade_or_capital_authority"
)

_USER_DECISIONS = {"acted", "ignored", "deferred", "blocked"}

_OUTCOMES = {
    "evidence_supported",
    "evidence_not_supported",
    "risk_gate_validated",
    "not_executed",
    "inconclusive",
}


class DecisionOutcomeReviewRejected(ValueError):
    """Raised when a review request violates deterministic local gates."""


class DecisionOutcomeReviewTargetDrift(DecisionOutcomeReviewRejected):
    """Raised when persisted evidence changed after the operator previewed it."""


@dataclass(frozen=True)
class DecisionOutcomeReviewRequest:
    idempotency_key: str
    reviewed_by: str
    user_decision: str
    outcome: str
    note: str
    expected_target_fingerprint: str
    confirmation: str
    schema_version: str = DECISION_OUTCOME_REVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "expected_target_fingerprint",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.schema_version != DECISION_OUTCOME_REVIEW_REQUEST_VERSION:
            raise ValueError("decision outcome review request version drifted")
        if self.user_decision not in _USER_DECISIONS:
            raise ValueError("unsupported user_decision")
        if self.outcome not in _OUTCOMES:
            raise ValueError("unsupported outcome")
        if self.confirmation != DECISION_OUTCOME_REVIEW_CONFIRMATION:
            raise ValueError("explicit no-authority review confirmation is required")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "idempotency_key": self.idempotency_key,
            "reviewed_by": self.reviewed_by,
            "user_decision": self.user_decision,
            "outcome": self.outcome,
            "note": self.note,
            "expected_target_fingerprint": self.expected_target_fingerprint,
            "confirmation": self.confirmation,
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewTarget:
    signal_id: int
    signal: dict[str, Any]
    signal_fingerprint: str
    action_task: dict[str, Any] | None
    risk_decision: dict[str, Any] | None
    execution_evidence: dict[str, Any]
    strategy_contribution_report: dict[str, Any]
    financial_evidence_status: str
    allowed_outcomes: tuple[str, ...]
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    fingerprint: str
    schema_version: str = DECISION_OUTCOME_REVIEW_TARGET_VERSION

    def to_dict(self) -> dict[str, Any]:
        contribution = self.strategy_contribution_report
        return {
            "schema_version": self.schema_version,
            "signal_id": self.signal_id,
            "signal": self.signal,
            "signal_fingerprint": self.signal_fingerprint,
            "action_task": self.action_task,
            "risk_decision": self.risk_decision,
            "execution_evidence": self.execution_evidence,
            "strategy_contribution_report": contribution,
            "financial_evidence_status": self.financial_evidence_status,
            "valuation_snapshot_id": contribution.get("valuation_snapshot_id"),
            "ledger_cutoff_id": contribution.get("ledger_cutoff_id", 0),
            "contribution_fingerprint": contribution.get("contribution_fingerprint"),
            "allowed_outcomes": list(self.allowed_outcomes),
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "target_fingerprint": self.fingerprint,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class StoredDecisionOutcomeReview:
    review_id: str
    signal_id: int
    idempotency_key: str
    request: dict[str, Any]
    request_fingerprint: str
    target: dict[str, Any]
    target_fingerprint: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
            "review_id": self.review_id,
            "signal_id": self.signal_id,
            "idempotency_key": self.idempotency_key,
            "reviewed_at": self.created_at,
            "reviewed_by": self.request.get("reviewed_by"),
            "user_decision": self.request.get("user_decision"),
            "outcome": self.request.get("outcome"),
            "note": self.request.get("note"),
            "request_fingerprint": self.request_fingerprint,
            "stored_target_fingerprint": self.target_fingerprint,
            "stored_target": self.target,
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.decision_outcome_review_replay.v1",
            "review_id": self.review_id,
            "valid": self.valid,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "persisted_facts_only": True,
            "provider_contacted": False,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class DecisionOutcomeReviewResult:
    review: StoredDecisionOutcomeReview
    current_target: DecisionOutcomeReviewTarget
    audit_replay: DecisionOutcomeReviewReplay
    reused: bool

    def to_dict(self) -> dict[str, Any]:
        binding_valid = (
            self.review.target_fingerprint == self.current_target.fingerprint
            and self.audit_replay.valid
        )
        return {
            "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
            "review": self.review.to_dict(),
            "current_target": self.current_target.to_dict(),
            "target_binding_valid": binding_valid,
            "stored_review_integrity_valid": self.audit_replay.valid,
            "audit_replay": self.audit_replay.to_dict(),
            "reused": self.reused,
            "persisted_facts_only": True,
            "provider_contacted": False,
            "database_writes_performed": True,
            "does_not_mutate_financial_state": True,
            "authorizes_execution": False,
            "authority_effect": "none",
        }


__all__ = [
    "DECISION_OUTCOME_REVIEW_CONFIRMATION",
    "DECISION_OUTCOME_REVIEW_CONTRACT_VERSION",
    "DECISION_OUTCOME_REVIEW_REQUEST_VERSION",
    "DECISION_OUTCOME_REVIEW_TARGET_VERSION",
    "DecisionOutcomeReviewRejected",
    "DecisionOutcomeReviewReplay",
    "DecisionOutcomeReviewRequest",
    "DecisionOutcomeReviewResult",
    "DecisionOutcomeReviewTarget",
    "DecisionOutcomeReviewTargetDrift",
    "StoredDecisionOutcomeReview",
]
