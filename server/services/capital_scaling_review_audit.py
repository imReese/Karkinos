"""Append-only audit workflow for evidence-based capital scaling reviews."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from server.services.capital_scaling_evidence_resolution import (
    RESOLVABLE_CAPITAL_SCALING_EVIDENCE_KINDS,
    UNSUPPORTED_CAPITAL_SCALING_EVIDENCE_KINDS,
    CapitalScalingEvidenceResolver,
)
from server.services.capital_scaling_review import (
    CapitalScalingReview,
    evaluate_capital_scaling_review,
)

CAPITAL_SCALING_EVALUATION_AUDIT_SCHEMA_VERSION = (
    "karkinos.capital_scaling_evaluation_audit.v1"
)
CAPITAL_SCALING_REVIEW_DECISION_SCHEMA_VERSION = (
    "karkinos.capital_scaling_human_review_decision.v1"
)
CAPITAL_SCALING_EVALUATION_EVENT_TYPE = "capital_scaling.evaluated"
CAPITAL_SCALING_EVALUATION_ENTITY_TYPE = "capital_scaling_evaluation"
CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE = "capital_scaling.decision_recorded"
CAPITAL_SCALING_REVIEW_DECISION_ENTITY_TYPE = "capital_scaling_review_decision"
CAPITAL_SCALING_EVENT_SOURCE = "capital_scaling_review"
CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT = (
    "record_scaling_review_decision_without_authority_change"
)
CAPITAL_SCALING_REVIEW_ACTIONS = (
    "request_new_authorization_for_scale_up",
    "hold",
    "scale_down",
    "disable",
)

_ALLOWED_DECISIONS: dict[str, frozenset[str]] = {
    "request_new_authorization_for_scale_up": frozenset(
        {
            "request_new_authorization_for_scale_up",
            "hold",
            "scale_down",
            "disable",
        }
    ),
    "hold": frozenset({"hold", "scale_down", "disable"}),
    "scale_down": frozenset({"scale_down", "disable"}),
    "disable": frozenset({"disable"}),
}


class CapitalScalingReviewDecisionRejected(ValueError):
    """Raised after an invalid human review decision has been audited."""

    def __init__(self, message: str, *, evidence: dict[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


class CapitalScalingReviewAuditService:
    """Persist scaling evidence and decisions without changing capital limits."""

    def __init__(
        self,
        *,
        db: Any,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get_status(self) -> dict[str, Any]:
        return {
            "schema_version": "karkinos.capital_scaling_review_status.v1",
            "review_contract_status": "evidence_only",
            "automatic_scale_up_enabled": False,
            "evidence_source_resolution_status": "persisted_fail_closed_resolution",
            "resolvable_evidence_kinds": list(
                RESOLVABLE_CAPITAL_SCALING_EVIDENCE_KINDS
            ),
            "unsupported_evidence_kinds": list(
                UNSUPPORTED_CAPITAL_SCALING_EVIDENCE_KINDS
            ),
            "authority_change_enabled": False,
            "new_authorization_issue_enabled": False,
            "runtime_limit_mutation_enabled": False,
            "automatic_protective_recommendations_enabled": True,
            "automatic_protective_mutation_enabled": False,
            "operator_identity_verified": False,
            "broker_submission_enabled": False,
            "supported_review_actions": list(CAPITAL_SCALING_REVIEW_ACTIONS),
            "acknowledgement": CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
            "limitations": [
                "Scale-up can only request a separate new authorization review.",
                "Scale-up remains blocked unless every required evidence kind resolves to a clear persisted source fact.",
                "Account Truth, after-cost, incident-window, capacity/liquidity, and operating-sample refs must point to a recorded computed evidence window.",
                "Scale-down and disable are recommendations until separately applied.",
                "No review decision changes runtime authority or broker behavior.",
            ],
        }

    def preview(self, *, review: CapitalScalingReview) -> dict[str, Any]:
        decision, resolution, evaluation_fingerprint = self._evaluate_review(review)
        return {
            **decision,
            "evaluation_fingerprint": evaluation_fingerprint,
            "evidence_resolution": resolution,
            "persisted": False,
            "reused": False,
            "operator_identity_verified": False,
            "authority_change_applied": False,
        }

    def record_evaluation(self, *, review: CapitalScalingReview) -> dict[str, Any]:
        decision, resolution, evaluation_fingerprint = self._evaluate_review(review)
        existing = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVALUATION_ENTITY_TYPE,
            entity_id=evaluation_fingerprint,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        recorded_at = _aware_utc(self._clock())
        payload = {
            "schema_version": CAPITAL_SCALING_EVALUATION_AUDIT_SCHEMA_VERSION,
            "review": _json_safe(review),
            "decision": decision,
            "evaluation_fingerprint": evaluation_fingerprint,
            "review_input_fingerprint": decision["input_fingerprint"],
            "evidence_resolution": resolution,
            "runtime_authority_status": "unchanged",
            "authority_change_applied": False,
            "automatic_scale_up_enabled": False,
            "evidence_source_resolution_status": resolution["resolution_status"],
            "operator_identity_verified": False,
            "broker_submission_enabled": False,
        }
        self._db.append_event_sync(
            event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
            timestamp=recorded_at.isoformat(),
            entity_type=CAPITAL_SCALING_EVALUATION_ENTITY_TYPE,
            entity_id=evaluation_fingerprint,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            source_ref=review.proposed_tier.tier_id,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVALUATION_ENTITY_TYPE,
            entity_id=evaluation_fingerprint,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("capital scaling evaluation was not recorded")
        return _event_response(saved[0], reused=False)

    def _evaluate_review(
        self,
        review: CapitalScalingReview,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        base_decision = evaluate_capital_scaling_review(review)
        decision = base_decision.to_dict()
        resolution = CapitalScalingEvidenceResolver(db=self._db).resolve(
            evidence=review.evidence
        )
        resolution_blockers = [str(item) for item in resolution.get("blockers") or []]
        decision["scale_up_blockers"] = list(
            dict.fromkeys(
                [str(item) for item in decision.get("scale_up_blockers") or []]
                + resolution_blockers
            )
        )
        decision["evidence_source_resolution_status"] = resolution["resolution_status"]
        decision["eligible_for_scale_up_review"] = (
            bool(decision.get("eligible_for_scale_up_review"))
            and not resolution_blockers
        )
        if (
            decision.get("recommended_action")
            == "request_new_authorization_for_scale_up"
            and resolution_blockers
        ):
            decision["recommended_action"] = "hold"
            decision["review_status"] = "hold_for_persisted_evidence_resolution"
        evaluation_fingerprint = _fingerprint(
            {
                "review_input_fingerprint": base_decision.input_fingerprint,
                "evidence_resolution_fingerprint": resolution["resolution_fingerprint"],
            }
        )
        return decision, resolution, evaluation_fingerprint

    def list_evaluations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVALUATION_ENTITY_TYPE,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def record_review_decision(
        self,
        *,
        evaluation_fingerprint: str,
        chosen_action: str,
        operator_label: str,
        acknowledgement: str,
    ) -> dict[str, Any]:
        evaluation = self._require_evaluation(evaluation_fingerprint)
        decision = evaluation.get("decision")
        decision = decision if isinstance(decision, dict) else {}
        recommended_action = str(decision.get("recommended_action") or "hold")
        rejection_reasons: list[str] = []
        if chosen_action not in CAPITAL_SCALING_REVIEW_ACTIONS:
            rejection_reasons.append("unsupported_review_action")
        elif chosen_action not in _ALLOWED_DECISIONS.get(
            recommended_action, frozenset()
        ):
            rejection_reasons.append("chosen_action_exceeds_evidence_recommendation")
        if not str(operator_label or "").strip():
            rejection_reasons.append("operator_label_missing")
        if acknowledgement != CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT:
            rejection_reasons.append("acknowledgement_mismatch")
        status = "rejected" if rejection_reasons else "recorded_unverified_identity"
        attempt = self._record_decision_attempt(
            evaluation_fingerprint=evaluation_fingerprint,
            evaluation=evaluation,
            recommended_action=recommended_action,
            chosen_action=chosen_action,
            operator_label=str(operator_label or "").strip(),
            acknowledgement=acknowledgement,
            status=status,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            raise CapitalScalingReviewDecisionRejected(
                "capital scaling review decision rejected: "
                + ", ".join(rejection_reasons),
                evidence=attempt,
            )
        return attempt

    def list_review_decisions(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_REVIEW_DECISION_ENTITY_TYPE,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=max(1, min(int(limit), 500)),
        )
        return [_event_response(row, reused=False) for row in rows]

    def _require_evaluation(self, fingerprint: str) -> dict[str, Any]:
        rows = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_EVALUATION_ENTITY_TYPE,
            entity_id=fingerprint,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=1,
        )
        if not rows:
            raise KeyError(f"capital scaling evaluation not found: {fingerprint}")
        return _event_response(rows[0], reused=False)

    def _record_decision_attempt(
        self,
        *,
        evaluation_fingerprint: str,
        evaluation: dict[str, Any],
        recommended_action: str,
        chosen_action: str,
        operator_label: str,
        acknowledgement: str,
        status: str,
        rejection_reasons: list[str],
    ) -> dict[str, Any]:
        identity = {
            "evaluation_fingerprint": evaluation_fingerprint,
            "recommended_action": recommended_action,
            "chosen_action": chosen_action,
            "operator_label": operator_label,
            "acknowledgement": acknowledgement,
            "status": status,
            "rejection_reasons": rejection_reasons,
        }
        review_decision_id = _fingerprint(identity)
        review = evaluation.get("review")
        review = review if isinstance(review, dict) else {}
        payload = {
            "schema_version": CAPITAL_SCALING_REVIEW_DECISION_SCHEMA_VERSION,
            "review_decision_id": review_decision_id,
            **identity,
            "current_tier_id": str(
                (review.get("current_tier") or {}).get("tier_id") or ""
            ),
            "proposed_tier_id": str(
                (review.get("proposed_tier") or {}).get("tier_id") or ""
            ),
            "requests_new_authorization": (
                chosen_action == "request_new_authorization_for_scale_up"
                and status != "rejected"
            ),
            "new_authorization_issued": False,
            "authority_change_applied": False,
            "runtime_limits_mutated": False,
            "automatic_scale_up_enabled": False,
            "operator_identity_verified": False,
            "broker_submission_enabled": False,
            "safety": _safety_flags(),
        }
        existing = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_REVIEW_DECISION_ENTITY_TYPE,
            entity_id=review_decision_id,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=1,
        )
        if existing:
            return _event_response(existing[0], reused=True)
        recorded_at = _aware_utc(self._clock())
        self._db.append_event_sync(
            event_type=CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE,
            timestamp=recorded_at.isoformat(),
            entity_type=CAPITAL_SCALING_REVIEW_DECISION_ENTITY_TYPE,
            entity_id=review_decision_id,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            source_ref=evaluation_fingerprint,
            payload=payload,
        )
        saved = self._db.list_events_sync(
            event_type=CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE,
            entity_type=CAPITAL_SCALING_REVIEW_DECISION_ENTITY_TYPE,
            entity_id=review_decision_id,
            source=CAPITAL_SCALING_EVENT_SOURCE,
            limit=1,
        )
        if not saved:
            raise RuntimeError("capital scaling review decision was not recorded")
        return _event_response(saved[0], reused=False)


def _event_response(row: dict[str, Any], *, reused: bool) -> dict[str, Any]:
    return {
        "event_id": int(row["id"]),
        "recorded_at": row["timestamp"],
        "created_at": row["created_at"],
        "persisted": True,
        "reused": reused,
        "input_fingerprint": row.get("entity_id") or "",
        **_json_object(row.get("payload_json")),
    }


def _safety_flags() -> dict[str, bool]:
    return {
        "does_not_issue_capital_authorization": True,
        "does_not_mutate_runtime_limits": True,
        "does_not_enable_or_resume_execution": True,
        "does_not_submit_or_cancel_broker_order": True,
        "does_not_auto_scale_up": True,
        "does_not_mutate_oms_or_production_ledger": True,
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
