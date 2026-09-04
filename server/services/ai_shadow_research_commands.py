"""Policy commands and human-only promotion workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_API_SCHEMA,
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_ID,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    SHADOW_RESEARCH_TIMEZONE,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
    ShadowResearchPolicy,
    ShadowResearchRejected,
)
from server.projections.ai_shadow_research import (
    project_shadow_research_candidate_status,
)
from server.projections.normalized_research_recommendation import (
    is_valid_normalized_research_recommendation,
)
from server.services.ai_shadow_research_daily_artifacts import (
    build_daily_strategy_promotion_binding,
)
from server.services.ai_shadow_research_qualification_support import (
    latest_qualification_attempt as read_latest_qualification_attempt,
)
from server.services.strategy_promotion_support import (
    AI_SHADOW_QUALIFICATION_READINESS_SCHEMA,
    STRATEGY_PROMOTION_SCHEMA_VERSION,
    lifecycle_metadata,
    resolve_ai_shadow_qualification_promotion_evidence,
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
                expected_confirmation = (
                    SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION
                    if merged.get("research_capital_mode")
                    == SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND
                    else SHADOW_RESEARCH_POLICY_CONFIRMATION
                )
                if confirmation != expected_confirmation:
                    raise PermissionError(
                        "standing shadow research requires exact owner authorization"
                    )
                merged["authorization"] = expected_confirmation
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
        qualification_runs = self._store.list_public_qualification_runs(limit=20)
        qualification_candidates = [
            candidate
            for qualification_run in qualification_runs
            for candidate in self._store.list_public_qualification_candidates(
                str(qualification_run["qualification_run_id"])
            )
        ]
        qualification_approvals = [
            approval
            for candidate in qualification_candidates
            if (
                approval := self._store.get_qualification_approval(
                    str(candidate["qualification_candidate_id"])
                )
            )
            is not None
        ]
        latest_market_date = runs[0]["market_date"] if runs else None
        kill_switch = self._kill_switch()
        latest_selection = daily_selections[0] if daily_selections else None
        latest_backup = daily_backups[0] if daily_backups else None
        latest_qualification_attempt = None
        daily_winner_candidate_id = None
        daily_research_winner_candidate_id = None
        current_source_pair_verified = bool(
            latest_selection
            and latest_backup
            and latest_selection.get("integrity_status") == "verified"
            and latest_backup.get("verification_status") == "verified"
            and latest_backup.get("run_id") == latest_selection.get("run_id")
            and latest_selection.get("run_id")
            and latest_selection.get("market_date")
            and latest_selection.get("selection_id")
            and latest_selection.get("selection_fingerprint")
            and latest_backup.get("artifact_fingerprint")
        )
        if (
            current_source_pair_verified
            and latest_selection.get("status") == "winner_selected"
        ):
            daily_winner_candidate_id = latest_selection.get("winner_candidate_id")
        if current_source_pair_verified:
            latest_qualification_attempt = read_latest_qualification_attempt(
                self._db,
                source_run_id=str(latest_selection.get("run_id") or ""),
                market_date=str(latest_selection.get("market_date") or ""),
                source_selection_id=str(latest_selection.get("selection_id") or ""),
                source_selection_fingerprint=str(
                    latest_selection.get("selection_fingerprint") or ""
                ),
                source_backup_fingerprint=str(
                    latest_backup.get("artifact_fingerprint") or ""
                ),
            )
            research_recommendation = latest_selection.get("research_recommendation")
            if (
                isinstance(research_recommendation, Mapping)
                and is_valid_normalized_research_recommendation(research_recommendation)
                and research_recommendation.get("status")
                == "best_available_for_further_research"
                and research_recommendation.get("account_qualified") is False
                and research_recommendation.get("promotion_eligible") is False
                and research_recommendation.get("authority_effect") == "none"
            ):
                daily_research_winner_candidate_id = research_recommendation.get(
                    "research_winner_candidate_id"
                )
        latest_qualification = (
            next(
                (
                    item
                    for item in qualification_runs
                    if item.get("source_run_id") == latest_selection.get("run_id")
                    and item.get("market_date") == latest_selection.get("market_date")
                    and item.get("source_selection_id")
                    == latest_selection.get("selection_id")
                    and item.get("source_selection_fingerprint")
                    == latest_selection.get("selection_fingerprint")
                    and item.get("source_backup_fingerprint")
                    == latest_backup.get("artifact_fingerprint")
                ),
                None,
            )
            if current_source_pair_verified
            else None
        )
        if latest_qualification is not None:
            latest_qualification_attempt = None
        winner_qualification_candidate_id = (
            latest_qualification.get("winner_qualification_candidate_id")
            if latest_qualification
            else None
        )
        account_qualification_status = (
            {
                "completed": "passed",
                "blocked": "blocked",
                "failed": "failed",
                "running": "running",
            }.get(str(latest_qualification.get("status") or ""), "not_evaluated")
            if latest_qualification
            else (
                str(latest_qualification_attempt["status"])
                if latest_qualification_attempt is not None
                else (
                    "not_evaluated"
                    if daily_research_winner_candidate_id
                    else "not_applicable"
                )
            )
        )
        research_outcome = {
            "status": (
                "new_candidate_available_for_human_review"
                if daily_winner_candidate_id
                else (
                    "best_available_formula_for_further_research"
                    if daily_research_winner_candidate_id
                    else "no_new_candidate_current_strategy_unchanged"
                )
            ),
            "new_candidate_winner_id": daily_winner_candidate_id,
            "research_winner_candidate_id": daily_research_winner_candidate_id,
            "account_qualification_status": account_qualification_status,
            "qualification_run_id": (
                latest_qualification.get("qualification_run_id")
                if latest_qualification
                else None
            ),
            "winner_qualification_candidate_id": (winner_qualification_candidate_id),
            "incumbent_strategy_policy": (
                "leave_current_human_approved_strategy_unchanged"
            ),
            "incumbent_strategy_state_changed": False,
            "daily_trading_decision_status": "not_evaluated",
            "implies_daily_trading_no_action": False,
        }
        provider_call_window = self._provider_call_window_status()
        now_reader = getattr(self, "_now", None)
        observed_at = (
            now_reader() if callable(now_reader) else datetime.now(timezone.utc)
        )
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        local_date = observed_at.astimezone(SHADOW_RESEARCH_TIMEZONE).date().isoformat()
        activity_reader = getattr(self._store, "provider_activity_for_local_date", None)
        today_provider_activity = (
            activity_reader(
                local_date,
                timezone_name=str(SHADOW_RESEARCH_TIMEZONE.key),
            )
            if callable(activity_reader)
            else {
                "schema_version": "karkinos.ai.provider_local_day_activity.v1",
                "local_date": local_date,
                "timezone": str(SHADOW_RESEARCH_TIMEZONE.key),
                "provider_calls": 0,
                "recorded_call_attempts": 0,
                "provider_free_rejections": 0,
                "last_attempt_at": None,
                "last_attempt_updated_at": None,
                "last_attempt_status": None,
                "last_attempt_failure_code": None,
                "last_attempt_kind": None,
                "last_attempt_market_date": None,
                "last_provider_call_at": None,
                "last_provider_call_market_date": None,
                "read_only": True,
                "provider_contact_performed": False,
                "database_writes_performed": False,
                "authority_effect": "none",
            }
        )
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "runtime_contract": SHADOW_RESEARCH_RUNTIME_CONTRACT,
            "policy": policy.to_dict(),
            "kill_switch": kill_switch,
            "usage": self._store.usage_for_market_date(latest_market_date),
            "today_provider_activity": today_provider_activity,
            "runs": runs,
            "candidates": candidates,
            "daily_selections": daily_selections,
            "daily_backups": daily_backups,
            "superseded_daily_selections": superseded_daily_selections,
            "superseded_daily_backups": superseded_daily_backups,
            "qualification_runs": qualification_runs,
            "qualification_candidates": qualification_candidates,
            "qualification_approvals": qualification_approvals,
            "latest_qualification_attempt": latest_qualification_attempt,
            "daily_new_candidate_winner_id": daily_winner_candidate_id,
            "daily_winner_candidate_id": daily_winner_candidate_id,
            "daily_research_winner_candidate_id": (daily_research_winner_candidate_id),
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
        comparison = candidate.get("comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        if (
            comparison.get("research_capital_mode") == "normalized_notional"
            or comparison.get("account_qualification_status") == "not_evaluated"
        ):
            raise ShadowResearchRejected("candidate_account_qualification_required")
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
            "strategy_promotion_state_recorded": True,
            "production_strategy_replaced": False,
            "production_strategy_registry_mutated": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
            "daily_selection": daily_artifacts["selection"],
            "daily_backup": daily_artifacts["backup"],
        }

    def approve_qualification_candidate(
        self,
        qualification_candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
    ) -> dict[str, Any]:
        timestamp = self._utc_now()
        approval = self._store.prepare_qualification_candidate_approval(
            qualification_candidate_id,
            approved_by=approved_by,
            notes=notes,
            confirmation=confirmation,
            now=timestamp,
        )
        evidence, blockers = resolve_ai_shadow_qualification_promotion_evidence(
            self._db,
            qualification_candidate_id,
            proposed_qualification_approval=approval,
        )
        if blockers or evidence.get("status") != "pass":
            raise ShadowResearchRejected(
                "qualification_promotion_evidence_invalid:"
                + ",".join(blockers or ["unknown"])
            )
        source_candidate_id = str(evidence["source_candidate_id"])
        strategy_id = f"ai_formula_shadow:{source_candidate_id}"
        readiness = {
            "schema_version": AI_SHADOW_QUALIFICATION_READINESS_SCHEMA,
            "strategy_id": strategy_id,
            "promotion_status": "promotable_for_paper_review",
            "is_promotable": True,
            "missing_requirements": [],
            "backtest_result_id": evidence["backtest_result_id"],
            "candidate_id": source_candidate_id,
            "qualification_candidate_id": qualification_candidate_id,
            "qualification_run_id": evidence["qualification_run_id"],
            "comparison_fingerprint": evidence["comparison_fingerprint"],
            "human_approval_id": evidence["qualification_approval_id"],
            "strategy_advancement_gate": evidence["strategy_advancement_gate"],
            "daily_strategy_artifact_binding": evidence[
                "daily_strategy_artifact_binding"
            ],
            "qualification_binding": evidence["qualification_binding"],
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_create_order": True,
            "does_not_authorize_execution": True,
            "does_not_change_capital_authority": True,
        }
        current = self._db.get_strategy_promotion_state_sync(strategy_id)
        normalized_actor = approved_by.strip()
        normalized_notes = notes.strip()
        gate_fingerprint = readiness["strategy_advancement_gate"].get(
            "evidence_fingerprint"
        )
        state_payload = {
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "readiness": readiness,
            "human_review": {
                "reviewer": normalized_actor,
                "review_note": normalized_notes,
                "confirmation_recorded": True,
                "strategy_advancement_gate_fingerprint": gate_fingerprint,
            },
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
        }
        event_payload = {
            "manual_confirmation_required": True,
            "manual_confirmation_recorded": True,
            "reviewer": normalized_actor,
            "review_note": normalized_notes,
            "strategy_advancement_gate_fingerprint": gate_fingerprint,
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
        }
        committed = self._store.approve_qualification_candidate_for_paper_shadow(
            qualification_candidate_id,
            approval=approval,
            strategy_id=strategy_id,
            readiness=readiness,
            state_payload=state_payload,
            event_payload=event_payload,
            expected_state=current,
            current_evidence_validator=lambda: (
                resolve_ai_shadow_qualification_promotion_evidence(
                    self._db,
                    qualification_candidate_id,
                    proposed_qualification_approval=approval,
                )
            ),
            actor=normalized_actor,
            now=timestamp,
        )
        approval = committed["qualification_approval"]
        promotion_state = {
            **committed["strategy_promotion"],
            "schema_version": STRATEGY_PROMOTION_SCHEMA_VERSION,
            "lifecycle": lifecycle_metadata("paper_shadow"),
        }
        return {
            **approval,
            "qualification_approval": approval,
            "qualification_run": self._store.get_public_qualification_run(
                str(evidence["qualification_run_id"])
            ),
            "qualification_candidate": (
                self._store.get_public_qualification_candidate(
                    qualification_candidate_id
                )
            ),
            "strategy_id": strategy_id,
            "strategy_promotion": promotion_state,
            "daily_strategy_artifact_binding": evidence[
                "daily_strategy_artifact_binding"
            ],
            "qualification_binding": evidence["qualification_binding"],
            "paper_shadow_stage_recorded": True,
            "strategy_promotion_state_recorded": True,
            "production_strategy_replaced": False,
            "production_strategy_registry_mutated": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
            "broker_submission_enabled": False,
            "capital_authority_granted": False,
        }
