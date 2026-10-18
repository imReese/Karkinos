"""Compatibility facade for promoted-memory analysis human reviews.

Domain contracts, read projections, workflow orchestration, and SQLite
persistence live in separate modules. Keep importing this module at existing
call sites; its public API remains stable.
"""

from server.contracts.external_promoted_memory_analysis_review import (
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION,
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION,
    EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION,
    ExternalPromotedMemoryAnalysisReviewAuditReplay,
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewReplay,
    ExternalPromotedMemoryAnalysisReviewRepository,
    ExternalPromotedMemoryAnalysisReviewTarget,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
    StoredExternalPromotedMemoryAnalysisReview,
)
from server.persistence.external_promoted_memory_analysis_review_uow import (
    ExternalPromotedMemoryAnalysisReviewStore,
)

from .external_promoted_memory_analysis_review_result import (
    ExternalPromotedMemoryAnalysisReviewResult,
)
from .external_promoted_memory_analysis_review_service import (
    HumanExternalPromotedMemoryAnalysisReviewService,
)

__all__ = [
    "EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONFIRMATION",
    "EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_CONTRACT_VERSION",
    "EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_REQUEST_VERSION",
    "ExternalPromotedMemoryAnalysisReviewAuditReplay",
    "ExternalPromotedMemoryAnalysisReviewRejected",
    "ExternalPromotedMemoryAnalysisReviewReplay",
    "ExternalPromotedMemoryAnalysisReviewRepository",
    "ExternalPromotedMemoryAnalysisReviewResult",
    "ExternalPromotedMemoryAnalysisReviewStore",
    "ExternalPromotedMemoryAnalysisReviewTarget",
    "HumanExternalPromotedMemoryAnalysisReviewRequest",
    "HumanExternalPromotedMemoryAnalysisReviewService",
    "StoredExternalPromotedMemoryAnalysisReview",
]
