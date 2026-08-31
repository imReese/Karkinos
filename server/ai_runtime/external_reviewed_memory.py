"""Explicit promotion of reviewed external research into revocable memory.

This compatibility façade preserves the public Phase 1.12 contract while
persistence, replay projection, deterministic values, and business orchestration
have explicit owners. Promotion and revocation remain human-confirmed,
non-authoritative, and unable to change financial or execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from server.contracts.external_reviewed_memory import (
    EXTERNAL_REVIEWED_MEMORY_CONTRACT_VERSION,
    EXTERNAL_REVIEWED_MEMORY_PROMOTION_CONFIRMATION,
    EXTERNAL_REVIEWED_MEMORY_REVOCATION_CONFIRMATION,
    ExternalReviewedMemoryAuditReplay,
    ExternalReviewedMemoryEffectiveStatus,
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryReplay,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryTarget,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
)
from server.persistence.external_reviewed_memory_projection import (
    external_reviewed_memory_promotion_from_row,
    external_reviewed_memory_revocation_from_row,
)
from server.persistence.external_reviewed_memory_repository import (
    ExternalReviewedMemoryRepositoryMixin,
)
from server.persistence.external_reviewed_memory_schema import (
    ExternalReviewedMemorySchemaMixin,
)
from server.persistence.external_reviewed_memory_uow import (
    ExternalReviewedMemoryUnitOfWorkMixin,
)

from .contracts import ArtifactKind, JsonObject, StoredArtifact
from .external_analysis_reviews import HumanExternalAnalysisReviewService
from .external_reviewed_memory_result import ExternalReviewedMemoryPromotionResult
from .external_reviewed_memory_service import (
    ExternalReviewedMemoryPromotionServiceBase,
)
from .external_reviewed_memory_values import (
    external_reviewed_memory_artifact_payload,
    external_reviewed_memory_content,
    external_reviewed_memory_event_hash,
    external_reviewed_memory_optional_non_empty_string,
)
from .store import AiAuditStore, IdempotencyConflict


class ExternalReviewedMemoryStore(
    ExternalReviewedMemoryUnitOfWorkMixin,
    ExternalReviewedMemoryRepositoryMixin,
    ExternalReviewedMemorySchemaMixin,
):
    """Immutable promotions plus one optional append-only revocation."""

    @staticmethod
    def _promotion_from_row(row: Any) -> StoredExternalReviewedMemoryPromotion:
        return _promotion_from_row(row)

    @staticmethod
    def _revocation_from_row(row: Any) -> StoredExternalReviewedMemoryRevocation:
        return _revocation_from_row(row)

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
    ) -> StoredExternalReviewedMemoryPromotion | None:
        return self._get_by_idempotency_key(idempotency_key)

    def get_by_review_id(
        self,
        review_id: str,
    ) -> StoredExternalReviewedMemoryPromotion | None:
        return self._get_by_review_id(review_id)

    def record_promotion(
        self,
        *,
        request: ExternalReviewedMemoryPromotionRequest,
        target: ExternalReviewedMemoryTarget,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryPromotion, bool]:
        return self._record_promotion(
            request=request,
            target=target,
            created_at=created_at,
        )

    def record_revocation(
        self,
        *,
        promotion: StoredExternalReviewedMemoryPromotion,
        request: ExternalReviewedMemoryRevocationRequest,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryRevocation, bool]:
        return self._record_revocation(
            promotion=promotion,
            request=request,
            created_at=created_at,
        )

    def get(self, promotion_id: str) -> StoredExternalReviewedMemoryPromotion:
        return self._get(promotion_id)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalReviewedMemoryPromotion, ...]:
        return self._list(review_id=review_id, limit=limit)

    def get_revocation(
        self,
        promotion_id: str,
    ) -> StoredExternalReviewedMemoryRevocation | None:
        return self._get_revocation(promotion_id)

    def verify_replay(
        self,
        promotion_id: str,
    ) -> ExternalReviewedMemoryAuditReplay:
        return self._verify_replay(promotion_id)


class ExternalReviewedMemoryPromotionService(
    ExternalReviewedMemoryPromotionServiceBase
):
    """Promote and revoke exact reviewed reports without model or authority I/O."""

    @staticmethod
    def _memory_content(**kwargs: object) -> JsonObject:
        return _memory_content(**kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _memory_artifact_payload(**kwargs: object) -> JsonObject:
        return _memory_artifact_payload(**kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _optional_non_empty_string(value: object) -> str | None:
        return _optional_non_empty_string(value)

    def __init__(
        self,
        *,
        review_service: HumanExternalAnalysisReviewService,
        ai_store: AiAuditStore,
        promotion_store: ExternalReviewedMemoryStore,
        now: Callable[[], str],
    ) -> None:
        super().__init__(
            review_service=review_service,
            ai_store=ai_store,
            promotion_store=promotion_store,
            now=now,
        )


def _memory_content(
    *,
    review_id: str,
    analysis_id: str,
    report: StoredArtifact,
    source_context_snapshot_id: str,
    source_context_fingerprint: str,
    source_retrieval_id: str | None,
    source_retrieval_target_fingerprint: str | None,
    provider_id: str,
    model_id: str,
    prompt_version: str,
    review_note: str,
    reviewed_by: str,
    human_rubric: dict[str, int],
) -> JsonObject:
    return external_reviewed_memory_content(
        review_id=review_id,
        analysis_id=analysis_id,
        report=report,
        source_context_snapshot_id=source_context_snapshot_id,
        source_context_fingerprint=source_context_fingerprint,
        source_retrieval_id=source_retrieval_id,
        source_retrieval_target_fingerprint=source_retrieval_target_fingerprint,
        provider_id=provider_id,
        model_id=model_id,
        prompt_version=prompt_version,
        review_note=review_note,
        reviewed_by=reviewed_by,
        human_rubric=human_rubric,
    )


def _memory_artifact_payload(
    *,
    review_id: str,
    analysis_id: str,
    report_artifact_id: str,
    content: JsonObject,
    evidence_reference_ids: Sequence[str],
) -> JsonObject:
    return external_reviewed_memory_artifact_payload(
        review_id=review_id,
        analysis_id=analysis_id,
        report_artifact_id=report_artifact_id,
        content=content,
        evidence_reference_ids=evidence_reference_ids,
    )


def _optional_non_empty_string(value: object) -> str | None:
    return external_reviewed_memory_optional_non_empty_string(value)


def _event_hash(
    *,
    promotion_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return external_reviewed_memory_event_hash(
        promotion_id=promotion_id,
        sequence=sequence,
        event_type=event_type,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )


def _promotion_from_row(row: Any) -> StoredExternalReviewedMemoryPromotion:
    return external_reviewed_memory_promotion_from_row(row)


def _revocation_from_row(row: Any) -> StoredExternalReviewedMemoryRevocation:
    return external_reviewed_memory_revocation_from_row(row)


ExternalReviewedMemoryPromotionResult._memory_artifact_payload = staticmethod(
    lambda **kwargs: _memory_artifact_payload(**kwargs)
)


for _public_type in (
    ExternalReviewedMemoryEffectiveStatus,
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryTarget,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
    ExternalReviewedMemoryAuditReplay,
    ExternalReviewedMemoryReplay,
    ExternalReviewedMemoryPromotionResult,
):
    _public_type.__module__ = __name__
del _public_type
