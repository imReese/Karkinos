"""Stable contracts for explicit reviewed-memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.ai_runtime.contracts import JsonObject, content_fingerprint

REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION = (
    "retrieve_reviewed_memory_as_non_authoritative_research_input"
)
REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION = "karkinos.ai.reviewed_memory_retrieval.v1"
MAX_REVIEWED_MEMORY_REVIEW_IDS = 20


class ReviewedMemoryRetrievalRejected(ValueError):
    """Raised when a requested memory cannot pass the retrieval gates."""


@dataclass(frozen=True)
class HumanReviewedMemoryRetrievalRequest:
    idempotency_key: str
    requested_by: str
    purpose: str
    current_context_snapshot_id: str
    review_ids: tuple[str, ...]
    confirmation: str
    schema_version: str = "karkinos.ai.reviewed_memory_retrieval_request.v1"

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
        if not self.review_ids or len(self.review_ids) > MAX_REVIEWED_MEMORY_REVIEW_IDS:
            raise ValueError(
                "review_ids must contain between 1 and "
                f"{MAX_REVIEWED_MEMORY_REVIEW_IDS} items"
            )
        if any(not item.strip() for item in self.review_ids):
            raise ValueError("review_ids must not contain empty values")
        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids must be unique")
        if self.confirmation != REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION:
            raise ValueError(
                "explicit non-authoritative reviewed-memory retrieval "
                "confirmation is required"
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
            "review_ids": list(self.review_ids),
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class EvidenceRebinding:
    tool_name: str
    kind: str
    source_reference_id: str
    source_fingerprint: str
    current_reference_id: str
    current_fingerprint: str
    current_status: str

    def to_dict(self) -> JsonObject:
        return {
            "tool_name": self.tool_name,
            "kind": self.kind,
            "source_reference_id": self.source_reference_id,
            "source_fingerprint": self.source_fingerprint,
            "current_reference_id": self.current_reference_id,
            "current_fingerprint": self.current_fingerprint,
            "current_status": self.current_status,
            "same_evidence_identity": (
                self.source_reference_id == self.current_reference_id
            ),
        }


@dataclass(frozen=True)
class ReviewedMemorySelection:
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
class ReviewedMemoryRetrievalTarget:
    current_context_snapshot_id: str
    current_context_fingerprint: str | None
    valuation_snapshot_id: str | None
    ledger_cutoff_id: int | None
    ledger_fingerprint: str | None
    selections: tuple[ReviewedMemorySelection, ...]
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.errors and bool(self.selections)


@dataclass(frozen=True)
class StoredReviewedMemoryRetrieval:
    retrieval_id: str
    request: HumanReviewedMemoryRetrievalRequest
    stored_idempotency_key: str
    request_fingerprint: str
    stored_current_context_snapshot_id: str
    retrieval_target_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ReviewedMemoryRetrievalAuditReplay:
    retrieval_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedMemoryRetrievalReplay:
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
            "schema_version": "karkinos.ai.reviewed_memory_retrieval_replay.v1",
            "retrieval_id": self.retrieval_id,
            "valid": self.valid,
            "retrieval_eligible": self.retrieval_eligible,
            "request_binding_valid": self.request_binding_valid,
            "target_binding_valid": self.target_binding_valid,
            "event_chain_valid": self.event_chain_valid,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_is_account_fact": False,
            "decision_handoff_enabled": False,
            "provider_invocation_count": 0,
            "authority_effect": "none",
        }


class ReviewedMemoryRetrievalRepository(Protocol):
    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredReviewedMemoryRetrieval | None: ...

    def record(
        self,
        *,
        request: HumanReviewedMemoryRetrievalRequest,
        target: ReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredReviewedMemoryRetrieval, bool]: ...

    def get(self, retrieval_id: str) -> StoredReviewedMemoryRetrieval: ...

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredReviewedMemoryRetrieval, ...]: ...

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ReviewedMemoryRetrievalAuditReplay: ...
