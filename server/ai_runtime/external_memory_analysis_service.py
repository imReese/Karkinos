"""Application service orchestrating human-confirmed external memory analysis."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

from server.contracts.external_memory_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID,
    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
    EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS,
    EXTERNAL_MEMORY_TERMINAL_STATUSES,
    ExternalMemoryAnalysisRecord,
    ExternalMemoryAnalysisReplay,
    ExternalMemoryAnalysisRepository,
    ExternalModelCallRecord,
    HumanExternalMemoryAnalysisRequest,
)
from server.contracts.idempotency import IdempotencyConflict

from .contracts import (
    ArtifactKind,
    JsonObject,
    ResearchWorkflow,
    StoredArtifact,
    ToolCallStatus,
    WorkflowStatus,
    content_fingerprint,
)
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
)
from .external_memory_analysis_output import utc_now
from .external_memory_analysis_provider import (
    OpenAICompatibleMemoryInformedProvider,
)
from .external_memory_analysis_result import ExternalMemoryAnalysisResult
from .external_memory_analysis_workflow import (
    external_memory_runtime_ids,
    external_memory_workflow_definition,
    register_external_memory_runtime,
)
from .memory_informed_analysis import (
    load_memory_informed_current_binding,
    load_memory_informed_inputs,
)
from .memory_retrieval import (
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalResult,
)
from .orchestrator import DeterministicWorkflowOrchestrator
from .permissions import default_tool_permission_registry
from .provider_connectivity_contracts import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
)
from .provider_connectivity_transport import UrllibJsonTransport
from .registry import AiRuntimeRegistry
from .store import AiAuditStore


class HumanExternalMemoryAnalysisService:
    """Run one explicit, current-evidence-bound external research workflow."""

    def __init__(
        self,
        *,
        settings_loader: Callable[[], ProviderConnectivitySettings],
        retrieval_service: HumanReviewedMemoryRetrievalService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        analysis_store: ExternalMemoryAnalysisRepository,
        transport: JsonHttpTransport | None = None,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        model_timeout_seconds: float = 180.0,
    ) -> None:
        if model_timeout_seconds <= 0 or model_timeout_seconds > 300:
            raise ValueError("model_timeout_seconds must be within (0, 300]")
        self._settings_loader = settings_loader
        self._retrieval_service = retrieval_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._analysis_store = analysis_store
        self._transport = transport or UrllibJsonTransport()
        self._now = now or utc_now
        self._monotonic = monotonic or time.monotonic
        self._model_timeout_seconds = model_timeout_seconds

    def start(
        self,
        request: HumanExternalMemoryAnalysisRequest,
    ) -> ExternalMemoryAnalysisResult:
        existing = self._analysis_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None and existing.request_fingerprint != (
            request.fingerprint
        ):
            raise IdempotencyConflict(
                "external memory analysis idempotency key was reused with "
                "different input"
            )
        if existing is not None:
            workflow = self._ai_store.get_workflow(existing.workflow_id)
            if workflow.status in EXTERNAL_MEMORY_TERMINAL_STATUSES or (
                existing.run_claimed_at
            ):
                retrieval, records = self._current_binding(existing)
                return self._result(
                    existing,
                    workflow=workflow,
                    retrieval=retrieval,
                    records=records,
                    reused=True,
                )

        inputs = load_memory_informed_inputs(
            retrieval_service=self._retrieval_service,
            ai_store=self._ai_store,
            evidence_repository=self._evidence_repository,
            retrieval_id=request.retrieval_id,
        )
        settings = self._settings_loader()
        provider_id, model_id = external_memory_runtime_ids(settings)
        registry = AiRuntimeRegistry(self._ai_store)
        register_external_memory_runtime(
            registry,
            settings=settings,
            provider_id=provider_id,
            model_id=model_id,
        )
        provider = OpenAICompatibleMemoryInformedProvider(
            provider_id=provider_id,
            model_id=model_id,
            settings=settings,
            request=request,
            inputs=inputs,
            ai_store=self._ai_store,
            analysis_store=self._analysis_store,
            transport=self._transport,
            now=self._now,
            monotonic=self._monotonic,
            timeout_seconds=self._model_timeout_seconds,
        )
        orchestrator = DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={provider_id: provider},
            tool_executors=CanonicalEvidenceToolExecutors(
                self._evidence_repository
            ).as_mapping(),
            now=self._now,
            max_provider_turns=2,
        )
        workflow = orchestrator.create_workflow(
            definition=external_memory_workflow_definition(model_id),
            context=inputs.context,
            idempotency_key=(
                "external-memory:"
                f"{request.idempotency_key}:{request.fingerprint}:"
                f"{inputs.retrieval.current_target.fingerprint}:"
                f"{content_fingerprint({'provider_id': provider_id, 'model_id': model_id, 'endpoint_origin': settings.endpoint_origin})}"
            ),
        )
        record, reused = self._analysis_store.create_or_get(
            request=request,
            workflow_id=workflow.workflow_id,
            inputs=inputs,
            provider_id=provider_id,
            model_id=model_id,
            endpoint_origin=settings.endpoint_origin,
            created_at=self._now(),
        )
        claimed = self._analysis_store.claim_run(
            record.analysis_id,
            claimed_at=self._now(),
        )
        if claimed and workflow.status not in EXTERNAL_MEMORY_TERMINAL_STATUSES:
            workflow = orchestrator.run(
                workflow.workflow_id,
                current_context=inputs.context,
            )
        elif not claimed:
            workflow = self._ai_store.get_workflow(workflow.workflow_id)
        return self._result(
            record,
            workflow=workflow,
            retrieval=inputs.retrieval,
            records=inputs.records,
            reused=reused or existing is not None,
        )

    def get(self, analysis_id: str) -> ExternalMemoryAnalysisResult:
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

    def list(self, *, limit: int = 50) -> tuple[ExternalMemoryAnalysisResult, ...]:
        return tuple(
            self.get(item.analysis_id)
            for item in self._analysis_store.list(limit=limit)
        )

    def replay(self, analysis_id: str) -> ExternalMemoryAnalysisReplay:
        return self.get(analysis_id).replay()

    def _current_binding(
        self,
        record: ExternalMemoryAnalysisRecord,
    ) -> tuple[
        ReviewedMemoryRetrievalResult | None,
        tuple[CanonicalEvidenceRecord, ...],
    ]:
        return load_memory_informed_current_binding(
            retrieval_service=self._retrieval_service,
            ai_store=self._ai_store,
            evidence_repository=self._evidence_repository,
            retrieval_id=record.request.retrieval_id,
            context_snapshot_id=record.context_snapshot_id,
        )

    def _result(
        self,
        record: ExternalMemoryAnalysisRecord,
        *,
        workflow: ResearchWorkflow,
        retrieval: ReviewedMemoryRetrievalResult | None,
        records: tuple[CanonicalEvidenceRecord, ...],
        reused: bool,
    ) -> ExternalMemoryAnalysisResult:
        artifacts = self._ai_store.list_artifacts(workflow.workflow_id)
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
            for item in self._ai_store.list_tool_calls(workflow.workflow_id)
        )
        model_calls = self._analysis_store.list_model_calls(workflow.workflow_id)
        audit = self._ai_store.verify_replay(workflow.workflow_id)
        errors = external_memory_binding_errors(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            records=records,
            artifacts=artifacts,
            tool_calls=tool_calls,
            model_calls=model_calls,
            audit_valid=audit.valid,
        )
        return ExternalMemoryAnalysisResult(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            artifacts=artifacts,
            tool_calls=tool_calls,
            model_calls=model_calls,
            audit_valid=audit.valid,
            audit_event_count=audit.event_count,
            audit_last_event_hash=audit.last_event_hash,
            audit_errors=audit.errors,
            binding_errors=errors,
            expected_current_evidence_count=len(records),
            reused=reused,
        )


def external_memory_binding_errors(
    *,
    record: ExternalMemoryAnalysisRecord,
    workflow: ResearchWorkflow,
    retrieval: ReviewedMemoryRetrievalResult | None,
    records: tuple[CanonicalEvidenceRecord, ...],
    artifacts: tuple[StoredArtifact, ...],
    tool_calls: tuple[JsonObject, ...],
    model_calls: tuple[ExternalModelCallRecord, ...],
    audit_valid: bool,
) -> tuple[str, ...]:
    errors: list[str] = []
    if record.stored_retrieval_id != record.request.retrieval_id:
        errors.append("analysis_retrieval_binding_drift")
    if record.stored_idempotency_key != record.request.idempotency_key:
        errors.append("analysis_idempotency_binding_drift")
    if record.request_fingerprint != record.request.fingerprint:
        errors.append("analysis_request_fingerprint_drift")
    if record.prompt_version != EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION:
        errors.append("analysis_prompt_version_drift")
    if workflow.definition.definition_id != EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID:
        errors.append("workflow_definition_drift")
    if workflow.context_snapshot_id != record.context_snapshot_id:
        errors.append("workflow_context_snapshot_drift")
    if workflow.context_fingerprint != record.context_fingerprint:
        errors.append("workflow_context_fingerprint_drift")
    if retrieval is None:
        errors.append("retrieval_or_current_evidence_invalid")
    else:
        if not retrieval.retrieval_eligible:
            errors.append("retrieval_no_longer_eligible")
        if retrieval.current_target.fingerprint != (
            record.retrieval_target_fingerprint
        ):
            errors.append("retrieval_target_fingerprint_drift")
        if retrieval.current_target.current_context_snapshot_id != (
            record.context_snapshot_id
        ):
            errors.append("retrieval_context_snapshot_drift")
        if retrieval.current_target.current_context_fingerprint != (
            record.context_fingerprint
        ):
            errors.append("retrieval_context_fingerprint_drift")
    if not audit_valid:
        errors.append("workflow_audit_invalid")

    expected_reads = {
        (stage_id, item.tool_name, item.reference_id)
        for stage_id in EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS
        for item in records
    }
    actual_reads = {
        (
            str(item.get("stage_id")),
            str(item.get("tool_name")),
            str(item.get("evidence_reference_id")),
        )
        for item in tool_calls
        if item.get("status") == ToolCallStatus.COMPLETED.value
    }
    if actual_reads != expected_reads or len(tool_calls) != len(expected_reads):
        errors.append("current_evidence_tool_read_set_incomplete")
    if any(
        item.get("stage_id") not in EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS
        or item.get("status") != ToolCallStatus.COMPLETED.value
        for item in tool_calls
    ):
        errors.append("current_evidence_tool_call_invalid")

    expected_reference_ids = tuple(item.reference_id for item in records)
    for artifact in artifacts:
        actual_fingerprint = content_fingerprint(
            {
                "workflow_id": artifact.workflow_id,
                "run_id": artifact.run_id,
                "stage_id": artifact.stage_id,
                "role_id": artifact.role_id,
                "kind": artifact.kind.value,
                "content": dict(artifact.content),
                "evidence_reference_ids": list(artifact.evidence_reference_ids),
            }
        )
        if actual_fingerprint != artifact.fingerprint:
            errors.append(f"artifact_fingerprint_drift:{artifact.artifact_id}")
        if tuple(artifact.evidence_reference_ids) != expected_reference_ids:
            errors.append(f"artifact_current_evidence_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_id") != record.request.retrieval_id:
            errors.append(f"artifact_retrieval_binding_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_target_fingerprint") != (
            record.retrieval_target_fingerprint
        ):
            errors.append(f"artifact_retrieval_target_drift:{artifact.artifact_id}")
        if artifact.content.get("memory_input_is_current_fact") is not False:
            errors.append(f"artifact_promotes_memory_to_fact:{artifact.artifact_id}")
        if artifact.content.get("authority_effect") != "none":
            errors.append(f"artifact_authority_effect_drift:{artifact.artifact_id}")
        provenance = artifact.content.get("provider_provenance")
        if not isinstance(provenance, Mapping):
            errors.append(
                f"artifact_provider_provenance_missing:{artifact.artifact_id}"
            )
        elif (
            provenance.get("provider_id") != record.provider_id
            or provenance.get("model_id") != record.model_id
            or provenance.get("prompt_version") != record.prompt_version
            or provenance.get("reasoning_content_persisted") is not False
        ):
            errors.append(f"artifact_provider_binding_drift:{artifact.artifact_id}")

    if workflow.status == WorkflowStatus.COMPLETED:
        if tuple(item.kind for item in artifacts) != (
            ArtifactKind.CLAIM,
            ArtifactKind.DEBATE,
            ArtifactKind.REPORT,
        ):
            errors.append("analysis_artifact_lifecycle_incomplete")
        if tuple(item.stage_id for item in model_calls) != (
            EXTERNAL_MEMORY_ANALYSIS_STAGE_IDS
        ):
            errors.append("external_model_call_lifecycle_incomplete")
        if any(item.status != "completed" for item in model_calls):
            errors.append("external_model_call_not_completed")
    for call in model_calls:
        if (
            call.provider_id != record.provider_id
            or call.model_id != record.model_id
            or call.prompt_version != record.prompt_version
        ):
            errors.append(f"external_model_call_binding_drift:{call.stage_id}")
    return tuple(dict.fromkeys(errors))
