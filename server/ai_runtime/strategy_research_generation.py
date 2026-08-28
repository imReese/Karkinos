"""Hypothesis-generation application workflow for AI strategy research."""

from __future__ import annotations

import asyncio

from server.ai_runtime.capture import (
    CAPTURE_CONFIRMATION,
    CaptureEvidenceType,
    HumanContextCaptureRequest,
)
from server.ai_runtime.contracts import JsonObject, WorkflowStatus
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.strategy_research_model_contract import bind_and_validate_drafts
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.ai_runtime.strategy_research_support import report_artifact
from server.ai_runtime.strategy_research_values import (
    ACCOUNT_STATE_TOOL,
    RESEARCH_TOOL,
    TERMINAL_WORKFLOW_STATUSES,
)
from server.composition.strategy_research import (
    build_strategy_research_orchestrator,
    register_strategy_research_runtime,
    strategy_research_runtime_ids,
    strategy_research_workflow_definition,
)
from server.contracts.strategy_research import (
    HypothesisGenerationRequest,
    StrategyResearchRejected,
)


class StrategyResearchGenerationMixin:
    async def generate_hypotheses(
        self, request: HypothesisGenerationRequest
    ) -> JsonObject:
        settings = self._require_settings()
        if not request.selection.has_account_binding:
            raise StrategyResearchRejected("research_account_binding_required")
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
        )
        orchestrator = build_strategy_research_orchestrator(
            ai_store=self._ai_store,
            registry=registry,
            provider=provider,
            evidence_repository=self._evidence_repository,
            selection=request.selection,
            now=self._now,
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
        if claimed and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
            workflow = await asyncio.to_thread(
                orchestrator.run,
                workflow.workflow_id,
                current_context=capture.context,
            )
        else:
            workflow = self._ai_store.getstrategy_research_workflow_definition(
                workflow.workflow_id
            )
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
            self._research_store.save_drafts(
                session["session_id"], drafts, created_at=self._now()
            )
        self._research_store.finish_session(
            session["session_id"],
            status=status,
            failure_code=workflow.failure_code,
            updated_at=self._now(),
        )
        return self.get_session(session["session_id"], reused=reused)
