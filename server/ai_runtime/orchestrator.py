"""Deterministic, restartable orchestration for non-executing AI research."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from .contracts import (
    AgentRole,
    AgentRunStatus,
    ArtifactDraft,
    ArtifactKind,
    EvidenceBoundContextSnapshot,
    JsonObject,
    ResearchWorkflow,
    ToolCall,
    ToolCallStatus,
    ToolExecutionResult,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
    content_fingerprint,
)
from .permissions import ToolEffect, ToolPermissionRegistry
from .provider import ProviderAdapter, ProviderRequest, ProviderResponse
from .registry import AiRuntimeRegistry
from .store import AiAuditStore


class ToolExecutor(Protocol):
    def __call__(
        self,
        arguments: JsonObject,
        context: EvidenceBoundContextSnapshot,
    ) -> JsonObject: ...


class WorkflowValidationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_TERMINAL_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}


class DeterministicWorkflowOrchestrator:
    """Run a persisted workflow with explicit identities and fail-closed tools."""

    def __init__(
        self,
        *,
        store: AiAuditStore,
        registry: AiRuntimeRegistry,
        permissions: ToolPermissionRegistry,
        providers: Mapping[str, ProviderAdapter],
        tool_executors: Mapping[str, ToolExecutor] | None = None,
        now: Callable[[], str] = _utc_now,
        max_provider_turns: int = 8,
    ) -> None:
        if max_provider_turns <= 0:
            raise ValueError("max_provider_turns must be positive")
        self._store = store
        self._registry = registry
        self._permissions = permissions
        self._providers = dict(providers)
        self._tool_executors = dict(tool_executors or {})
        self._now = now
        self._max_provider_turns = max_provider_turns

    def create_workflow(
        self,
        *,
        definition: WorkflowDefinition,
        context: EvidenceBoundContextSnapshot,
        idempotency_key: str,
    ) -> ResearchWorkflow:
        self._validate_definition(definition)
        created_at = self._now()
        workflow, reused = self._store.create_or_get_workflow(
            definition=definition,
            context=context,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        if not reused:
            self._store.append_event(
                workflow.workflow_id,
                event_type="workflow.created",
                payload={
                    "definition_id": definition.definition_id,
                    "definition_fingerprint": definition.fingerprint,
                    "context_snapshot_id": context.snapshot_id,
                    "context_fingerprint": context.fingerprint,
                    "valuation_snapshot_id": context.valuation_snapshot_id,
                    "ledger_cutoff_id": context.ledger_cutoff_id,
                    "persisted_facts_only": True,
                },
                created_at=created_at,
            )
        return workflow

    def run(
        self,
        workflow_id: str,
        *,
        current_context: EvidenceBoundContextSnapshot | None = None,
        max_stages: int | None = None,
    ) -> ResearchWorkflow:
        if max_stages is not None and max_stages <= 0:
            raise ValueError("max_stages must be positive when present")
        workflow = self._store.get_workflow(workflow_id)
        if workflow.status in _TERMINAL_STATUSES:
            return workflow
        context = current_context or self._store.get_context(
            workflow.context_snapshot_id
        )
        if (
            context.snapshot_id != workflow.context_snapshot_id
            or context.fingerprint != workflow.context_fingerprint
        ):
            return self._block_evidence_drift(workflow, context)

        event_type = (
            "workflow.started"
            if workflow.status == WorkflowStatus.PENDING
            else "workflow.resumed"
        )
        now = self._now()
        workflow = self._store.update_workflow(
            workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            current_stage_index=workflow.current_stage_index,
            partial_result=workflow.partial_result,
            failure_code=None,
            updated_at=now,
        )
        self._store.append_event(
            workflow.workflow_id,
            event_type=event_type,
            payload={"current_stage_index": workflow.current_stage_index},
            created_at=now,
        )

        processed = 0
        while workflow.current_stage_index < len(workflow.definition.stages):
            if max_stages is not None and processed >= max_stages:
                return workflow
            workflow = self._run_stage(workflow, context)
            if workflow.status in _TERMINAL_STATUSES:
                return workflow
            processed += 1

        completed_at = self._now()
        workflow = self._store.update_workflow(
            workflow.workflow_id,
            status=WorkflowStatus.COMPLETED,
            current_stage_index=len(workflow.definition.stages),
            partial_result=False,
            failure_code=None,
            updated_at=completed_at,
        )
        self._store.append_event(
            workflow.workflow_id,
            event_type="workflow.completed",
            payload={"stage_count": len(workflow.definition.stages)},
            created_at=completed_at,
        )
        return workflow

    def _validate_definition(self, definition: WorkflowDefinition) -> None:
        for stage in definition.stages:
            role = self._registry.require_role(stage.role_id)
            model = self._registry.require_model(stage.model_id)
            provider = self._registry.require_provider(model.provider_id)
            adapter = self._providers.get(provider.provider_id)
            if adapter is None:
                raise WorkflowValidationError(
                    f"provider adapter is not bound: {provider.provider_id}"
                )
            if adapter.provider_id != provider.provider_id:
                raise WorkflowValidationError("provider adapter identity mismatch")
            if stage.output_kind not in role.allowed_artifact_kinds:
                raise WorkflowValidationError(
                    f"role {role.role_id} cannot produce {stage.output_kind.value}"
                )
            unknown_tools = set(role.allowed_tools) - set(self._permissions.tool_names)
            if unknown_tools:
                raise WorkflowValidationError(
                    f"role {role.role_id} names unregistered tools: "
                    f"{sorted(unknown_tools)}"
                )

    def _run_stage(
        self,
        workflow: ResearchWorkflow,
        context: EvidenceBoundContextSnapshot,
    ) -> ResearchWorkflow:
        stage = workflow.definition.stages[workflow.current_stage_index]
        role = self._registry.require_role(stage.role_id)
        model = self._registry.require_model(stage.model_id)
        provider = self._registry.require_provider(model.provider_id)
        adapter = self._providers[provider.provider_id]
        input_artifact_ids = tuple(
            artifact.artifact_id
            for artifact in self._store.list_artifacts(workflow.workflow_id)
        )
        initial_request = ProviderRequest(
            workflow_id=workflow.workflow_id,
            stage_id=stage.stage_id,
            role_id=role.role_id,
            model_id=model.model_id,
            context_snapshot_id=context.snapshot_id,
            context_fingerprint=context.fingerprint,
            input_artifact_ids=input_artifact_ids,
            tool_results=(),
            turn_index=0,
        )
        run_id = f"ai-run-{content_fingerprint({'workflow_id': workflow.workflow_id, 'stage_id': stage.stage_id})[:24]}"
        started_at = self._now()
        agent_run = self._store.start_agent_run(
            run_id=run_id,
            workflow_id=workflow.workflow_id,
            stage_id=stage.stage_id,
            role_id=role.role_id,
            model_id=model.model_id,
            provider_id=provider.provider_id,
            request=initial_request.to_dict(),
            started_at=started_at,
        )
        if agent_run.status != AgentRunStatus.RUNNING:
            return self._fail_stage(
                workflow,
                run_id=run_id,
                stage_id=stage.stage_id,
                failure_code="non_resumable_agent_run_state",
                response=None,
            )
        self._store.append_event(
            workflow.workflow_id,
            event_type="stage.started",
            payload={
                "stage_id": stage.stage_id,
                "run_id": run_id,
                "role_id": role.role_id,
                "model_id": model.model_id,
                "provider_id": provider.provider_id,
            },
            created_at=started_at,
        )

        tool_results: list[ToolExecutionResult] = []
        response_history: list[JsonObject] = []
        seen_request_ids: set[str] = set()
        final_response: ProviderResponse | None = None
        try:
            for turn_index in range(self._max_provider_turns):
                request = ProviderRequest(
                    workflow_id=workflow.workflow_id,
                    stage_id=stage.stage_id,
                    role_id=role.role_id,
                    model_id=model.model_id,
                    context_snapshot_id=context.snapshot_id,
                    context_fingerprint=context.fingerprint,
                    input_artifact_ids=input_artifact_ids,
                    tool_results=tuple(tool_results),
                    turn_index=turn_index,
                )
                response = adapter.invoke(request)
                response_history.append(response.to_dict())
                if response.tool_requests and response.artifacts:
                    raise WorkflowValidationError(
                        "provider turn cannot request tools and finalize artifacts together"
                    )
                if response.tool_requests:
                    for tool_request in response.tool_requests:
                        if tool_request.request_id in seen_request_ids:
                            raise WorkflowValidationError(
                                f"duplicate tool request id: {tool_request.request_id}"
                            )
                        seen_request_ids.add(tool_request.request_id)
                        result = self._execute_tool(
                            workflow=workflow,
                            run_id=run_id,
                            stage_id=stage.stage_id,
                            role_id=role.role_id,
                            role=role,
                            request=tool_request,
                            context=context,
                        )
                        tool_results.append(result)
                    continue
                final_response = response
                break
            if final_response is None:
                raise WorkflowValidationError("provider turn limit exceeded")
            self._validate_artifacts(
                drafts=final_response.artifacts,
                expected_kind=stage.output_kind,
                role_allowed_kinds=role.allowed_artifact_kinds,
                context=context,
                required=stage.required,
            )
        except PermissionError as exc:
            return self._fail_stage(
                workflow,
                run_id=run_id,
                stage_id=stage.stage_id,
                failure_code="unauthorized_tool_request",
                response={"turns": response_history, "error": str(exc)},
            )
        except Exception as exc:
            return self._fail_stage(
                workflow,
                run_id=run_id,
                stage_id=stage.stage_id,
                failure_code=_failure_code(exc),
                response={"turns": response_history, "error": str(exc)},
            )

        assert final_response is not None
        artifact_ids = []
        for draft in final_response.artifacts:
            artifact = self._store.record_artifact(
                workflow_id=workflow.workflow_id,
                run_id=run_id,
                stage_id=stage.stage_id,
                role_id=role.role_id,
                draft=draft,
                created_at=self._now(),
            )
            artifact_ids.append(artifact.artifact_id)

        finished_at = self._now()
        run_status = (
            AgentRunStatus.PARTIAL
            if final_response.partial
            else AgentRunStatus.COMPLETED
        )
        self._store.finish_agent_run(
            run_id,
            status=run_status,
            response={
                "turns": response_history,
                "artifact_ids": artifact_ids,
                "partial": final_response.partial,
            },
            error_code=None,
            finished_at=finished_at,
        )
        if final_response.partial:
            workflow = self._store.update_workflow(
                workflow.workflow_id,
                status=WorkflowStatus.PARTIAL,
                current_stage_index=workflow.current_stage_index,
                partial_result=True,
                failure_code="partial_stage_result",
                updated_at=finished_at,
            )
            self._store.append_event(
                workflow.workflow_id,
                event_type="stage.partial",
                payload={
                    "stage_id": stage.stage_id,
                    "run_id": run_id,
                    "artifact_ids": artifact_ids,
                },
                created_at=finished_at,
            )
            return workflow

        next_index = workflow.current_stage_index + 1
        workflow = self._store.update_workflow(
            workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            current_stage_index=next_index,
            partial_result=workflow.partial_result,
            failure_code=None,
            updated_at=finished_at,
        )
        self._store.append_event(
            workflow.workflow_id,
            event_type="stage.completed",
            payload={
                "stage_id": stage.stage_id,
                "run_id": run_id,
                "artifact_ids": artifact_ids,
                "next_stage_index": next_index,
            },
            created_at=finished_at,
        )
        return workflow

    def _execute_tool(
        self,
        *,
        workflow: ResearchWorkflow,
        run_id: str,
        stage_id: str,
        role_id: str,
        role: AgentRole,
        request: ToolRequest,
        context: EvidenceBoundContextSnapshot,
    ) -> ToolExecutionResult:
        authorization = self._permissions.authorize(
            role=role,
            tool_name=request.tool_name,
            context=context,
        )
        call_id = f"ai-tool-{content_fingerprint({'run_id': run_id, **request.to_dict()})[:24]}"
        created_at = self._now()
        if not authorization.allowed:
            self._store.record_tool_call(
                ToolCall(
                    call_id=call_id,
                    run_id=run_id,
                    workflow_id=workflow.workflow_id,
                    stage_id=stage_id,
                    role_id=role_id,
                    tool_name=request.tool_name,
                    status=ToolCallStatus.DENIED,
                    arguments=dict(request.arguments),
                    result=None,
                    denial_reason=authorization.reason,
                    created_at=created_at,
                    completed_at=created_at,
                )
            )
            raise PermissionError(authorization.reason)
        executor = self._tool_executors.get(request.tool_name)
        if executor is None:
            self._store.record_tool_call(
                ToolCall(
                    call_id=call_id,
                    run_id=run_id,
                    workflow_id=workflow.workflow_id,
                    stage_id=stage_id,
                    role_id=role_id,
                    tool_name=request.tool_name,
                    status=ToolCallStatus.DENIED,
                    arguments=dict(request.arguments),
                    result=None,
                    denial_reason="tool_executor_not_bound",
                    created_at=created_at,
                    completed_at=created_at,
                )
            )
            raise PermissionError("tool_executor_not_bound")
        try:
            output = executor(dict(request.arguments), context)
            if not isinstance(output, dict):
                raise TypeError("tool output must be a JSON object")
            permission = authorization.permission
            if permission and permission.effect == ToolEffect.READ_PERSISTED:
                reference_id = str(output.get("evidence_reference_id") or "")
                if reference_id not in context.evidence_reference_ids:
                    raise WorkflowValidationError(
                        "read tool output is not bound to context evidence"
                    )
                if output.get("persisted_facts_only") is not True:
                    raise WorkflowValidationError(
                        "read tool output is not marked persisted-facts-only"
                    )
        except Exception as exc:
            self._store.record_tool_call(
                ToolCall(
                    call_id=call_id,
                    run_id=run_id,
                    workflow_id=workflow.workflow_id,
                    stage_id=stage_id,
                    role_id=role_id,
                    tool_name=request.tool_name,
                    status=ToolCallStatus.FAILED,
                    arguments=dict(request.arguments),
                    result=None,
                    denial_reason=_failure_code(exc),
                    created_at=created_at,
                    completed_at=self._now(),
                )
            )
            raise
        completed_at = self._now()
        self._store.record_tool_call(
            ToolCall(
                call_id=call_id,
                run_id=run_id,
                workflow_id=workflow.workflow_id,
                stage_id=stage_id,
                role_id=role_id,
                tool_name=request.tool_name,
                status=ToolCallStatus.COMPLETED,
                arguments=dict(request.arguments),
                result=output,
                denial_reason=None,
                created_at=created_at,
                completed_at=completed_at,
            )
        )
        return ToolExecutionResult(
            request_id=request.request_id,
            tool_name=request.tool_name,
            output=output,
        )

    def _validate_artifacts(
        self,
        *,
        drafts: tuple[ArtifactDraft, ...],
        expected_kind: ArtifactKind,
        role_allowed_kinds: tuple[ArtifactKind, ...],
        context: EvidenceBoundContextSnapshot,
        required: bool,
    ) -> None:
        if required and not drafts:
            raise WorkflowValidationError("required stage produced no artifact")
        if len(drafts) > 1:
            raise WorkflowValidationError("phase-one stages produce one artifact")
        for draft in drafts:
            if draft.kind != expected_kind:
                raise WorkflowValidationError("stage artifact kind mismatch")
            if draft.kind not in role_allowed_kinds:
                raise WorkflowValidationError("role artifact kind denied")
            unknown_refs = set(draft.evidence_reference_ids) - set(
                context.evidence_reference_ids
            )
            if unknown_refs:
                raise WorkflowValidationError(
                    f"artifact cites evidence outside context: {sorted(unknown_refs)}"
                )
            if draft.kind == ArtifactKind.TRADE_PLAN_DRAFT:
                if draft.content.get("executable") is not False:
                    raise WorkflowValidationError("trade-plan draft is executable")
                if draft.content.get("requires_human_review") is not True:
                    raise WorkflowValidationError(
                        "trade-plan draft lacks human review gate"
                    )
                if draft.content.get("authority_effect") != "none":
                    raise WorkflowValidationError(
                        "trade-plan draft changes execution authority"
                    )

    def _fail_stage(
        self,
        workflow: ResearchWorkflow,
        *,
        run_id: str,
        stage_id: str,
        failure_code: str,
        response: dict[str, Any] | None,
    ) -> ResearchWorkflow:
        failed_at = self._now()
        self._store.finish_agent_run(
            run_id,
            status=AgentRunStatus.FAILED,
            response=response,
            error_code=failure_code,
            finished_at=failed_at,
        )
        partial_result = bool(self._store.list_artifacts(workflow.workflow_id))
        workflow = self._store.update_workflow(
            workflow.workflow_id,
            status=WorkflowStatus.FAILED,
            current_stage_index=workflow.current_stage_index,
            partial_result=partial_result,
            failure_code=failure_code,
            updated_at=failed_at,
        )
        self._store.append_event(
            workflow.workflow_id,
            event_type="stage.failed",
            payload={
                "stage_id": stage_id,
                "run_id": run_id,
                "failure_code": failure_code,
                "partial_result": partial_result,
            },
            created_at=failed_at,
        )
        return workflow

    def _block_evidence_drift(
        self,
        workflow: ResearchWorkflow,
        current_context: EvidenceBoundContextSnapshot,
    ) -> ResearchWorkflow:
        blocked_at = self._now()
        workflow = self._store.update_workflow(
            workflow.workflow_id,
            status=WorkflowStatus.BLOCKED,
            current_stage_index=workflow.current_stage_index,
            partial_result=workflow.partial_result,
            failure_code="evidence_drift",
            updated_at=blocked_at,
        )
        self._store.append_event(
            workflow.workflow_id,
            event_type="workflow.blocked",
            payload={
                "failure_code": "evidence_drift",
                "expected_context_snapshot_id": workflow.context_snapshot_id,
                "expected_context_fingerprint": workflow.context_fingerprint,
                "observed_context_snapshot_id": current_context.snapshot_id,
                "observed_context_fingerprint": current_context.fingerprint,
                "observed_valuation_snapshot_id": (
                    current_context.valuation_snapshot_id
                ),
                "observed_ledger_cutoff_id": current_context.ledger_cutoff_id,
            },
            created_at=blocked_at,
        )
        return workflow


def _failure_code(exc: Exception) -> str:
    name = exc.__class__.__name__.replace("Error", "").strip("_")
    normalized = "".join(
        f"_{char.lower()}" if char.isupper() else char for char in name
    ).lstrip("_")
    return normalized or "stage_failure"
