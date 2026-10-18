"""Compatibility façade for external memory-informed analysis.

The stable import surface is retained while contracts, persistence, provider
transport, workflow definition, response validation, and orchestration each
have one physical owner.
"""

from server.contracts.external_memory_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION,
    EXTERNAL_MEMORY_ANALYSIS_CONTRACT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID,
    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS,
    ExternalMemoryAnalysisRecord,
    ExternalMemoryAnalysisRejected,
    ExternalMemoryAnalysisReplay,
    ExternalMemoryAuthenticationError,
    ExternalMemoryHttpError,
    ExternalMemoryInvalidResponseError,
    ExternalMemoryModelCallAlreadyAttemptedError,
    ExternalMemoryNetworkError,
    ExternalMemoryRateLimitedError,
    ExternalMemoryTimeoutError,
    ExternalModelCallRecord,
    HumanExternalMemoryAnalysisRequest,
)
from server.persistence.external_memory_analysis import (
    ExternalMemoryAnalysisStore,
    model_call_from_row,
    record_from_row,
)

from .external_memory_analysis_provider import (
    OpenAICompatibleMemoryInformedProvider,
)
from .external_memory_analysis_result import ExternalMemoryAnalysisResult
from .external_memory_analysis_service import (
    HumanExternalMemoryAnalysisService,
)

__all__ = [
    "EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION",
    "EXTERNAL_MEMORY_ANALYSIS_CONTRACT_VERSION",
    "EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID",
    "EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION",
    "EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS",
    "ExternalMemoryAnalysisRecord",
    "ExternalMemoryAnalysisRejected",
    "ExternalMemoryAnalysisReplay",
    "ExternalMemoryAnalysisResult",
    "ExternalMemoryAnalysisStore",
    "ExternalMemoryAuthenticationError",
    "ExternalMemoryHttpError",
    "ExternalMemoryInvalidResponseError",
    "ExternalMemoryModelCallAlreadyAttemptedError",
    "ExternalMemoryNetworkError",
    "ExternalMemoryRateLimitedError",
    "ExternalMemoryTimeoutError",
    "ExternalModelCallRecord",
    "HumanExternalMemoryAnalysisRequest",
    "HumanExternalMemoryAnalysisService",
    "OpenAICompatibleMemoryInformedProvider",
    "model_call_from_row",
    "record_from_row",
]
