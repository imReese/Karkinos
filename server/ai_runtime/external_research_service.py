"""Application service for human-started external backtest research."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import cast

from server.contracts.external_research import (
    EXTERNAL_BACKTEST_REPORT_PROMPT,
    EXTERNAL_BACKTEST_REPORT_ROLE,
    EXTERNAL_RESEARCH_EVIDENCE_TOOL,
    ExternalBacktestReportRecord,
    ExternalBacktestReportRejected,
    HumanExternalBacktestReportRequest,
)

from .capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    HumanContextCaptureRequest,
    HumanResearchContextCaptureService,
)
from .contracts import (
    AgentRole,
    ArtifactKind,
    ModelRegistration,
    ProviderRegistration,
    ResearchWorkflow,
    canonical_json,
)
from .evidence import CanonicalEvidenceRepository, CanonicalEvidenceToolExecutors
from .external_research_provider import OpenAICompatibleBacktestReportProvider
from .external_research_result import ExternalBacktestReportResult
from .external_research_store import ExternalBacktestReportAuditStore
from .external_research_workflow import (
    TERMINAL_WORKFLOW_STATUSES,
    external_report_workflow_definition,
    utc_now,
)
from .orchestrator import DeterministicWorkflowOrchestrator, ToolExecutor
from .permissions import default_tool_permission_registry
from .provider_connectivity_contracts import (
    JsonHttpTransport,
    ProviderConnectivitySettings,
)
from .provider_connectivity_transport import HttpxDeadlineJsonTransport
from .registry import AiRuntimeRegistry
from .store import AiAuditStore


class HumanExternalBacktestReportService:
    """Capture, authorize, run, and audit one explicit external report."""

    def __init__(
        self,
        *,
        settings: ProviderConnectivitySettings,
        capture_service: HumanResearchContextCaptureService,
        evidence_repository: CanonicalEvidenceRepository,
        ai_store: AiAuditStore,
        report_store: ExternalBacktestReportAuditStore,
        transport: JsonHttpTransport | None = None,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
        model_timeout_seconds: float = 180.0,
    ) -> None:
        self._settings = settings
        self._capture_service = capture_service
        self._evidence_repository = evidence_repository
        self._ai_store = ai_store
        self._report_store = report_store
        self._transport = transport or HttpxDeadlineJsonTransport()
        self._now = now or utc_now
        self._monotonic = monotonic or time.monotonic
        if model_timeout_seconds <= 0 or model_timeout_seconds > 300:
            raise ValueError("model_timeout_seconds must be within (0, 300]")
        self._model_timeout_seconds = model_timeout_seconds

    async def run(
        self,
        request: HumanExternalBacktestReportRequest,
    ) -> ExternalBacktestReportResult:
        capture = await self._capture_service.capture(
            HumanContextCaptureRequest(
                idempotency_key=f"external-report:{request.idempotency_key}",
                requested_by=request.requested_by,
                research_question=request.research_question,
                account_alias=request.account_alias,
                evidence_types=(CaptureEvidenceType.RESEARCH_EVIDENCE,),
                confirmation=CAPTURE_CONFIRMATION,
                backtest_result_id=request.backtest_result_id,
            )
        )
        if len(capture.records) != 1:
            raise ExternalBacktestReportRejected(
                "external report requires exactly one research evidence record"
            )
        evidence = capture.records[0]
        if evidence.tool_name != EXTERNAL_RESEARCH_EVIDENCE_TOOL:
            raise ExternalBacktestReportRejected(
                "external report received an unexpected evidence type"
            )
        if not evidence.authoritative:
            raise ExternalBacktestReportRejected(
                f"external report requires complete evidence; status={evidence.status}"
            )
        if evidence.payload.get("analysis_ready") is not True:
            blockers = evidence.payload.get("analysis_blocking_reasons")
            raise ExternalBacktestReportRejected(
                "saved backtest is not ready for external analysis: "
                + canonical_json(blockers if isinstance(blockers, list) else [])
            )

        runtime_provider_id, runtime_model_id = self._runtime_ids()
        registry = AiRuntimeRegistry(self._ai_store)
        self._register_runtime(
            registry,
            provider_id=runtime_provider_id,
            model_id=runtime_model_id,
        )
        context_binding = {
            "context_snapshot_id": capture.context.snapshot_id,
            "context_fingerprint": capture.context.fingerprint,
            "valuation_snapshot_id": capture.context.valuation_snapshot_id,
            "ledger_cutoff_id": capture.context.ledger_cutoff_id,
            "ledger_fingerprint": capture.context.ledger_fingerprint,
            "evidence_reference_id": evidence.reference_id,
            "evidence_record_fingerprint": evidence.record_fingerprint,
        }
        provider = OpenAICompatibleBacktestReportProvider(
            provider_id=runtime_provider_id,
            settings=self._settings,
            evidence_reference_id=evidence.reference_id,
            research_question=request.research_question,
            context_binding=context_binding,
            transport=self._transport,
            monotonic=self._monotonic,
            timeout_seconds=self._model_timeout_seconds,
        )
        orchestrator = DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={runtime_provider_id: provider},
            tool_executors=cast(
                Mapping[str, ToolExecutor],
                CanonicalEvidenceToolExecutors(self._evidence_repository).as_mapping(),
            ),
            now=self._now,
            max_provider_turns=2,
        )
        workflow = orchestrator.create_workflow(
            definition=external_report_workflow_definition(runtime_model_id),
            context=capture.context,
            idempotency_key=f"external-report:{request.idempotency_key}",
        )
        record, reused = self._report_store.create_or_get(
            request,
            capture_id=capture.run.capture_id,
            workflow_id=workflow.workflow_id,
            context_snapshot_id=capture.context.snapshot_id,
            context_fingerprint=capture.context.fingerprint,
            evidence_reference_id=evidence.reference_id,
            provider_id=runtime_provider_id,
            model_id=runtime_model_id,
            created_at=self._now(),
        )
        claimed = self._report_store.claim_run(
            record.analysis_id,
            claimed_at=self._now(),
        )
        if claimed and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
            workflow = await asyncio.to_thread(
                orchestrator.run,
                workflow.workflow_id,
                current_context=capture.context,
            )
        elif not claimed:
            workflow = self._ai_store.get_workflow(workflow.workflow_id)
        return self._result(record, workflow=workflow, reused=reused)

    def _runtime_ids(self) -> tuple[str, str]:
        provider_id = f"karkinos.external_research.{self._settings.provider_id}.v1"
        model_id = f"{provider_id}:{self._settings.model_name}"
        return provider_id, model_id

    def _register_runtime(
        self,
        registry: AiRuntimeRegistry,
        *,
        provider_id: str,
        model_id: str,
    ) -> None:
        registry.register_provider(
            ProviderRegistration(
                provider_id=provider_id,
                display_name=(
                    f"{self._settings.provider_id} evidence-bound research edge"
                ),
                adapter_kind=self._settings.adapter_kind,
                enabled=True,
                capabilities=(
                    "saved_backtest_evidence_report",
                    "provider_side_tools_disabled",
                ),
            )
        )
        registry.register_model(
            ModelRegistration(
                model_id=model_id,
                provider_id=provider_id,
                model_name=self._settings.model_name,
                enabled=True,
                purposes=("human_started_backtest_evidence_review",),
            )
        )
        registry.register_role(
            AgentRole(
                role_id=EXTERNAL_BACKTEST_REPORT_ROLE,
                display_name="External backtest evidence analyst",
                purpose=(
                    "Analyze one exact saved-backtest evidence record without "
                    "investment, account, risk, capital, or execution authority."
                ),
                allowed_tools=(EXTERNAL_RESEARCH_EVIDENCE_TOOL,),
                allowed_artifact_kinds=(ArtifactKind.REPORT,),
                instructions_version=EXTERNAL_BACKTEST_REPORT_PROMPT,
            )
        )

    def _result(
        self,
        record: ExternalBacktestReportRecord,
        *,
        workflow: ResearchWorkflow,
        reused: bool,
    ) -> ExternalBacktestReportResult:
        artifacts = self._ai_store.list_artifacts(workflow.workflow_id)
        report = next(
            (item for item in artifacts if item.kind == ArtifactKind.REPORT),
            None,
        )
        binding_validity, binding_errors = self._binding_validity(record)
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
        return ExternalBacktestReportResult(
            record=record,
            workflow=workflow,
            report=report,
            tool_calls=tool_calls,
            audit_replay=self._ai_store.verify_replay(workflow.workflow_id),
            binding_validity=binding_validity,
            binding_errors=binding_errors,
            external_model_stage_run_count=len(
                self._ai_store.list_agent_runs(workflow.workflow_id)
            ),
            reused=reused,
        )

    def _binding_validity(
        self,
        record: ExternalBacktestReportRecord,
    ) -> tuple[str, tuple[str, ...]]:
        errors: list[str] = []
        try:
            context = self._ai_store.get_context(record.context_snapshot_id)
        except LookupError:
            return "invalid", ("context_snapshot_missing",)
        if context.fingerprint != record.context_fingerprint:
            errors.append("context_fingerprint_mismatch")
        evidence = self._evidence_repository.get(record.evidence_reference_id)
        if evidence is None:
            errors.append("evidence_record_missing")
        else:
            reference = next(
                (
                    item
                    for item in context.evidence_references
                    if item.reference_id == record.evidence_reference_id
                ),
                None,
            )
            if reference is None or reference != evidence.to_reference():
                errors.append("evidence_context_binding_mismatch")
        return ("valid", ()) if not errors else ("invalid", tuple(errors))


__all__ = ["HumanExternalBacktestReportService"]
