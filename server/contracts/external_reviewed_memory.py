"""Stable contracts for revocable external reviewed-research memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from server.ai_runtime.contracts import JsonObject, content_fingerprint

EXTERNAL_REVIEWED_MEMORY_PROMOTION_CONFIRMATION = (
    "promote_reviewed_external_research_to_revocable_historical_memory_"
    "without_current_fact_decision_or_trade_authority"
)
EXTERNAL_REVIEWED_MEMORY_REVOCATION_CONFIRMATION = (
    "revoke_external_research_memory_recall_without_deleting_history_or_"
    "changing_trade_authority"
)
EXTERNAL_REVIEWED_MEMORY_CONTRACT_VERSION = (
    "karkinos.ai.external_reviewed_memory_promotion.v1"
)


class ExternalReviewedMemoryEffectiveStatus(StrEnum):
    RECALL_ELIGIBLE = "recall_eligible"
    REVOKED = "revoked"
    INVALIDATED_BY_SOURCE_DRIFT = "invalidated_by_source_drift"


class ExternalReviewedMemoryPromotionRejected(ValueError):
    """Raised when an explicit promotion or revocation fails closed."""


@dataclass(frozen=True)
class ExternalReviewedMemoryPromotionRequest:
    idempotency_key: str
    promoted_by: str
    rationale: str
    confirmation: str
    schema_version: str = "karkinos.ai.external_reviewed_memory_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "promoted_by",
            "rationale",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != EXTERNAL_REVIEWED_MEMORY_PROMOTION_CONFIRMATION:
            raise ValueError(
                "explicit reviewed-research memory confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "promoted_by": self.promoted_by,
            "rationale": self.rationale,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalReviewedMemoryRevocationRequest:
    idempotency_key: str
    revoked_by: str
    reason: str
    confirmation: str
    schema_version: str = "karkinos.ai.external_reviewed_memory_revocation_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "revoked_by",
            "reason",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != EXTERNAL_REVIEWED_MEMORY_REVOCATION_CONFIRMATION:
            raise ValueError(
                "explicit reviewed-memory revocation confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "revoked_by": self.revoked_by,
            "reason": self.reason,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalReviewedMemoryTarget:
    review_id: str
    analysis_id: str
    workflow_id: str
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_id: str | None
    source_retrieval_target_fingerprint: str | None
    report_artifact_id: str | None
    report_artifact_fingerprint: str | None
    evidence_reference_ids: tuple[str, ...]
    provider_id: str
    model_id: str
    prompt_version: str
    memory_content: JsonObject | None
    memory_artifact_fingerprint: str | None
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return (
            not self.errors
            and self.report_artifact_id is not None
            and self.memory_content is not None
            and self.memory_artifact_fingerprint is not None
            and bool(self.evidence_reference_ids)
        )


@dataclass(frozen=True)
class StoredExternalReviewedMemoryPromotion:
    promotion_id: str
    review_id: str
    analysis_id: str
    workflow_id: str
    request: ExternalReviewedMemoryPromotionRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_id: str
    memory_content: JsonObject
    memory_artifact_fingerprint: str
    evidence_reference_ids: tuple[str, ...]
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_id: str | None
    source_retrieval_target_fingerprint: str | None
    report_artifact_id: str
    report_artifact_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    created_at: str


@dataclass(frozen=True)
class StoredExternalReviewedMemoryRevocation:
    revocation_id: str
    promotion_id: str
    request: ExternalReviewedMemoryRevocationRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ExternalReviewedMemoryAuditReplay:
    promotion_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalReviewedMemoryReplay:
    promotion_id: str
    review_id: str
    valid: bool
    promotion_binding_valid: bool
    source_binding_valid: bool
    memory_artifact_binding_valid: bool
    revocation_binding_valid: bool
    event_chain_valid: bool
    revoked: bool
    memory_recall_eligible: bool
    effective_status: ExternalReviewedMemoryEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.external_reviewed_memory_replay.v1",
            "promotion_id": self.promotion_id,
            "review_id": self.review_id,
            "valid": self.valid,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "revocation_binding_valid": self.revocation_binding_valid,
            "event_chain_valid": self.event_chain_valid,
            "revoked": self.revoked,
            "memory_recall_eligible": self.memory_recall_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_is_current_fact": False,
            "automatic_recall_enabled": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }
