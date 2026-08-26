"""Compatibility facade for explicit promoted-analysis memory retrieval."""

from server.contracts.external_promoted_analysis_memory_retrieval import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_REQUEST_VERSION,
    MAX_EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_IDS,
    CurrentContextValidator,
    ExternalPromotedAnalysisMemoryContextReader,
    ExternalPromotedAnalysisMemoryEvidenceReader,
    ExternalPromotedAnalysisMemoryRetrievalAuditReplay,
    ExternalPromotedAnalysisMemoryRetrievalRejected,
    ExternalPromotedAnalysisMemoryRetrievalReplay,
    ExternalPromotedAnalysisMemoryRetrievalRepository,
    ExternalPromotedAnalysisMemoryRetrievalTarget,
    ExternalPromotedAnalysisMemorySelection,
    HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    StoredExternalPromotedAnalysisMemoryRetrieval,
)
from server.persistence.external_promoted_analysis_memory_retrieval_uow import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_SCHEMA,
    ExternalPromotedAnalysisMemoryRetrievalStore,
    event_hash,
    retrieval_from_row,
)

from .external_promoted_analysis_memory_retrieval_result import (
    ExternalPromotedAnalysisMemoryRetrievalResult,
)
from .external_promoted_analysis_memory_retrieval_service import (
    HumanExternalPromotedAnalysisMemoryRetrievalService,
)

# Preserve historical white-box seams as aliases to their single owners.
_MAX_PROMOTION_IDS = MAX_EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_IDS
_SCHEMA = EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_SCHEMA
_event_hash = event_hash
_retrieval_from_row = retrieval_from_row

__all__ = [
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_REQUEST_VERSION",
    "CurrentContextValidator",
    "ExternalPromotedAnalysisMemoryContextReader",
    "ExternalPromotedAnalysisMemoryEvidenceReader",
    "ExternalPromotedAnalysisMemoryRetrievalAuditReplay",
    "ExternalPromotedAnalysisMemoryRetrievalRejected",
    "ExternalPromotedAnalysisMemoryRetrievalReplay",
    "ExternalPromotedAnalysisMemoryRetrievalRepository",
    "ExternalPromotedAnalysisMemoryRetrievalResult",
    "ExternalPromotedAnalysisMemoryRetrievalStore",
    "ExternalPromotedAnalysisMemoryRetrievalTarget",
    "ExternalPromotedAnalysisMemorySelection",
    "HumanExternalPromotedAnalysisMemoryRetrievalRequest",
    "StoredExternalPromotedAnalysisMemoryRetrieval",
]
