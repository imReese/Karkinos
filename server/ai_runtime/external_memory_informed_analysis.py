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

from .external_memory_analysis_output import build_output_contract as _output_contract
from .external_memory_analysis_output import (
    build_system_instructions as _system_instructions,
)
from .external_memory_analysis_output import decode_stage_output as _decode_stage_output
from .external_memory_analysis_output import (
    external_edge_request_options as _edge_request_options,
)
from .external_memory_analysis_output import message_text as _message_text
from .external_memory_analysis_output import (
    redact_sensitive_content as _redact_sensitive_content,
)
from .external_memory_analysis_output import (
    safe_external_error_code as _safe_external_error_code,
)
from .external_memory_analysis_output import safe_usage as _safe_usage
from .external_memory_analysis_output import utc_now as _utc_now
from .external_memory_analysis_provider import (
    OpenAICompatibleMemoryInformedProvider,
)
from .external_memory_analysis_result import ExternalMemoryAnalysisResult
from .external_memory_analysis_service import (
    HumanExternalMemoryAnalysisService,
    external_memory_binding_errors,
)
from .external_memory_analysis_workflow import (
    external_memory_runtime_ids as _runtime_ids,
)
from .external_memory_analysis_workflow import (
    external_memory_stage_artifact_kind as _stage_artifact_kind,
)
from .external_memory_analysis_workflow import (
    external_memory_stage_focus as _stage_focus,
)
from .external_memory_analysis_workflow import (
    external_memory_workflow_definition as _workflow_definition,
)
from .external_memory_analysis_workflow import (
    register_external_memory_runtime as _register_runtime,
)

_binding_errors = external_memory_binding_errors

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
