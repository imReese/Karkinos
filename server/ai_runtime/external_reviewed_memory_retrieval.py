"""Versioned retrieval of promoted external reviewed-research memory.

This compatibility façade preserves the public Phase 1.13 contract while
contracts, projections, persistence, and business orchestration have explicit
owners. Retrieval remains human-started, evidence-bound, non-authoritative,
and unable to change financial, decision, or execution authority.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from server.contracts.external_reviewed_memory_retrieval import (
    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION,
    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    CurrentContextValidator,
    ExternalReviewedMemoryRetrievalAuditReplay,
    ExternalReviewedMemoryRetrievalRejected,
    ExternalReviewedMemoryRetrievalReplay,
    ExternalReviewedMemoryRetrievalTarget,
    ExternalReviewedMemorySelection,
    HumanExternalReviewedMemoryRetrievalRequest,
    StoredExternalReviewedMemoryRetrieval,
)
from server.persistence.external_reviewed_memory_retrieval_projection import (
    external_reviewed_memory_retrieval_from_row,
)
from server.persistence.external_reviewed_memory_retrieval_repository import (
    ExternalReviewedMemoryRetrievalRepositoryMixin,
)
from server.persistence.external_reviewed_memory_retrieval_schema import (
    ExternalReviewedMemoryRetrievalSchemaMixin,
)
from server.persistence.external_reviewed_memory_retrieval_uow import (
    ExternalReviewedMemoryRetrievalUnitOfWorkMixin,
)

from .contracts import JsonObject
from .evidence import CanonicalEvidenceRepository
from .external_reviewed_memory import ExternalReviewedMemoryPromotionService
from .external_reviewed_memory_retrieval_result import (
    ExternalReviewedMemoryRetrievalResult,
)
from .external_reviewed_memory_retrieval_service import (
    HumanExternalReviewedMemoryRetrievalServiceBase,
)
from .external_reviewed_memory_retrieval_values import (
    external_reviewed_memory_retrieval_event_hash,
)
from .store import AiAuditStore, IdempotencyConflict

_MAX_PROMOTION_IDS = 20


class ExternalReviewedMemoryRetrievalStore(
    ExternalReviewedMemoryRetrievalUnitOfWorkMixin,
    ExternalReviewedMemoryRetrievalRepositoryMixin,
    ExternalReviewedMemoryRetrievalSchemaMixin,
):
    """Append-only exact promotion retrieval requests and audit events."""

    @staticmethod
    def _retrieval_from_row(row: Any) -> StoredExternalReviewedMemoryRetrieval:
        return _retrieval_from_row(row)

    @staticmethod
    def _event_hash(**kwargs: object) -> str:
        return _event_hash(**kwargs)  # type: ignore[arg-type]

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        self._init_schema()

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalReviewedMemoryRetrieval | None:
        return self._get_by_idempotency_key(idempotency_key)

    def record(
        self,
        *,
        request: HumanExternalReviewedMemoryRetrievalRequest,
        target: ExternalReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryRetrieval, bool]:
        return self._record(request=request, target=target, created_at=created_at)

    def get(self, retrieval_id: str) -> StoredExternalReviewedMemoryRetrieval:
        return self._get(retrieval_id)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredExternalReviewedMemoryRetrieval, ...]:
        return self._list(limit=limit)

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ExternalReviewedMemoryRetrievalAuditReplay:
        return self._verify_replay(retrieval_id)


class HumanExternalReviewedMemoryRetrievalService(
    HumanExternalReviewedMemoryRetrievalServiceBase
):
    """Retrieve exact promoted memory and rebind it to current evidence."""

    def __init__(
        self,
        *,
        promotion_service: ExternalReviewedMemoryPromotionService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        current_context_validator: CurrentContextValidator,
        retrieval_store: ExternalReviewedMemoryRetrievalStore,
        now: Callable[[], str],
    ) -> None:
        super().__init__(
            promotion_service=promotion_service,
            ai_store=ai_store,
            evidence_repository=evidence_repository,
            current_context_validator=current_context_validator,
            retrieval_store=retrieval_store,
            now=now,
        )


def _event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return external_reviewed_memory_retrieval_event_hash(
        retrieval_id=retrieval_id,
        sequence=sequence,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )


def _retrieval_from_row(row: Any) -> StoredExternalReviewedMemoryRetrieval:
    return external_reviewed_memory_retrieval_from_row(row)


for _public_type in (
    ExternalReviewedMemoryRetrievalRejected,
    HumanExternalReviewedMemoryRetrievalRequest,
    ExternalReviewedMemorySelection,
    ExternalReviewedMemoryRetrievalTarget,
    StoredExternalReviewedMemoryRetrieval,
    ExternalReviewedMemoryRetrievalAuditReplay,
    ExternalReviewedMemoryRetrievalReplay,
    ExternalReviewedMemoryRetrievalResult,
):
    _public_type.__module__ = __name__
del _public_type
