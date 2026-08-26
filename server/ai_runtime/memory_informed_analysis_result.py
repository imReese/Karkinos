"""Replay-safe result projection for memory-informed fixture analysis."""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts.memory_informed_analysis import (
    MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION,
    MEMORY_INFORMED_MODEL_ID,
    MEMORY_INFORMED_PROVIDER_ID,
    MemoryInformedAnalysisRecord,
    MemoryInformedAnalysisReplay,
)

from .contracts import (
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    ToolCallStatus,
    WorkflowStatus,
)
from .memory_informed_analysis_values import memory_informed_artifact_payload
from .memory_retrieval import ReviewedMemoryRetrievalResult


@dataclass(frozen=True)
class MemoryInformedAnalysisResult:
    record: MemoryInformedAnalysisRecord
    workflow: ResearchWorkflow
    retrieval: ReviewedMemoryRetrievalResult | None
    artifacts: tuple[StoredArtifact, ...]
    tool_calls: tuple[JsonObject, ...]
    audit_valid: bool
    audit_event_count: int
    audit_last_event_hash: str | None
    audit_errors: tuple[str, ...]
    binding_errors: tuple[str, ...]
    expected_current_evidence_count: int
    fixture_stage_run_count: int
    reused: bool

    @property
    def binding_validity(self) -> str:
        return "valid" if not self.binding_errors else "invalidated_by_drift"

    @property
    def current_evidence_reads_complete(self) -> bool:
        completed = [
            item
            for item in self.tool_calls
            if item.get("status") == ToolCallStatus.COMPLETED.value
        ]
        return len(completed) == self.expected_current_evidence_count and len(
            completed
        ) == len(self.tool_calls)

    @property
    def replay_valid(self) -> bool:
        return (
            self.workflow.status == WorkflowStatus.COMPLETED
            and self.binding_validity == "valid"
            and self.current_evidence_reads_complete
            and self.audit_valid
        )

    def replay(self) -> MemoryInformedAnalysisReplay:
        errors = list(self.binding_errors)
        errors.extend(self.audit_errors)
        if self.workflow.status != WorkflowStatus.COMPLETED:
            errors.append(f"workflow_not_completed:{self.workflow.status.value}")
        if not self.current_evidence_reads_complete:
            errors.append("current_evidence_reads_incomplete")
        return MemoryInformedAnalysisReplay(
            analysis_id=self.record.analysis_id,
            workflow_id=self.record.workflow_id,
            valid=self.replay_valid,
            workflow_status=self.workflow.status,
            binding_validity=self.binding_validity,
            current_evidence_reads_complete=self.current_evidence_reads_complete,
            audit_event_count=self.audit_event_count,
            last_event_hash=self.audit_last_event_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def artifact_payload(artifact: StoredArtifact) -> JsonObject:
        return memory_informed_artifact_payload(artifact)

    def to_dict(self) -> JsonObject:
        retrieval_payload = self.retrieval.to_dict() if self.retrieval else None
        return {
            "schema_version": MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION,
            "analysis_id": self.record.analysis_id,
            "retrieval_id": self.record.request.retrieval_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "partial_result": self.workflow.partial_result,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "valuation_snapshot_id": (
                retrieval_payload.get("valuation_snapshot_id")
                if retrieval_payload
                else None
            ),
            "ledger_cutoff_id": (
                retrieval_payload.get("ledger_cutoff_id") if retrieval_payload else None
            ),
            "ledger_fingerprint": (
                retrieval_payload.get("ledger_fingerprint")
                if retrieval_payload
                else None
            ),
            "stored_retrieval_target_fingerprint": (
                self.record.retrieval_target_fingerprint
            ),
            "current_retrieval_target_fingerprint": (
                self.retrieval.current_target.fingerprint if self.retrieval else None
            ),
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "current_evidence_reads_complete": self.current_evidence_reads_complete,
            "expected_current_evidence_count": self.expected_current_evidence_count,
            "current_evidence_read_count": sum(
                item.get("status") == ToolCallStatus.COMPLETED.value
                for item in self.tool_calls
            ),
            "artifacts": [self.artifact_payload(item) for item in self.artifacts],
            "tool_calls": [dict(item) for item in self.tool_calls],
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
            "provider_id": MEMORY_INFORMED_PROVIDER_ID,
            "model_id": MEMORY_INFORMED_MODEL_ID,
            "fixture_only": True,
            "fixture_stage_run_count": self.fixture_stage_run_count,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "real_provider_registered": False,
            "provider_side_tools_enabled": False,
            "retrieval_tool_registered": False,
            "automatic_recall_enabled": False,
            "semantic_search_used": False,
            "persisted_facts_only": True,
            "memory_input_is_current_fact": False,
            "current_evidence_was_independently_read": (
                self.current_evidence_reads_complete
            ),
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "memory_artifact_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }
