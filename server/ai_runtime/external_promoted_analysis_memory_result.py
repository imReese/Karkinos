"""Read projection for an explicitly promoted external-analysis memory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from server.contracts.external_promoted_analysis_memory import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
    ExternalPromotedAnalysisMemoryAuditReplay,
    ExternalPromotedAnalysisMemoryEffectiveStatus,
    ExternalPromotedAnalysisMemoryReplay,
    ExternalPromotedAnalysisMemoryTarget,
    StoredExternalPromotedAnalysisMemoryPromotion,
    StoredExternalPromotedAnalysisMemoryRevocation,
)

from .contracts import ArtifactKind, JsonObject, content_fingerprint


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryPromotionResult:
    promotion: StoredExternalPromotedAnalysisMemoryPromotion
    current_target: ExternalPromotedAnalysisMemoryTarget
    revocation: StoredExternalPromotedAnalysisMemoryRevocation | None
    audit_replay: ExternalPromotedAnalysisMemoryAuditReplay
    reused: bool

    @property
    def promotion_binding_valid(self) -> bool:
        return (
            self.promotion.promotion_target_fingerprint
            == self.current_target.fingerprint
        )

    @property
    def source_binding_valid(self) -> bool:
        target = self.current_target
        promotion = self.promotion
        return (
            target.eligible
            and promotion.review_id == target.review_id
            and promotion.analysis_id == target.analysis_id
            and promotion.workflow_id == target.workflow_id
            and promotion.retrieval_id == target.retrieval_id
            and promotion.source_context_snapshot_id
            == target.source_context_snapshot_id
            and promotion.source_context_fingerprint
            == target.source_context_fingerprint
            and promotion.source_retrieval_target_fingerprint
            == target.source_retrieval_target_fingerprint
            and promotion.source_promotion_ids == target.source_promotion_ids
            and content_fingerprint(list(promotion.selected_memory_sources))
            == content_fingerprint(list(target.selected_memory_sources))
            and promotion.report_artifact_id == target.report_artifact_id
            and promotion.report_artifact_fingerprint
            == target.report_artifact_fingerprint
            and promotion.evidence_reference_ids == target.evidence_reference_ids
            and promotion.provider_id == target.provider_id
            and promotion.model_id == target.model_id
            and promotion.prompt_version == target.prompt_version
            and promotion.review_target_fingerprint == target.review_target_fingerprint
            and promotion.review_event_hash == target.review_event_hash
            and promotion.quality_evidence_fingerprint
            == target.quality_evidence_fingerprint
            and promotion.cost_evidence_fingerprint == target.cost_evidence_fingerprint
        )

    @property
    def memory_artifact_binding_valid(self) -> bool:
        target = self.current_target
        if (
            target.memory_content is None
            or target.memory_artifact_fingerprint is None
            or target.report_artifact_id is None
        ):
            return False
        expected = content_fingerprint(
            memory_artifact_payload(
                review_id=target.review_id,
                analysis_id=target.analysis_id,
                report_artifact_id=target.report_artifact_id,
                content=target.memory_content,
                evidence_reference_ids=target.evidence_reference_ids,
            )
        )
        return (
            self.promotion.memory_content == target.memory_content
            and self.promotion.memory_artifact_fingerprint == expected
            and target.memory_artifact_fingerprint == expected
            and self.promotion.memory_artifact_id
            == f"ai-external-promoted-analysis-memory-{expected[:24]}"
        )

    @property
    def revocation_binding_valid(self) -> bool:
        revocation = self.revocation
        if revocation is None:
            return True
        return (
            revocation.promotion_id == self.promotion.promotion_id
            and revocation.promotion_target_fingerprint
            == self.promotion.promotion_target_fingerprint
            and revocation.memory_artifact_fingerprint
            == self.promotion.memory_artifact_fingerprint
        )

    @property
    def revoked(self) -> bool:
        return self.revocation is not None

    @property
    def historical_record_valid(self) -> bool:
        return (
            self.promotion_binding_valid
            and self.source_binding_valid
            and self.memory_artifact_binding_valid
            and self.revocation_binding_valid
            and self.audit_replay.valid
        )

    @property
    def memory_recall_eligible(self) -> bool:
        return self.historical_record_valid and not self.revoked

    @property
    def effective_status(self) -> ExternalPromotedAnalysisMemoryEffectiveStatus:
        if not self.historical_record_valid:
            return (
                ExternalPromotedAnalysisMemoryEffectiveStatus.INVALIDATED_BY_SOURCE_DRIFT
            )
        if self.revoked:
            return ExternalPromotedAnalysisMemoryEffectiveStatus.REVOKED
        return ExternalPromotedAnalysisMemoryEffectiveStatus.RECALL_ELIGIBLE

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.promotion_binding_valid:
            reasons.append("promoted_analysis_memory_target_fingerprint_drift")
        if not self.source_binding_valid:
            reasons.extend(self.current_target.errors)
            reasons.append("promoted_analysis_memory_source_binding_drift")
        if not self.memory_artifact_binding_valid:
            reasons.append("promoted_analysis_memory_artifact_binding_drift")
        if not self.revocation_binding_valid:
            reasons.append("promoted_analysis_memory_revocation_binding_drift")
        reasons.extend(self.audit_replay.errors)
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalPromotedAnalysisMemoryReplay:
        return ExternalPromotedAnalysisMemoryReplay(
            promotion_id=self.promotion.promotion_id,
            review_id=self.promotion.review_id,
            valid=self.historical_record_valid,
            event_chain_valid=self.audit_replay.valid,
            promotion_binding_valid=self.promotion_binding_valid,
            source_binding_valid=self.source_binding_valid,
            memory_artifact_binding_valid=self.memory_artifact_binding_valid,
            revocation_binding_valid=self.revocation_binding_valid,
            revoked=self.revoked,
            memory_recall_eligible=self.memory_recall_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        promotion = self.promotion
        revocation = self.revocation
        return {
            "schema_version": EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
            "promotion_id": promotion.promotion_id,
            "review_id": promotion.review_id,
            "analysis_id": promotion.analysis_id,
            "workflow_id": promotion.workflow_id,
            "retrieval_id": promotion.retrieval_id,
            "effective_status": self.effective_status.value,
            "promoted_by": promotion.request.promoted_by,
            "rationale": promotion.request.rationale,
            "created_at": promotion.created_at,
            "source_promotion_ids": list(promotion.source_promotion_ids),
            "selected_memory_sources": [
                dict(item) for item in promotion.selected_memory_sources
            ],
            "source_context_snapshot_id": promotion.source_context_snapshot_id,
            "source_context_fingerprint": promotion.source_context_fingerprint,
            "source_retrieval_target_fingerprint": (
                promotion.source_retrieval_target_fingerprint
            ),
            "report_artifact_id": promotion.report_artifact_id,
            "report_artifact_fingerprint": promotion.report_artifact_fingerprint,
            "provider_id": promotion.provider_id,
            "model_id": promotion.model_id,
            "prompt_version": promotion.prompt_version,
            "review_target_fingerprint": promotion.review_target_fingerprint,
            "review_event_hash": promotion.review_event_hash,
            "quality_evidence_fingerprint": promotion.quality_evidence_fingerprint,
            "cost_evidence_fingerprint": promotion.cost_evidence_fingerprint,
            "stored_promotion_target_fingerprint": (
                promotion.promotion_target_fingerprint
            ),
            "current_promotion_target_fingerprint": self.current_target.fingerprint,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "memory_artifact": {
                "artifact_id": promotion.memory_artifact_id,
                "artifact_kind": ArtifactKind.MEMORY.value,
                "artifact_fingerprint": promotion.memory_artifact_fingerprint,
                "evidence_reference_ids": list(promotion.evidence_reference_ids),
                "content": (
                    dict(promotion.memory_content)
                    if self.memory_recall_eligible
                    else None
                ),
            },
            "revoked": self.revoked,
            "revocation": (
                {
                    "revocation_id": revocation.revocation_id,
                    "revoked_by": revocation.request.revoked_by,
                    "reason": revocation.request.reason,
                    "created_at": revocation.created_at,
                }
                if revocation is not None
                else None
            ),
            "revocation_binding_valid": self.revocation_binding_valid,
            "memory_recall_eligible": self.memory_recall_eligible,
            "invalidation_reasons": list(self.invalidation_reasons),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "explicit_human_promotion_required": True,
            "automatic_memory_promotion_enabled": False,
            "automatic_recall_enabled": False,
            "retrieval_contract_available": True,
            "retrieval_contract_version": (
                "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
            ),
            "legacy_phase_1_12_contract_modified": False,
            "external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


def memory_artifact_payload(
    *,
    review_id: str,
    analysis_id: str,
    report_artifact_id: str,
    content: JsonObject,
    evidence_reference_ids: Sequence[str],
) -> JsonObject:
    """Return the canonical fingerprint payload for the stored memory artifact."""
    return {
        "kind": ArtifactKind.MEMORY.value,
        "source_review_id": review_id,
        "source_analysis_id": analysis_id,
        "source_artifact_ids": [report_artifact_id],
        "content": dict(content),
        "evidence_reference_ids": list(evidence_reference_ids),
        "authority_effect": "none",
    }
