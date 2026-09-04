"""Public facade for evidence-bound, after-close AI strategy research."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data.store import DataStore
from server.ai_runtime.provider_call_window import ProviderCallWindowPolicy
from server.ai_runtime.strategy_research import StrategyResearchService
from server.contracts.ai_shadow_research_automation import (
    CITATION_CONTRACT_RETRYABLE_FAILURE_CODES,
    CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE,
    CORRECTED_PANEL_CITATION_FAILURE_CODE,
    CORRECTED_PANEL_CITATION_RESUME_ITERATION,
    CORRECTED_PANEL_CITATION_RESUME_STAGE,
    LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
    OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES,
    PROVIDER_FREE_RETRYABLE_FAILURE_CODES,
    SHADOW_RESEARCH_ACCOUNT_BOUND_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_API_SCHEMA,
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION,
    SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION,
    SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS,
    SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_PAUSE_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
    SHADOW_RESEARCH_POLICY_ID,
    SHADOW_RESEARCH_POLICY_SCHEMA,
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION,
    SHADOW_RESEARCH_RETRY_CONFIRMATION,
    SHADOW_RESEARCH_RUN_TYPE,
    SHADOW_RESEARCH_RUNTIME_CONTRACT,
    SHADOW_RESEARCH_SINGLE_PROVIDER_CALL_RUNWAY_SECONDS,
    SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION,
    SHADOW_RESEARCH_TIMEZONE,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED,
    SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED,
    TIMEOUT_RESUME_COMPLETED_ITERATIONS,
    TIMEOUT_RESUME_ITERATION,
    TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES,
    PreparedBaseline,
    ShadowResearchPolicy,
    ShadowResearchRejected,
    build_shadow_research_iteration_context,
    build_shadow_research_iteration_lineage,
)
from server.dependencies import AppState
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.release_activation import wait_for_release_activation
from server.services.ai_shadow_research_baseline import AiShadowResearchBaselineMixin
from server.services.ai_shadow_research_candidate_workflow import (
    AiShadowResearchCandidateWorkflowMixin,
)
from server.services.ai_shadow_research_commands import AiShadowResearchCommandsMixin
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.ai_shadow_research_policy import (
    build_corrected_panel_rearm_evidence,
)
from server.services.ai_shadow_research_support import (
    AiShadowResearchSupportMixin,
    NullShadowResearchEventBus,
    is_after_shadow_research_close,
    shadow_research_backtest_source_fingerprint,
    shadow_research_failure_code,
)
from server.services.ai_shadow_research_workflow import AiShadowResearchWorkflowMixin
from server.services.valuation_snapshot import build_current_valuation_snapshot

logger = logging.getLogger(__name__)


_CITATION_CONTRACT_RETRYABLE_FAILURE_CODES = CITATION_CONTRACT_RETRYABLE_FAILURE_CODES
_OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES = OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES
_TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES = TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES
_TIMEOUT_RESUME_COMPLETED_ITERATIONS = TIMEOUT_RESUME_COMPLETED_ITERATIONS
_TIMEOUT_RESUME_ITERATION = TIMEOUT_RESUME_ITERATION
_CORRECTED_PANEL_CITATION_RESUME_ITERATION = CORRECTED_PANEL_CITATION_RESUME_ITERATION
_CORRECTED_PANEL_CITATION_RESUME_STAGE = CORRECTED_PANEL_CITATION_RESUME_STAGE
_CORRECTED_PANEL_CITATION_FAILURE_CODE = CORRECTED_PANEL_CITATION_FAILURE_CODE
_CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE = (
    CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE
)
_SHANGHAI_TZ = SHADOW_RESEARCH_TIMEZONE
_PROVIDER_FREE_RETRYABLE_FAILURE_CODES = PROVIDER_FREE_RETRYABLE_FAILURE_CODES
_LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES = LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES
_after_close = is_after_shadow_research_close
_backtest_source_fingerprint = shadow_research_backtest_source_fingerprint
_build_corrected_panel_rearm_evidence = build_corrected_panel_rearm_evidence
_build_iteration_context = build_shadow_research_iteration_context
_failure_code = shadow_research_failure_code
_iteration_lineage = build_shadow_research_iteration_lineage
_NullEventBus = NullShadowResearchEventBus


class AiShadowResearchAutomationService(
    AiShadowResearchCommandsMixin,
    AiShadowResearchWorkflowMixin,
    AiShadowResearchCandidateWorkflowMixin,
    AiShadowResearchBaselineMixin,
    AiShadowResearchSupportMixin,
):
    """Run one complete after-close research cycle under a persisted policy."""

    def __init__(
        self,
        *,
        state: AppState,
        store: ShadowResearchStore,
        data_store: DataStore,
        research_service_builder: (
            Callable[[bool], StrategyResearchService] | None
        ) = None,
        reviewed_fee_schedule_resolver: Callable[..., dict[str, Any]] | None = None,
        daily_artifact_store: DailyStrategyArtifactStore | None = None,
        now: Callable[[], datetime] | None = None,
        provider_call_window_policy: ProviderCallWindowPolicy | None = None,
        provider_runway_seconds: int = (
            SHADOW_RESEARCH_MINIMUM_OFF_PEAK_RUNWAY_SECONDS
        ),
        provider_call_runway_seconds: int = (
            SHADOW_RESEARCH_SINGLE_PROVIDER_CALL_RUNWAY_SECONDS
        ),
        execution_guard: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._db = state.require_database()
        self._store = store
        self._data_store = data_store
        self._research_service_builder = research_service_builder
        self._reviewed_fee_schedule_resolver = reviewed_fee_schedule_resolver
        self._daily_artifacts = daily_artifact_store or DailyStrategyArtifactStore(
            db_path=Path(self._db.path),
            backup_root=store.path.parent / "strategy-research-backups",
        )
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._provider_call_window_policy = provider_call_window_policy
        self._provider_runway_seconds = provider_runway_seconds
        self._provider_call_runway_seconds = provider_call_runway_seconds
        self._execution_guard = execution_guard

    def _require_execution_current(self) -> None:
        if self._execution_guard is not None:
            self._execution_guard()

    def _build_corrected_panel_rearm_evidence(
        self, prepared: PreparedBaseline
    ) -> dict[str, Any]:
        return _build_corrected_panel_rearm_evidence(prepared)

    def _optional_corrected_panel_rearm_evidence(
        self, prepared: PreparedBaseline
    ) -> dict[str, Any] | None:
        try:
            return _build_corrected_panel_rearm_evidence(prepared)
        except ShadowResearchRejected:
            return None

    def _build_current_valuation_snapshot(self) -> dict[str, Any]:
        return build_current_valuation_snapshot(self._db, persist=True)


def build_ai_shadow_research_automation_service(
    state: AppState,
    *,
    research_service_builder: Callable[[bool], StrategyResearchService],
    execution_guard: Callable[[], None] | None = None,
) -> AiShadowResearchAutomationService:
    from server.composition.ai_shadow_research_automation import (
        compose_ai_shadow_research_automation_service,
    )

    return compose_ai_shadow_research_automation_service(
        state,
        research_service_builder=research_service_builder,
        service_type=AiShadowResearchAutomationService,
        execution_guard=execution_guard,
    )


async def run_ai_shadow_research_automation_loop(
    *,
    state: AppState,
    job_scheduler_builder: Callable[[], Any],
    qualification_service_builder: Callable[[], Any] | None = None,
    interval_seconds: float = 300.0,
) -> None:
    """Run provider-free qualification and enqueue isolated research work."""
    qualification_service: Any | None = None
    job_scheduler: Any | None = None
    while True:
        await wait_for_release_activation()
        try:
            if job_scheduler is None:
                job_scheduler = job_scheduler_builder()
            await asyncio.to_thread(job_scheduler.enqueue_if_authorized)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Shadow research durable enqueue failed closed", exc_info=True
            )
        if qualification_service_builder is not None:
            try:
                if qualification_service is None:
                    qualification_service = qualification_service_builder()
                qualification_result = await qualification_service.run_once()
                if qualification_result.get("status") in {"blocked", "failed"}:
                    attempt = qualification_result.get("qualification_attempt") or {}
                    run = qualification_result.get("run") or {}
                    logger.warning(
                        "Shadow research account qualification returned %s "
                        "for source_run_id=%s failure_code=%s blockers=%s "
                        "attempt_id=%s",
                        qualification_result.get("status"),
                        attempt.get("source_run_id") or run.get("source_run_id"),
                        qualification_result.get("failure_code")
                        or run.get("failure_code"),
                        qualification_result.get("blockers")
                        or run.get("blockers")
                        or [],
                        attempt.get("attempt_id"),
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Shadow research account qualification failed closed",
                    exc_info=True,
                )
        await asyncio.sleep(max(30.0, interval_seconds))
