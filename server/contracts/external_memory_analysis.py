"""Stable contracts for human-confirmed external memory analysis."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from server.ai_runtime.contracts import JsonObject, WorkflowStatus, content_fingerprint

EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION = (
    "send_reviewed_memory_and_current_canonical_evidence_to_configured_external_"
    "model_for_claim_debate_report_without_trade_authority"
)
EXTERNAL_MEMORY_ANALYSIS_CONTRACT_VERSION = (
    "karkinos.ai.external_memory_informed_analysis.v1"
)
EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION = (
    "karkinos.ai.external_memory_informed_prompt.v2"
)
EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID = "karkinos.external_memory_informed_analysis.v1"

EXTERNAL_MEMORY_CLAIM_STAGE_ID = "external_current_evidence_claim"
EXTERNAL_MEMORY_DEBATE_STAGE_ID = "external_memory_evidence_debate"
EXTERNAL_MEMORY_REPORT_STAGE_ID = "external_memory_evidence_report"
EXTERNAL_MEMORY_CLAIM_ROLE_ID = "karkinos.role.external_memory_claim.v1"
EXTERNAL_MEMORY_DEBATE_ROLE_ID = "karkinos.role.external_memory_debate.v1"
EXTERNAL_MEMORY_REPORT_ROLE_ID = "karkinos.role.external_memory_report.v1"
EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS = (
    EXTERNAL_MEMORY_CLAIM_STAGE_ID,
    EXTERNAL_MEMORY_DEBATE_STAGE_ID,
    EXTERNAL_MEMORY_REPORT_STAGE_ID,
)
EXTERNAL_MEMORY_TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.PARTIAL,
        WorkflowStatus.FAILED,
        WorkflowStatus.BLOCKED,
    }
)


class ExternalMemoryAnalysisRejected(ValueError):
    """Raised before network I/O when intent or evidence is inadmissible."""


class ExternalMemoryAuthenticationError(RuntimeError):
    pass


class ExternalMemoryRateLimitedError(RuntimeError):
    pass


class ExternalMemoryHttpError(RuntimeError):
    pass


class ExternalMemoryTimeoutError(RuntimeError):
    pass


class ExternalMemoryNetworkError(RuntimeError):
    pass


class ExternalMemoryInvalidResponseError(RuntimeError):
    pass


class ExternalMemoryModelCallAlreadyAttemptedError(RuntimeError):
    pass


@dataclass(frozen=True)
class HumanExternalMemoryAnalysisRequest:
    retrieval_id: str
    idempotency_key: str
    requested_by: str
    research_question: str
    confirmation: str
    schema_version: str = "karkinos.ai.external_memory_request.v1"

    def __post_init__(self) -> None:
        for name in (
            "retrieval_id",
            "idempotency_key",
            "requested_by",
            "research_question",
            "schema_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.confirmation != EXTERNAL_MEMORY_ANALYSIS_CONFIRMATION:
            raise PermissionError(
                "external memory-informed analysis requires explicit financial "
                "evidence export and no-authority confirmation"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "retrieval_id": self.retrieval_id,
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "research_question": self.research_question,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ExternalMemoryAnalysisRecord:
    analysis_id: str
    request: HumanExternalMemoryAnalysisRequest
    stored_retrieval_id: str
    stored_idempotency_key: str
    request_fingerprint: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    retrieval_target_fingerprint: str
    provider_id: str
    model_id: str
    endpoint_origin: str
    prompt_version: str
    run_claimed_at: str | None
    created_at: str


@dataclass(frozen=True)
class ExternalModelCallRecord:
    workflow_id: str
    stage_id: str
    provider_id: str
    model_id: str
    prompt_version: str
    status: str
    request_payload_fingerprint: str
    response_fingerprint: str | None
    response_model: str | None
    http_status: int | None
    usage: JsonObject
    finish_reason: str | None
    reasoning_content_present: bool
    reasoning_content_char_count: int
    error_code: str | None
    started_at: str
    finished_at: str | None

    def to_dict(self) -> JsonObject:
        return {
            "stage_id": self.stage_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "status": self.status,
            "request_payload_fingerprint": self.request_payload_fingerprint,
            "response_fingerprint": self.response_fingerprint,
            "response_model": self.response_model,
            "http_status": self.http_status,
            "usage": dict(self.usage),
            "finish_reason": self.finish_reason,
            "reasoning_content_present": self.reasoning_content_present,
            "reasoning_content_char_count": self.reasoning_content_char_count,
            "reasoning_content_persisted": False,
            "error_code": self.error_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass(frozen=True)
class ExternalMemoryAnalysisReplay:
    analysis_id: str
    workflow_id: str
    valid: bool
    workflow_status: WorkflowStatus
    binding_validity: str
    current_evidence_reads_complete: bool
    model_call_count: int
    audit_event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.external_memory_replay.v1",
            "analysis_id": self.analysis_id,
            "workflow_id": self.workflow_id,
            "valid": self.valid,
            "workflow_status": self.workflow_status.value,
            "binding_validity": self.binding_validity,
            "current_evidence_reads_complete": self.current_evidence_reads_complete,
            "external_model_invocation_count": self.model_call_count,
            "audit_event_count": self.audit_event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_input_is_current_fact": False,
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


class ExternalMemoryAnalysisRepository(Protocol):
    """Persistence boundary consumed by the provider and application service."""

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ExternalMemoryAnalysisRecord | None: ...

    def create_or_get(
        self,
        *,
        request: HumanExternalMemoryAnalysisRequest,
        workflow_id: str,
        inputs: ExternalMemoryAnalysisPersistenceInputs,
        provider_id: str,
        model_id: str,
        endpoint_origin: str,
        created_at: str,
    ) -> tuple[ExternalMemoryAnalysisRecord, bool]: ...

    def claim_run(self, analysis_id: str, *, claimed_at: str) -> bool: ...

    def get(self, analysis_id: str) -> ExternalMemoryAnalysisRecord: ...

    def list(self, *, limit: int = 50) -> tuple[ExternalMemoryAnalysisRecord, ...]: ...

    def start_model_call(
        self,
        *,
        workflow_id: str,
        stage_id: str,
        provider_id: str,
        model_id: str,
        request_payload_fingerprint: str,
        started_at: str,
    ) -> bool: ...

    def finish_model_call(
        self,
        *,
        workflow_id: str,
        stage_id: str,
        status: str,
        response_fingerprint: str | None,
        response_model: str | None,
        http_status: int | None,
        usage: Mapping[str, int] | None,
        finish_reason: str | None,
        reasoning_content_present: bool,
        reasoning_content_char_count: int,
        error_code: str | None,
        finished_at: str,
    ) -> None: ...

    def list_model_calls(
        self,
        workflow_id: str,
    ) -> tuple[ExternalModelCallRecord, ...]: ...


class ExternalMemoryContextBinding(Protocol):
    snapshot_id: str
    fingerprint: str


class ExternalMemoryRetrievalTargetBinding(Protocol):
    fingerprint: str


class ExternalMemoryRetrievalBinding(Protocol):
    current_target: ExternalMemoryRetrievalTargetBinding


class ExternalMemoryAnalysisPersistenceInputs(Protocol):
    """Minimum immutable identity needed when claiming an analysis row."""

    context: ExternalMemoryContextBinding
    retrieval: ExternalMemoryRetrievalBinding
