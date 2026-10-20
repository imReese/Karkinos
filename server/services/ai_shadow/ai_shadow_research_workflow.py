"""After-close AI shadow research orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timezone
from typing import Any

from analytics.normalized_research_gate import baseline_research_evidence_blockers
from analytics.strategy_advancement_gate import strategy_advancement_backtest_view
from core.types import BarFrequency
from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.provider_call_window import (
    ProviderCallDeferred,
    ProviderExecutionFenced,
)
from server.ai_runtime.strategy_research import StrategyResearchSelection
from server.contracts.ai_shadow_research_automation import (
    CORRECTED_PANEL_CITATION_RESUME_ITERATION,
    CORRECTED_PANEL_CITATION_RESUME_STAGE,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
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
from server.contracts.strategy_research import STRATEGY_RESEARCH_PROMPT_VERSION
from server.services.account.reviewed_fee_schedule import (
    ReviewedFeeScheduleReadRejected,
    ReviewedFeeScheduleRejected,
)
from server.services.ai_shadow.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
)
from server.services.ai_shadow.ai_shadow_research_support import (
    is_after_shadow_research_close,
    shadow_research_failure_code,
    shadow_research_market_close_as_of,
)

logger = logging.getLogger(__name__)


class AiShadowResearchWorkflowMixin:
    def _research_validation_grant(self, policy):
        from server.contracts.research_observation_automation import (
            read_research_validation_policy,
        )

        try:
            return read_research_validation_policy(self._db, now=self._now()), None
        except ValueError as exc:
            if policy.simulation_validation is not None:
                return None, {
                    **self.status(),
                    "run_status": "awaiting_independent_validation",
                    "failure_code": str(exc),
                    "provider_call_performed": False,
                }
            return None, None

    async def _formal_warmup_preflight(self, policy, grant, *, window_closed=False):
        if (
            not grant
            or grant.get("schema_version") != "karkinos.research_simulation_policy.v1"
        ):
            return None
        from server.services.research.datasets import ensure_forward_seed_for_source

        try:
            source = await asyncio.to_thread(
                self._validation_seed_source, policy, grant
            )
            if window_closed and self._validation_seed_prepared(source):
                return None
            seed = await asyncio.to_thread(
                ensure_forward_seed_for_source,
                self._db,
                self._state.require_config(),
                source=source,
                now=self._now(),
                data_store=self._data_store,
            )
        except ValueError as exc:
            return self._record_preflight(
                status="blocked_by_market_evidence",
                failure_code=shadow_research_failure_code(exc),
            )
        if seed.get("status") != "ready":
            return {
                **self.status(),
                "run_status": "awaiting_verified_research_inputs",
                "forward_validation": seed,
                "provider_call_performed": False,
            }
        return None

    async def _forward_validation_preflight(self, grant) -> dict[str, Any] | None:
        if grant:
            pending = self._open_deployment_reservation(grant)
            if pending:
                from data.storage.objects import ContentAddressedObjectStore
                from server.services.research_observation_automation import (
                    start_reserved_champion_observation,
                )

                objects = ContentAddressedObjectStore(
                    self._db.path.parent / "research" / "objects"
                )
                forward = await start_reserved_champion_observation(
                    self._db,
                    objects,
                    source_result_id=pending["evidence"]["reservation"][
                        "candidate_result_id"
                    ],
                    grant=grant,
                    now=self._now(),
                    config=self._state.require_config(),
                    reservation_id=pending["sealed_test_id"],
                )
                if (
                    pending.get("evidence", {})
                    .get("reservation", {})
                    .get("simulation_policy")
                    and forward.get("status") == "ready"
                ):
                    try:
                        evaluation = await self._evaluate_independent_simulation(
                            pending
                        )
                    except ValueError as exc:
                        forward = {
                            **forward,
                            "final_status": "waiting",
                            "final_blocker": str(exc),
                        }
                    else:
                        return {
                            **self.status(),
                            "run_status": "completed",
                            "validation_status": "completed",
                            "final_evaluation": evaluation,
                            "provider_call_performed": False,
                        }
                return {
                    **self.status(),
                    "run_status": "awaiting_independent_validation",
                    "provider_call_performed": False,
                    "forward_validation": forward,
                    "sealed_test_id": pending["sealed_test_id"],
                }
        return None

    async def _evaluate_independent_simulation(self, reserved):
        """Final inference uses the frozen research source, never account readiness."""
        from server.services.research_final_evaluation import evaluate_reserved_champion

        store, source, adapter = self._independent_simulation_inputs(reserved)
        return await evaluate_reserved_champion(
            research_store=store,
            source=source,
            adapter=adapter,
            now=self._now(),
            calendar_db=self._db,
        )

    async def _verified_seed_preflight(self, prepared, grant) -> dict[str, Any] | None:
        scope = (
            prepared.result.get("metrics_json", {})
            .get("market_universe_truth", {})
            .get("deployment_scope")
        )
        if grant and scope:
            from data.storage.objects import ContentAddressedObjectStore
            from server.services.research.datasets import ensure_forward_seed_for_source
            from server.services.research_observation_inputs import (
                load_research_observation_source,
            )

            objects = ContentAddressedObjectStore(
                self._db.path.parent / "research" / "objects"
            )
            seed_row = {
                "id": prepared.seed_result_id,
                "config_json": prepared.request.model_dump(mode="json"),
                "metrics_json": prepared.result["metrics_json"],
            }
            seed_source = load_research_observation_source(
                seed_row, objects, allow_unbound_dataset=True
            )
            seed_source["source_selection"] = {
                "deployment_scope": scope,
                "portfolio_policy_id": scope["portfolio_policy_id"],
                "start_date": prepared.request.start_date,
                "end_date": prepared.request.end_date,
            }
            seed_source["start_date"] = prepared.request.start_date
            seed_source["end_date"] = prepared.request.end_date
            seed_source["forward_minimum_observations"] = grant["statistical_policy"][
                "minimum_observations"
            ]
            seed_source["minimum_bars"] = scope["universe_policy"][
                "minimum_history_rows"
            ]
            seed = await asyncio.to_thread(
                ensure_forward_seed_for_source,
                self._db,
                self._state.require_config(),
                source=seed_source,
                now=self._now(),
                data_store=self._data_store,
            )
            if seed.get("status") != "ready":
                return {
                    **self.status(),
                    "run_status": "awaiting_verified_research_inputs",
                    "forward_validation": seed,
                    "provider_call_performed": False,
                }
        return None

    async def _prepare_validation_baseline(self, policy, grant):
        board = (
            {
                "entry_board_policy": grant["entry_board_policy"],
                "initial_cash_override": float(grant["initial_cash"]),
            }
            if grant
            and grant.get("schema_version") == "karkinos.research_simulation_policy.v1"
            else {}
        )
        return await asyncio.to_thread(self._prepare_baseline, policy, **board)

    async def run_once(self) -> dict[str, Any]:
        from data.dataset.reader import daily_bar_dataset_read_scope

        with daily_bar_dataset_read_scope(join_existing=True):
            return await self._run_once_with_inputs()

    async def _run_once_with_inputs(self) -> dict[str, Any]:
        policy = self.get_policy()
        preflight = self._policy_preflight(policy)
        if preflight is not None:
            return preflight

        # Preserve a real future holdout: unrelated market capture continues,
        # but no overlapping model research may inspect its reserved interval.
        grant, validation_blocker = self._research_validation_grant(policy)
        if validation_blocker is not None:
            return validation_blocker
        if forward_preflight := await self._forward_validation_preflight(grant):
            return forward_preflight
        if policy.research_end_date is not None and (
            self._now().astimezone(SHADOW_RESEARCH_TIMEZONE).date().isoformat()
            > policy.research_end_date
        ):
            return {
                **self.status(),
                "run_status": "research_window_frozen",
                "provider_call_performed": False,
                "sealed_end_date": policy.sealed_end_date,
            }
        independent_simulation = bool(
            grant
            and grant.get("schema_version") == "karkinos.research_simulation_policy.v1"
        )
        if not independent_simulation:
            self._require_deepseek_provider()
        provider_window_preflight, batch_deadline_at = (
            self._provider_batch_window_admission()
        )
        if warmup := await self._formal_warmup_preflight(
            policy, grant, window_closed=provider_window_preflight is not None
        ):
            return warmup
        if independent_simulation:
            self._require_deepseek_provider()
        if provider_window_preflight is not None:
            return provider_window_preflight

        try:
            prepared = await self._prepare_validation_baseline(policy, grant)
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
        if deadline_preflight := self._batch_deadline_preflight(batch_deadline_at):
            return deadline_preflight
        if seed_preflight := await self._verified_seed_preflight(prepared, grant):
            return seed_preflight
        if research_preflight := self._normalized_baseline_research_preflight(
            policy=policy,
            prepared=prepared,
        ):
            return research_preflight
        if close_preflight := self._market_close_preflight(policy, prepared):
            return close_preflight

        research_context, context_preflight = await self._research_context_for_run(
            policy=policy,
            prepared=prepared,
            batch_deadline_at=batch_deadline_at,
        )
        if context_preflight is not None:
            return context_preflight
        assert research_context is not None
        account_bound = research_context["account_fact_binding_present"] is True

        input_fingerprint = content_fingerprint(
            {
                "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
                "prompt_version": STRATEGY_RESEARCH_PROMPT_VERSION,
                "policy": policy.to_dict(),
                **self._provider_window_input_evidence(batch_deadline_at),
                "baseline_fingerprint": prepared.fingerprint,
                "research_context": research_context,
                "publication_entry_board_policy": grant.get("entry_board_policy")
                if grant
                else None,
            }
        )
        selection_components = self._selection_components(
            policy=policy,
            prepared=prepared,
            research_context=research_context,
            account_bound=account_bound,
        )
        now_text = self._now().astimezone(timezone.utc).isoformat()
        run, reused = self._store.claim_run(
            market_date=prepared.market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=prepared.seed_result_id,
            research_capital_mode=str(research_context["research_capital_mode"]),
            research_context_id=str(research_context["context_id"]),
            valuation_snapshot_id=(
                str(research_context["valuation_snapshot_id"])
                if account_bound
                else None
            ),
            ledger_cutoff_id=int(research_context["ledger_cutoff_id"]),
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
                    "evaluated_research_only",
                    "research_blocked",
                }:
                    raise ShadowResearchRejected(
                        candidate.get("comparison", {}).get("failure_code")
                        or "sequential_iteration_not_complete"
                    )
                candidates.append(candidate)
                valid_drafts.append(dict(draft))
                previous_iteration = {
                    "hypotheses": hypotheses,
                    "draft": draft,
                    "candidate": candidate,
                }
                self._require_provider_batch_deadline(batch_deadline_at)
            self._require_provider_batch_deadline(batch_deadline_at)
            return await self._finish_research_run(
                run=run,
                candidates=candidates,
                drafts=valid_drafts,
                expected_candidate_count=policy.max_candidates_per_run,
                selection=selection,
                local_research=local_research,
                market_date=prepared.market_date,
            )
        except asyncio.CancelledError:
            raise
        except ProviderCallDeferred as exc:
            failure_code = shadow_research_failure_code(exc)
            self._store.update_run(
                run["run_id"],
                now=self._utc_now(),
                status="deferred_for_provider_off_peak",
                failure_code=failure_code,
            )
            deferred = self._record_preflight(
                status="deferred_for_provider_off_peak",
                failure_code=failure_code,
                market_date=prepared.market_date,
                evidence=exc.decision.to_dict(),
            )
            return {
                **deferred,
                "run_id": run["run_id"],
                "reused": False,
            }
        except ProviderExecutionFenced:
            raise
        except Exception as exc:
            logger.warning(
                "After-close AI shadow research failed closed", exc_info=True
            )
            self._require_execution_current()
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

    async def _finish_research_run(
        self,
        *,
        run: Mapping[str, Any],
        candidates: list[dict[str, Any]],
        drafts: list[dict[str, Any]],
        expected_candidate_count: int,
        selection: StrategyResearchSelection,
        local_research: Any,
        market_date: str,
    ) -> dict[str, Any]:
        # Only complete local evaluations are appended by the iteration loop.
        terminal_status = (
            "completed" if len(candidates) == expected_candidate_count else "partial"
        )
        daily_artifacts: dict[str, Any] | None = None
        daily_artifact_failure: str | None = None
        try:
            self._require_execution_current()
            daily_artifacts = self._daily_artifacts.record_daily_artifacts(
                run=run,
                candidates=candidates,
                drafts=drafts,
                expected_candidate_count=expected_candidate_count,
                run_status=terminal_status,
                created_at=self._utc_now(),
            )
            if selection.has_sealed_holdout:
                from server.services.research_final_evaluation import (
                    reserve_final_research_evaluation,
                )

                reservation = await reserve_final_research_evaluation(
                    db=self._db,
                    research_store=local_research._research_store,
                    run=run,
                    selection=selection,
                    candidates=candidates,
                    daily_selection=daily_artifacts["selection"],
                    now=self._utc_now(),
                    reviewed_fee_schedule_resolver=self._reviewed_fee_schedule_resolver,
                    account_config=self._state.require_config(),
                )
                if (
                    reservation
                    and reservation.get("evidence", {})
                    .get("reservation", {})
                    .get("publication_grant")
                    or reservation
                    and reservation.get("evidence", {})
                    .get("reservation", {})
                    .get("simulation_policy")
                ):
                    from data.storage.objects import ContentAddressedObjectStore
                    from server.services.research_observation_automation import (
                        start_reserved_champion_observation,
                    )

                    objects = ContentAddressedObjectStore(
                        self._db.path.parent / "research" / "objects"
                    )
                    await start_reserved_champion_observation(
                        self._db,
                        objects,
                        source_result_id=reservation["evidence"]["reservation"][
                            "candidate_result_id"
                        ],
                        grant=reservation["evidence"]["reservation"].get(
                            "simulation_policy"
                        )
                        or reservation["evidence"]["reservation"]["publication_grant"],
                        now=self._now(),
                        config=self._state.require_config(),
                        reservation_id=reservation["sealed_test_id"],
                    )
        except DailyStrategyArtifactRejected as exc:
            daily_artifact_failure = shadow_research_failure_code(exc)
            terminal_status = "partial"
        self._require_execution_current()
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
        await self._notify(market_date, candidates, daily_artifacts)
        return {
            **self.status(),
            "run_status": terminal_status,
            "run_id": run["run_id"],
            "reused": False,
        }

    def _market_close_preflight(
        self,
        policy: Any,
        prepared: Any,
    ) -> dict[str, Any] | None:
        now_dt = self._now().astimezone(SHADOW_RESEARCH_TIMEZONE)
        if is_after_shadow_research_close(
            prepared.market_date,
            now_dt,
            policy.after_close_time,
        ):
            return None
        return {
            **self.status(),
            "run_status": "waiting_for_market_close",
            "market_date": prepared.market_date,
        }

    def _normalized_baseline_research_preflight(
        self,
        *,
        policy: Any,
        prepared: Any,
    ) -> dict[str, Any] | None:
        if (
            policy.research_capital_mode
            != SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
        ):
            return None
        blockers = baseline_research_evidence_blockers(
            strategy_advancement_backtest_view(prepared.result)
        )
        if not blockers:
            return None
        return self._record_preflight(
            status="blocked_by_research_evidence",
            failure_code=blockers[0],
            market_date=prepared.market_date,
            evidence={"blockers": blockers},
        )

    def _selection_components(
        self,
        *,
        policy: Any,
        prepared: Any,
        research_context: Mapping[str, Any],
        account_bound: bool,
    ) -> dict[str, Any]:
        truth = prepared.result.get("metrics_json", {}).get("market_universe_truth", {})
        scope = truth.get("deployment_scope")
        simulation = policy.simulation_validation or {}
        sealed_end = policy.sealed_end_date
        if scope and not sealed_end:
            from datetime import date, timedelta

            from server.contracts.research_observation_automation import (
                read_research_validation_policy,
            )

            try:
                grant = read_research_validation_policy(self._db, now=self._now())
            except ValueError:
                grant = None
            if grant:
                profile = grant["statistical_policy"]
                checkpoint = date.fromisoformat(profile["decision_checkpoint"])
                interval = int(profile.get("checkpoint_interval_days", 0))
                cutoff = max(
                    date.fromisoformat(prepared.request.end_date), self._now().date()
                )
                if checkpoint <= cutoff and interval <= 0:
                    raise ShadowResearchRejected("deployment_checkpoint_expired")
                while checkpoint <= cutoff:
                    checkpoint += timedelta(days=interval)
                sealed_end = checkpoint.isoformat()
        return {
            **(
                {
                    "deployment_scope": scope,
                    "portfolio_policy_id": scope["portfolio_policy_id"],
                }
                if scope
                else {}
            ),
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
            **({"sealed_end_date": sealed_end} if sealed_end else {}),
            "initial_cash": prepared.request.initial_cash,
            **(
                {
                    "simulation_validation_binding": {
                        key: simulation[key]
                        for key in ("grant_id", "generation", "initial_cash")
                    }
                }
                if simulation.get("enabled") is True
                else {}
            ),
            "cost_model_reference": prepared.cost_model_reference,
            "account_truth_freshness_as_of": (
                shadow_research_market_close_as_of(
                    prepared.market_date,
                    policy.after_close_time,
                ).isoformat()
                if account_bound
                else None
            ),
            "valuation_snapshot_id": (
                str(research_context["valuation_snapshot_id"])
                if account_bound
                else None
            ),
            "ledger_cutoff_id": (
                int(research_context["ledger_cutoff_id"]) if account_bound else None
            ),
        }

    async def _research_context_for_run(
        self,
        *,
        policy: Any,
        prepared: Any,
        batch_deadline_at: Any,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if (
            policy.research_capital_mode
            == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
        ):
            return self._nominal_research_binding(prepared), None
        try:
            valuation = await asyncio.to_thread(self._build_current_valuation_snapshot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return None, self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code=shadow_research_failure_code(exc),
                market_date=prepared.market_date,
            )
        if deadline_preflight := self._batch_deadline_preflight(batch_deadline_at):
            return None, deadline_preflight
        if valuation.get("status") != "complete":
            return None, self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_snapshot_not_complete",
                market_date=prepared.market_date,
            )
        if str(valuation.get("trade_date")) != prepared.market_date:
            return None, self._record_preflight(
                status="blocked_by_account_evidence",
                failure_code="valuation_market_date_mismatch",
                market_date=prepared.market_date,
            )
        return {
            "schema_version": "karkinos.ai.account_bound_research_context.v1",
            "research_capital_mode": policy.research_capital_mode,
            "context_id": str(valuation["snapshot_id"]),
            "valuation_snapshot_id": str(valuation["snapshot_id"]),
            "ledger_cutoff_id": int(valuation["ledger_cutoff_id"]),
            "account_fact_binding_present": True,
        }, None

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
