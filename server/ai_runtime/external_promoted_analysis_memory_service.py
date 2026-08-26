"""Human-controlled promotion and revocation workflow for analysis memory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from server.contracts.external_promoted_analysis_memory import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
    ExternalPromotedAnalysisMemoryArtifactReader,
    ExternalPromotedAnalysisMemoryPromotionRequest,
    ExternalPromotedAnalysisMemoryRejected,
    ExternalPromotedAnalysisMemoryReplay,
    ExternalPromotedAnalysisMemoryRepository,
    ExternalPromotedAnalysisMemoryRevocationRequest,
    ExternalPromotedAnalysisMemoryTarget,
    StoredExternalPromotedAnalysisMemoryPromotion,
)
from server.contracts.idempotency import IdempotencyConflict

from .contracts import ArtifactKind, JsonObject, StoredArtifact, content_fingerprint
from .external_promoted_analysis_memory_result import (
    ExternalPromotedAnalysisMemoryPromotionResult,
    memory_artifact_payload,
)
from .external_promoted_memory_analysis_reviews import (
    HumanExternalPromotedMemoryAnalysisReviewService,
)


class ExternalPromotedAnalysisMemoryPromotionService:
    """Promote and revoke an exact reviewed result without model I/O."""

    def __init__(
        self,
        *,
        review_service: HumanExternalPromotedMemoryAnalysisReviewService,
        ai_store: ExternalPromotedAnalysisMemoryArtifactReader,
        promotion_store: ExternalPromotedAnalysisMemoryRepository,
        now: Callable[[], str],
    ) -> None:
        self._review_service = review_service
        self._ai_store = ai_store
        self._promotion_store = promotion_store
        self._now = now

    def promote(
        self,
        review_id: str,
        request: ExternalPromotedAnalysisMemoryPromotionRequest,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        existing = self._promotion_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if (
                existing.review_id != review_id
                or existing.request_fingerprint != request.fingerprint
            ):
                raise IdempotencyConflict(
                    "promoted-analysis memory promotion idempotency key was "
                    "reused with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(review_id)
        if not target.eligible:
            raise ExternalPromotedAnalysisMemoryRejected(
                "reviewed promoted-memory analysis cannot become historical "
                "memory: " + "; ".join(target.errors)
            )
        promotion, reused = self._promotion_store.record_promotion(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(promotion, reused=reused)

    def revoke(
        self,
        promotion_id: str,
        request: ExternalPromotedAnalysisMemoryRevocationRequest,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        promotion = self._promotion_store.get(promotion_id)
        _, reused = self._promotion_store.record_revocation(
            promotion=promotion,
            request=request,
            created_at=self._now(),
        )
        return self._result(promotion, reused=reused)

    def get(
        self,
        promotion_id: str,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        return self._result(self._promotion_store.get(promotion_id), reused=True)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ExternalPromotedAnalysisMemoryPromotionResult, ...]:
        return tuple(
            self._result(promotion, reused=True)
            for promotion in self._promotion_store.list(
                review_id=review_id,
                limit=limit,
            )
        )

    def replay(self, promotion_id: str) -> ExternalPromotedAnalysisMemoryReplay:
        return self.get(promotion_id).replay()

    def _result(
        self,
        promotion: StoredExternalPromotedAnalysisMemoryPromotion,
        *,
        reused: bool,
    ) -> ExternalPromotedAnalysisMemoryPromotionResult:
        return ExternalPromotedAnalysisMemoryPromotionResult(
            promotion=promotion,
            current_target=self._target(promotion.review_id),
            revocation=self._promotion_store.get_revocation(promotion.promotion_id),
            audit_replay=self._promotion_store.verify_replay(promotion.promotion_id),
            reused=reused,
        )

    def _target(self, review_id: str) -> ExternalPromotedAnalysisMemoryTarget:
        errors: list[str] = []
        review = self._review_service.get(review_id)
        if not review.reviewed_research_eligible:
            errors.extend(review.invalidation_reasons)
            if not review.invalidation_reasons:
                errors.append(f"review_not_eligible:{review.effective_status.value}")
        review_replay = review.replay()
        if not review_replay.valid:
            errors.append("promoted_memory_analysis_review_replay_invalid")

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

        memory_content_value: JsonObject | None = None
        memory_artifact_fingerprint: str | None = None
        evidence_reference_ids: tuple[str, ...] = ()
        if report is not None:
            report_content = dict(report.content)
            if report_content.get("authoritative") is not False:
                errors.append("report_authority_flag_invalid")
            if report_content.get("requires_human_review") is not True:
                errors.append("report_human_review_flag_invalid")
            if report_content.get("authority_effect") != "none":
                errors.append("report_authority_effect_invalid")
            if report_content.get("memory_created") is not False:
                errors.append("source_report_memory_flag_invalid")
            if report_content.get("retrieval_id") != review.review.retrieval_id:
                errors.append("report_retrieval_id_binding_drift")
            if report_content.get("retrieval_target_fingerprint") != (
                review.current_target.source_retrieval_target_fingerprint
            ):
                errors.append("report_retrieval_target_binding_drift")
            evidence_reference_ids = tuple(report.evidence_reference_ids)
            if not evidence_reference_ids:
                errors.append("source_report_has_no_evidence_references")
            memory_content_value = memory_content(
                review_id=review.review.review_id,
                analysis_id=review.review.analysis_id,
                retrieval_id=review.review.retrieval_id,
                report=report,
                source_context_snapshot_id=review.current_target.context_snapshot_id,
                source_context_fingerprint=review.current_target.context_fingerprint,
                source_retrieval_target_fingerprint=(
                    review.current_target.source_retrieval_target_fingerprint
                ),
                source_promotion_ids=review.review.promotion_ids,
                selected_memory_sources=review.review.selected_memory_sources,
                provider_id=review.review.provider_id,
                model_id=review.review.model_id,
                prompt_version=review.review.prompt_version,
                review_note=review.review.request.note,
                reviewed_by=review.review.request.reviewed_by,
                human_rubric=review.review.request.quality_rubric.to_dict(),
                factual_error_count=review.review.request.factual_error_count,
                unsupported_claim_count=(review.review.request.unsupported_claim_count),
                quality_evidence_fingerprint=content_fingerprint(
                    review.review.quality_evidence
                ),
                cost_evidence_fingerprint=content_fingerprint(
                    review.review.cost_evidence
                ),
            )
            memory_artifact_fingerprint = content_fingerprint(
                memory_artifact_payload(
                    review_id=review.review.review_id,
                    analysis_id=review.review.analysis_id,
                    report_artifact_id=report.artifact_id,
                    content=memory_content_value,
                    evidence_reference_ids=evidence_reference_ids,
                )
            )

        target_payload: JsonObject = {
            "contract": EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
            "review_id": review.review.review_id,
            "review_target_fingerprint": review.current_target.fingerprint,
            "review_event_hash": review.audit_replay.last_event_hash,
            "review_replay_valid": review_replay.valid,
            "analysis_id": review.review.analysis_id,
            "workflow_id": review.review.workflow_id,
            "retrieval_id": review.review.retrieval_id,
            "source_context_snapshot_id": review.current_target.context_snapshot_id,
            "source_context_fingerprint": review.current_target.context_fingerprint,
            "source_retrieval_target_fingerprint": (
                review.current_target.source_retrieval_target_fingerprint
            ),
            "source_promotion_ids": list(review.review.promotion_ids),
            "selected_memory_sources": list(review.review.selected_memory_sources),
            "report_artifact_id": report.artifact_id if report is not None else None,
            "report_artifact_fingerprint": (
                report.fingerprint if report is not None else None
            ),
            "evidence_reference_ids": list(evidence_reference_ids),
            "provider_id": review.review.provider_id,
            "model_id": review.review.model_id,
            "prompt_version": review.review.prompt_version,
            "quality_evidence_fingerprint": content_fingerprint(
                review.review.quality_evidence
            ),
            "cost_evidence_fingerprint": content_fingerprint(
                review.review.cost_evidence
            ),
            "memory_artifact_fingerprint": memory_artifact_fingerprint,
            "errors": list(dict.fromkeys(errors)),
        }
        return ExternalPromotedAnalysisMemoryTarget(
            review_id=review.review.review_id,
            analysis_id=review.review.analysis_id,
            workflow_id=review.review.workflow_id,
            retrieval_id=review.review.retrieval_id,
            source_context_snapshot_id=review.current_target.context_snapshot_id,
            source_context_fingerprint=review.current_target.context_fingerprint,
            source_retrieval_target_fingerprint=(
                review.current_target.source_retrieval_target_fingerprint
            ),
            source_promotion_ids=review.review.promotion_ids,
            selected_memory_sources=review.review.selected_memory_sources,
            report_artifact_id=report.artifact_id if report is not None else None,
            report_artifact_fingerprint=(
                report.fingerprint if report is not None else None
            ),
            evidence_reference_ids=evidence_reference_ids,
            provider_id=review.review.provider_id,
            model_id=review.review.model_id,
            prompt_version=review.review.prompt_version,
            review_target_fingerprint=review.current_target.fingerprint,
            review_event_hash=review.audit_replay.last_event_hash,
            quality_evidence_fingerprint=content_fingerprint(
                review.review.quality_evidence
            ),
            cost_evidence_fingerprint=content_fingerprint(review.review.cost_evidence),
            memory_content=memory_content_value,
            memory_artifact_fingerprint=memory_artifact_fingerprint,
            fingerprint=content_fingerprint(target_payload),
            errors=tuple(dict.fromkeys(errors)),
        )


def memory_content(
    *,
    review_id: str,
    analysis_id: str,
    retrieval_id: str,
    report: StoredArtifact,
    source_context_snapshot_id: str,
    source_context_fingerprint: str,
    source_retrieval_target_fingerprint: str | None,
    source_promotion_ids: Sequence[str],
    selected_memory_sources: Sequence[JsonObject],
    provider_id: str,
    model_id: str,
    prompt_version: str,
    review_note: str,
    reviewed_by: str,
    human_rubric: dict[str, int],
    factual_error_count: int,
    unsupported_claim_count: int,
    quality_evidence_fingerprint: str,
    cost_evidence_fingerprint: str,
) -> JsonObject:
    """Build the immutable, non-authoritative historical memory content."""
    source = dict(report.content)
    normalized_report = {
        field_name: source[field_name]
        for field_name in (
            "title",
            "summary",
            "findings",
            "counterpoints",
            "limitations",
            "follow_up_checks",
            "conclusion",
        )
        if field_name in source
    }
    provenance = source.get("provider_provenance")
    safe_provenance: JsonObject = {}
    if isinstance(provenance, Mapping):
        for field_name in (
            "provider_id",
            "model_id",
            "response_model",
            "prompt_version",
            "request_payload_fingerprint",
            "response_fingerprint",
            "http_status",
            "latency_ms",
            "timeout_seconds",
            "usage",
            "finish_reason",
            "reasoning_mode_requested",
            "reasoning_effort_requested",
            "reasoning_content_present",
            "reasoning_content_char_count",
            "reasoning_content_persisted",
        ):
            if field_name in provenance:
                safe_provenance[field_name] = provenance[field_name]
    return {
        "schema_version": ("karkinos.ai.external_promoted_analysis_memory_artifact.v1"),
        "scope": f"external-promoted-memory-analysis/{analysis_id}",
        "source_review_id": review_id,
        "source_analysis_id": analysis_id,
        "source_report_artifact_id": report.artifact_id,
        "source_report_artifact_fingerprint": report.fingerprint,
        "source_retrieval_id": retrieval_id,
        "source_retrieval_target_fingerprint": source_retrieval_target_fingerprint,
        "source_context_snapshot_id": source_context_snapshot_id,
        "source_context_fingerprint": source_context_fingerprint,
        "source_promotion_ids": list(source_promotion_ids),
        "selected_memory_source_fingerprints": [
            item.get("selection_fingerprint") for item in selected_memory_sources
        ],
        "source_provider_id": provider_id,
        "source_model_id": model_id,
        "source_prompt_version": prompt_version,
        "reviewed_by": reviewed_by,
        "review_note": review_note,
        "human_quality_rubric": dict(human_rubric),
        "factual_error_count": factual_error_count,
        "unsupported_claim_count": unsupported_claim_count,
        "quality_evidence_fingerprint": quality_evidence_fingerprint,
        "cost_evidence_fingerprint": cost_evidence_fingerprint,
        "historical_report": normalized_report,
        "provider_provenance": safe_provenance,
        "validity_status": (
            "reviewed_historical_research_invalid_on_source_evidence_audit_or_"
            "lineage_drift_and_explicitly_revocable"
        ),
        "human_review_required_on_retrieval": True,
        "automatic_recall_allowed": False,
        "is_current_fact": False,
        "requires_current_evidence_rebinding": True,
        "decision_input_created": False,
        "trade_plan_created": False,
        "authority_effect": "none",
    }
