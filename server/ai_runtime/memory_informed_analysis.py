"""Offline analysis of reviewed memory against current canonical evidence.

This compatibility façade preserves the Phase 1 public API and patch seams.
Contracts, result projection, workflow assembly, business orchestration, and
SQLite persistence have explicit owners. The workflow remains deterministic,
provider-free, non-authoritative, and unable to grant financial authority.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.contracts.memory_informed_analysis import (
    MEMORY_INFORMED_ANALYSIS_CONFIRMATION,
    MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION,
    MEMORY_INFORMED_CLAIM_ROLE_ID,
    MEMORY_INFORMED_CLAIM_STAGE_ID,
    MEMORY_INFORMED_DEBATE_ROLE_ID,
    MEMORY_INFORMED_DEBATE_STAGE_ID,
    MEMORY_INFORMED_DEFINITION_ID,
    MEMORY_INFORMED_MODEL_ID,
    MEMORY_INFORMED_PROVIDER_ID,
    MEMORY_INFORMED_REPORT_ROLE_ID,
    MEMORY_INFORMED_REPORT_STAGE_ID,
    MEMORY_INFORMED_TERMINAL_STATUSES,
    HumanMemoryInformedAnalysisRequest,
    MemoryInformedAnalysisRecord,
    MemoryInformedAnalysisRejected,
    MemoryInformedAnalysisReplay,
)
from server.persistence.memory_informed_analysis_projection import (
    memory_informed_analysis_record_from_row,
)
from server.persistence.memory_informed_analysis_repository import (
    MemoryInformedAnalysisRepositoryMixin,
)
from server.persistence.memory_informed_analysis_schema import (
    MEMORY_INFORMED_ANALYSIS_SCHEMA,
    MemoryInformedAnalysisSchemaMixin,
)
from server.persistence.memory_informed_analysis_uow import (
    MemoryInformedAnalysisUnitOfWorkMixin,
)

from .contracts import (
    EvidenceBoundContextSnapshot,
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    WorkflowDefinition,
)
from .evidence import CanonicalEvidenceRecord, CanonicalEvidenceRepository
from .memory_informed_analysis_result import (
    MemoryInformedAnalysisResult as MemoryInformedAnalysisResultBase,
)
from .memory_informed_analysis_service import (
    HumanMemoryInformedFixtureAnalysisServiceBase,
)
from .memory_informed_analysis_values import (
    MemoryInformedInputs,
    load_memory_informed_current_binding_value,
    load_memory_informed_current_records_value,
    load_memory_informed_inputs_value,
    memory_informed_artifact_payload,
    memory_informed_binding_errors,
    memory_informed_lease_expiry,
)
from .memory_informed_analysis_workflow import (
    memory_informed_fixture_responses,
    memory_informed_stage_ids,
    memory_informed_workflow_definition,
    register_memory_informed_runtime,
)
from .memory_retrieval import (
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalResult,
)
from .provider import ProviderResponse
from .registry import AiRuntimeRegistry
from .store import AiAuditStore

_CLAIM_STAGE_ID = MEMORY_INFORMED_CLAIM_STAGE_ID
_DEBATE_STAGE_ID = MEMORY_INFORMED_DEBATE_STAGE_ID
_REPORT_STAGE_ID = MEMORY_INFORMED_REPORT_STAGE_ID
_CLAIM_ROLE_ID = MEMORY_INFORMED_CLAIM_ROLE_ID
_DEBATE_ROLE_ID = MEMORY_INFORMED_DEBATE_ROLE_ID
_REPORT_ROLE_ID = MEMORY_INFORMED_REPORT_ROLE_ID
_TERMINAL_STATUSES = MEMORY_INFORMED_TERMINAL_STATUSES
_ANALYSIS_SCHEMA = MEMORY_INFORMED_ANALYSIS_SCHEMA
_AnalysisInputs = MemoryInformedInputs


class MemoryInformedAnalysisResult(MemoryInformedAnalysisResultBase):
    """Compatibility result that retains the façade artifact patch seam."""

    @staticmethod
    def artifact_payload(artifact: StoredArtifact) -> JsonObject:
        return _artifact_payload(artifact)


class MemoryInformedAnalysisStore(
    MemoryInformedAnalysisUnitOfWorkMixin,
    MemoryInformedAnalysisRepositoryMixin,
    MemoryInformedAnalysisSchemaMixin,
):
    """Idempotent retrieval-to-workflow mappings with a short run lease."""

    @staticmethod
    def _record_from_row(row: Any) -> MemoryInformedAnalysisRecord:
        return _record_from_row(row)

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def init(self) -> None:
        self._init_schema()

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MemoryInformedAnalysisRecord | None:
        return self._get_by_idempotency_key(idempotency_key)

    def create_or_get(
        self,
        *,
        request: HumanMemoryInformedAnalysisRequest,
        workflow_id: str,
        context: EvidenceBoundContextSnapshot,
        retrieval_target_fingerprint: str,
        created_at: str,
    ) -> tuple[MemoryInformedAnalysisRecord, bool]:
        return self._create_or_get(
            request=request,
            workflow_id=workflow_id,
            context=context,
            retrieval_target_fingerprint=retrieval_target_fingerprint,
            created_at=created_at,
        )

    def claim_run(
        self,
        analysis_id: str,
        *,
        claimed_at: str,
        expires_at: str,
    ) -> bool:
        return self._claim_run(
            analysis_id,
            claimed_at=claimed_at,
            expires_at=expires_at,
        )

    def get(self, analysis_id: str) -> MemoryInformedAnalysisRecord:
        return self._get(analysis_id)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[MemoryInformedAnalysisRecord, ...]:
        return self._list(limit=limit)


class HumanMemoryInformedFixtureAnalysisService(
    HumanMemoryInformedFixtureAnalysisServiceBase
):
    """Run reviewed memory through a current-evidence-only fixture workflow."""

    result_type = MemoryInformedAnalysisResult

    @staticmethod
    def stage_ids() -> tuple[str, ...]:
        return _stage_ids()

    @staticmethod
    def workflow_definition() -> WorkflowDefinition:
        return _workflow_definition()

    @staticmethod
    def register_runtime(registry: AiRuntimeRegistry) -> None:
        _register_runtime(registry)

    @staticmethod
    def fixture_responses(
        *,
        request: HumanMemoryInformedAnalysisRequest,
        inputs: MemoryInformedInputs,
        partial_stage_id: str | None,
    ) -> dict[str, tuple[ProviderResponse, ...]]:
        return _fixture_responses(
            request=request,
            inputs=inputs,
            partial_stage_id=partial_stage_id,
        )

    @staticmethod
    def load_inputs(**kwargs: Any) -> MemoryInformedInputs:
        return load_memory_informed_inputs(**kwargs)

    @staticmethod
    def load_current_binding(**kwargs: Any) -> tuple[
        ReviewedMemoryRetrievalResult | None,
        tuple[CanonicalEvidenceRecord, ...],
    ]:
        return load_memory_informed_current_binding(**kwargs)

    @staticmethod
    def load_current_records(**kwargs: Any) -> tuple[CanonicalEvidenceRecord, ...]:
        return load_memory_informed_current_records(**kwargs)

    @staticmethod
    def binding_errors(**kwargs: Any) -> tuple[str, ...]:
        return _binding_errors(**kwargs)

    @staticmethod
    def lease_expiry(claimed_at: str, seconds: int) -> str:
        return _lease_expiry(claimed_at, seconds)


def load_memory_informed_inputs(
    *,
    retrieval_service: HumanReviewedMemoryRetrievalService,
    ai_store: AiAuditStore,
    evidence_repository: CanonicalEvidenceRepository,
    retrieval_id: str,
) -> MemoryInformedInputs:
    return load_memory_informed_inputs_value(
        retrieval_service=retrieval_service,
        ai_store=ai_store,
        evidence_repository=evidence_repository,
        retrieval_id=retrieval_id,
    )


def load_memory_informed_current_binding(
    *,
    retrieval_service: HumanReviewedMemoryRetrievalService,
    ai_store: AiAuditStore,
    evidence_repository: CanonicalEvidenceRepository,
    retrieval_id: str,
    context_snapshot_id: str,
) -> tuple[
    ReviewedMemoryRetrievalResult | None,
    tuple[CanonicalEvidenceRecord, ...],
]:
    return load_memory_informed_current_binding_value(
        retrieval_service=retrieval_service,
        ai_store=ai_store,
        evidence_repository=evidence_repository,
        retrieval_id=retrieval_id,
        context_snapshot_id=context_snapshot_id,
    )


def load_memory_informed_current_records(
    *,
    evidence_repository: CanonicalEvidenceRepository,
    context: EvidenceBoundContextSnapshot,
) -> tuple[CanonicalEvidenceRecord, ...]:
    return load_memory_informed_current_records_value(
        evidence_repository=evidence_repository,
        context=context,
    )


def _workflow_definition() -> WorkflowDefinition:
    return memory_informed_workflow_definition()


def _register_runtime(registry: AiRuntimeRegistry) -> None:
    register_memory_informed_runtime(registry)


def _fixture_responses(
    *,
    request: HumanMemoryInformedAnalysisRequest,
    inputs: MemoryInformedInputs,
    partial_stage_id: str | None,
) -> dict[str, tuple[ProviderResponse, ...]]:
    return memory_informed_fixture_responses(
        request=request,
        inputs=inputs,
        partial_stage_id=partial_stage_id,
    )


def _binding_errors(
    *,
    record: MemoryInformedAnalysisRecord,
    workflow: ResearchWorkflow,
    retrieval: ReviewedMemoryRetrievalResult | None,
    records: tuple[CanonicalEvidenceRecord, ...],
    artifacts: tuple[StoredArtifact, ...],
    tool_calls: tuple[JsonObject, ...],
    audit_valid: bool,
) -> tuple[str, ...]:
    return memory_informed_binding_errors(
        record=record,
        workflow=workflow,
        retrieval=retrieval,
        records=records,
        artifacts=artifacts,
        tool_calls=tool_calls,
        audit_valid=audit_valid,
    )


def _artifact_payload(artifact: StoredArtifact) -> JsonObject:
    return memory_informed_artifact_payload(artifact)


def _stage_ids() -> tuple[str, ...]:
    return memory_informed_stage_ids()


def _lease_expiry(claimed_at: str, seconds: int) -> str:
    return memory_informed_lease_expiry(claimed_at, seconds)


def _record_from_row(row: Any) -> MemoryInformedAnalysisRecord:
    return memory_informed_analysis_record_from_row(row)


for _public_type in (
    MemoryInformedAnalysisRejected,
    HumanMemoryInformedAnalysisRequest,
    MemoryInformedAnalysisRecord,
    MemoryInformedAnalysisReplay,
    MemoryInformedAnalysisResult,
    MemoryInformedInputs,
):
    _public_type.__module__ = __name__
del _public_type
