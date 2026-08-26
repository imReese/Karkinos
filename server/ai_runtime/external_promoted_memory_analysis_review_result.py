"""Read projection for a human-reviewed promoted-memory analysis."""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts.external_promoted_memory_analysis_review import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION,
    ExternalPromotedMemoryAnalysisReviewAuditReplay,
    ExternalPromotedMemoryAnalysisReviewReplay,
    ExternalPromotedMemoryAnalysisReviewTarget,
    StoredExternalPromotedMemoryAnalysisReview,
)

from .contracts import JsonObject, content_fingerprint
from .external_analysis_reviews import (
    ExternalAnalysisReviewDecision,
    ExternalAnalysisReviewEffectiveStatus,
)


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewResult:
    review: StoredExternalPromotedMemoryAnalysisReview
    current_target: ExternalPromotedMemoryAnalysisReviewTarget
    audit_replay: ExternalPromotedMemoryAnalysisReviewAuditReplay
    reused: bool

    @property
    def target_binding_valid(self) -> bool:
        return (
            self.review.analysis_target_fingerprint == self.current_target.fingerprint
        )

    @property
    def reviewer_found_blocking_errors(self) -> bool:
        return (
            self.review.request.factual_error_count > 0
            or self.review.request.unsupported_claim_count > 0
        )

    @property
    def reviewed_research_eligible(self) -> bool:
        return (
            self.review.request.decision
            == ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
            and self.target_binding_valid
            and self.current_target.acceptance_eligible
            and not self.reviewer_found_blocking_errors
            and self.audit_replay.valid
        )

    @property
    def effective_status(self) -> ExternalAnalysisReviewEffectiveStatus:
        decision = self.review.request.decision
        if decision == ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH:
            if self.reviewed_research_eligible:
                return ExternalAnalysisReviewEffectiveStatus.REVIEWED_RESEARCH
            return ExternalAnalysisReviewEffectiveStatus.INVALIDATED_BY_EVIDENCE_DRIFT
        if decision == ExternalAnalysisReviewDecision.REQUEST_REVISION:
            return ExternalAnalysisReviewEffectiveStatus.REVISION_REQUESTED
        return ExternalAnalysisReviewEffectiveStatus.REJECTED

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.target_binding_valid:
            reasons.append("external_promoted_memory_analysis_target_fingerprint_drift")
        reasons.extend(self.current_target.acceptance_errors)
        reasons.extend(self.audit_replay.errors)
        if self.review.request.factual_error_count > 0:
            reasons.append("reviewer_identified_factual_errors")
        if self.review.request.unsupported_claim_count > 0:
            reasons.append("reviewer_identified_unsupported_claims")
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalPromotedMemoryAnalysisReviewReplay:
        valid = (
            self.audit_replay.valid
            and self.target_binding_valid
            and (
                self.review.request.decision
                != ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
                or (
                    self.current_target.acceptance_eligible
                    and not self.reviewer_found_blocking_errors
                )
            )
        )
        return ExternalPromotedMemoryAnalysisReviewReplay(
            review_id=self.review.review_id,
            analysis_id=self.review.analysis_id,
            valid=valid,
            review_event_chain_valid=self.audit_replay.valid,
            analysis_target_binding_valid=self.target_binding_valid,
            reviewed_research_eligible=self.reviewed_research_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        request = self.review.request
        quality = dict(self.review.quality_evidence)
        quality["human_rubric"] = request.quality_rubric.to_dict()
        quality["human_rubric_total"] = request.quality_rubric.total
        quality["human_rubric_maximum"] = 20
        quality["factual_error_count"] = request.factual_error_count
        quality["unsupported_claim_count"] = request.unsupported_claim_count
        return {
            "schema_version": (
                EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION
            ),
            "review_id": self.review.review_id,
            "analysis_id": self.review.analysis_id,
            "workflow_id": self.review.workflow_id,
            "retrieval_id": self.review.retrieval_id,
            "decision": request.decision.value,
            "effective_status": self.effective_status.value,
            "note": request.note,
            "reviewed_by": request.reviewed_by,
            "created_at": self.review.created_at,
            "report_artifact_id": self.review.report_artifact_id,
            "provider_id": self.review.provider_id,
            "model_id": self.review.model_id,
            "prompt_version": self.review.prompt_version,
            "promotion_ids": list(self.review.promotion_ids),
            "selected_memory_sources": [
                dict(item) for item in self.review.selected_memory_sources
            ],
            "stored_source_retrieval_target_fingerprint": (
                self.review.source_retrieval_target_fingerprint
            ),
            "current_source_retrieval_target_fingerprint": (
                self.current_target.source_retrieval_target_fingerprint
            ),
            "stored_base_analysis_target_fingerprint": (
                self.review.base_analysis_target_fingerprint
            ),
            "current_base_analysis_target_fingerprint": (
                self.current_target.base_analysis_target_fingerprint
            ),
            "stored_analysis_target_fingerprint": (
                self.review.analysis_target_fingerprint
            ),
            "current_analysis_target_fingerprint": self.current_target.fingerprint,
            "analysis_target_binding_valid": self.target_binding_valid,
            "analysis_acceptance_eligible": self.current_target.acceptance_eligible,
            "reviewed_research_eligible": self.reviewed_research_eligible,
            "quality_evidence": quality,
            "current_quality_evidence": dict(self.current_target.quality_evidence),
            "quality_evidence_binding_valid": (
                content_fingerprint(self.review.quality_evidence)
                == content_fingerprint(self.current_target.quality_evidence)
            ),
            "cost_evidence": dict(self.review.cost_evidence),
            "invalidation_reasons": list(self.invalidation_reasons),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "human_review_required": True,
            "review_external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "memory_artifact_created": False,
            "memory_recall_eligible": False,
            "automatic_memory_promotion_enabled": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }
