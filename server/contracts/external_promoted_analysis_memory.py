"""Stable contracts for explicitly promoted external-analysis memory."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from server.ai_runtime.contracts import JsonObject, StoredArtifact, content_fingerprint

EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION = (
    "promote_reviewed_promoted_memory_analysis_to_revocable_historical_"
    "memory_without_current_fact_decision_or_trade_authority"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION = (
    "revoke_promoted_analysis_memory_recall_without_deleting_history_or_"
    "changing_trade_authority"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_promotion.v1"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_request.v1"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_revocation_request.v1"
)


class ExternalPromotedAnalysisMemoryEffectiveStatus(StrEnum):
    RECALL_ELIGIBLE = "recall_eligible"
    REVOKED = "revoked"
    INVALIDATED_BY_SOURCE_DRIFT = "invalidated_by_source_drift"


class ExternalPromotedAnalysisMemoryRejected(ValueError):
    """Raised when a promotion or revocation fails closed."""


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryPromotionRequest:
    idempotency_key: str
    promoted_by: str
    rationale: str
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "promoted_by",
            "rationale",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != (
            EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION
        ):
            raise ValueError(
                "explicit promoted-analysis memory confirmation is required"
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
class ExternalPromotedAnalysisMemoryRevocationRequest:
    idempotency_key: str
    revoked_by: str
    reason: str
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "revoked_by",
            "reason",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != (
            EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION
        ):
            raise ValueError(
                "explicit promoted-analysis memory revocation confirmation is "
                "required"
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
class ExternalPromotedAnalysisMemoryTarget:
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    source_promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    report_artifact_id: str | None
    report_artifact_fingerprint: str | None
    evidence_reference_ids: tuple[str, ...]
    provider_id: str
    model_id: str
    prompt_version: str
    review_target_fingerprint: str
    review_event_hash: str | None
    quality_evidence_fingerprint: str
    cost_evidence_fingerprint: str
    memory_content: JsonObject | None
    memory_artifact_fingerprint: str | None
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return (
            not self.errors
            and self.report_artifact_id is not None
            and self.report_artifact_fingerprint is not None
            and bool(self.evidence_reference_ids)
            and bool(self.source_promotion_ids)
            and len(self.source_promotion_ids) == len(self.selected_memory_sources)
            and self.memory_content is not None
            and self.memory_artifact_fingerprint is not None
        )


@dataclass(frozen=True)
class StoredExternalPromotedAnalysisMemoryPromotion:
    promotion_id: str
    review_id: str
    analysis_id: str
    workflow_id: str
    retrieval_id: str
    request: ExternalPromotedAnalysisMemoryPromotionRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_id: str
    memory_content: JsonObject
    memory_artifact_fingerprint: str
    evidence_reference_ids: tuple[str, ...]
    source_context_snapshot_id: str
    source_context_fingerprint: str
    source_retrieval_target_fingerprint: str | None
    source_promotion_ids: tuple[str, ...]
    selected_memory_sources: tuple[JsonObject, ...]
    report_artifact_id: str
    report_artifact_fingerprint: str
    provider_id: str
    model_id: str
    prompt_version: str
    review_target_fingerprint: str
    review_event_hash: str | None
    quality_evidence_fingerprint: str
    cost_evidence_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class StoredExternalPromotedAnalysisMemoryRevocation:
    revocation_id: str
    promotion_id: str
    request: ExternalPromotedAnalysisMemoryRevocationRequest
    request_fingerprint: str
    promotion_target_fingerprint: str
    memory_artifact_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryAuditReplay:
    promotion_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryReplay:
    promotion_id: str
    review_id: str
    valid: bool
    event_chain_valid: bool
    promotion_binding_valid: bool
    source_binding_valid: bool
    memory_artifact_binding_valid: bool
    revocation_binding_valid: bool
    revoked: bool
    memory_recall_eligible: bool
    effective_status: ExternalPromotedAnalysisMemoryEffectiveStatus
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": (
                "karkinos.ai.external_promoted_analysis_memory_replay.v1"
            ),
            "promotion_id": self.promotion_id,
            "review_id": self.review_id,
            "valid": self.valid,
            "event_chain_valid": self.event_chain_valid,
            "promotion_binding_valid": self.promotion_binding_valid,
            "source_binding_valid": self.source_binding_valid,
            "memory_artifact_binding_valid": self.memory_artifact_binding_valid,
            "revocation_binding_valid": self.revocation_binding_valid,
            "revoked": self.revoked,
            "memory_recall_eligible": self.memory_recall_eligible,
            "effective_status": self.effective_status.value,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "automatic_recall_enabled": False,
            "retrieval_contract_available": True,
            "retrieval_contract_version": (
                "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
            ),
            "legacy_phase_1_12_contract_modified": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
        }


class ExternalPromotedAnalysisMemoryRepository(Protocol):
    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion | None: ...

    def record_promotion(
        self,
        *,
        request: ExternalPromotedAnalysisMemoryPromotionRequest,
        target: ExternalPromotedAnalysisMemoryTarget,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, bool]: ...

    def record_revocation(
        self,
        *,
        promotion: StoredExternalPromotedAnalysisMemoryPromotion,
        request: ExternalPromotedAnalysisMemoryRevocationRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRevocation, bool]: ...

    def get(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion: ...

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, ...]: ...

    def get_revocation(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryRevocation | None: ...

    def verify_replay(
        self,
        promotion_id: str,
    ) -> ExternalPromotedAnalysisMemoryAuditReplay: ...


class ExternalPromotedAnalysisMemoryArtifactReader(Protocol):
    def list_artifacts(self, workflow_id: str) -> Sequence[StoredArtifact]: ...
