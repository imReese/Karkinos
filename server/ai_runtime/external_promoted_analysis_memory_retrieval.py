"""Compatibility facade for explicit promoted-analysis memory retrieval."""

from server.contracts.external_promoted_analysis_memory_retrieval import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONFIRMATION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_REQUEST_VERSION,
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
    ExternalPromotedAnalysisMemoryRetrievalStore,
)

from .external_promoted_analysis_memory_retrieval_result import (
    ExternalPromotedAnalysisMemoryRetrievalResult,
)
from .external_promoted_analysis_memory_retrieval_service import (
    HumanExternalPromotedAnalysisMemoryRetrievalService,
)

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
