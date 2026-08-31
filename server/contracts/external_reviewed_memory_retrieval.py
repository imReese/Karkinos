"""Stable contracts for external reviewed-memory retrieval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from server.ai_runtime.contracts import (
    EvidenceBoundContextSnapshot,
    JsonObject,
    content_fingerprint,
)
from server.ai_runtime.evidence import CanonicalEvidenceRecord
from server.ai_runtime.memory_retrieval import EvidenceRebinding

EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION = (
    "retrieve_promoted_external_reviewed_memory_with_current_canonical_"
    "evidence_as_non_authoritative_research_input"
)
EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION = (
    "karkinos.ai.external_reviewed_memory_retrieval.v1"
)
_MAX_PROMOTION_IDS = 20

CurrentContextValidator = Callable[
    [EvidenceBoundContextSnapshot],
    tuple[CanonicalEvidenceRecord, ...],
]


class ExternalReviewedMemoryRetrievalRejected(ValueError):
    """Raised when a promoted memory or current context fails closed."""


@dataclass(frozen=True)
class HumanExternalReviewedMemoryRetrievalRequest:
    idempotency_key: str
    requested_by: str
    purpose: str
    current_context_snapshot_id: str
    promotion_ids: tuple[str, ...]
    confirmation: str
    schema_version: str = "karkinos.ai.external_reviewed_memory_retrieval_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "requested_by",
            "purpose",
            "current_context_snapshot_id",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not self.promotion_ids or len(self.promotion_ids) > _MAX_PROMOTION_IDS:
            raise ValueError(
                "promotion_ids must contain between 1 and "
                f"{_MAX_PROMOTION_IDS} items"
            )
        if any(not item.strip() for item in self.promotion_ids):
            raise ValueError("promotion_ids must not contain empty values")
        if len(self.promotion_ids) != len(set(self.promotion_ids)):
            raise ValueError("promotion_ids must be unique")
        if self.confirmation != EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION:
            raise ValueError(
                "explicit promoted external-memory retrieval confirmation is "
                "required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "purpose": self.purpose,
            "current_context_snapshot_id": self.current_context_snapshot_id,
            "promotion_ids": list(self.promotion_ids),
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalReviewedMemorySelection:
    promotion_id: str
    review_id: str
    analysis_id: str
    source_context_snapshot_id: str
    memory_artifact_id: str
    memory_artifact_fingerprint: str
    memory_content: JsonObject
    rebindings: tuple[EvidenceRebinding, ...]
    fingerprint: str

    def to_dict(self) -> JsonObject:
        return {
            "source_type": "external_reviewed_memory_promotion",
            "promotion_id": self.promotion_id,
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "source_context_snapshot_id": self.source_context_snapshot_id,
            "memory_artifact_id": self.memory_artifact_id,
            "memory_artifact_fingerprint": self.memory_artifact_fingerprint,
            "memory_content": dict(self.memory_content),
            "evidence_rebindings": [item.to_dict() for item in self.rebindings],
            "selection_fingerprint": self.fingerprint,
            "memory_role": "historical_reviewed_research_input",
            "memory_is_current_fact": False,
            "current_evidence_must_be_read": True,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ExternalReviewedMemoryRetrievalTarget:
    current_context_snapshot_id: str
    current_context_fingerprint: str | None
    valuation_snapshot_id: str | None
    ledger_cutoff_id: int | None
    ledger_fingerprint: str | None
    selections: tuple[ExternalReviewedMemorySelection, ...]
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.errors and bool(self.selections)


@dataclass(frozen=True)
class StoredExternalReviewedMemoryRetrieval:
    retrieval_id: str
    request: HumanExternalReviewedMemoryRetrievalRequest
    stored_idempotency_key: str
    request_fingerprint: str
    stored_current_context_snapshot_id: str
    retrieval_target_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ExternalReviewedMemoryRetrievalAuditReplay:
    retrieval_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalReviewedMemoryRetrievalReplay:
    retrieval_id: str
    valid: bool
    retrieval_eligible: bool
    request_binding_valid: bool
    target_binding_valid: bool
    event_chain_valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": (
                "karkinos.ai.external_reviewed_memory_retrieval_replay.v1"
            ),
            "retrieval_id": self.retrieval_id,
            "valid": self.valid,
            "retrieval_eligible": self.retrieval_eligible,
            "request_binding_valid": self.request_binding_valid,
            "target_binding_valid": self.target_binding_valid,
            "event_chain_valid": self.event_chain_valid,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "legacy_retrieval_v1_modified": False,
            "memory_is_account_fact": False,
            "automatic_recall_enabled": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }
