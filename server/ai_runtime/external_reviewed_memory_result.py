"""Replay and projection result for external reviewed memory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from server.contracts.external_reviewed_memory import (
    EXTERNAL_REVIEWED_MEMORY_CONTRACT_VERSION,
    ExternalReviewedMemoryAuditReplay,
    ExternalReviewedMemoryEffectiveStatus,
    ExternalReviewedMemoryReplay,
    ExternalReviewedMemoryTarget,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
)

from .contracts import ArtifactKind, JsonObject, content_fingerprint
from .external_reviewed_memory_values import (
    external_reviewed_memory_artifact_payload,
)


@dataclass(frozen=True)
class ExternalReviewedMemoryPromotionResult:
    _memory_artifact_payload: ClassVar[Callable[..., JsonObject]] = staticmethod(
        external_reviewed_memory_artifact_payload
    )

    promotion: StoredExternalReviewedMemoryPromotion
    current_target: ExternalReviewedMemoryTarget
    revocation: StoredExternalReviewedMemoryRevocation | None
    audit_replay: ExternalReviewedMemoryAuditReplay
    reused: bool

    @property
    def promotion_binding_valid(self) -> bool:
        return (
            self.promotion.request_fingerprint == self.promotion.request.fingerprint
            and self.promotion.review_id == self.current_target.review_id
        )

    @property
    def source_binding_valid(self) -> bool:
        target = self.current_target
        promotion = self.promotion
        return (
            target.eligible
            and promotion.promotion_target_fingerprint == target.fingerprint
            and promotion.analysis_id == target.analysis_id
            and promotion.workflow_id == target.workflow_id
            and promotion.source_context_snapshot_id
            == target.source_context_snapshot_id
            and promotion.source_context_fingerprint
            == target.source_context_fingerprint
            and promotion.source_retrieval_id == target.source_retrieval_id
            and promotion.source_retrieval_target_fingerprint
            == target.source_retrieval_target_fingerprint
            and promotion.report_artifact_id == target.report_artifact_id
            and promotion.report_artifact_fingerprint
            == target.report_artifact_fingerprint
            and promotion.evidence_reference_ids == target.evidence_reference_ids
            and promotion.provider_id == target.provider_id
            and promotion.model_id == target.model_id
            and promotion.prompt_version == target.prompt_version
            and promotion.memory_artifact_fingerprint
            == target.memory_artifact_fingerprint
        )

    @property
    def memory_artifact_binding_valid(self) -> bool:
        expected_fingerprint = content_fingerprint(
            self._memory_artifact_payload(
                review_id=self.promotion.review_id,
                analysis_id=self.promotion.analysis_id,
                report_artifact_id=self.promotion.report_artifact_id,
                content=self.promotion.memory_content,
                evidence_reference_ids=self.promotion.evidence_reference_ids,
            )
        )
        return (
            self.promotion.memory_artifact_fingerprint == expected_fingerprint
            and self.promotion.memory_artifact_id
            == f"ai-external-memory-{expected_fingerprint[:24]}"
        )

    @property
    def revocation_binding_valid(self) -> bool:
        revocation = self.revocation
        if revocation is None:
            return True
        return (
            revocation.promotion_id == self.promotion.promotion_id
            and revocation.request_fingerprint == revocation.request.fingerprint
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
    def effective_status(self) -> ExternalReviewedMemoryEffectiveStatus:
        if not self.historical_record_valid:
            return ExternalReviewedMemoryEffectiveStatus.INVALIDATED_BY_SOURCE_DRIFT
        if self.revoked:
            return ExternalReviewedMemoryEffectiveStatus.REVOKED
        return ExternalReviewedMemoryEffectiveStatus.RECALL_ELIGIBLE

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.promotion_binding_valid:
            reasons.append("memory_promotion_request_binding_drift")
        if not self.source_binding_valid:
            reasons.append("memory_promotion_source_binding_drift")
        if not self.memory_artifact_binding_valid:
            reasons.append("memory_artifact_fingerprint_drift")
        if not self.revocation_binding_valid:
            reasons.append("memory_revocation_binding_drift")
        reasons.extend(self.current_target.errors)
        reasons.extend(self.audit_replay.errors)
        if self.revoked:
            reasons.append("memory_recall_revoked")
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalReviewedMemoryReplay:
        return ExternalReviewedMemoryReplay(
            promotion_id=self.promotion.promotion_id,
            review_id=self.promotion.review_id,
            valid=self.historical_record_valid,
            promotion_binding_valid=self.promotion_binding_valid,
            source_binding_valid=self.source_binding_valid,
            memory_artifact_binding_valid=self.memory_artifact_binding_valid,
            revocation_binding_valid=self.revocation_binding_valid,
            event_chain_valid=self.audit_replay.valid,
            revoked=self.revoked,
            memory_recall_eligible=self.memory_recall_eligible,
            effective_status=self.effective_status,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        memory = self.promotion
        return {
            "schema_version": EXTERNAL_REVIEWED_MEMORY_CONTRACT_VERSION,
            "promotion_id": memory.promotion_id,
            "review_id": memory.review_id,
            "analysis_id": memory.analysis_id,
            "workflow_id": memory.workflow_id,
            "promoted_by": memory.request.promoted_by,
            "rationale": memory.request.rationale,
            "created_at": memory.created_at,
            "effective_status": self.effective_status.value,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "revocation_binding_valid": self.revocation_binding_valid,
            "memory_recall_eligible": self.memory_recall_eligible,
            "invalidation_reasons": list(self.invalidation_reasons),
            "memory_artifact": {
                "artifact_id": memory.memory_artifact_id,
                "kind": ArtifactKind.MEMORY.value,
                "fingerprint": memory.memory_artifact_fingerprint,
                "content": (
                    dict(memory.memory_content) if self.memory_recall_eligible else None
                ),
                "content_hidden": not self.memory_recall_eligible,
                "evidence_reference_ids": list(memory.evidence_reference_ids),
                "source_artifact_ids": [memory.report_artifact_id],
                "source_review_id": memory.review_id,
                "is_current_fact": False,
                "requires_current_evidence_rebinding": True,
                "authority_effect": "none",
            },
            "source_binding": {
                "context_snapshot_id": memory.source_context_snapshot_id,
                "context_fingerprint": memory.source_context_fingerprint,
                "retrieval_id": memory.source_retrieval_id,
                "retrieval_target_fingerprint": (
                    memory.source_retrieval_target_fingerprint
                ),
                "report_artifact_id": memory.report_artifact_id,
                "report_artifact_fingerprint": memory.report_artifact_fingerprint,
                "provider_id": memory.provider_id,
                "model_id": memory.model_id,
                "prompt_version": memory.prompt_version,
            },
            "revocation": (
                {
                    "revocation_id": self.revocation.revocation_id,
                    "revoked_by": self.revocation.request.revoked_by,
                    "reason": self.revocation.request.reason,
                    "created_at": self.revocation.created_at,
                }
                if self.revocation is not None
                else None
            ),
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "reused": self.reused,
            "explicit_human_promotion_required": True,
            "automatic_recall_enabled": False,
            "legacy_retrieval_contract_modified": False,
            "external_model_invocation_count": 0,
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "provider_promotion_eligible": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }
