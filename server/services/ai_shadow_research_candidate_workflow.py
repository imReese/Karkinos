"""Sequential hypothesis, backtest and critique candidate workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import ProviderCallDeferred
from server.ai_runtime.strategy_research import (
    BACKTEST_CONFIRMATION,
    CRITIQUE_EXPORT_CONFIRMATION,
    HYPOTHESIS_EXPORT_CONFIRMATION,
    CritiqueRequest,
    FormulaBacktestRequest,
    HypothesisGenerationRequest,
    StrategyResearchSelection,
)
from server.ai_runtime.strategy_research_support import strategy_research_json_object
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    TIMEOUT_RESUME_ITERATION,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    build_shadow_research_iteration_lineage,
)
from server.projections.normalized_research_operation_preview import (
    project_normalized_research_operation_preview,
)
from server.services.ai_shadow_research_support import (
    shadow_research_backtest_source_fingerprint,
    shadow_research_critique_usage,
    shadow_research_failure_code,
    shadow_research_hypothesis_usage,
)


class AiShadowResearchCandidateWorkflowMixin:
    async def _generate_iteration_hypothesis(
        self,
        *,
        run: Mapping[str, Any],
        policy: ShadowResearchPolicy,
        selection: StrategyResearchSelection,
        external_research: Any,
        iteration_context: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        iteration_number = int(iteration_context["iteration_number"])
        self._require_runtime_authorization(policy)
        call_id = f"{run['run_id']}:hypothesis:iteration:{iteration_number:02d}"
        resume_extension_id = str(run.get("partial_resume_extension_id") or "")
        provider_free_partial_resume_id = str(
            run.get("provider_free_partial_resume_id") or ""
        )
        if resume_extension_id and provider_free_partial_resume_id:
            raise ShadowResearchRejected("partial_resume_authority_conflict")
        if resume_extension_id:
            if iteration_number != TIMEOUT_RESUME_ITERATION:
                raise ShadowResearchRejected(
                    "timeout_resume_may_only_generate_fifth_hypothesis"
                )
            call_id += (
                ":timeout-resume:"
                + content_fingerprint({"extension_id": resume_extension_id})[:12]
            )
        if provider_free_partial_resume_id and iteration_number == int(
            run.get("partial_resume_iteration") or 0
        ):
            call_id += (
                ":provider-free-resume:"
                + content_fingerprint({"resume_id": provider_free_partial_resume_id})[
                    :12
                ]
            )
        self._require_provider_call_window()
        _, call_reused = self._store.claim_provider_call(
            call_id=call_id,
            run_id=str(run["run_id"]),
            market_date=str(run["market_date"]),
            call_kind="hypothesis_iteration",
            call_limit=policy.max_provider_calls_per_market_date,
            daily_token_budget=policy.daily_token_budget,
            now=self._utc_now(),
        )
        if call_reused:
            raise ShadowResearchRejected(
                "iteration_hypothesis_provider_call_already_claimed"
            )
        try:
            hypotheses = await external_research.generate_hypotheses(
                HypothesisGenerationRequest(
                    idempotency_key=call_id,
                    requested_by=f"automation:{policy.updated_by}",
                    account_alias="standing-owner-authorized-shadow-research",
                    research_question=policy.research_question,
                    selection=selection,
                    confirmation=HYPOTHESIS_EXPORT_CONFIRMATION,
                    iteration_context=dict(iteration_context),
                )
            )
        except ProviderCallDeferred as exc:
            self._defer_provider_call(call_id, str(exc))
            raise
        except asyncio.CancelledError:
            self._fail_provider_call(call_id, "provider_call_cancelled_uncertain")
            raise
        except Exception as exc:
            self._fail_provider_call(call_id, shadow_research_failure_code(exc))
            raise
        self._store.finish_provider_call(
            call_id,
            status=str(hypotheses.get("status") or "failed"),
            actual_tokens=shadow_research_hypothesis_usage(hypotheses),
            failure_code=hypotheses.get("failure_code"),
            now=self._utc_now(),
        )
        if hypotheses.get("status") != "completed":
            failure_code = str(hypotheses.get("failure_code") or "").strip()
            if (
                failure_code
                and len(failure_code) <= 160
                and all(char.isalnum() or char in "_:-." for char in failure_code)
            ):
                raise ShadowResearchRejected(failure_code)
            raise ShadowResearchRejected("iteration_hypothesis_generation_not_complete")
        drafts = hypotheses.get("drafts")
        if not isinstance(drafts, list) or len(drafts) != 1:
            raise ShadowResearchRejected("iteration_requires_exactly_one_draft")
        draft = drafts[0]
        if (
            not isinstance(draft, dict)
            or draft.get("validation", {}).get("status") != "valid"
        ):
            raise ShadowResearchRejected("iteration_hypothesis_not_locally_validated")
        if draft.get("iteration_context_fingerprint") != iteration_context.get(
            "context_fingerprint"
        ):
            raise ShadowResearchRejected("iteration_hypothesis_context_mismatch")
        return dict(hypotheses), dict(draft)

    async def _run_candidate(
        self,
        *,
        run: Mapping[str, Any],
        policy: ShadowResearchPolicy,
        hypotheses: Mapping[str, Any],
        draft: Mapping[str, Any],
        iteration_context: Mapping[str, Any],
        baseline_result_id: int,
        local_research: Any,
        external_research: Any,
        completed_backtest: Mapping[str, Any] | None = None,
        critique_resume_extension_id: str | None = None,
    ) -> dict[str, Any]:
        draft_id = str(draft["draft_id"])
        backtest_run_id: str | None = None
        candidate_result_id: int | None = None
        critique_id: str | None = None
        try:
            if bool(critique_resume_extension_id) != (completed_backtest is not None):
                raise ShadowResearchRejected(
                    "critique_resume_checkpoint_binding_incomplete"
                )
            self._require_runtime_authorization(policy)
            if completed_backtest is None:
                backtest = await local_research.run_formula_backtest(
                    FormulaBacktestRequest(
                        idempotency_key=f"{run['run_id']}:backtest:{draft_id}",
                        requested_by=f"automation:{policy.updated_by}",
                        session_id=str(hypotheses["session_id"]),
                        draft_id=draft_id,
                        confirmation=BACKTEST_CONFIRMATION,
                    )
                )
                if backtest.get("status") != "completed" or not backtest.get(
                    "canonical_backtest"
                ):
                    raise ShadowResearchRejected("formula_backtest_not_complete")
                backtest_run_id = str(backtest["backtest_run_id"])
                candidate_result_id = int(backtest["canonical_backtest"]["result_id"])
            else:
                backtest_run_id = str(completed_backtest.get("backtest_run_id") or "")
                candidate_result_id = int(
                    completed_backtest.get("candidate_result_id") or 0
                )
                if not backtest_run_id or candidate_result_id <= 0:
                    raise ShadowResearchRejected(
                        "completed_formula_backtest_checkpoint_invalid"
                    )
            self._require_runtime_authorization(policy)
            call_id = f"{run['run_id']}:critique:{draft_id}"
            if critique_resume_extension_id:
                call_id += (
                    ":corrected-panel-citation-resume:"
                    + content_fingerprint(
                        {"extension_id": critique_resume_extension_id}
                    )[:12]
                )
            self._require_provider_call_window()
            _, call_reused = self._store.claim_provider_call(
                call_id=call_id,
                run_id=str(run["run_id"]),
                market_date=str(run["market_date"]),
                call_kind="critique",
                call_limit=policy.max_provider_calls_per_market_date,
                daily_token_budget=policy.daily_token_budget,
                now=self._utc_now(),
            )
            if call_reused:
                raise ShadowResearchRejected("critique_provider_call_already_claimed")
            try:
                critique = await external_research.critique(
                    CritiqueRequest(
                        idempotency_key=call_id,
                        requested_by=f"automation:{policy.updated_by}",
                        session_id=str(hypotheses["session_id"]),
                        draft_id=draft_id,
                        backtest_run_id=backtest_run_id,
                        confirmation=CRITIQUE_EXPORT_CONFIRMATION,
                    )
                )
            except ProviderCallDeferred as exc:
                self._defer_provider_call(call_id, str(exc))
                raise
            except asyncio.CancelledError:
                self._fail_provider_call(call_id, "provider_call_cancelled_uncertain")
                raise
            except Exception as exc:
                self._fail_provider_call(call_id, shadow_research_failure_code(exc))
                raise
            self._store.finish_provider_call(
                call_id,
                status=str(critique.get("status") or "failed"),
                actual_tokens=shadow_research_critique_usage(critique),
                failure_code=critique.get("failure_code"),
                now=self._utc_now(),
            )
            if critique.get("status") != "completed":
                failure_code = str(critique.get("failure_code") or "").strip()
                if (
                    failure_code
                    and len(failure_code) <= 160
                    and all(char.isalnum() or char in "_:-." for char in failure_code)
                ):
                    raise ShadowResearchRejected(failure_code)
                raise ShadowResearchRejected("strategy_critique_not_complete")
            critique_id = str(critique["critique_id"])
            comparison = await self._build_comparison(
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                draft=draft,
                critique=critique,
                iteration_context=iteration_context,
                research_capital_mode=policy.research_capital_mode,
            )
            normalized_research = (
                policy.research_capital_mode
                == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
            )
            recommendation = (
                "formula_research_candidate"
                if normalized_research
                else str(comparison["recommendation"])
            )
            return self._store.save_candidate(
                run_id=str(run["run_id"]),
                session_id=str(hypotheses["session_id"]),
                draft_id=draft_id,
                backtest_run_id=backtest_run_id,
                critique_id=critique_id,
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                status=(
                    "evaluated_research_only"
                    if normalized_research
                    else (
                        "awaiting_human_approval"
                        if recommendation == "paper_shadow_review"
                        else "research_blocked"
                    )
                ),
                recommendation=recommendation,
                comparison=comparison,
                now=self._utc_now(),
            )
        except ProviderCallDeferred:
            raise
        except Exception as exc:
            return self._store.save_candidate(
                run_id=str(run["run_id"]),
                session_id=str(hypotheses["session_id"]),
                draft_id=draft_id,
                backtest_run_id=backtest_run_id,
                critique_id=critique_id,
                baseline_result_id=baseline_result_id,
                candidate_result_id=candidate_result_id,
                status="failed_closed",
                recommendation="reject",
                comparison={
                    "schema_version": "karkinos.ai.shadow_research_comparison.v1",
                    "failure_code": shadow_research_failure_code(exc),
                    "research_capital_mode": policy.research_capital_mode,
                    "account_qualification_status": (
                        "not_evaluated"
                        if policy.research_capital_mode
                        == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
                        else "failed_closed"
                    ),
                    "iteration_lineage": build_shadow_research_iteration_lineage(
                        iteration_context,
                        current_formula_fingerprint=draft.get("formula_fingerprint"),
                    ),
                    "promotion_gate": {
                        "status": "blocked",
                        "blockers": [shadow_research_failure_code(exc)],
                    },
                    "automatic_strategy_replacement_enabled": False,
                    "broker_submission_enabled": False,
                },
                now=self._utc_now(),
            )

    async def _build_comparison(
        self,
        *,
        baseline_result_id: int,
        candidate_result_id: int,
        draft: Mapping[str, Any],
        critique: Mapping[str, Any],
        iteration_context: Mapping[str, Any],
        research_capital_mode: str,
    ) -> dict[str, Any]:
        baseline = await self._db.get_backtest_result(baseline_result_id)
        candidate = await self._db.get_backtest_result(candidate_result_id)
        if not isinstance(baseline, dict) or not isinstance(candidate, dict):
            raise ShadowResearchRejected("comparison_backtest_missing")
        baseline_view = strategy_advancement_backtest_view(baseline)
        candidate_view = strategy_advancement_backtest_view(candidate)
        candidate_metrics = strategy_research_json_object(
            candidate.get("metrics") or candidate.get("metrics_json")
        )
        operation_preview = project_normalized_research_operation_preview(
            candidate_metrics.get("normalized_research_operation_preview")
        )
        if operation_preview is not None and (
            operation_preview.get("formula_fingerprint")
            != draft.get("formula_fingerprint")
            or operation_preview.get("dataset_snapshot_id")
            != candidate_view.get("dataset_snapshot_id")
        ):
            operation_preview = None
        critique_artifact = (
            critique.get("artifact")
            if isinstance(critique.get("artifact"), Mapping)
            else {}
        )
        advancement_gate = build_strategy_advancement_gate(
            baseline=baseline_view,
            candidate=candidate_view,
            critique_evidence={
                "status": critique.get("status"),
                "critique_id": critique.get("critique_id"),
                "artifact_fingerprint": (
                    content_fingerprint(critique_artifact)
                    if critique_artifact
                    else None
                ),
            },
        )
        improvements = {
            "total_return": candidate_view["total_return"]
            >= baseline_view["total_return"],
            "sharpe": candidate_view["sharpe"] >= baseline_view["sharpe"],
            "max_drawdown": abs(candidate_view["max_drawdown"])
            <= abs(baseline_view["max_drawdown"]),
        }
        recommendation = (
            "paper_shadow_review" if advancement_gate.passed else "keep_researching"
        )
        return {
            "schema_version": "karkinos.ai.shadow_research_comparison.v1",
            "baseline_source_fingerprint": shadow_research_backtest_source_fingerprint(
                baseline
            ),
            "candidate_source_fingerprint": shadow_research_backtest_source_fingerprint(
                candidate
            ),
            "economic_hypothesis": draft.get("economic_hypothesis"),
            "risk_impact": draft.get("risk_impact"),
            "failure_conditions": list(draft.get("failure_conditions") or []),
            "limitations": list(draft.get("limitations") or []),
            "baseline": baseline_view,
            "candidate": candidate_view,
            "deltas": {
                "total_return": candidate_view["total_return"]
                - baseline_view["total_return"],
                "sharpe": candidate_view["sharpe"] - baseline_view["sharpe"],
                "max_drawdown": candidate_view["max_drawdown"]
                - baseline_view["max_drawdown"],
                "total_cost": candidate_view["total_cost"]
                - baseline_view["total_cost"],
            },
            "improvements": improvements,
            "deepseek_critique": critique_artifact,
            "research_capital_mode": research_capital_mode,
            "account_qualification_status": (
                "not_evaluated"
                if research_capital_mode
                == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
                else ("passed" if advancement_gate.passed else "blocked")
            ),
            **(
                {"normalized_research_operation_preview": operation_preview}
                if research_capital_mode
                == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
                and operation_preview is not None
                else {}
            ),
            "iteration_lineage": build_shadow_research_iteration_lineage(
                iteration_context,
                current_formula_fingerprint=draft.get("formula_fingerprint"),
            ),
            "recommendation": recommendation,
            "promotion_gate": advancement_gate.to_json_dict(),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "authority_effect": "research_only",
        }
