"""Evidence-rebinding service for explicit reviewed-memory retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from server.contracts.memory_retrieval import (
    EvidenceRebinding,
    HumanReviewedMemoryRetrievalRequest,
    ReviewedMemoryRetrievalRejected,
    ReviewedMemoryRetrievalReplay,
    ReviewedMemoryRetrievalRepository,
    ReviewedMemoryRetrievalTarget,
    ReviewedMemorySelection,
    StoredReviewedMemoryRetrieval,
)

from .analysis_reviews import (
    AnalysisReviewEffectiveStatus,
    HumanAnalysisReviewService,
)
from .contracts import EvidenceBoundContextSnapshot, JsonObject, content_fingerprint
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from .memory_retrieval_result import ReviewedMemoryRetrievalResult
from .store import AiAuditStore, IdempotencyConflict
from .task_analysis import HumanResearchTaskFixtureAnalysisService


class HumanReviewedMemoryRetrievalServiceBase:
    """Select exact reviewed memory and rebind it to current evidence."""

    _exact_memory_artifact: Any

    def __init__(
        self,
        *,
        review_service: HumanAnalysisReviewService,
        analysis_service: HumanResearchTaskFixtureAnalysisService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        retrieval_store: ReviewedMemoryRetrievalRepository,
        now: Callable[[], str],
    ) -> None:
        self._review_service = review_service
        self._analysis_service = analysis_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._retrieval_store = retrieval_store
        self._now = now

    def start(
        self,
        request: HumanReviewedMemoryRetrievalRequest,
    ) -> ReviewedMemoryRetrievalResult:
        existing = self._retrieval_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request.fingerprint:
                raise IdempotencyConflict(
                    "reviewed-memory retrieval idempotency key was reused "
                    "with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(request)
        if not target.eligible:
            raise ReviewedMemoryRetrievalRejected(
                "reviewed-memory retrieval failed closed: " + "; ".join(target.errors)
            )
        stored, reused = self._retrieval_store.record(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def get(self, retrieval_id: str) -> ReviewedMemoryRetrievalResult:
        return self._result(self._retrieval_store.get(retrieval_id), reused=True)

    def list(self, *, limit: int = 50) -> tuple[ReviewedMemoryRetrievalResult, ...]:
        return tuple(
            self._result(item, reused=True)
            for item in self._retrieval_store.list(limit=limit)
        )

    def replay(self, retrieval_id: str) -> ReviewedMemoryRetrievalReplay:
        return self.get(retrieval_id).replay()

    def _result(
        self,
        stored: StoredReviewedMemoryRetrieval,
        *,
        reused: bool,
    ) -> ReviewedMemoryRetrievalResult:
        return ReviewedMemoryRetrievalResult(
            stored=stored,
            current_target=self._target(stored.request),
            audit_replay=self._retrieval_store.verify_replay(stored.retrieval_id),
            reused=reused,
        )

    def _target(
        self,
        request: HumanReviewedMemoryRetrievalRequest,
    ) -> ReviewedMemoryRetrievalTarget:
        errors: list[str] = []
        context: EvidenceBoundContextSnapshot | None = None
        current_records: tuple[CanonicalEvidenceRecord, ...] = ()
        try:
            context = self._ai_store.get_context(request.current_context_snapshot_id)
            current_records = self._validate_current_context(context)
        except (LookupError, EvidenceIdentityMismatch, ValueError) as exc:
            errors.append(f"current_context_invalid:{exc}")

        selections: list[ReviewedMemorySelection] = []
        if context is not None and current_records:
            current_by_tool: dict[str, list[CanonicalEvidenceRecord]] = defaultdict(
                list
            )
            for record in current_records:
                current_by_tool[record.tool_name].append(record)
            for review_id in request.review_ids:
                try:
                    selection = self._selection(
                        review_id=review_id,
                        current_by_tool=current_by_tool,
                    )
                except (
                    LookupError,
                    EvidenceIdentityMismatch,
                    ReviewedMemoryRetrievalRejected,
                    ValueError,
                ) as exc:
                    errors.append(f"review_not_retrievable:{review_id}:{exc}")
                else:
                    selections.append(selection)

        target_payload: JsonObject = {
            "current_context_snapshot_id": request.current_context_snapshot_id,
            "current_context_fingerprint": (
                context.fingerprint if context is not None else None
            ),
            "valuation_snapshot_id": (
                context.valuation_snapshot_id if context is not None else None
            ),
            "ledger_cutoff_id": (
                context.ledger_cutoff_id if context is not None else None
            ),
            "ledger_fingerprint": (
                context.ledger_fingerprint if context is not None else None
            ),
            "selections": [
                {
                    "review_id": item.review_id,
                    "selection_fingerprint": item.fingerprint,
                }
                for item in selections
            ],
            "errors": list(dict.fromkeys(errors)),
        }
        return ReviewedMemoryRetrievalTarget(
            current_context_snapshot_id=request.current_context_snapshot_id,
            current_context_fingerprint=(
                context.fingerprint if context is not None else None
            ),
            valuation_snapshot_id=(
                context.valuation_snapshot_id if context is not None else None
            ),
            ledger_cutoff_id=(
                context.ledger_cutoff_id if context is not None else None
            ),
            ledger_fingerprint=(
                context.ledger_fingerprint if context is not None else None
            ),
            selections=tuple(selections),
            fingerprint=content_fingerprint(target_payload),
            errors=tuple(dict.fromkeys(errors)),
        )

    def _validate_current_context(
        self,
        context: EvidenceBoundContextSnapshot,
    ) -> tuple[CanonicalEvidenceRecord, ...]:
        expected_snapshot_id = f"ai-context-{context.fingerprint[:24]}"
        if context.snapshot_id != expected_snapshot_id:
            raise EvidenceIdentityMismatch("current context fingerprint drifted")
        records: list[CanonicalEvidenceRecord] = []
        for reference in context.evidence_references:
            record = self._evidence_repository.get(reference.reference_id)
            if record is None:
                raise EvidenceIdentityMismatch(
                    f"current evidence missing:{reference.reference_id}"
                )
            if record.to_reference() != reference:
                raise EvidenceIdentityMismatch(
                    f"current evidence reference drifted:{reference.reference_id}"
                )
            if (
                record.valuation_snapshot_id != context.valuation_snapshot_id
                or record.ledger_cutoff_id != context.ledger_cutoff_id
                or record.ledger_fingerprint != context.ledger_fingerprint
            ):
                raise EvidenceIdentityMismatch(
                    "current evidence financial identity drifted:"
                    f"{reference.reference_id}"
                )
            if not record.authoritative:
                raise EvidenceIdentityMismatch(
                    f"current evidence is not complete:{reference.reference_id}:"
                    f"{record.status}"
                )
            records.append(record)
        if not records:
            raise EvidenceIdentityMismatch("current context has no evidence")
        tool_names = [item.tool_name for item in records]
        if len(tool_names) != len(set(tool_names)):
            raise EvidenceIdentityMismatch(
                "current context has ambiguous duplicate canonical tools"
            )
        return tuple(records)

    def _selection(
        self,
        *,
        review_id: str,
        current_by_tool: Mapping[str, Sequence[CanonicalEvidenceRecord]],
    ) -> ReviewedMemorySelection:
        review = self._review_service.get(review_id)
        if (
            review.effective_status != AnalysisReviewEffectiveStatus.REVIEWED_MEMORY
            or not review.memory_recall_eligible
        ):
            reasons = review.invalidation_reasons or (
                f"effective_status:{review.effective_status.value}",
            )
            raise ReviewedMemoryRetrievalRejected("; ".join(reasons))
        analysis = self._analysis_service.get(review.review.analysis_id)
        memory_artifact = self._exact_memory_artifact(
            artifacts=analysis.artifacts,
            memory_artifact_id=review.review.memory_artifact_id,
        )
        rebindings: list[EvidenceRebinding] = []
        for source_reference_id in memory_artifact.evidence_reference_ids:
            source = self._evidence_repository.get(source_reference_id)
            if source is None:
                raise EvidenceIdentityMismatch(
                    f"source evidence missing:{source_reference_id}"
                )
            candidates = current_by_tool.get(source.tool_name, ())
            if len(candidates) != 1:
                raise EvidenceIdentityMismatch(
                    "current evidence mapping requires exactly one "
                    f"{source.tool_name} record"
                )
            current = candidates[0]
            rebindings.append(
                EvidenceRebinding(
                    tool_name=source.tool_name,
                    kind=source.kind,
                    source_reference_id=source.reference_id,
                    source_fingerprint=source.record_fingerprint,
                    current_reference_id=current.reference_id,
                    current_fingerprint=current.record_fingerprint,
                    current_status=current.status,
                )
            )
        selection_payload: JsonObject = {
            "review_id": review.review.review_id,
            "review_target_fingerprint": review.current_target.fingerprint,
            "review_audit_last_event_hash": review.audit_replay.last_event_hash,
            "analysis_id": analysis.record.analysis_id,
            "source_context_snapshot_id": analysis.record.context_snapshot_id,
            "memory_artifact_id": memory_artifact.artifact_id,
            "memory_artifact_fingerprint": memory_artifact.fingerprint,
            "memory_content": dict(memory_artifact.content),
            "rebindings": [item.to_dict() for item in rebindings],
        }
        return ReviewedMemorySelection(
            review_id=review.review.review_id,
            analysis_id=analysis.record.analysis_id,
            source_context_snapshot_id=analysis.record.context_snapshot_id,
            memory_artifact_id=memory_artifact.artifact_id,
            memory_artifact_fingerprint=memory_artifact.fingerprint,
            memory_content=dict(memory_artifact.content),
            rebindings=tuple(rebindings),
            fingerprint=content_fingerprint(selection_payload),
        )
