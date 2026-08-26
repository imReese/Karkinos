"""Explicit retrieval of human-reviewed research memory.

This compatibility façade preserves the original reviewed-memory retrieval
contract while stable contracts, deterministic projections, persistence, and
business orchestration have explicit owners. Retrieval remains human-started,
evidence-bound, non-authoritative, and unable to change financial, decision,
or execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from server.contracts.memory_retrieval import (
    MAX_REVIEWED_MEMORY_REVIEW_IDS,
    REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    EvidenceRebinding,
    HumanReviewedMemoryRetrievalRequest,
    ReviewedMemoryRetrievalAuditReplay,
    ReviewedMemoryRetrievalRejected,
    ReviewedMemoryRetrievalReplay,
    ReviewedMemoryRetrievalTarget,
    ReviewedMemorySelection,
    StoredReviewedMemoryRetrieval,
)
from server.persistence.memory_retrieval_projection import (
    reviewed_memory_retrieval_from_row,
)
from server.persistence.memory_retrieval_repository import (
    ReviewedMemoryRetrievalRepositoryMixin,
)
from server.persistence.memory_retrieval_schema import (
    REVIEWED_MEMORY_RETRIEVAL_SCHEMA,
    ReviewedMemoryRetrievalSchemaMixin,
)
from server.persistence.memory_retrieval_uow import (
    ReviewedMemoryRetrievalUnitOfWorkMixin,
)

from .analysis_reviews import HumanAnalysisReviewService
from .contracts import JsonObject, StoredArtifact
from .evidence import CanonicalEvidenceRepository
from .memory_retrieval_result import ReviewedMemoryRetrievalResult
from .memory_retrieval_service import HumanReviewedMemoryRetrievalServiceBase
from .memory_retrieval_values import (
    exact_memory_artifact,
    reviewed_memory_retrieval_event_hash,
)
from .store import AiAuditStore, IdempotencyConflict
from .task_analysis import HumanResearchTaskFixtureAnalysisService

_MAX_REVIEW_IDS = MAX_REVIEWED_MEMORY_REVIEW_IDS
_RETRIEVAL_SCHEMA = REVIEWED_MEMORY_RETRIEVAL_SCHEMA


class ReviewedMemoryRetrievalStore(
    ReviewedMemoryRetrievalUnitOfWorkMixin,
    ReviewedMemoryRetrievalRepositoryMixin,
    ReviewedMemoryRetrievalSchemaMixin,
):
    """Append-only retrieval requests and their single-event audit chains."""

    @staticmethod
    def _retrieval_from_row(row: Any) -> StoredReviewedMemoryRetrieval:
        return _retrieval_from_row(row)

    @staticmethod
    def _retrieval_event_hash(**kwargs: object) -> str:
        return _retrieval_event_hash(**kwargs)  # type: ignore[arg-type]

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        self._init_schema()

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredReviewedMemoryRetrieval | None:
        return self._get_by_idempotency_key(idempotency_key)

    def record(
        self,
        *,
        request: HumanReviewedMemoryRetrievalRequest,
        target: ReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredReviewedMemoryRetrieval, bool]:
        return self._record(request=request, target=target, created_at=created_at)

    def get(self, retrieval_id: str) -> StoredReviewedMemoryRetrieval:
        return self._get(retrieval_id)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredReviewedMemoryRetrieval, ...]:
        return self._list(limit=limit)

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ReviewedMemoryRetrievalAuditReplay:
        return self._verify_replay(retrieval_id)


class HumanReviewedMemoryRetrievalService(HumanReviewedMemoryRetrievalServiceBase):
    """Select exact reviewed memory and rebind it to current evidence."""

    @staticmethod
    def _exact_memory_artifact(
        *,
        artifacts: Sequence[StoredArtifact],
        memory_artifact_id: str | None,
    ) -> StoredArtifact:
        return _exact_memory_artifact(
            artifacts=artifacts,
            memory_artifact_id=memory_artifact_id,
        )

    def __init__(
        self,
        *,
        review_service: HumanAnalysisReviewService,
        analysis_service: HumanResearchTaskFixtureAnalysisService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        retrieval_store: ReviewedMemoryRetrievalStore,
        now: Callable[[], str],
    ) -> None:
        super().__init__(
            review_service=review_service,
            analysis_service=analysis_service,
            ai_store=ai_store,
            evidence_repository=evidence_repository,
            retrieval_store=retrieval_store,
            now=now,
        )


def _exact_memory_artifact(
    *,
    artifacts: Sequence[StoredArtifact],
    memory_artifact_id: str | None,
) -> StoredArtifact:
    return exact_memory_artifact(
        artifacts=artifacts,
        memory_artifact_id=memory_artifact_id,
    )


def _retrieval_event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return reviewed_memory_retrieval_event_hash(
        retrieval_id=retrieval_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )


def _retrieval_from_row(row: Any) -> StoredReviewedMemoryRetrieval:
    return reviewed_memory_retrieval_from_row(row)


for _public_type in (
    ReviewedMemoryRetrievalRejected,
    HumanReviewedMemoryRetrievalRequest,
    EvidenceRebinding,
    ReviewedMemorySelection,
    ReviewedMemoryRetrievalTarget,
    StoredReviewedMemoryRetrieval,
    ReviewedMemoryRetrievalAuditReplay,
    ReviewedMemoryRetrievalReplay,
    ReviewedMemoryRetrievalResult,
):
    _public_type.__module__ = __name__
del _public_type
