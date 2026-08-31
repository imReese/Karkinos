"""Human review workflow for promoted-memory external analyses."""

from __future__ import annotations

from collections.abc import Callable

from server.contracts.external_promoted_memory_analysis_review import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION,
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewReplay,
    ExternalPromotedMemoryAnalysisReviewRepository,
    ExternalPromotedMemoryAnalysisReviewTarget,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
    StoredExternalPromotedMemoryAnalysisReview,
)
from server.contracts.idempotency import IdempotencyConflict

from .contracts import JsonObject, content_fingerprint
from .external_analysis_reviews import (
    ExternalAnalysisReviewDecision,
    review_target,
)
from .external_promoted_memory_analysis import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION,
    ExternalPromotedMemoryAnalysisResult,
    HumanExternalPromotedMemoryAnalysisService,
)
from .external_promoted_memory_analysis_review_result import (
    ExternalPromotedMemoryAnalysisReviewResult,
)


class HumanExternalPromotedMemoryAnalysisReviewService:
    """Record and revalidate one human disposition without model I/O."""

    def __init__(
        self,
        *,
        analysis_service: HumanExternalPromotedMemoryAnalysisService,
        review_store: ExternalPromotedMemoryAnalysisReviewRepository,
        now: Callable[[], str],
    ) -> None:
        self._analysis_service = analysis_service
        self._review_store = review_store
        self._now = now

    def review(
        self,
        analysis_id: str,
        request: HumanExternalPromotedMemoryAnalysisReviewRequest,
    ) -> ExternalPromotedMemoryAnalysisReviewResult:
        existing = self._review_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.analysis_id != analysis_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "external promoted-memory analysis review idempotency key "
                    "was reused with different input"
                )
            return self._result(existing, reused=True)

        target = promoted_review_target(self._analysis_service.get(analysis_id))
        if request.decision == (
            ExternalAnalysisReviewDecision.ACCEPT_AS_REVIEWED_RESEARCH
        ):
            blockers = list(target.acceptance_errors)
            if request.factual_error_count:
                blockers.append("reviewer_identified_factual_errors")
            if request.unsupported_claim_count:
                blockers.append("reviewer_identified_unsupported_claims")
            if blockers:
                raise ExternalPromotedMemoryAnalysisReviewRejected(
                    "external promoted-memory analysis cannot become reviewed "
                    "research: " + "; ".join(dict.fromkeys(blockers))
                )
        stored, reused = self._review_store.record(
            target=target,
            request=request,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def get(self, review_id: str) -> ExternalPromotedMemoryAnalysisReviewResult:
        return self._result(self._review_store.get(review_id), reused=True)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalPromotedMemoryAnalysisReviewResult, ...]:
        return tuple(
            self._result(stored, reused=True)
            for stored in self._review_store.list(
                analysis_id=analysis_id,
                limit=limit,
            )
        )

    def replay(self, review_id: str) -> ExternalPromotedMemoryAnalysisReviewReplay:
        return self.get(review_id).replay()

    def _result(
        self,
        stored: StoredExternalPromotedMemoryAnalysisReview,
        *,
        reused: bool,
    ) -> ExternalPromotedMemoryAnalysisReviewResult:
        target = promoted_review_target(self._analysis_service.get(stored.analysis_id))
        return ExternalPromotedMemoryAnalysisReviewResult(
            review=stored,
            current_target=target,
            audit_replay=self._review_store.verify_replay(stored.review_id),
            reused=reused,
        )


def promoted_review_target(
    promoted: ExternalPromotedMemoryAnalysisResult,
) -> ExternalPromotedMemoryAnalysisReviewTarget:
    analysis = promoted.analysis
    base = review_target(analysis)
    errors = list(base.acceptance_errors)
    if analysis.record.request.schema_version != (
        EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION
    ):
        errors.append("analysis_request_is_not_promoted_memory_v1")

    source = promoted.source_retrieval
    retrieval_id = analysis.record.request.retrieval_id
    promotion_ids = promoted.promotion_ids
    selected_memory_sources: tuple[JsonObject, ...] = ()
    source_target_fingerprint: str | None = None
    source_evidence: JsonObject = {
        "retrieval_id": retrieval_id,
        "source_present": False,
    }
    if source is None:
        errors.append("source_promoted_memory_retrieval_missing")
    else:
        source_target_fingerprint = source.current_target.fingerprint
        selections = source.current_target.selections
        selected_memory_sources = tuple(
            {
                "promotion_id": item.promotion_id,
                "review_id": item.review_id,
                "source_analysis_id": item.analysis_id,
                "source_context_snapshot_id": item.source_context_snapshot_id,
                "memory_artifact_id": item.memory_artifact_id,
                "memory_artifact_fingerprint": item.memory_artifact_fingerprint,
                "selection_fingerprint": item.fingerprint,
            }
            for item in selections
        )
        source_evidence = {
            "retrieval_id": source.stored.retrieval_id,
            "source_present": True,
            "request_fingerprint": source.stored.request_fingerprint,
            "stored_target_fingerprint": source.stored.retrieval_target_fingerprint,
            "current_target_fingerprint": source.current_target.fingerprint,
            "request_binding_valid": source.request_binding_valid,
            "target_binding_valid": source.target_binding_valid,
            "retrieval_eligible": source.retrieval_eligible,
            "promotion_ids": list(source.stored.request.promotion_ids),
            "selected_memory_source_fingerprints": [
                item.fingerprint for item in selections
            ],
            "audit": {
                "valid": source.audit_replay.valid,
                "event_count": source.audit_replay.event_count,
                "last_event_hash": source.audit_replay.last_event_hash,
                "errors": list(source.audit_replay.errors),
            },
            "invalidation_reasons": list(source.invalidation_reasons),
        }
        if source.stored.retrieval_id != retrieval_id:
            errors.append("source_promoted_memory_retrieval_id_drift")
        if not source.retrieval_eligible:
            errors.append("source_promoted_memory_retrieval_not_eligible")
        if not source.replay().valid:
            errors.append("source_promoted_memory_retrieval_replay_invalid")
        if analysis.record.retrieval_target_fingerprint != (
            source.current_target.fingerprint
        ):
            errors.append("analysis_source_retrieval_target_fingerprint_drift")

    if not promotion_ids:
        errors.append("source_promotion_ids_missing")
    if len(promotion_ids) != len(set(promotion_ids)):
        errors.append("source_promotion_ids_are_not_unique")
    selected_promotion_ids = tuple(
        str(item["promotion_id"]) for item in selected_memory_sources
    )
    if selected_promotion_ids != promotion_ids:
        errors.append("source_promotion_selection_binding_drift")

    target_payload = {
        "contract": EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION,
        "analysis_id": base.analysis_id,
        "workflow_id": base.workflow_id,
        "retrieval_id": retrieval_id,
        "context_snapshot_id": base.context_snapshot_id,
        "context_fingerprint": base.context_fingerprint,
        "provider_id": base.provider_id,
        "model_id": base.model_id,
        "prompt_version": base.prompt_version,
        "report_artifact_id": base.report_artifact_id,
        "promotion_ids": list(promotion_ids),
        "selected_memory_sources": list(selected_memory_sources),
        "base_analysis_target_fingerprint": base.fingerprint,
        "source_retrieval": source_evidence,
        "quality_evidence": base.quality_evidence,
    }
    return ExternalPromotedMemoryAnalysisReviewTarget(
        analysis_id=base.analysis_id,
        workflow_id=base.workflow_id,
        retrieval_id=retrieval_id,
        context_snapshot_id=base.context_snapshot_id,
        context_fingerprint=base.context_fingerprint,
        provider_id=base.provider_id,
        model_id=base.model_id,
        prompt_version=base.prompt_version,
        report_artifact_id=base.report_artifact_id,
        promotion_ids=promotion_ids,
        selected_memory_sources=selected_memory_sources,
        base_analysis_target_fingerprint=base.fingerprint,
        source_retrieval_target_fingerprint=source_target_fingerprint,
        quality_evidence=dict(base.quality_evidence),
        fingerprint=content_fingerprint(target_payload),
        acceptance_errors=tuple(dict.fromkeys(errors)),
    )
