"""Hypothesis-generation application workflow for AI strategy research."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    HumanContextCaptureRequest,
)
from server.ai_runtime.contracts import (
    AgentRole,
    AIResearchCapability,
    ArtifactDraft,
    ArtifactKind,
    JsonObject,
    ModelRegistration,
    ProviderRegistration,
    StageDefinition,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
)
from server.ai_runtime.provider import ProviderRequest, ProviderResponse
from server.ai_runtime.provider_call_window import ProviderCallDeferred
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.strategy_research_citations import (
    compact_hypothesis_citation_catalog,
    resolve_hypothesis_citations,
)
from server.ai_runtime.strategy_research_model_contract import (
    bind_and_validate_drafts,
    normalize_hypothesis_payload,
)
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.ai_runtime.strategy_research_support import report_artifact
from server.ai_runtime.strategy_research_values import (
    ACCOUNT_STATE_TOOL,
    CATALOG_TOOL,
    RESEARCH_TOOL,
    SELECTION_TOOL,
    TERMINAL_WORKFLOW_STATUSES,
)
from server.composition.strategy_research import (
    STRATEGY_RESEARCH_WORKFLOW_BUDGET,
    build_strategy_research_orchestrator,
    register_strategy_research_runtime,
    strategy_research_runtime_ids,
    strategy_research_workflow_definition,
)
from server.contracts.strategy_research import (
    LOCAL_HYPOTHESIS_ADMISSION_VERSION,
    STRATEGY_RESEARCH_MAX_INPUT_BYTES,
    HypothesisGenerationRequest,
    LocalHypothesisAdmissionRequest,
    StrategyResearchRejected,
)


class _LocalHypothesisAdmissionAdapter:
    """Validate imported output in the audit runtime; never invoke a model."""

    provider_id = "codex_conversation"

    def __init__(
        self,
        request: LocalHypothesisAdmissionRequest,
        *,
        session_id: str,
        evidence_reference_id: str,
        admitted_at: str,
    ) -> None:
        self._request = request
        self._session_id = session_id
        self._evidence_reference_id = evidence_reference_id
        self._admitted_at = admitted_at

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.turn_index == 0:
            return ProviderResponse(
                tool_requests=(
                    ToolRequest(
                        "read-bound-research-evidence",
                        RESEARCH_TOOL,
                        {"evidence_reference_id": self._evidence_reference_id},
                    ),
                    ToolRequest("read-formula-catalog", CATALOG_TOOL, {}),
                    ToolRequest("read-frozen-selection", SELECTION_TOOL, {}),
                ),
                message="Read canonical inputs for local artifact admission; no model call.",
            )
        results = {item.tool_name: dict(item.output) for item in request.tool_results}
        evidence = results.get(RESEARCH_TOOL, {})
        if (
            request.turn_index != 1
            or len(request.tool_results) != 3
            or evidence.get("evidence_reference_id") != self._evidence_reference_id
            or evidence.get("authoritative") is not True
            or evidence.get("persisted_facts_only") is not True
            or evidence.get("status") != "complete"
        ):
            raise StrategyResearchRejected("local_admission_evidence_invalid")
        sources = {
            "saved_backtest_evidence": evidence.get("payload"),
            "approved_formula_catalog": results.get(CATALOG_TOOL),
            "operator_frozen_selection": results.get(SELECTION_TOOL),
            "iteration_context": self._request.iteration_context or {},
        }
        normalized = normalize_hypothesis_payload(
            self._request.artifact,
            expected_draft_count=1 if self._request.iteration_context else None,
        )
        normalized = resolve_hypothesis_citations(
            normalized,
            citation_catalog=compact_hypothesis_citation_catalog(
                citation_sources=sources
            ),
            citation_sources=sources,
        )
        normalized["provider_provenance"] = {
            **self._request.source_provenance,
            "admitted_at": self._admitted_at,
            "admission_evidence_bound": True,
        }
        drafts = bind_and_validate_drafts(
            normalized,
            session_id=self._session_id,
            workflow_id=request.workflow_id,
            context_snapshot_id=request.context_snapshot_id,
            context_fingerprint=request.context_fingerprint,
            evidence_reference_id=self._evidence_reference_id,
            selection=self._request.selection,
            research_question=self._request.research_question,
            iteration_context=self._request.iteration_context,
            provider_id=self.provider_id,
            model_id=request.model_id,
            prompt_version=LOCAL_HYPOTHESIS_ADMISSION_VERSION,
        )
        return ProviderResponse(
            artifacts=(
                ArtifactDraft(
                    kind=ArtifactKind.REPORT,
                    content={"drafts": drafts},
                    evidence_reference_ids=(self._evidence_reference_id,),
                ),
            ),
            message="Local artifact validation/admission finished; no model invocation or authority.",
        )


class StrategyResearchGenerationMixin:
    async def admit_local_hypotheses(
        self, request: LocalHypothesisAdmissionRequest
    ) -> JsonObject:
        """Persist truthful local proposal lineage through normal draft validation."""
        # Frozen dataclasses still contain caller-owned JSON across await boundaries.
        request = deepcopy(request)
        request = replace(request, selection=replace(request.selection))
        self._require_accepted_research_task(request)
        self._require_execution_current()
        admitted_at = self._now()
        source_times = [
            item["observed_at"] for item in request.prior_diagnostic_exposures
        ]
        if request.source_authored_at is not None:
            source_times.append(request.source_authored_at)
        if any(
            datetime.fromisoformat(value) > datetime.fromisoformat(admitted_at)
            for value in source_times
        ):
            raise StrategyResearchRejected("local_admission_source_time_in_future")
        if (
            len(canonical_json(request.artifact).encode("utf-8"))
            > STRATEGY_RESEARCH_MAX_INPUT_BYTES
        ):
            raise StrategyResearchRejected("strategy_research_input_too_large")
        await self._validate_saved_selection(request.selection)
        session, reused = self._research_store.create_or_get_session(
            request, created_at=admitted_at
        )
        if reused and session["status"] != "pending":
            return self.get_session(session["session_id"], reused=True)
        capture = await self._capture_service.capture(
            HumanContextCaptureRequest(
                idempotency_key=f"local-strategy-admission:{request.idempotency_key}",
                requested_by=request.requested_by,
                research_question=request.research_question,
                account_alias=request.account_alias,
                evidence_types=(CaptureEvidenceType.RESEARCH_EVIDENCE,),
                confirmation=CAPTURE_CONFIRMATION,
                backtest_result_id=request.selection.saved_backtest_result_id,
            )
        )
        if (
            len(capture.records) != 1
            or capture.records[0].tool_name != RESEARCH_TOOL
            or not capture.records[0].authoritative
        ):
            raise StrategyResearchRejected("saved_backtest_evidence_not_authoritative")
        evidence = capture.records[0]
        provider_id = _LocalHypothesisAdmissionAdapter.provider_id
        model_id = f"{provider_id}:{request.source_model_id}"
        role_id = "local.strategy_hypothesis_artifact_admission.v1"
        registry = AiRuntimeRegistry(self._ai_store)
        registry.register_provider(
            ProviderRegistration(
                provider_id=provider_id,
                display_name="Conversation-authored local artifacts",
                adapter_kind="local_artifact_admission",
                enabled=True,
                capabilities=(
                    "hypothesis_artifact_admission",
                    "no_model_invocation",
                    "no_external_calls",
                ),
            )
        )
        registry.register_model(
            ModelRegistration(
                model_id=model_id,
                provider_id=provider_id,
                model_name=request.source_model_id,
                enabled=True,
                purposes=("caller_declared_artifact_source_identity_only",),
            )
        )
        registry.register_role(
            AgentRole(
                role_id=role_id,
                display_name="Local hypothesis artifact admission",
                purpose="Validate and admit caller-authored hypotheses against canonical evidence; never generate, score or approve them.",
                capability=AIResearchCapability.PROPOSE,
                allowed_tools=(RESEARCH_TOOL, CATALOG_TOOL, SELECTION_TOOL),
                allowed_artifact_kinds=(ArtifactKind.REPORT,),
                instructions_version=LOCAL_HYPOTHESIS_ADMISSION_VERSION,
            )
        )
        provider = _LocalHypothesisAdmissionAdapter(
            request,
            session_id=session["session_id"],
            evidence_reference_id=evidence.reference_id,
            admitted_at=admitted_at,
        )
        orchestrator = build_strategy_research_orchestrator(
            ai_store=self._ai_store,
            registry=registry,
            provider=provider,
            evidence_repository=self._evidence_repository,
            selection=request.selection,
            now=self._now,
            execution_guard=self._execution_guard,
        )
        workflow = orchestrator.create_workflow(
            definition=WorkflowDefinition(
                definition_id=LOCAL_HYPOTHESIS_ADMISSION_VERSION,
                name="Local hypothesis artifact validation and admission",
                stages=(
                    StageDefinition(
                        stage_id="local_hypothesis_artifact_admission",
                        role_id=role_id,
                        model_id=model_id,
                        output_kind=ArtifactKind.REPORT,
                    ),
                ),
                research_budget=STRATEGY_RESEARCH_WORKFLOW_BUDGET,
            ),
            context=capture.context,
            idempotency_key=f"local-strategy-admission:{request.idempotency_key}",
        )
        claimed = self._research_store.claim_session_run(
            session["session_id"],
            binding={
                "context_snapshot_id": capture.context.snapshot_id,
                "context_fingerprint": capture.context.fingerprint,
                "evidence_reference_id": evidence.reference_id,
                "workflow_id": workflow.workflow_id,
            },
            provider_id=provider_id,
            model_id=model_id,
            claimed_at=self._now(),
        )
        if claimed and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
            workflow = await asyncio.to_thread(
                orchestrator.run, workflow.workflow_id, current_context=capture.context
            )
        else:
            return self.get_session(session["session_id"], reused=True)
        self._require_execution_current()
        if workflow.status == WorkflowStatus.COMPLETED:
            self._research_store.save_drafts(
                session["session_id"],
                report_artifact(self._ai_store, workflow.workflow_id).content["drafts"],
                created_at=self._now(),
            )
        self._research_store.finish_session(
            session["session_id"],
            status=workflow.status.value,
            failure_code=workflow.failure_code,
            updated_at=self._now(),
        )
        return self.get_session(session["session_id"], reused=reused)

    async def generate_hypotheses(
        self, request: HypothesisGenerationRequest
    ) -> JsonObject:
        request = deepcopy(request)
        request = replace(request, selection=replace(request.selection))
        selection = request.selection
        if request.prior_diagnostic_exposures:
            current = datetime.fromisoformat(self._now())
            if any(
                datetime.fromisoformat(item["observed_at"]) > current
                for item in request.prior_diagnostic_exposures
            ):
                raise StrategyResearchRejected("prior_diagnostic_source_time_in_future")
        self._require_accepted_research_task(request)
        settings = self._require_settings()
        await self._validate_saved_selection(request.selection)
        reviewed_fee_schedule_resolution = await asyncio.to_thread(
            self._resolve_reviewed_fee_schedule,
            request.selection,
        )
        session, reused = self._research_store.create_or_get_session(
            request, created_at=self._now()
        )
        if reused and session["status"] in {
            "completed",
            "failed",
            "partial",
            "blocked",
            "running",
        }:
            return self.get_session(session["session_id"], reused=True)
        self._require_provider_send_window()

        evidence_types = (CaptureEvidenceType.RESEARCH_EVIDENCE,)
        if request.selection.has_account_binding:
            evidence_types = (
                CaptureEvidenceType.RESEARCH_EVIDENCE,
                CaptureEvidenceType.ACCOUNT_STATE,
            )
        capture = await self._capture_service.capture(
            HumanContextCaptureRequest(
                idempotency_key=f"strategy-hypothesis:{request.idempotency_key}",
                requested_by=request.requested_by,
                research_question=request.research_question,
                account_alias=request.account_alias,
                evidence_types=evidence_types,
                confirmation=CAPTURE_CONFIRMATION,
                backtest_result_id=request.selection.saved_backtest_result_id,
            )
        )
        records_by_tool = {record.tool_name: record for record in capture.records}
        if len(records_by_tool) != len(capture.records):
            raise StrategyResearchRejected("duplicate_captured_strategy_evidence")
        evidence = records_by_tool.get(RESEARCH_TOOL)
        if (
            len(capture.records) != len(evidence_types)
            or evidence is None
            or not evidence.authoritative
        ):
            raise StrategyResearchRejected("saved_backtest_evidence_not_authoritative")
        account_evidence = None
        if request.selection.has_account_binding:
            if (
                capture.context.valuation_snapshot_id
                != request.selection.valuation_snapshot_id
                or capture.context.ledger_cutoff_id
                != request.selection.ledger_cutoff_id
            ):
                raise StrategyResearchRejected("account_evidence_binding_mismatch")
            account_evidence = records_by_tool.get(ACCOUNT_STATE_TOOL)
            if account_evidence is None or not account_evidence.authoritative:
                raise StrategyResearchRejected("account_evidence_not_authoritative")
        if request.selection.has_account_binding:
            account_capital_evidence = self._build_account_capital_evidence(
                selection=request.selection,
                account_evidence=account_evidence,
                reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
            )
            if account_capital_evidence.get("status") != "pass":
                failure_code = str(
                    next(
                        iter(account_capital_evidence.get("issues") or []),
                        "research_account_capital_evidence_not_passing",
                    )
                )
                self._research_store.finish_session(
                    session["session_id"],
                    status="blocked",
                    failure_code=failure_code,
                    updated_at=self._now(),
                )
                raise StrategyResearchRejected(failure_code)
        provider_id, model_id = strategy_research_runtime_ids(settings, "hypothesis")
        registry = AiRuntimeRegistry(self._ai_store)
        register_strategy_research_runtime(
            registry, settings, provider_id, model_id, "hypothesis"
        )
        claimed = False

        def require_current() -> None:
            self._require_execution_current()
            self._resolve_simulation_entry_board_policy(selection)

        def require_claim_current() -> None:
            self._require_execution_current()
            if claimed:
                self._resolve_simulation_entry_board_policy(selection)

        def observe_transport(event_type: str, payload: JsonObject) -> None:
            self._ai_store.append_event(
                workflow.workflow_id,
                event_type=event_type,
                payload={**payload, "provider_id": provider_id, "model_id": model_id},
                created_at=self._now(),
            )

        provider = StrategyResearchModelProvider(
            provider_id=provider_id,
            settings=settings,
            mode="hypothesis",
            evidence_reference_id=evidence.reference_id,
            account_evidence_reference_id=(
                account_evidence.reference_id if account_evidence is not None else None
            ),
            selection=request.selection.to_external_dict(),
            research_question=request.research_question,
            critique_input=None,
            iteration_context=request.iteration_context,
            transport=self._transport,
            monotonic=self._monotonic,
            timeout_seconds=self._model_timeout_seconds,
            send_admission=self._provider_send_admission,
            research_history=request.research_history,
            execution_guard=require_current,
            transport_event=observe_transport,
        )
        orchestrator = build_strategy_research_orchestrator(
            ai_store=self._ai_store,
            registry=registry,
            provider=provider,
            evidence_repository=self._evidence_repository,
            selection=request.selection,
            now=self._now,
            execution_guard=(
                require_claim_current
                if selection.simulation_validation_binding is not None
                else self._execution_guard
            ),
        )
        workflow = orchestrator.create_workflow(
            definition=strategy_research_workflow_definition(model_id, "hypothesis"),
            context=capture.context,
            idempotency_key=f"strategy-hypothesis:{request.idempotency_key}",
        )
        claimed = self._research_store.claim_session_run(
            session["session_id"],
            binding={
                "context_snapshot_id": capture.context.snapshot_id,
                "context_fingerprint": capture.context.fingerprint,
                "evidence_reference_id": evidence.reference_id,
                "workflow_id": workflow.workflow_id,
            },
            provider_id=provider_id,
            model_id=model_id,
            claimed_at=self._now(),
        )
        if not claimed:
            return self.get_session(session["session_id"], reused=True)
        try:
            require_current()
            if workflow.status not in TERMINAL_WORKFLOW_STATUSES:
                workflow = await asyncio.to_thread(
                    orchestrator.run,
                    workflow.workflow_id,
                    current_context=capture.context,
                )
            else:
                workflow = self._ai_store.get_workflow(workflow.workflow_id)
            require_current()
            status = workflow.status.value
            if workflow.status == WorkflowStatus.COMPLETED:
                artifact = report_artifact(self._ai_store, workflow.workflow_id)
                drafts = bind_and_validate_drafts(
                    artifact.content,
                    session_id=session["session_id"],
                    workflow_id=workflow.workflow_id,
                    context_snapshot_id=capture.context.snapshot_id,
                    context_fingerprint=capture.context.fingerprint,
                    evidence_reference_id=evidence.reference_id,
                    selection=request.selection,
                    research_question=request.research_question,
                    iteration_context=request.iteration_context,
                    provider_id=provider_id,
                    model_id=model_id,
                )
                require_current()
                self._research_store.save_drafts(
                    session["session_id"], drafts, created_at=self._now()
                )
            require_current()
            self._research_store.finish_session(
                session["session_id"],
                status=status,
                failure_code=workflow.failure_code,
                updated_at=self._now(),
            )
        except ProviderCallDeferred as exc:
            self._require_execution_current()
            self._research_store.finish_session(
                session["session_id"],
                status="blocked",
                failure_code=str(exc),
                updated_at=self._now(),
            )
            raise
        except StrategyResearchRejected as exc:
            if selection.simulation_validation_binding is None or not claimed:
                raise
            # Revocation cannot authorize drafts, but must not erase our failure.
            self._require_execution_current()
            self._research_store.finish_session(
                session["session_id"],
                status="blocked",
                failure_code=str(exc),
                updated_at=self._now(),
            )
            raise
        return self.get_session(session["session_id"], reused=reused)
