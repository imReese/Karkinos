"""After-close AI shadow research orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timezone
from typing import Any

from core.types import BarFrequency
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research import StrategyResearchSelection
from server.contracts.ai_shadow_research_automation import (
    CORRECTED_PANEL_CITATION_RESUME_ITERATION,
    CORRECTED_PANEL_CITATION_RESUME_STAGE,
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    SHADOW_RESEARCH_TIMEZONE,
    TIMEOUT_RESUME_COMPLETED_ITERATIONS,
    TIMEOUT_RESUME_ITERATION,
    ShadowResearchRejected,
    build_shadow_research_iteration_context,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
)
from server.services.ai_shadow_research_support import (
    is_after_shadow_research_close,
    shadow_research_failure_code,
    shadow_research_market_close_as_of,
)
from server.services.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)

logger = logging.getLogger(__name__)


class AiShadowResearchWorkflowMixin:
    async def run_once(self) -> dict[str, Any]:
        policy = self.get_policy()
        preflight = self._policy_preflight(policy)
        if preflight is not None:
            return preflight

        provider_window_preflight, batch_deadline_at = (
            self._provider_batch_window_admission()
        )
        if provider_window_preflight is not None:
            return provider_window_preflight

        try:
            prepared = await asyncio.to_thread(self._prepare_baseline, policy)
        except asyncio.CancelledError:
            raise
        except (ReviewedFeeScheduleRejected, ReviewedFeeScheduleReadRejected) as exc:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code=exc.code,
            )
        except Exception as exc:
            return self._record_preflight(
                status="blocked_by_market_evidence",
                failure_code=shadow_research_failure_code(exc),
            )
        deadline_preflight = self._provider_batch_deadline_preflight(batch_deadline_at)
        if deadline_preflight is not None:
            return deadline_preflight
        now_dt = self._now().astimezone(SHADOW_RESEARCH_TIMEZONE)
        if not is_after_shadow_research_close(
            prepared.market_date, now_dt, policy.after_close_time
        ):
            return {
                **self.status(),
                "run_status": "waiting_for_market_close",
                "market_date": prepared.market_date,
            }

        try:
            valuation = await asyncio.to_thread(self._build_current_valuation_snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code=shadow_research_failure_code(exc),
                market_date=prepared.market_date,
            )
        deadline_preflight = self._provider_batch_deadline_preflight(batch_deadline_at)
        if deadline_preflight is not None:
            return deadline_preflight
        if (
            policy.require_complete_account_evidence
            and valuation.get("status") != "complete"
        ):
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_snapshot_not_complete",
                market_date=prepared.market_date,
            )
        if str(valuation.get("trade_date")) != prepared.market_date:
            return self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_market_date_mismatch",
                market_date=prepared.market_date,
            )

        input_fingerprint = content_fingerprint(
            {
                "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
                "policy": policy.to_dict(),
                "provider_call_window_policy": (
                    self._provider_call_window_policy.to_dict()
                    if self._provider_call_window_policy is not None
                    else None
                ),
                "provider_batch_deadline_at": (
                    batch_deadline_at.isoformat()
                    if batch_deadline_at is not None
                    else None
                ),
                "baseline_fingerprint": prepared.fingerprint,
                "valuation_snapshot_id": valuation["snapshot_id"],
                "ledger_cutoff_id": valuation["ledger_cutoff_id"],
            }
        )
        selection_components = {
            "universe": tuple(
                asset["symbol"] for asset in prepared.request.assets or []
            ),
            "asset_classes": tuple(
                asset["asset_class"] for asset in prepared.request.assets or []
            ),
            "dataset_snapshot_id": str(prepared.snapshot["snapshot_id"]),
            "start_date": prepared.request.start_date,
            "end_date": prepared.request.end_date,
            "frequency": BarFrequency.DAILY.value,
            "initial_cash": prepared.request.initial_cash,
            "cost_model_reference": prepared.cost_model_reference,
            "account_truth_freshness_as_of": shadow_research_market_close_as_of(
                prepared.market_date,
                policy.after_close_time,
            ).isoformat(),
            "valuation_snapshot_id": str(valuation["snapshot_id"]),
            "ledger_cutoff_id": int(valuation["ledger_cutoff_id"]),
        }
        now_text = self._now().astimezone(timezone.utc).isoformat()
        run, reused = self._store.claim_run(
            market_date=prepared.market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=prepared.seed_result_id,
            valuation_snapshot_id=str(valuation["snapshot_id"]),
            ledger_cutoff_id=int(valuation["ledger_cutoff_id"]),
            now=now_text,
            timeout_resume_input_evidence={
                "baseline_fingerprint": prepared.fingerprint,
                "requested_by": f"automation:{policy.updated_by}",
                "account_alias": "standing-owner-authorized-shadow-research",
                "research_question": policy.research_question,
                "selection_components": selection_components,
            },
            corrected_panel_rearm_evidence=(
                self._optional_corrected_panel_rearm_evidence(prepared)
            ),
        )
        if reused:
            return {
                **self.status(),
                "run_status": run["status"],
                "run_id": run["run_id"],
                "reused": True,
            }

        try:
            baseline_result_id = int(run.get("baseline_result_id") or 0)
            if not baseline_result_id:
                baseline_result_id = self._store.save_baseline(
                    baseline_fingerprint=prepared.fingerprint,
                    request=prepared.request,
                    result=prepared.result,
                    now=now_text,
                )
                run = self._store.update_run(
                    run["run_id"], now=now_text, baseline_result_id=baseline_result_id
                )

            selection = StrategyResearchSelection(
                saved_backtest_result_id=baseline_result_id,
                **selection_components,
            )
            self._require_deepseek_provider()
            research = self._build_research_service(external=True)
            local_research = self._build_research_service(external=False)
            resume_iteration = int(run.get("partial_resume_iteration") or 1)
            resume_stage = str(run.get("partial_resume_stage") or "")
            provider_free_partial_resume_id = str(
                run.get("provider_free_partial_resume_id") or ""
            )
            first_critique_checkpoint: dict[str, Any] | None = None
            if provider_free_partial_resume_id:
                if resume_stage:
                    raise ShadowResearchRejected(
                        "provider_free_partial_resume_stage_conflict"
                    )
                checkpoint = self._store.load_provider_free_partial_resume_checkpoint(
                    str(run["run_id"]),
                    resume_id=provider_free_partial_resume_id,
                    expected_fingerprint=str(
                        run.get("partial_resume_evidence_fingerprint") or ""
                    ),
                )
                candidates = list(checkpoint["candidates"])
                valid_drafts = list(checkpoint["drafts"])
                previous_iteration = checkpoint["previous_iteration"]
                if (
                    len(candidates) != resume_iteration - 1
                    or len(valid_drafts) != resume_iteration - 1
                ):
                    raise ShadowResearchRejected(
                        "provider_free_partial_resume_completed_iteration_count_invalid"
                    )
            elif resume_stage == CORRECTED_PANEL_CITATION_RESUME_STAGE:
                if resume_iteration != CORRECTED_PANEL_CITATION_RESUME_ITERATION:
                    raise ShadowResearchRejected(
                        "corrected_panel_citation_resume_iteration_invalid"
                    )
                first_critique_checkpoint = (
                    self._store.load_first_critique_resume_checkpoint(
                        str(run["run_id"]),
                        expected_fingerprint=str(
                            run.get("partial_resume_evidence_fingerprint") or ""
                        ),
                    )
                )
                candidates: list[dict[str, Any]] = []
                valid_drafts: list[dict[str, Any]] = []
                previous_iteration: dict[str, Any] | None = None
            elif resume_iteration == 1:
                candidates = []
                valid_drafts = []
                previous_iteration = None
            else:
                if resume_iteration != TIMEOUT_RESUME_ITERATION:
                    raise ShadowResearchRejected("partial_resume_iteration_invalid")
                checkpoint = self._store.load_partial_resume_checkpoint(
                    str(run["run_id"]),
                    expected_fingerprint=str(
                        run.get("partial_resume_evidence_fingerprint") or ""
                    ),
                )
                candidates = list(checkpoint["candidates"])
                valid_drafts = list(checkpoint["drafts"])
                previous_iteration = checkpoint["previous_iteration"]
                if (
                    len(candidates) != TIMEOUT_RESUME_COMPLETED_ITERATIONS
                    or len(valid_drafts) != TIMEOUT_RESUME_COMPLETED_ITERATIONS
                ):
                    raise ShadowResearchRejected(
                        "partial_resume_completed_iteration_count_invalid"
                    )
            for iteration_number in range(
                resume_iteration, policy.max_candidates_per_run + 1
            ):
                self._require_provider_batch_deadline(batch_deadline_at)
                iteration_context = build_shadow_research_iteration_context(
                    iteration_number=iteration_number,
                    total_iterations=policy.max_candidates_per_run,
                    previous_iteration=previous_iteration,
                )
                completed_backtest: Mapping[str, Any] | None = None
                critique_resume_extension_id: str | None = None
                if first_critique_checkpoint is not None and iteration_number == 1:
                    if (
                        iteration_context
                        != first_critique_checkpoint["iteration_context"]
                    ):
                        raise ShadowResearchRejected(
                            "corrected_panel_citation_resume_iteration_context_drift"
                        )
                    hypotheses = dict(first_critique_checkpoint["hypotheses"])
                    draft = dict(first_critique_checkpoint["draft"])
                    completed_backtest = dict(
                        first_critique_checkpoint["completed_backtest"]
                    )
                    critique_resume_extension_id = str(
                        run.get("partial_resume_extension_id") or ""
                    )
                    if not critique_resume_extension_id:
                        raise ShadowResearchRejected(
                            "corrected_panel_citation_resume_extension_missing"
                        )
                else:
                    generation_run = run
                    if resume_stage == CORRECTED_PANEL_CITATION_RESUME_STAGE:
                        generation_run = {
                            **run,
                            "partial_resume_extension_id": None,
                            "partial_resume_iteration": None,
                            "partial_resume_stage": None,
                        }
                    hypotheses, draft = await self._generate_iteration_hypothesis(
                        run=generation_run,
                        policy=policy,
                        selection=selection,
                        external_research=research,
                        iteration_context=iteration_context,
                    )
                run = self._store.update_run(
                    run["run_id"],
                    now=self._utc_now(),
                    session_id=hypotheses["session_id"],
                )
                candidate = await self._run_candidate(
                    run=run,
                    policy=policy,
                    hypotheses=hypotheses,
                    draft=draft,
                    iteration_context=iteration_context,
                    baseline_result_id=baseline_result_id,
                    local_research=local_research,
                    external_research=research,
                    completed_backtest=completed_backtest,
                    critique_resume_extension_id=critique_resume_extension_id,
                )
                if candidate.get("status") not in {
                    "awaiting_human_approval",
                    "research_blocked",
                }:
                    raise ShadowResearchRejected("sequential_iteration_not_complete")
                candidates.append(candidate)
                valid_drafts.append(dict(draft))
                previous_iteration = {
                    "hypotheses": hypotheses,
                    "draft": draft,
                    "candidate": candidate,
                }
                self._require_provider_batch_deadline(batch_deadline_at)
            self._require_provider_batch_deadline(batch_deadline_at)
            terminal_status = (
                "completed"
                if candidates
                and all(
                    item["status"] in {"awaiting_human_approval", "research_blocked"}
                    for item in candidates
                )
                else "partial"
            )
            daily_artifacts: dict[str, Any] | None = None
            daily_artifact_failure: str | None = None
            try:
                daily_artifacts = self._daily_artifacts.record_daily_artifacts(
                    run=run,
                    candidates=candidates,
                    drafts=valid_drafts,
                    expected_candidate_count=policy.max_candidates_per_run,
                    run_status=terminal_status,
                    created_at=self._utc_now(),
                )
            except DailyStrategyArtifactRejected as exc:
                daily_artifact_failure = shadow_research_failure_code(exc)
                terminal_status = "partial"
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status=terminal_status,
                candidate_count=len(candidates),
                failure_code=(
                    daily_artifact_failure
                    or (
                        None
                        if terminal_status == "completed"
                        else "candidate_stage_partial"
                    )
                ),
            )
            await self._notify(prepared.market_date, candidates, daily_artifacts)
            return {
                **self.status(),
                "run_status": terminal_status,
                "run_id": run["run_id"],
                "reused": False,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "After-close AI shadow research failed closed", exc_info=True
            )
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status="failed",
                failure_code=shadow_research_failure_code(exc),
            )
            return {
                **self.status(),
                "run_status": "failed",
                "run_id": run["run_id"],
                "failure_code": shadow_research_failure_code(exc),
            }

    def _policy_preflight(self, policy: Any) -> dict[str, Any] | None:
        if not policy.enabled:
            return {**self.status(), "run_status": "disabled"}
        if self._kill_switch()["enabled"]:
            return self._record_preflight(
                status="blocked_by_kill_switch",
                failure_code="kill_switch_enabled",
            )
        if (
            policy.max_candidates_per_run == SHADOW_RESEARCH_MAX_CANDIDATES
            and policy.max_provider_calls_per_market_date
            == SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            and policy.daily_token_budget is None
        ):
            return None
        if (
            policy.daily_token_budget is not None
            and policy.authorization
            == SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION
        ):
            return None
        return self._record_preflight(
            status="blocked_by_policy",
            failure_code=(
                "unbounded_daily_token_policy_not_authorized"
                if policy.daily_token_budget is not None
                else "five_sequential_iterations_not_authorized"
            ),
        )
