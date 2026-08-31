"""Stable contracts for offline, memory-informed fixture analysis."""

from __future__ import annotations

from dataclasses import dataclass

from server.ai_runtime.contracts import JsonObject, WorkflowStatus, content_fingerprint

MEMORY_INFORMED_ANALYSIS_CONFIRMATION = (
    "run_offline_memory_informed_fixture_with_current_evidence_"
    "without_trade_authority"
)
MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION = (
    "karkinos.ai.memory_informed_fixture_analysis.v1"
)
MEMORY_INFORMED_PROVIDER_ID = "karkinos.fixture.memory_informed.v1"
MEMORY_INFORMED_MODEL_ID = "karkinos.fixture.memory_informed.research.v1"
MEMORY_INFORMED_DEFINITION_ID = "karkinos.memory_informed_fixture.v1"

MEMORY_INFORMED_CLAIM_STAGE_ID = "current_evidence_claim"
MEMORY_INFORMED_DEBATE_STAGE_ID = "memory_evidence_debate"
MEMORY_INFORMED_REPORT_STAGE_ID = "memory_evidence_report"
MEMORY_INFORMED_CLAIM_ROLE_ID = "karkinos.role.memory_informed_claim.v1"
MEMORY_INFORMED_DEBATE_ROLE_ID = "karkinos.role.memory_informed_debate.v1"
MEMORY_INFORMED_REPORT_ROLE_ID = "karkinos.role.memory_informed_report.v1"
MEMORY_INFORMED_TERMINAL_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}


class MemoryInformedAnalysisRejected(ValueError):
    """Raised when the retrieval or current evidence cannot start analysis."""


@dataclass(frozen=True)
class HumanMemoryInformedAnalysisRequest:
    retrieval_id: str
    idempotency_key: str
    requested_by: str
    research_question: str
    confirmation: str
    schema_version: str = "karkinos.ai.memory_informed_fixture_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "retrieval_id",
            "idempotency_key",
            "requested_by",
            "research_question",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != MEMORY_INFORMED_ANALYSIS_CONFIRMATION:
            raise ValueError(
                "explicit offline memory-informed analysis confirmation is required"
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
class MemoryInformedAnalysisRecord:
    analysis_id: str
    request: HumanMemoryInformedAnalysisRequest
    stored_retrieval_id: str
    stored_idempotency_key: str
    request_fingerprint: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    retrieval_target_fingerprint: str
    run_claimed_at: str | None
    run_claim_expires_at: str | None
    created_at: str


@dataclass(frozen=True)
class MemoryInformedAnalysisReplay:
    analysis_id: str
    workflow_id: str
    valid: bool
    workflow_status: WorkflowStatus
    binding_validity: str
    current_evidence_reads_complete: bool
    audit_event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.memory_informed_fixture_replay.v1",
            "analysis_id": self.analysis_id,
            "workflow_id": self.workflow_id,
            "valid": self.valid,
            "workflow_status": self.workflow_status.value,
            "binding_validity": self.binding_validity,
            "current_evidence_reads_complete": self.current_evidence_reads_complete,
            "audit_event_count": self.audit_event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "fixture_only": True,
            "memory_input_is_current_fact": False,
            "external_model_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }
