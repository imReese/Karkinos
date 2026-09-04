"""Canonical-backtest critique application workflow for strategy research."""

from __future__ import annotations

import asyncio

from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from server.ai_runtime.contracts import JsonObject, WorkflowStatus, content_fingerprint
from server.ai_runtime.provider_call_window import ProviderCallDeferred
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
    validate_persisted_fee_schedule_binding,
)
from server.ai_runtime.strategy_research_privacy import (
    build_normalized_lot_feasibility_evidence,
    build_normalized_research_pack,
    build_normalized_signal_execution_evidence,
)
from server.ai_runtime.strategy_research_provider import StrategyResearchModelProvider
from server.ai_runtime.strategy_research_support import (
    critique_response,
    report_artifact,
    selection_from_session,
    strategy_research_json_object,
    strategy_research_request_json,
)
from server.ai_runtime.strategy_research_values import TERMINAL_WORKFLOW_STATUSES
from server.composition.strategy_research import (
    build_strategy_research_orchestrator,
    register_strategy_research_runtime,
    strategy_research_runtime_ids,
    strategy_research_workflow_definition,
)
from server.contracts.strategy_research import CritiqueRequest, StrategyResearchRejected


class StrategyResearchCritiqueMixin:
    async def critique(self, request: CritiqueRequest) -> JsonObject:
        settings = self._require_settings()
        session = self._research_store.get_session(request.session_id)
        self._validate_session_integrity(session)
        draft_row = self._research_store.get_draft(request.session_id, request.draft_id)
        backtest = self._research_store.get_backtest(request.backtest_run_id)
        if (
            backtest["status"] != "completed"
            or not backtest["canonical_backtest_result_id"]
        ):
            raise StrategyResearchRejected("canonical_backtest_not_complete")
        if backtest["draft_id"] != request.draft_id:
            raise StrategyResearchRejected("critique_draft_backtest_mismatch")
        backtest_replay_valid, _ = self._research_store.verify_events(
            str(backtest["backtest_run_id"])
        )
        if not backtest_replay_valid:
            raise StrategyResearchRejected("formula_backtest_audit_drift")
        saved = await self._db.get_backtest_result(
            backtest["canonical_backtest_result_id"]
        )
        if not isinstance(saved, dict):
            raise StrategyResearchRejected("canonical_backtest_result_missing")
        metrics = strategy_research_json_object(saved.get("metrics_json"))
        evidence = metrics.get("research_evidence_bundle")
        if not isinstance(evidence, dict):
            raise StrategyResearchRejected("canonical_research_evidence_missing")
        dataset_snapshot = metrics.get("dataset_snapshot")
        if not isinstance(dataset_snapshot, dict):
            raise StrategyResearchRejected("canonical_dataset_snapshot_missing")
        after_cost_evidence = metrics.get("evidence_bundle")
        if not isinstance(after_cost_evidence, dict):
            raise StrategyResearchRejected("canonical_after_cost_evidence_missing")
        oos_validation = metrics.get("oos_validation")
        if not isinstance(oos_validation, dict):
            raise StrategyResearchRejected("canonical_oos_validation_missing")
        cost_summary = strategy_research_json_object(saved.get("cost_summary_json"))
        if content_fingerprint(evidence) != backtest["evidence_fingerprint"]:
            raise StrategyResearchRejected("canonical_backtest_artifact_drift")

        provider_id, model_id = strategy_research_runtime_ids(settings, "critique")
        critique, reused = self._research_store.create_or_get_critique(
            request,
            provider_id=provider_id,
            model_id=model_id,
            created_at=self._now(),
        )
        if reused and critique["status"] in {
            "completed",
            "failed",
            "partial",
            "blocked",
            "running",
        }:
            return critique_response(critique, reused=True)
        self._require_provider_send_window()

        context = self._ai_store.get_context(session["context_snapshot_id"])
        evidence_reference_id = str(session["evidence_reference_id"])
        selection = selection_from_session(session)
        reviewed_fee_schedule_resolution = await asyncio.to_thread(
            self._resolve_reviewed_fee_schedule,
            selection,
        )
        validate_persisted_fee_schedule_binding(
            selection,
            metrics,
            reviewed_fee_schedule_resolution,
        )
        account_capital_evidence = self._account_capital_evidence_for_session(
            session=session,
            selection=selection,
            reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
        )
        persisted_account_capital = metrics.get("account_capital_constraint")
        account_binding_valid = (
            is_valid_passed_research_account_capital_evidence(
                persisted_account_capital,
                expected_initial_cash=selection.initial_cash,
                expected_valuation_snapshot_id=selection.valuation_snapshot_id,
                expected_ledger_cutoff_id=selection.ledger_cutoff_id,
            )
            if selection.has_account_binding
            else isinstance(persisted_account_capital, dict)
            and persisted_account_capital == account_capital_evidence
        )
        if not account_binding_valid or content_fingerprint(
            persisted_account_capital
        ) != content_fingerprint(account_capital_evidence):
            raise StrategyResearchRejected(
                "persisted_research_account_capital_binding_drift"
            )
        await asyncio.to_thread(
            RestrictedFormulaBacktestAdapter(
                data_store=self._data_store
            ).validate_selection,
            selection,
            expected_dataset_snapshot=dataset_snapshot,
            reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
        )
        normalized_pack = build_normalized_research_pack(
            performance=saved,
            after_cost_evidence=after_cost_evidence,
            cost_summary=cost_summary,
            research_evidence_bundle=evidence,
            oos_validation=oos_validation,
        )
        normalized_performance = normalized_pack["performance_summary"]
        normalized_cost = normalized_pack["cost_summary"]
        required_binding_echo = {
            "canonical_backtest_result_id": int(
                backtest["canonical_backtest_result_id"]
            ),
            "formula_fingerprint": backtest["formula_fingerprint"],
            "dataset_snapshot_id": backtest["dataset_snapshot_id"],
            "cost_model_reference": backtest["cost_model_reference"],
            "notional_policy_id": normalized_pack["notional_policy_id"],
            **normalized_performance,
            **normalized_cost,
            "oos_validation_fingerprint": content_fingerprint(oos_validation),
            "research_evidence_fingerprint": content_fingerprint(evidence),
        }
        registry = AiRuntimeRegistry(self._ai_store)
        register_strategy_research_runtime(
            registry, settings, provider_id, model_id, "critique"
        )
        provider = StrategyResearchModelProvider(
            provider_id=provider_id,
            settings=settings,
            mode="critique",
            evidence_reference_id=evidence_reference_id,
            selection=selection.to_external_dict(),
            research_question=strategy_research_request_json(session)[
                "research_question"
            ],
            iteration_context=None,
            critique_input={
                "hypothesis_draft": draft_row["contract"],
                "canonical_backtest_result_id": backtest[
                    "canonical_backtest_result_id"
                ],
                "canonical_backtest": {
                    **required_binding_echo,
                    "result_id": int(backtest["canonical_backtest_result_id"]),
                    "performance_summary": normalized_performance,
                    "after_cost_evidence": normalized_pack["after_cost_summary"],
                    "cost_summary": normalized_cost,
                    "oos_validation": normalized_pack["oos_validation"],
                    "research_evidence_bundle": normalized_pack[
                        "research_evidence_bundle"
                    ],
                    "signal_execution_evidence": (
                        build_normalized_signal_execution_evidence(
                            metrics.get("signal_execution_evidence")
                        )
                    ),
                    "lot_feasibility_evidence": (
                        build_normalized_lot_feasibility_evidence(
                            metrics.get("lot_feasibility_evidence")
                        )
                    ),
                },
                "required_binding_echo": required_binding_echo,
                "canonical_research_evidence": normalized_pack[
                    "research_evidence_bundle"
                ],
                "formula_fingerprint": backtest["formula_fingerprint"],
                "dataset_snapshot_id": backtest["dataset_snapshot_id"],
                "cost_model_reference": backtest["cost_model_reference"],
            },
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
            selection=selection,
            now=self._now,
            execution_guard=self._execution_guard,
        )
        workflow = orchestrator.create_workflow(
            definition=strategy_research_workflow_definition(model_id, "critique"),
            context=context,
            idempotency_key=f"strategy-critique:{request.idempotency_key}",
        )
        claimed = self._research_store.claim_critique(
            critique["critique_id"],
            workflow_id=workflow.workflow_id,
            claimed_at=self._now(),
        )
        try:
            if claimed and workflow.status not in TERMINAL_WORKFLOW_STATUSES:
                workflow = await asyncio.to_thread(
                    orchestrator.run,
                    workflow.workflow_id,
                    current_context=context,
                )
            else:
                workflow = self._ai_store.getstrategy_research_workflow_definition(
                    workflow.workflow_id
                )
        except ProviderCallDeferred as exc:
            self._require_execution_current()
            self._research_store.finish_critique(
                critique["critique_id"],
                status="blocked",
                artifact=None,
                failure_code=str(exc),
                updated_at=self._now(),
            )
            raise
        self._require_execution_current()
        artifact_payload = None
        if workflow.status == WorkflowStatus.COMPLETED:
            artifact_payload = report_artifact(
                self._ai_store, workflow.workflow_id
            ).content
        self._require_execution_current()
        self._research_store.finish_critique(
            critique["critique_id"],
            status=workflow.status.value,
            artifact=artifact_payload,
            failure_code=workflow.failure_code,
            updated_at=self._now(),
        )
        return critique_response(
            self._research_store.get_critique(critique["critique_id"]),
            reused=reused,
        )
