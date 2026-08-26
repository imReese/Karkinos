"""Stable contracts for human review of promoted-memory analyses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ExternalAnalysisReviewEffectiveStatus,
    ProviderPricingSnapshot,
)

EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION = (
    "record_external_promoted_memory_analysis_review_without_memory_decision_or_"
    "trade_authority"
)
EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_memory_analysis_review.v1"
)
EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_memory_analysis_review_request.v1"
)


class ExternalPromotedMemoryAnalysisReviewRejected(ValueError):
    """Raised when a promoted-memory analysis disposition fails local gates."""


@dataclass(frozen=True)
class HumanExternalPromotedMemoryAnalysisReviewRequest:
    idempotency_key: str
    reviewed_by: str
    decision: ExternalAnalysisReviewDecision
    note: str
    quality_rubric: ExternalAnalysisQualityRubric
    factual_error_count: int
    unsupported_claim_count: int
    pricing_snapshot: ProviderPricingSnapshot | None
    pricing_unavailable_reason: str | None
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.schema_version != (
            EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION
        ):
            raise ValueError("promoted-memory analysis review request version drifted")
        for field_name in ("factual_error_count", "unsupported_claim_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        unavailable_reason = str(self.pricing_unavailable_reason or "").strip()
        if self.pricing_snapshot is None and not unavailable_reason:
            raise ValueError(
                "pricing_unavailable_reason is required without a pricing snapshot"
            )
        if self.pricing_snapshot is not None and unavailable_reason:
            raise ValueError(
                "pricing snapshot and pricing_unavailable_reason are mutually exclusive"
            )
        if self.pricing_snapshot is None:
            object.__setattr__(self, "pricing_unavailable_reason", unavailable_reason)
        if self.confirmation != EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION:
            raise ValueError(
                "explicit promoted-memory external analysis review confirmation "
                "is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "reviewed_by": self.reviewed_by,
            "decision": self.decision.value,
            "note": self.note,
            "quality_rubric": self.quality_rubric.to_dict(),
            "factual_error_count": self.factual_error_count,
            "unsupported_claim_count": self.unsupported_claim_count,
            "pricing_snapshot": (
                self.pricing_snapshot.to_dict() if self.pricing_snapshot else None
            ),
            "pricing_unavailable_reason": self.pricing_unavailable_reason,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewTarget:
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    context_snapshot_id: str
    context_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    report_artifact_id: str | None
    promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    base_analysis_target_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    quality_evidence: JsonObject
    fingerprint: str
    acceptance_errors: tuple[str, ...]

    @property
    def acceptance_eligible(self) -> bool:
        return (
            not self.acceptance_errors
            and self.report_artifact_id is not None
            and bool(self.promotion_ids)
            and len(self.selected_memory_sources) == len(self.promotion_ids)
        )


@dataclass(frozen=True)
class StoredExternalPromotedMemoryAnalysisReview:
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    idempotency_key: str
    request: HumanExternalPromotedMemoryAnalysisReviewRequest
    request_fingerprint: str
    analysis_target_fingerprint: str
    base_analysis_target_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    report_artifact_id: str | None
    provider_id: str
    model_id: str
    prompt_version: str
    promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    quality_evidence: JsonObject
    cost_evidence: JsonObject
    created_at: str


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewAuditReplay:
    review_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisReviewReplay:
    review_id: str
    analysis_id: str
    valid: bool
    review_event_chain_valid: bool
    analysis_target_binding_valid: bool
    reviewed_research_eligible: bool
    effective_status: ExternalAnalysisReviewEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": (
                "karkinos.ai.external_promoted_memory_analysis_review_replay.v1"
            ),
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "valid": self.valid,
            "review_event_chain_valid": self.review_event_chain_valid,
            "analysis_target_binding_valid": self.analysis_target_binding_valid,
            "reviewed_research_eligible": self.reviewed_research_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_artifact_created": False,
            "memory_recall_eligible": False,
            "automatic_memory_promotion_enabled": False,
            "provider_promotion_eligible": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


class ExternalPromotedMemoryAnalysisReviewRepository(Protocol):
    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedMemoryAnalysisReview | None: ...

    def record(
        self,
        *,
        target: ExternalPromotedMemoryAnalysisReviewTarget,
        request: HumanExternalPromotedMemoryAnalysisReviewRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, bool]: ...

    def get(self, review_id: str) -> StoredExternalPromotedMemoryAnalysisReview: ...

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, ...]: ...

    def verify_replay(
        self,
        review_id: str,
    ) -> ExternalPromotedMemoryAnalysisReviewAuditReplay: ...
