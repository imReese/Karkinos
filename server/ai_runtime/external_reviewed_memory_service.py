"""Business service for revocable external reviewed-research memory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from server.contracts.external_reviewed_memory import (
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryReplay,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryTarget,
    StoredExternalReviewedMemoryPromotion,
)

from .contracts import ArtifactKind, JsonObject, StoredArtifact, content_fingerprint
from .external_analysis_reviews import HumanExternalAnalysisReviewService
from .external_reviewed_memory_result import ExternalReviewedMemoryPromotionResult
from .store import AiAuditStore, IdempotencyConflict


class ExternalReviewedMemoryPromotionServiceBase:
    """Promote and revoke exact reviewed reports without model or authority I/O."""

    _memory_content: Any
    _memory_artifact_payload: Any
    _optional_non_empty_string: Any

    def __init__(
        self,
        *,
        review_service: HumanExternalAnalysisReviewService,
        ai_store: AiAuditStore,
        promotion_store: Any,
        now: Callable[[], str],
    ) -> None:
        self._review_service = review_service
        self._ai_store = ai_store
        self._promotion_store = promotion_store
        self._now = now

    def promote(
        self,
        review_id: str,
        request: ExternalReviewedMemoryPromotionRequest,
    ) -> ExternalReviewedMemoryPromotionResult:
        existing = self._promotion_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.review_id != review_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "external reviewed-memory promotion idempotency key was reused "
                    "with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(review_id)
        if not target.eligible:
            raise ExternalReviewedMemoryPromotionRejected(
                "external reviewed research cannot become historical memory: "
                + "; ".join(target.errors)
            )
        stored, reused = self._promotion_store.record_promotion(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def revoke(
        self,
        promotion_id: str,
        request: ExternalReviewedMemoryRevocationRequest,
    ) -> ExternalReviewedMemoryPromotionResult:
        promotion = self._promotion_store.get(promotion_id)
        _, reused = self._promotion_store.record_revocation(
            promotion=promotion,
            request=request,
            created_at=self._now(),
        )
        return self._result(promotion, reused=reused)

    def get(self, promotion_id: str) -> ExternalReviewedMemoryPromotionResult:
        return self._result(self._promotion_store.get(promotion_id), reused=True)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalReviewedMemoryPromotionResult, ...]:
        return tuple(
            self._result(promotion, reused=True)
            for promotion in self._promotion_store.list(
                review_id=review_id,
                limit=limit,
            )
        )

    def replay(self, promotion_id: str) -> ExternalReviewedMemoryReplay:
        return self.get(promotion_id).replay()

    def _result(
        self,
        promotion: StoredExternalReviewedMemoryPromotion,
        *,
        reused: bool,
    ) -> ExternalReviewedMemoryPromotionResult:
        return ExternalReviewedMemoryPromotionResult(
            promotion=promotion,
            current_target=self._target(promotion.review_id),
            revocation=self._promotion_store.get_revocation(promotion.promotion_id),
            audit_replay=self._promotion_store.verify_replay(promotion.promotion_id),
            reused=reused,
        )

    def _target(self, review_id: str) -> ExternalReviewedMemoryTarget:
        errors: list[str] = []
        review = self._review_service.get(review_id)
        if not review.reviewed_research_eligible:
            errors.extend(review.invalidation_reasons)
            if not review.invalidation_reasons:
                errors.append(f"review_not_eligible:{review.effective_status.value}")
        replay = review.replay()
        if not replay.valid:
            errors.append("external_analysis_review_replay_invalid")

        report: StoredArtifact | None = None
        report_id = review.review.report_artifact_id
        if report_id is None:
            errors.append("review_has_no_report_artifact")
        else:
            matches = [
                artifact
                for artifact in self._ai_store.list_artifacts(review.review.workflow_id)
                if artifact.artifact_id == report_id
                and artifact.kind == ArtifactKind.REPORT
            ]
            if len(matches) != 1:
                errors.append("review_must_bind_exactly_one_report_artifact")
            else:
                report = matches[0]

        memory_content: JsonObject | None = None
        memory_artifact_fingerprint: str | None = None
        evidence_reference_ids: tuple[str, ...] = ()
        source_retrieval_id: str | None = None
        source_retrieval_target_fingerprint: str | None = None
        if report is not None:
            report_content = dict(report.content)
            source_retrieval_id = self._optional_non_empty_string(
                report_content.get("retrieval_id")
            )
            source_retrieval_target_fingerprint = self._optional_non_empty_string(
                report_content.get("retrieval_target_fingerprint")
            )
            if source_retrieval_id is None:
                errors.append("report_retrieval_binding_missing")
            if source_retrieval_target_fingerprint is None:
                errors.append("report_retrieval_target_binding_missing")
            if report_content.get("authoritative") is not False:
                errors.append("report_authority_flag_invalid")
            if report_content.get("requires_human_review") is not True:
                errors.append("report_human_review_flag_invalid")
            if report_content.get("authority_effect") != "none":
                errors.append("report_authority_effect_invalid")
            if report_content.get("memory_created") is not False:
                errors.append("source_report_memory_flag_invalid")
            evidence_reference_ids = tuple(report.evidence_reference_ids)
            if not evidence_reference_ids:
                errors.append("source_report_has_no_evidence_references")
            memory_content = self._memory_content(
                review_id=review.review.review_id,
                analysis_id=review.review.analysis_id,
                report=report,
                source_context_snapshot_id=(review.current_target.context_snapshot_id),
                source_context_fingerprint=review.current_target.context_fingerprint,
                source_retrieval_id=source_retrieval_id,
                source_retrieval_target_fingerprint=(
                    source_retrieval_target_fingerprint
                ),
                provider_id=review.review.provider_id,
                model_id=review.review.model_id,
                prompt_version=review.review.prompt_version,
                review_note=review.review.request.note,
                reviewed_by=review.review.request.reviewed_by,
                human_rubric=review.review.request.quality_rubric.to_dict(),
            )
            memory_artifact_fingerprint = content_fingerprint(
                self._memory_artifact_payload(
                    review_id=review.review.review_id,
                    analysis_id=review.review.analysis_id,
                    report_artifact_id=report.artifact_id,
                    content=memory_content,
                    evidence_reference_ids=evidence_reference_ids,
                )
            )

        target_payload: JsonObject = {
            "review_id": review.review.review_id,
            "review_target_fingerprint": review.current_target.fingerprint,
            "review_audit_last_event_hash": review.audit_replay.last_event_hash,
            "review_replay_valid": replay.valid,
            "analysis_id": review.review.analysis_id,
            "workflow_id": review.review.workflow_id,
            "source_context_snapshot_id": (review.current_target.context_snapshot_id),
            "source_context_fingerprint": review.current_target.context_fingerprint,
            "source_retrieval_id": source_retrieval_id,
            "source_retrieval_target_fingerprint": (
                source_retrieval_target_fingerprint
            ),
            "report_artifact_id": report.artifact_id if report is not None else None,
            "report_artifact_fingerprint": (
                report.fingerprint if report is not None else None
            ),
            "evidence_reference_ids": list(evidence_reference_ids),
            "provider_id": review.review.provider_id,
            "model_id": review.review.model_id,
            "prompt_version": review.review.prompt_version,
            "memory_artifact_fingerprint": memory_artifact_fingerprint,
            "errors": list(dict.fromkeys(errors)),
        }
        return ExternalReviewedMemoryTarget(
            review_id=review.review.review_id,
            analysis_id=review.review.analysis_id,
            workflow_id=review.review.workflow_id,
            source_context_snapshot_id=review.current_target.context_snapshot_id,
            source_context_fingerprint=review.current_target.context_fingerprint,
            source_retrieval_id=source_retrieval_id,
            source_retrieval_target_fingerprint=(source_retrieval_target_fingerprint),
            report_artifact_id=report.artifact_id if report is not None else None,
            report_artifact_fingerprint=(
                report.fingerprint if report is not None else None
            ),
            evidence_reference_ids=evidence_reference_ids,
            provider_id=review.review.provider_id,
            model_id=review.review.model_id,
            prompt_version=review.review.prompt_version,
            memory_content=memory_content,
            memory_artifact_fingerprint=memory_artifact_fingerprint,
            fingerprint=content_fingerprint(target_payload),
            errors=tuple(dict.fromkeys(errors)),
        )
