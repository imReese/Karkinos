"""Compatibility facade for explicit external-analysis memory promotion.

Contracts, projections, orchestration, and SQLite persistence are implemented
in responsibility-specific modules. Existing imports remain supported here.
"""

from server.contracts.external_promoted_analysis_memory import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION,
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION,
    ExternalPromotedAnalysisMemoryArtifactReader,
    ExternalPromotedAnalysisMemoryAuditReplay,
    ExternalPromotedAnalysisMemoryEffectiveStatus,
    ExternalPromotedAnalysisMemoryPromotionRequest,
    ExternalPromotedAnalysisMemoryRejected,
    ExternalPromotedAnalysisMemoryReplay,
    ExternalPromotedAnalysisMemoryRepository,
    ExternalPromotedAnalysisMemoryRevocationRequest,
    ExternalPromotedAnalysisMemoryTarget,
    StoredExternalPromotedAnalysisMemoryPromotion,
    StoredExternalPromotedAnalysisMemoryRevocation,
)
from server.persistence.external_promoted_analysis_memory_uow import (
    ExternalPromotedAnalysisMemoryStore,
)

from .external_promoted_analysis_memory_result import (
    ExternalPromotedAnalysisMemoryPromotionResult,
)
from .external_promoted_analysis_memory_service import (
    ExternalPromotedAnalysisMemoryPromotionService,
)

__all__ = [
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_CONTRACT_VERSION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_PROMOTION_CONFIRMATION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REQUEST_VERSION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_CONFIRMATION",
    "EXTERNAL_PROMOTED_ANALYSIS_MEMORY_REVOCATION_REQUEST_VERSION",
    "ExternalPromotedAnalysisMemoryArtifactReader",
    "ExternalPromotedAnalysisMemoryAuditReplay",
    "ExternalPromotedAnalysisMemoryEffectiveStatus",
    "ExternalPromotedAnalysisMemoryPromotionRequest",
    "ExternalPromotedAnalysisMemoryPromotionResult",
    "ExternalPromotedAnalysisMemoryPromotionService",
    "ExternalPromotedAnalysisMemoryRejected",
    "ExternalPromotedAnalysisMemoryReplay",
    "ExternalPromotedAnalysisMemoryRepository",
    "ExternalPromotedAnalysisMemoryRevocationRequest",
    "ExternalPromotedAnalysisMemoryStore",
    "ExternalPromotedAnalysisMemoryTarget",
    "StoredExternalPromotedAnalysisMemoryPromotion",
    "StoredExternalPromotedAnalysisMemoryRevocation",
]
