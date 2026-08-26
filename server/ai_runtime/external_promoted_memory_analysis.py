"""External analysis of explicitly retrieved promoted research memory.

This Phase 1.14 boundary deliberately reuses the evidence-bound prompt,
provider adapter, deterministic orchestrator, and local canonical-evidence
tools from the Phase 1.10 external analysis.  It changes only the source
contract and persistence edge: the selected memory must come from the
versioned Phase 1.13 promoted-memory retrieval, and its analysis rows live in
separate canonical tables.

The external model remains an optional, explicitly started edge adapter.  It
has no provider-side tools and no access to account mutation, Decision, OMS,
risk, kill-switch, capital-authority, submit, or cancel capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass

from server.persistence.external_promoted_memory_analysis import (
    ExternalPromotedMemoryAnalysisPersistenceMixin,
)

from .contracts import JsonObject
from .external_memory_informed_analysis import (
    ExternalMemoryAnalysisResult,
    ExternalMemoryAnalysisStore,
    HumanExternalMemoryAnalysisRequest,
    HumanExternalMemoryAnalysisService,
)
from .external_reviewed_memory_retrieval import (
    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    ExternalReviewedMemoryRetrievalResult,
    HumanExternalReviewedMemoryRetrievalService,
)

EXTERNAL_PROMOTED_MEMORY_ANALYSIS_CONTRACT_VERSION = (
    "karkinos.ai.external_promoted_memory_analysis.v1"
)
EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION = (
    "karkinos.ai.external_promoted_memory_request.v1"
)


class ExternalPromotedMemoryAnalysisStore(
    ExternalPromotedMemoryAnalysisPersistenceMixin,
    ExternalMemoryAnalysisStore,
):
    """Isolated request and redacted model-call audit store for Phase 1.14."""


@dataclass(frozen=True)
class ExternalPromotedMemoryAnalysisResult:
    """Versioned projection over the shared evidence-bound analysis engine."""

    analysis: ExternalMemoryAnalysisResult
    source_retrieval: ExternalReviewedMemoryRetrievalResult | None

    @property
    def promotion_ids(self) -> tuple[str, ...]:
        if self.source_retrieval is None:
            return ()
        return self.source_retrieval.stored.request.promotion_ids

    def replay(self) -> JsonObject:
        payload = self.analysis.replay().to_dict()
        payload.update(
            {
                "schema_version": (
                    "karkinos.ai.external_promoted_memory_analysis_replay.v1"
                ),
                "memory_source": "promoted_external_reviewed_memory",
                "promotion_ids": list(self.promotion_ids),
                "source_retrieval_schema_version": (
                    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION
                ),
                "legacy_retrieval_v1_modified": False,
                "automatic_recall_enabled": False,
                "decision_handoff_enabled": False,
                "authority_effect": "none",
            }
        )
        return payload

    def to_dict(self) -> JsonObject:
        payload = self.analysis.to_dict()
        source = self.source_retrieval
        payload.update(
            {
                "schema_version": EXTERNAL_PROMOTED_MEMORY_ANALYSIS_CONTRACT_VERSION,
                "request_schema_version": (self.analysis.record.request.schema_version),
                "memory_source": "promoted_external_reviewed_memory",
                "source_retrieval_schema_version": (
                    EXTERNAL_REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION
                ),
                "promotion_ids": list(self.promotion_ids),
                "promoted_memory_retrieval_eligible": (
                    source.retrieval_eligible if source is not None else False
                ),
                "source_retrieval_invalidation_reasons": (
                    list(source.invalidation_reasons) if source is not None else []
                ),
                "selected_memory_sources": (
                    [
                        {
                            "promotion_id": item.promotion_id,
                            "review_id": item.review_id,
                            "source_analysis_id": item.analysis_id,
                            "memory_artifact_id": item.memory_artifact_id,
                            "memory_artifact_fingerprint": (
                                item.memory_artifact_fingerprint
                            ),
                        }
                        for item in source.current_target.selections
                    ]
                    if source is not None and source.retrieval_eligible
                    else []
                ),
                "external_context_scope": (
                    "selected_promoted_reviewed_memory_and_bound_current_"
                    "canonical_evidence"
                ),
                "legacy_retrieval_v1_modified": False,
                "automatic_recall_enabled": False,
                "semantic_search_used": False,
                "provider_side_tools_enabled": False,
                "local_read_only_tools_used": True,
                "model_reasoning_mode_preserved": True,
                "reasoning_content_persisted": False,
                "requires_human_review": True,
                "decision_handoff_enabled": False,
                "trade_plan_created": False,
                "authority_effect": "none",
            }
        )
        return payload


class HumanExternalPromotedMemoryAnalysisService:
    """Expose the shared model workflow only for Phase 1.13 retrievals."""

    def __init__(
        self,
        *,
        analysis_service: HumanExternalMemoryAnalysisService,
        retrieval_service: HumanExternalReviewedMemoryRetrievalService,
    ) -> None:
        self._analysis_service = analysis_service
        self._retrieval_service = retrieval_service

    def start(
        self,
        request: HumanExternalMemoryAnalysisRequest,
    ) -> ExternalPromotedMemoryAnalysisResult:
        if request.schema_version != EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REQUEST_VERSION:
            raise ValueError("promoted-memory analysis request schema is required")
        return self._wrap(self._analysis_service.start(request))

    def get(self, analysis_id: str) -> ExternalPromotedMemoryAnalysisResult:
        return self._wrap(self._analysis_service.get(analysis_id))

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[ExternalPromotedMemoryAnalysisResult, ...]:
        return tuple(
            self._wrap(item) for item in self._analysis_service.list(limit=limit)
        )

    def replay(self, analysis_id: str) -> JsonObject:
        return self.get(analysis_id).replay()

    def _wrap(
        self,
        analysis: ExternalMemoryAnalysisResult,
    ) -> ExternalPromotedMemoryAnalysisResult:
        try:
            source = self._retrieval_service.get(analysis.record.request.retrieval_id)
        except (LookupError, ValueError):
            source = None
        return ExternalPromotedMemoryAnalysisResult(
            analysis=analysis,
            source_retrieval=source,
        )
