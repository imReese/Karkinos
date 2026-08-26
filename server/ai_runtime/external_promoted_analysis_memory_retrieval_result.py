"""Read projection for explicit promoted-analysis memory retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from server.contracts.external_promoted_analysis_memory_retrieval import (
    EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION,
    ExternalPromotedAnalysisMemoryRetrievalAuditReplay,
    ExternalPromotedAnalysisMemoryRetrievalReplay,
    ExternalPromotedAnalysisMemoryRetrievalTarget,
    StoredExternalPromotedAnalysisMemoryRetrieval,
)

from .contracts import JsonObject


@dataclass(frozen=True)
class ExternalPromotedAnalysisMemoryRetrievalResult:
    stored: StoredExternalPromotedAnalysisMemoryRetrieval
    current_target: ExternalPromotedAnalysisMemoryRetrievalTarget
    audit_replay: ExternalPromotedAnalysisMemoryRetrievalAuditReplay
    reused: bool

    @property
    def request_binding_valid(self) -> bool:
        return (
            self.stored.request_fingerprint == self.stored.request.fingerprint
            and self.stored.stored_idempotency_key
            == self.stored.request.idempotency_key
            and self.stored.stored_current_context_snapshot_id
            == self.stored.request.current_context_snapshot_id
        )

    @property
    def target_binding_valid(self) -> bool:
        return (
            self.stored.retrieval_target_fingerprint == self.current_target.fingerprint
        )

    @property
    def retrieval_eligible(self) -> bool:
        return (
            self.request_binding_valid
            and self.target_binding_valid
            and self.current_target.eligible
            and self.audit_replay.valid
        )

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.request_binding_valid:
            reasons.append("promoted_analysis_memory_retrieval_request_binding_drift")
        if not self.target_binding_valid:
            reasons.append("promoted_analysis_memory_retrieval_target_binding_drift")
        reasons.extend(self.current_target.errors)
        reasons.extend(self.audit_replay.errors)
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ExternalPromotedAnalysisMemoryRetrievalReplay:
        return ExternalPromotedAnalysisMemoryRetrievalReplay(
            retrieval_id=self.stored.retrieval_id,
            valid=self.retrieval_eligible,
            retrieval_eligible=self.retrieval_eligible,
            request_binding_valid=self.request_binding_valid,
            target_binding_valid=self.target_binding_valid,
            event_chain_valid=self.audit_replay.valid,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        target = self.current_target
        return {
            "schema_version": (
                EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_CONTRACT_VERSION
            ),
            "retrieval_id": self.stored.retrieval_id,
            "requested_by": self.stored.request.requested_by,
            "purpose": self.stored.request.purpose,
            "promotion_ids": list(self.stored.request.promotion_ids),
            "current_context_snapshot_id": target.current_context_snapshot_id,
            "current_context_fingerprint": target.current_context_fingerprint,
            "valuation_snapshot_id": target.valuation_snapshot_id,
            "ledger_cutoff_id": target.ledger_cutoff_id,
            "ledger_fingerprint": target.ledger_fingerprint,
            "stored_retrieval_target_fingerprint": (
                self.stored.retrieval_target_fingerprint
            ),
            "current_retrieval_target_fingerprint": target.fingerprint,
            "request_binding_valid": self.request_binding_valid,
            "target_binding_valid": self.target_binding_valid,
            "retrieval_eligible": self.retrieval_eligible,
            "status": (
                "ready_for_evidence_bound_research_context"
                if self.retrieval_eligible
                else "invalidated"
            ),
            "invalidation_reasons": list(self.invalidation_reasons),
            "selected_memories": (
                [item.to_dict() for item in target.selections]
                if self.retrieval_eligible
                else []
            ),
            "selected_memory_count": (
                len(target.selections) if self.retrieval_eligible else 0
            ),
            "created_at": self.stored.created_at,
            "reused": self.reused,
            "explicit_human_start_required": True,
            "automatic_recall_enabled": False,
            "semantic_search_used": False,
            "phase_1_8_retrieval_modified": False,
            "phase_1_13_retrieval_modified": False,
            "external_model_consumption_enabled": False,
            "provider_tool_registered": False,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "persisted_facts_only": True,
            "memory_is_account_fact": False,
            "current_evidence_must_be_read": True,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }
