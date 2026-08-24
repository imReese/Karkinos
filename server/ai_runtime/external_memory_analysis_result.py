"""Read projection and replay verdict for external memory analysis."""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts.external_memory_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_CONTRACT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS,
    ExternalMemoryAnalysisRecord,
    ExternalMemoryAnalysisReplay,
    ExternalModelCallRecord,
)

from .contracts import (
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    ToolCallStatus,
    WorkflowStatus,
)
from .memory_retrieval import ReviewedMemoryRetrievalResult


@dataclass(frozen=True)
class ExternalMemoryAnalysisResult:
    record: ExternalMemoryAnalysisRecord
    workflow: ResearchWorkflow
    retrieval: ReviewedMemoryRetrievalResult | None
    artifacts: tuple[StoredArtifact, ...]
    tool_calls: tuple[JsonObject, ...]
    model_calls: tuple[ExternalModelCallRecord, ...]
    audit_valid: bool
    audit_event_count: int
    audit_last_event_hash: str | None
    audit_errors: tuple[str, ...]
    binding_errors: tuple[str, ...]
    expected_current_evidence_count: int
    reused: bool

    @property
    def binding_validity(self) -> str:
        return "valid" if not self.binding_errors else "invalidated_by_drift"

    @property
    def current_evidence_reads_complete(self) -> bool:
        if self.expected_current_evidence_count <= 0:
            return False
        expected_total = self.expected_current_evidence_count * len(
            EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS
        )
        completed = [
            item
            for item in self.tool_calls
            if item.get("status") == ToolCallStatus.COMPLETED.value
        ]
        return len(completed) == expected_total and len(completed) == len(
            self.tool_calls
        )

    @property
    def replay_valid(self) -> bool:
        return (
            self.workflow.status == WorkflowStatus.COMPLETED
            and self.binding_validity == "valid"
            and self.current_evidence_reads_complete
            and self.audit_valid
        )

    def replay(self) -> ExternalMemoryAnalysisReplay:
        errors = list(self.binding_errors)
        errors.extend(self.audit_errors)
        if self.workflow.status != WorkflowStatus.COMPLETED:
            errors.append(f"workflow_not_completed:{self.workflow.status.value}")
        if not self.current_evidence_reads_complete:
            errors.append("current_evidence_reads_incomplete")
        return ExternalMemoryAnalysisReplay(
            analysis_id=self.record.analysis_id,
            workflow_id=self.record.workflow_id,
            valid=self.replay_valid,
            workflow_status=self.workflow.status,
            binding_validity=self.binding_validity,
            current_evidence_reads_complete=self.current_evidence_reads_complete,
            model_call_count=len(self.model_calls),
            audit_event_count=self.audit_event_count,
            last_event_hash=self.audit_last_event_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    def to_dict(self) -> JsonObject:
        retrieval = self.retrieval
        return {
            "schema_version": EXTERNAL_MEMORY_ANALYSIS_CONTRACT_VERSION,
            "analysis_id": self.record.analysis_id,
            "retrieval_id": self.record.request.retrieval_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "partial_result": self.workflow.partial_result,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "valuation_snapshot_id": (
                retrieval.current_target.valuation_snapshot_id if retrieval else None
            ),
            "ledger_cutoff_id": (
                retrieval.current_target.ledger_cutoff_id if retrieval else None
            ),
            "ledger_fingerprint": (
                retrieval.current_target.ledger_fingerprint if retrieval else None
            ),
            "stored_retrieval_target_fingerprint": (
                self.record.retrieval_target_fingerprint
            ),
            "current_retrieval_target_fingerprint": (
                retrieval.current_target.fingerprint if retrieval else None
            ),
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "current_evidence_reads_complete": self.current_evidence_reads_complete,
            "expected_current_evidence_count": self.expected_current_evidence_count,
            "current_evidence_read_count": sum(
                item.get("status") == ToolCallStatus.COMPLETED.value
                for item in self.tool_calls
            ),
            "artifacts": [_artifact_payload(item) for item in self.artifacts],
            "tool_calls": [dict(item) for item in self.tool_calls],
            "model_calls": [item.to_dict() for item in self.model_calls],
            "audit_replay": {
                "valid": self.audit_valid,
                "event_count": self.audit_event_count,
                "last_event_hash": self.audit_last_event_hash,
                "errors": list(self.audit_errors),
            },
            "requested_by": self.record.request.requested_by,
            "research_question": self.record.request.research_question,
            "created_at": self.record.created_at,
            "reused": self.reused,
            "provider_id": self.record.provider_id,
            "model_id": self.record.model_id,
            "endpoint_origin": self.record.endpoint_origin,
            "prompt_version": self.record.prompt_version,
            "external_model_invocation_count": len(self.model_calls),
            "external_context_scope": (
                "selected_reviewed_memory_and_bound_current_canonical_evidence"
            ),
            "explicit_financial_evidence_export_confirmed": True,
            "account_alias_sent": False,
            "credentials_sent_as_content": False,
            "provider_side_tools_enabled": False,
            "local_read_only_tools_used": True,
            "model_reasoning_mode_preserved": True,
            "reasoning_content_persisted": False,
            "automatic_recall_enabled": False,
            "semantic_search_used": False,
            "persisted_facts_only": True,
            "memory_input_is_current_fact": False,
            "research_output_is_account_fact": False,
            "requires_human_review": True,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "memory_artifact_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


def _artifact_payload(artifact: StoredArtifact) -> JsonObject:
    return {
        "artifact_id": artifact.artifact_id,
        "stage_id": artifact.stage_id,
        "role_id": artifact.role_id,
        "kind": artifact.kind.value,
        "content": dict(artifact.content),
        "evidence_reference_ids": list(artifact.evidence_reference_ids),
        "fingerprint": artifact.fingerprint,
        "created_at": artifact.created_at,
        "authority_effect": "none",
    }
