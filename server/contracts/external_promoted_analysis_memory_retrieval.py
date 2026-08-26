"""Stable contracts for explicit retrieval of promoted analysis memory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from server.ai_runtime.contracts import (
    EvidenceBoundContextSnapshot,
    JsonObject,
    content_fingerprint,
)
from server.ai_runtime.evidence import CanonicalEvidenceRecord
from server.ai_runtime.memory_retrieval import EvidenceRebinding

EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION = (
    "retrieve_promoted_external_analysis_memory_with_current_canonical_"
    "evidence_as_non_authoritative_research_input"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
)
EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_analysis_memory_retrieval_request.v1"
)
MAX_EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_IDS = 20

CurrentContextValidator = Callable[
    [EvidenceBoundContextSnapshot],
    tuple[CanonicalEvidenceRecord, ...],
]


class ExternalPromotedAnalysisMemoryRetrievalRejected(ValueError):
    """Raised when a promoted memory or current context fails closed."""


@dataclass(frozen=True)
class HumanExternalPromotedAnalysisMemoryRetrievalRequest:
    idempotency_key: str
    requested_by: str
    purpose: str
    current_context_snapshot_id: str
    promotion_ids: tuple[str, ...]
    confirmation: str
    schema_version: str = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_REQUEST_VERSION

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
        if (
            not self.promotion_ids
            or len(self.promotion_ids)
            > MAX_EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_IDS
        ):
            raise ValueError(
                "promotion_ids must contain between 1 and "
                f"{MAX_EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_IDS} items"
            )
        if any(not item.strip() for item in self.promotion_ids):
            raise ValueError("promotion_ids must not contain empty values")
        if len(self.promotion_ids) != len(set(self.promotion_ids)):
            raise ValueError("promotion_ids must be unique")
        if (
            self.confirmation
            != EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION
        ):
            raise ValueError(
                "explicit promoted-analysis memory retrieval confirmation is "
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
class ExternalPromotedAnalysisMemorySelection:
    promotion_id: str
    review_id: str
    analysis_id: str
    workflow_id: str
    source_context_snapshot_id: str
    memory_artifact_id: str
    memory_artifact_fingerprint: str
    memory_content: JsonObject
    provider_id: str
    model_id: str
    prompt_version: str
    rebindings: tuple[EvidenceRebinding, ...]
    fingerprint: str

    def to_dict(self) -> JsonObject:
        return {
            "source_type": "external_promoted_analysis_memory",
            "promotion_id": self.promotion_id,
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "workflow_id": self.workflow_id,
            "source_context_snapshot_id": self.source_context_snapshot_id,
            "memory_artifact_id": self.memory_artifact_id,
            "memory_artifact_fingerprint": self.memory_artifact_fingerprint,
            "memory_content": dict(self.memory_content),
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "evidence_rebindings": [item.to_dict() for item in self.rebindings],
            "selection_fingerprint": self.fingerprint,
            "memory_role": "historical_reviewed_research_input",
            "memory_is_current_fact": False,
            "current_evidence_must_be_read": True,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryRetrievalTarget:
    current_context_snapshot_id: str
    current_context_fingerprint: str | None
    valuation_snapshot_id: str | None
    ledger_cutoff_id: int | None
    ledger_fingerprint: str | None
    selections: tuple[ExternalPromotedAnalysisMemorySelection, ...]
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.errors and bool(self.selections)


@dataclass(frozen=True)
class StoredExternalPromotedAnalysisMemoryRetrieval:
    retrieval_id: str
    request: HumanExternalPromotedAnalysisMemoryRetrievalRequest
    stored_idempotency_key: str
    request_fingerprint: str
    stored_current_context_snapshot_id: str
    retrieval_target_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryRetrievalAuditReplay:
    retrieval_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryRetrievalReplay:
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
                "karkinos.ai.external_promoted_analysis_memory_retrieval_replay.v1"
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
            "phase_1_8_retrieval_modified": False,
            "phase_1_13_retrieval_modified": False,
            "memory_is_account_fact": False,
            "automatic_recall_enabled": False,
            "provider_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


class ExternalPromotedAnalysisMemoryRetrievalRepository(Protocol):
    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedAnalysisMemoryRetrieval | None: ...

    def record(
        self,
        *,
        request: HumanExternalPromotedAnalysisMemoryRetrievalRequest,
        target: ExternalPromotedAnalysisMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRetrieval, bool]: ...

    def get(
        self,
        retrieval_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryRetrieval: ...

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRetrieval, ...]: ...

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ExternalPromotedAnalysisMemoryRetrievalAuditReplay: ...


class ExternalPromotedAnalysisMemoryContextReader(Protocol):
    def get_context(self, snapshot_id: str) -> EvidenceBoundContextSnapshot: ...


class ExternalPromotedAnalysisMemoryEvidenceReader(Protocol):
    def get(self, reference_id: str) -> CanonicalEvidenceRecord | None: ...
