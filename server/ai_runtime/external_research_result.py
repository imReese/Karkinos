"""Application result projection for an external backtest evidence report."""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts.external_research import (
    EXTERNAL_BACKTEST_REPORT_CONTRACT,
    ExternalBacktestReportRecord,
)

from .contracts import JsonObject, ResearchWorkflow, StoredArtifact
from .store import AuditReplayResult


@dataclass(frozen=True)
class ExternalBacktestReportResult:
    record: ExternalBacktestReportRecord
    workflow: ResearchWorkflow
    report: StoredArtifact | None
    tool_calls: tuple[JsonObject, ...]
    audit_replay: AuditReplayResult
    binding_validity: str
    binding_errors: tuple[str, ...]
    external_model_stage_run_count: int
    reused: bool

    def to_dict(self) -> JsonObject:
        report_payload = None
        if self.report is not None:
            report_payload = {
                "artifact_id": self.report.artifact_id,
                "kind": self.report.kind.value,
                "content": dict(self.report.content),
                "evidence_reference_ids": list(self.report.evidence_reference_ids),
                "fingerprint": self.report.fingerprint,
                "created_at": self.report.created_at,
            }
        return {
            "schema_version": EXTERNAL_BACKTEST_REPORT_CONTRACT,
            "analysis_id": self.record.analysis_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "backtest_result_id": self.record.backtest_result_id,
            "capture_id": self.record.capture_id,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "evidence_reference_id": self.record.evidence_reference_id,
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "report": report_payload,
            "tool_calls": [dict(item) for item in self.tool_calls],
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "provider_id": self.record.provider_id,
            "model_id": self.record.model_id,
            "prompt_version": self.record.prompt_version,
            "requested_by": self.record.requested_by,
            "created_at": self.record.created_at,
            "reused": self.reused,
            "external_model_used": self.external_model_stage_run_count > 0,
            "external_model_stage_run_count": self.external_model_stage_run_count,
            "external_context_scope": "saved_backtest_research_evidence_only",
            "account_holdings_sent": False,
            "market_or_broker_provider_fetch_used": False,
            "provider_side_tools_enabled": False,
            "research_output_is_account_fact": False,
            "decision_input_created": False,
            "trade_plan_created": False,
            "memory_created": False,
            "authority_effect": "none",
            "oms_write_count": 0,
            "ledger_write_count": 0,
            "risk_decision_write_count": 0,
            "capital_authority_write_count": 0,
            "broker_action_count": 0,
        }


__all__ = ["ExternalBacktestReportResult"]
