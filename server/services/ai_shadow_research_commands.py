"""Policy commands and human-only promotion workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_API_SCHEMA,
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_ID,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
    ShadowResearchPolicy,
    ShadowResearchRejected,
)
from server.projections.ai_shadow_research import (
    project_shadow_research_candidate_status,
)
from server.services.ai_shadow_research_daily_artifacts import (
    build_daily_strategy_promotion_binding,
)


class AiShadowResearchCommandsMixin:
    def get_policy(self) -> ShadowResearchPolicy:
        stored = self._db.get_automation_policy_sync(SHADOW_RESEARCH_POLICY_ID)
        return ShadowResearchPolicy.from_mapping(stored)

    def update_policy(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get_policy().to_dict()
        merged = {**current, **dict(patch)}
        merged["token_budget_mode"] = (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if merged.get("daily_token_budget") is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
        )
        enabled = bool(merged.get("enabled", False))
        confirmation = str(merged.pop("confirmation", "") or "")
        if enabled:
            if merged.get("daily_token_budget") is not None:
                if confirmation != SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION:
                    raise PermissionError(
                        "bounded daily token policy requires exact legacy authorization"
                    )
                merged["authorization"] = (
                    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION
                )
            else:
                if confirmation != SHADOW_RESEARCH_POLICY_CONFIRMATION:
                    raise PermissionError(
                        "standing shadow research requires exact owner authorization"
                    )
                merged["authorization"] = SHADOW_RESEARCH_POLICY_CONFIRMATION
        else:
            if confirmation != SHADOW_RESEARCH_PAUSE_CONFIRMATION:
                raise PermissionError(
                    "pausing shadow research requires exact confirmation"
                )
            merged["authorization"] = ""
        policy = ShadowResearchPolicy.from_mapping(merged)
        saved = self._db.upsert_automation_policy_sync(
            policy_id=SHADOW_RESEARCH_POLICY_ID,
            payload=policy.to_dict(),
            updated_by=policy.updated_by,
        )
        return {
            **policy.to_dict(),
            "created_at": saved.get("created_at"),
            "updated_at": saved.get("updated_at"),
        }

    def status(self) -> dict[str, Any]:
        policy = self.get_policy()
        runs = self._store.list_runs(limit=20)
        candidates = [
            project_shadow_research_candidate_status(candidate)
            for candidate in self._store.list_candidates(limit=50)
        ]
        daily_selections = self._daily_artifacts.list_selections(limit=20)
        daily_backups = self._daily_artifacts.list_backups(limit=20)
        superseded_daily_selections = self._daily_artifacts.list_superseded_selections(
            limit=20
        )
        superseded_daily_backups = self._daily_artifacts.list_superseded_backups(
            limit=20
        )
        latest_market_date = runs[0]["market_date"] if runs else None
        kill_switch = self._kill_switch()
        latest_selection = daily_selections[0] if daily_selections else None
        latest_backup = daily_backups[0] if daily_backups else None
        daily_winner_candidate_id = None
        if (
            latest_selection
            and latest_backup
            and latest_selection.get("integrity_status") == "verified"
            and latest_selection.get("status") == "winner_selected"
            and latest_backup.get("verification_status") == "verified"
            and latest_backup.get("run_id") == latest_selection.get("run_id")
        ):
            daily_winner_candidate_id = latest_selection.get("winner_candidate_id")
        research_outcome = {
            "status": (
                "new_candidate_available_for_human_review"
                if daily_winner_candidate_id
                else "no_new_candidate_current_strategy_unchanged"
            ),
            "new_candidate_winner_id": daily_winner_candidate_id,
            "incumbent_strategy_policy": (
                "leave_current_human_approved_strategy_unchanged"
            ),
            "incumbent_strategy_state_changed": False,
            "daily_trading_decision_status": "not_evaluated",
            "implies_daily_trading_no_action": False,
        }
        provider_call_window = self._provider_call_window_status()
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
            "policy": policy.to_dict(),
            "kill_switch": kill_switch,
            "usage": self._store.usage_for_market_date(latest_market_date),
            "runs": runs,
            "candidates": candidates,
            "daily_selections": daily_selections,
            "daily_backups": daily_backups,
            "superseded_daily_selections": superseded_daily_selections,
            "superseded_daily_backups": superseded_daily_backups,
            "daily_new_candidate_winner_id": daily_winner_candidate_id,
            "daily_winner_candidate_id": daily_winner_candidate_id,
            "research_outcome": research_outcome,
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
            "authority_effect": "research_only",
            **(
                {"provider_call_window": provider_call_window}
                if provider_call_window is not None
                else {}
            ),
        }

    def readiness_status(self) -> dict[str, Any]:
        """Return the bounded policy projection used by local readiness checks."""
        provider_call_window = self._provider_call_window_status()
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
            "policy": self.get_policy().to_dict(),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "human_paper_shadow_approval_required": True,
            "authority_effect": "research_only",
            **(
                {"provider_call_window": provider_call_window}
                if provider_call_window is not None
                else {}
            ),
        }

    def authorize_retry(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_retry(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    async def authorize_corrected_panel_rearm(
        self,
        completed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        policy = self.get_policy()
        if (
            not policy.enabled
            or policy.max_candidates_per_run != SHADOW_RESEARCH_MAX_CANDIDATES
            or policy.max_provider_calls_per_market_date
            != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            or policy.daily_token_budget is not None
        ):
            raise ShadowResearchRejected(
                "corrected_panel_rearm_requires_complete_enabled_policy"
            )
        prepared = await asyncio.to_thread(self._prepare_baseline, policy)
        rearm_evidence = self._build_corrected_panel_rearm_evidence(prepared)
        return await asyncio.to_thread(
            self._store.authorize_corrected_panel_rearm,
            completed_run_id,
            rearm_evidence=rearm_evidence,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_timeout_resume_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_timeout_resume_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    async def authorize_corrected_panel_citation_resume_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        policy = self.get_policy()
        if (
            not policy.enabled
            or policy.max_candidates_per_run != SHADOW_RESEARCH_MAX_CANDIDATES
            or policy.max_provider_calls_per_market_date
            != SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            or policy.daily_token_budget is not None
        ):
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_requires_complete_enabled_policy"
            )
        prepared = await asyncio.to_thread(self._prepare_baseline, policy)
        rearm_evidence = self._build_corrected_panel_rearm_evidence(prepared)
        return await asyncio.to_thread(
            self._store.authorize_corrected_panel_citation_resume_extension,
            failed_run_id,
            rearm_evidence=rearm_evidence,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_output_truncation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_output_truncation_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def authorize_citation_call_extension(
        self,
        failed_run_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        return self._store.authorize_citation_call_extension(
            failed_run_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        candidate = self._store.get_candidate(candidate_id)
        daily_artifacts = self._daily_artifacts.require_verified_winner(
            candidate_id=candidate_id,
            run_id=str(candidate.get("run_id") or ""),
        )
        daily_strategy_artifact_binding = build_daily_strategy_promotion_binding(
            daily_artifacts
        )
        approval = self._store.approve_candidate(
            candidate_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=self._utc_now(),
        )
        candidate = self._store.get_candidate(candidate_id)
        candidate_result_id = int(candidate.get("candidate_result_id") or 0)
        if not candidate_result_id:
            raise ShadowResearchRejected("candidate_backtest_result_missing")
        strategy_id = f"ai_formula_shadow:{candidate_id}"
        readiness = {
            "schema_version": "karkinos.ai.shadow_research_promotion_readiness.v1",
            "strategy_id": strategy_id,
            "promotion_status": "promotable_for_paper_review",
            "is_promotable": True,
            "missing_requirements": [],
            "backtest_result_id": candidate_result_id,
            "candidate_id": candidate_id,
            "critique_id": candidate.get("critique_id"),
            "comparison_fingerprint": content_fingerprint(candidate["comparison"]),
            "human_approval_id": approval["promotion_id"],
            "strategy_advancement_gate": candidate["comparison"]["promotion_gate"],
            "daily_strategy_artifact_binding": daily_strategy_artifact_binding,
            "live_like_enabled": False,
            "broker_submission_enabled": False,
        }
        from server.services.strategy_promotion_pipeline import (
            STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            StrategyPromotionPipeline,
        )

        pipeline = StrategyPromotionPipeline(db=self._db)
        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        if current is not None and str(current.get("stage")) == "paper_shadow":
            if (
                bool(current.get("live_like_enabled"))
                or int(current.get("backtest_result_id") or 0) != candidate_result_id
            ):
                raise ShadowResearchRejected("canonical_paper_shadow_stage_conflict")
            promotion_state = next(
                item
                for item in pipeline.list_states()
                if item["strategy_id"] == strategy_id
            )
            current_readiness = promotion_state.get("payload", {}).get("readiness")
            current_readiness = (
                current_readiness if isinstance(current_readiness, dict) else {}
            )
            if (
                current_readiness.get("daily_strategy_artifact_binding")
                != daily_strategy_artifact_binding
            ):
                raise ShadowResearchRejected(
                    "canonical_paper_shadow_daily_artifact_binding_conflict"
                )
        else:
            pipeline.evaluate_readiness(readiness, actor=approved_by.strip())
            promotion_state = pipeline.request_promotion(
                strategy_id,
                target_stage="paper_shadow",
                readiness=readiness,
                actor=approved_by.strip(),
                confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
                review_note=notes.strip(),
            )
        self._store.finalize_candidate_paper_shadow_stage(
            candidate_id,
            strategy_promotion=promotion_state,
            now=self._utc_now(),
        )
        return {
            **approval,
            "strategy_id": strategy_id,
            "strategy_promotion": promotion_state,
            "paper_shadow_stage_recorded": True,
            "production_strategy_replaced": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
            "daily_selection": daily_artifacts["selection"],
            "daily_backup": daily_artifacts["backup"],
        }
