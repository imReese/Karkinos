"""Evidence-rebinding workflow for explicit promoted-memory retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from server.contracts.external_promoted_analysis_memory_retrieval import (
    CurrentContextValidator,
    ExternalPromotedAnalysisMemoryContextReader,
    ExternalPromotedAnalysisMemoryEvidenceReader,
    ExternalPromotedAnalysisMemoryRetrievalRejected,
    ExternalPromotedAnalysisMemoryRetrievalReplay,
    ExternalPromotedAnalysisMemoryRetrievalRepository,
    ExternalPromotedAnalysisMemoryRetrievalTarget,
    ExternalPromotedAnalysisMemorySelection,
    HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    StoredExternalPromotedAnalysisMemoryRetrieval,
)
from server.contracts.idempotency import IdempotencyConflict

from .contracts import EvidenceBoundContextSnapshot, JsonObject, content_fingerprint
from .evidence import CanonicalEvidenceRecord, EvidenceIdentityMismatch
from .external_promoted_analysis_memory import (
    ExternalPromotedAnalysisMemoryPromotionService,
)
from .external_promoted_analysis_memory_retrieval_result import (
    ExternalPromotedAnalysisMemoryRetrievalResult,
)
from .memory_retrieval import EvidenceRebinding

EvidenceByTool = dict[str, list[CanonicalEvidenceRecord]]


class HumanExternalPromotedAnalysisMemoryRetrievalService:
    """Retrieve exact promoted memory and rebind every current evidence item."""

    def __init__(
        self,
        *,
        promotion_service: ExternalPromotedAnalysisMemoryPromotionService,
        ai_store: ExternalPromotedAnalysisMemoryContextReader,
        evidence_repository: ExternalPromotedAnalysisMemoryEvidenceReader,
        current_context_validator: CurrentContextValidator,
        retrieval_store: ExternalPromotedAnalysisMemoryRetrievalRepository,
        now: Callable[[], str],
    ) -> None:
        self._promotion_service = promotion_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._current_context_validator = current_context_validator
        self._retrieval_store = retrieval_store
        self._now = now

    def start(
        self,
        request: HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    ) -> ExternalPromotedAnalysisMemoryRetrievalResult:
        existing = self._retrieval_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request.fingerprint:
                raise IdempotencyConflict(
                    "promoted-analysis memory retrieval idempotency key was "
                    "reused with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(request)
        if not target.eligible:
            raise ExternalPromotedAnalysisMemoryRetrievalRejected(
                "promoted-analysis memory retrieval failed closed: "
                + "; ".join(target.errors)
            )
        stored, reused = self._retrieval_store.record(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def get(
        self,
        retrieval_id: str,
    ) -> ExternalPromotedAnalysisMemoryRetrievalResult:
        return self._result(self._retrieval_store.get(retrieval_id), reused=True)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[ExternalPromotedAnalysisMemoryRetrievalResult, ...]:
        return tuple(
            self._result(item, reused=True)
            for item in self._retrieval_store.list(limit=limit)
        )

    def replay(
        self,
        retrieval_id: str,
    ) -> ExternalPromotedAnalysisMemoryRetrievalReplay:
        return self.get(retrieval_id).replay()

    def _result(
        self,
        stored: StoredExternalPromotedAnalysisMemoryRetrieval,
        *,
        reused: bool,
    ) -> ExternalPromotedAnalysisMemoryRetrievalResult:
        return ExternalPromotedAnalysisMemoryRetrievalResult(
            stored=stored,
            current_target=self._target(stored.request),
            audit_replay=self._retrieval_store.verify_replay(stored.retrieval_id),
            reused=reused,
        )

    def _target(
        self,
        request: HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    ) -> ExternalPromotedAnalysisMemoryRetrievalTarget:
        errors: list[str] = []
        context: EvidenceBoundContextSnapshot | None = None
        current_records: tuple[CanonicalEvidenceRecord, ...] = ()
        try:
            context = self._ai_store.get_context(request.current_context_snapshot_id)
            current_records = self._current_context_validator(context)
        except (LookupError, EvidenceIdentityMismatch, ValueError) as exc:
            errors.append(f"current_context_invalid:{exc}")

        selections: list[ExternalPromotedAnalysisMemorySelection] = []
        if context is not None and current_records:
            current_by_tool: EvidenceByTool = defaultdict(list)
            for record in current_records:
                current_by_tool[record.tool_name].append(record)
            for promotion_id in request.promotion_ids:
                try:
                    selection = self._selection(
                        promotion_id=promotion_id,
                        current_by_tool=current_by_tool,
                    )
                except (
                    LookupError,
                    EvidenceIdentityMismatch,
                    ExternalPromotedAnalysisMemoryRetrievalRejected,
                    ValueError,
                ) as exc:
                    errors.append(f"promotion_not_retrievable:{promotion_id}:{exc}")
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
                    "promotion_id": item.promotion_id,
                    "selection_fingerprint": item.fingerprint,
                }
                for item in selections
            ],
            "errors": list(dict.fromkeys(errors)),
        }
        return ExternalPromotedAnalysisMemoryRetrievalTarget(
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

    def _selection(
        self,
        *,
        promotion_id: str,
        current_by_tool: EvidenceByTool,
    ) -> ExternalPromotedAnalysisMemorySelection:
        promotion = self._promotion_service.get(promotion_id)
        if not promotion.memory_recall_eligible:
            reasons = promotion.invalidation_reasons or (
                f"effective_status:{promotion.effective_status.value}",
            )
            raise ExternalPromotedAnalysisMemoryRetrievalRejected("; ".join(reasons))
        rebindings: list[EvidenceRebinding] = []
        for source_reference_id in promotion.promotion.evidence_reference_ids:
            source = self._evidence_repository.get(source_reference_id)
            if source is None:
                raise EvidenceIdentityMismatch(
                    f"source evidence missing:{source_reference_id}"
                )
            candidates = current_by_tool.get(source.tool_name, [])
            if len(candidates) != 1:
                raise EvidenceIdentityMismatch(
                    "current evidence mapping requires exactly one "
                    f"{source.tool_name} record"
                )
            current = candidates[0]
            if current.kind != source.kind:
                raise EvidenceIdentityMismatch(
                    f"current evidence kind drifted:{source.tool_name}"
                )
            if current.status != "complete":
                raise EvidenceIdentityMismatch(
                    f"current evidence is not complete:{source.tool_name}"
                )
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
            "promotion_id": promotion.promotion.promotion_id,
            "promotion_target_fingerprint": promotion.current_target.fingerprint,
            "promotion_audit_last_event_hash": promotion.audit_replay.last_event_hash,
            "review_id": promotion.promotion.review_id,
            "analysis_id": promotion.promotion.analysis_id,
            "workflow_id": promotion.promotion.workflow_id,
            "source_context_snapshot_id": (
                promotion.promotion.source_context_snapshot_id
            ),
            "memory_artifact_id": promotion.promotion.memory_artifact_id,
            "memory_artifact_fingerprint": (
                promotion.promotion.memory_artifact_fingerprint
            ),
            "memory_content": dict(promotion.promotion.memory_content),
            "provider_id": promotion.promotion.provider_id,
            "model_id": promotion.promotion.model_id,
            "prompt_version": promotion.promotion.prompt_version,
            "review_target_fingerprint": (
                promotion.promotion.review_target_fingerprint
            ),
            "quality_evidence_fingerprint": (
                promotion.promotion.quality_evidence_fingerprint
            ),
            "cost_evidence_fingerprint": (
                promotion.promotion.cost_evidence_fingerprint
            ),
            "rebindings": [item.to_dict() for item in rebindings],
        }
        return ExternalPromotedAnalysisMemorySelection(
            promotion_id=promotion.promotion.promotion_id,
            review_id=promotion.promotion.review_id,
            analysis_id=promotion.promotion.analysis_id,
            workflow_id=promotion.promotion.workflow_id,
            source_context_snapshot_id=promotion.promotion.source_context_snapshot_id,
            memory_artifact_id=promotion.promotion.memory_artifact_id,
            memory_artifact_fingerprint=(
                promotion.promotion.memory_artifact_fingerprint
            ),
            memory_content=dict(promotion.promotion.memory_content),
            provider_id=promotion.promotion.provider_id,
            model_id=promotion.promotion.model_id,
            prompt_version=promotion.promotion.prompt_version,
            rebindings=tuple(rebindings),
            fingerprint=content_fingerprint(selection_payload),
        )
