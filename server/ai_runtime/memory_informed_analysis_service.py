"""Application service for offline memory-informed fixture analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from server.contracts.memory_informed_analysis import (
    MEMORY_INFORMED_DEFINITION_ID,
    MEMORY_INFORMED_MODEL_ID,
    MEMORY_INFORMED_PROVIDER_ID,
    MEMORY_INFORMED_TERMINAL_STATUSES,
    HumanMemoryInformedAnalysisRequest,
    MemoryInformedAnalysisRecord,
    MemoryInformedAnalysisReplay,
)

from .contracts import (
    EvidenceBoundContextSnapshot,
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    ToolCallStatus,
)
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
)
from .memory_informed_analysis_result import MemoryInformedAnalysisResult
from .memory_informed_analysis_values import (
    MemoryInformedInputs,
    load_memory_informed_current_binding_value,
    load_memory_informed_current_records_value,
    load_memory_informed_inputs_value,
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
from .orchestrator import DeterministicWorkflowOrchestrator, ToolExecutor
from .permissions import default_tool_permission_registry
from .provider import DeterministicFixtureProvider, ProviderResponse
from .registry import AiRuntimeRegistry
from .store import AiAuditStore, IdempotencyConflict


class HumanMemoryInformedFixtureAnalysisServiceBase:
    """Run reviewed memory through a current-evidence-only fixture workflow."""

    result_type = MemoryInformedAnalysisResult

    def __init__(
        self,
        *,
        retrieval_service: HumanReviewedMemoryRetrievalService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        analysis_store: Any,
        now: Callable[[], str],
        fixture_failures: Mapping[tuple[str, int], Exception] | None = None,
        partial_stage_id: str | None = None,
        run_lease_seconds: int = 30,
    ) -> None:
        if run_lease_seconds <= 0 or run_lease_seconds > 300:
            raise ValueError("run_lease_seconds must be within [1, 300]")
        if partial_stage_id not in {None, *self.stage_ids()}:
            raise ValueError("partial_stage_id is not a workflow stage")
        self._retrieval_service = retrieval_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._analysis_store = analysis_store
        self._now = now
        self._fixture_failures = dict(fixture_failures or {})
        self._partial_stage_id = partial_stage_id
        self._run_lease_seconds = run_lease_seconds

    def start(
        self,
        request: HumanMemoryInformedAnalysisRequest,
    ) -> MemoryInformedAnalysisResult:
        existing = self._analysis_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None and existing.request_fingerprint != request.fingerprint:
            raise IdempotencyConflict(
                "memory-informed analysis idempotency key was reused with "
                "different input"
            )
        if existing is not None:
            existing_workflow = self._ai_store.get_workflow(existing.workflow_id)
            if existing_workflow.status in MEMORY_INFORMED_TERMINAL_STATUSES:
                retrieval, records = self._current_binding(existing)
                return self._result(
                    existing,
                    workflow=existing_workflow,
                    retrieval=retrieval,
                    records=records,
                    reused=True,
                )
        inputs = self._inputs(request.retrieval_id)
        orchestrator = self._orchestrator(request=request, inputs=inputs)
        workflow = orchestrator.create_workflow(
            definition=self.workflow_definition(),
            context=inputs.context,
            idempotency_key=(
                f"memory-informed:{request.idempotency_key}:{request.fingerprint}"
            ),
        )
        record, reused = self._analysis_store.create_or_get(
            request=request,
            workflow_id=workflow.workflow_id,
            context=inputs.context,
            retrieval_target_fingerprint=inputs.retrieval.current_target.fingerprint,
            created_at=self._now(),
        )
        if workflow.status not in MEMORY_INFORMED_TERMINAL_STATUSES:
            claimed_at = self._now()
            claimed = self._analysis_store.claim_run(
                record.analysis_id,
                claimed_at=claimed_at,
                expires_at=self.lease_expiry(
                    claimed_at,
                    self._run_lease_seconds,
                ),
            )
            if claimed:
                workflow = orchestrator.run(
                    workflow.workflow_id,
                    current_context=inputs.context,
                )
            else:
                workflow = self._ai_store.get_workflow(workflow.workflow_id)
        return self._result(
            record,
            workflow=workflow,
            retrieval=inputs.retrieval,
            records=inputs.records,
            reused=reused or existing is not None,
        )

    def get(self, analysis_id: str) -> MemoryInformedAnalysisResult:
        record = self._analysis_store.get(analysis_id)
        workflow = self._ai_store.get_workflow(record.workflow_id)
        retrieval, records = self._current_binding(record)
        return self._result(
            record,
            workflow=workflow,
            retrieval=retrieval,
            records=records,
            reused=True,
        )

    def list(self, *, limit: int = 50) -> tuple[MemoryInformedAnalysisResult, ...]:
        return tuple(
            self.get(record.analysis_id)
            for record in self._analysis_store.list(limit=limit)
        )

    def replay(self, analysis_id: str) -> MemoryInformedAnalysisReplay:
        return self.get(analysis_id).replay()

    def _inputs(self, retrieval_id: str) -> MemoryInformedInputs:
        return self.load_inputs(
            retrieval_service=self._retrieval_service,
            ai_store=self._ai_store,
            evidence_repository=self._evidence_repository,
            retrieval_id=retrieval_id,
        )

    def _current_binding(
        self,
        record: MemoryInformedAnalysisRecord,
    ) -> tuple[
        ReviewedMemoryRetrievalResult | None,
        tuple[CanonicalEvidenceRecord, ...],
    ]:
        return self.load_current_binding(
            retrieval_service=self._retrieval_service,
            ai_store=self._ai_store,
            evidence_repository=self._evidence_repository,
            retrieval_id=record.request.retrieval_id,
            context_snapshot_id=record.context_snapshot_id,
        )

    def _current_records(
        self,
        context: EvidenceBoundContextSnapshot,
    ) -> tuple[CanonicalEvidenceRecord, ...]:
        return self.load_current_records(
            evidence_repository=self._evidence_repository,
            context=context,
        )

    def _orchestrator(
        self,
        *,
        request: HumanMemoryInformedAnalysisRequest,
        inputs: MemoryInformedInputs,
    ) -> DeterministicWorkflowOrchestrator:
        registry = AiRuntimeRegistry(self._ai_store)
        self.register_runtime(registry)
        provider = DeterministicFixtureProvider(
            provider_id=MEMORY_INFORMED_PROVIDER_ID,
            responses=self.fixture_responses(
                request=request,
                inputs=inputs,
                partial_stage_id=self._partial_stage_id,
            ),
            failures=self._fixture_failures,
        )
        return DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={MEMORY_INFORMED_PROVIDER_ID: provider},
            tool_executors=cast(
                Mapping[str, ToolExecutor],
                CanonicalEvidenceToolExecutors(self._evidence_repository).as_mapping(),
            ),
            now=self._now,
            max_provider_turns=2,
        )

    def _result(
        self,
        record: MemoryInformedAnalysisRecord,
        *,
        workflow: ResearchWorkflow,
        retrieval: ReviewedMemoryRetrievalResult | None,
        records: tuple[CanonicalEvidenceRecord, ...],
        reused: bool,
    ) -> MemoryInformedAnalysisResult:
        artifacts = self._ai_store.list_artifacts(workflow.workflow_id)
        calls = self._ai_store.list_tool_calls(workflow.workflow_id)
        tool_calls = tuple(
            {
                "call_id": item.call_id,
                "run_id": item.run_id,
                "stage_id": item.stage_id,
                "role_id": item.role_id,
                "tool_name": item.tool_name,
                "status": item.status.value,
                "evidence_reference_id": item.arguments.get("evidence_reference_id"),
                "denial_reason": item.denial_reason,
            }
            for item in calls
        )
        audit = self._ai_store.verify_replay(workflow.workflow_id)
        errors = self.binding_errors(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            records=records,
            artifacts=artifacts,
            tool_calls=tool_calls,
            audit_valid=audit.valid,
        )
        return self.result_type(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            artifacts=artifacts,
            tool_calls=tool_calls,
            audit_valid=audit.valid,
            audit_event_count=audit.event_count,
            audit_last_event_hash=audit.last_event_hash,
            audit_errors=audit.errors,
            binding_errors=errors,
            expected_current_evidence_count=len(records),
            fixture_stage_run_count=len(
                self._ai_store.list_agent_runs(workflow.workflow_id)
            ),
            reused=reused,
        )

    @staticmethod
    def stage_ids() -> tuple[str, ...]:
        return memory_informed_stage_ids()

    @staticmethod
    def workflow_definition() -> Any:
        return memory_informed_workflow_definition()

    @staticmethod
    def register_runtime(registry: AiRuntimeRegistry) -> None:
        register_memory_informed_runtime(registry)

    @staticmethod
    def fixture_responses(
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

    @staticmethod
    def load_inputs(**kwargs: Any) -> MemoryInformedInputs:
        return load_memory_informed_inputs_value(**kwargs)

    @staticmethod
    def load_current_binding(**kwargs: Any) -> tuple[
        ReviewedMemoryRetrievalResult | None,
        tuple[CanonicalEvidenceRecord, ...],
    ]:
        return load_memory_informed_current_binding_value(**kwargs)

    @staticmethod
    def load_current_records(**kwargs: Any) -> tuple[CanonicalEvidenceRecord, ...]:
        return load_memory_informed_current_records_value(**kwargs)

    @staticmethod
    def binding_errors(**kwargs: Any) -> tuple[str, ...]:
        return memory_informed_binding_errors(**kwargs)

    @staticmethod
    def lease_expiry(claimed_at: str, seconds: int) -> str:
        return memory_informed_lease_expiry(claimed_at, seconds)
