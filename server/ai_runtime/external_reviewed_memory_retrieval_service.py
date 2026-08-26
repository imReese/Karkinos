"""Read-only evidence-rebinding service for external reviewed memory."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from server.contracts.external_reviewed_memory_retrieval import (
    CurrentContextValidator,
    ExternalReviewedMemoryRetrievalRejected,
    ExternalReviewedMemoryRetrievalReplay,
    ExternalReviewedMemoryRetrievalTarget,
    ExternalReviewedMemorySelection,
    HumanExternalReviewedMemoryRetrievalRequest,
    StoredExternalReviewedMemoryRetrieval,
)

from .contracts import EvidenceBoundContextSnapshot, JsonObject, content_fingerprint
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from .external_reviewed_memory_retrieval_result import (
    ExternalReviewedMemoryRetrievalResult,
)
from .memory_retrieval import EvidenceRebinding
from .store import AiAuditStore, IdempotencyConflict


class HumanExternalReviewedMemoryRetrievalServiceBase:
    """Retrieve exact promoted memory and rebind it to current evidence."""

    def __init__(
        self,
        *,
        promotion_service: Any,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        current_context_validator: CurrentContextValidator,
        retrieval_store: Any,
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
        request: HumanExternalReviewedMemoryRetrievalRequest,
    ) -> ExternalReviewedMemoryRetrievalResult:
        existing = self._retrieval_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request.fingerprint:
                raise IdempotencyConflict(
                    "external reviewed-memory retrieval idempotency key was reused "
                    "with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(request)
        if not target.eligible:
            raise ExternalReviewedMemoryRetrievalRejected(
                "external reviewed-memory retrieval failed closed: "
                + "; ".join(target.errors)
            )
        stored, reused = self._retrieval_store.record(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def get(self, retrieval_id: str) -> ExternalReviewedMemoryRetrievalResult:
        return self._result(self._retrieval_store.get(retrieval_id), reused=True)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[ExternalReviewedMemoryRetrievalResult, ...]:
        return tuple(
            self._result(item, reused=True)
            for item in self._retrieval_store.list(limit=limit)
        )

    def replay(self, retrieval_id: str) -> ExternalReviewedMemoryRetrievalReplay:
        return self.get(retrieval_id).replay()

    def _result(
        self,
        stored: StoredExternalReviewedMemoryRetrieval,
        *,
        reused: bool,
    ) -> ExternalReviewedMemoryRetrievalResult:
        return ExternalReviewedMemoryRetrievalResult(
            stored=stored,
            current_target=self._target(stored.request),
            audit_replay=self._retrieval_store.verify_replay(stored.retrieval_id),
            reused=reused,
        )

    def _target(
        self,
        request: HumanExternalReviewedMemoryRetrievalRequest,
    ) -> ExternalReviewedMemoryRetrievalTarget:
        errors: list[str] = []
        context: EvidenceBoundContextSnapshot | None = None
        current_records: tuple[CanonicalEvidenceRecord, ...] = ()
        try:
            context = self._ai_store.get_context(request.current_context_snapshot_id)
            current_records = self._current_context_validator(context)
        except (LookupError, EvidenceIdentityMismatch, ValueError) as exc:
            errors.append(f"current_context_invalid:{exc}")

        selections: list[ExternalReviewedMemorySelection] = []
        if context is not None and current_records:
            current_by_tool: dict[str, list[CanonicalEvidenceRecord]] = defaultdict(
                list
            )
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
                    ExternalReviewedMemoryRetrievalRejected,
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
        return ExternalReviewedMemoryRetrievalTarget(
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
        current_by_tool: Mapping[str, Sequence[CanonicalEvidenceRecord]],
    ) -> ExternalReviewedMemorySelection:
        promotion = self._promotion_service.get(promotion_id)
        if not promotion.memory_recall_eligible:
            reasons = promotion.invalidation_reasons or (
                f"effective_status:{promotion.effective_status.value}",
            )
            raise ExternalReviewedMemoryRetrievalRejected("; ".join(reasons))
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
            "promotion_audit_last_event_hash": (promotion.audit_replay.last_event_hash),
            "review_id": promotion.promotion.review_id,
            "analysis_id": promotion.promotion.analysis_id,
            "source_context_snapshot_id": (
                promotion.promotion.source_context_snapshot_id
            ),
            "memory_artifact_id": promotion.promotion.memory_artifact_id,
            "memory_artifact_fingerprint": (
                promotion.promotion.memory_artifact_fingerprint
            ),
            "memory_content": dict(promotion.promotion.memory_content),
            "rebindings": [item.to_dict() for item in rebindings],
        }
        return ExternalReviewedMemorySelection(
            promotion_id=promotion.promotion.promotion_id,
            review_id=promotion.promotion.review_id,
            analysis_id=promotion.promotion.analysis_id,
            source_context_snapshot_id=(promotion.promotion.source_context_snapshot_id),
            memory_artifact_id=promotion.promotion.memory_artifact_id,
            memory_artifact_fingerprint=(
                promotion.promotion.memory_artifact_fingerprint
            ),
            memory_content=dict(promotion.promotion.memory_content),
            rebindings=tuple(rebindings),
            fingerprint=content_fingerprint(selection_payload),
        )
