"""Stable facade for automatic daily decision evidence workflows."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from server.services.account_truth_broker_statement_roll_forward import (
    roll_forward_daily_broker_statement_for_state,
)
from server.services.account_truth_replay import (
    build_account_truth_replay_evidence,
    verify_account_truth_replay_evidence,
)
from server.services.automation_control import AutomationControlService
from server.services.daily_decision_background_schedule import (
    build_background_schedule_result,
    build_next_verified_trading_window,
    next_trading_day,
    project_daily_candidate_background_schedule,
    unavailable_next_reviewed_window,
)
from server.services.daily_decision_evidence_collection import (
    collect_daily_decision_evidence,
)
from server.services.daily_decision_evidence_composition import (
    bind_promoted_strategy_scan,
)
from server.services.daily_decision_evidence_composition import (
    build_daily_decision_evidence_automation_service as compose_daily_decision_evidence_automation_service,
)
from server.services.daily_decision_evidence_composition import (
    promoted_scan_cache_key,
)
from server.services.daily_decision_evidence_contracts import (
    DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE,
    DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION,
    DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE,
    DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE,
    DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION,
    DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION,
    DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION,
    DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS,
    DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION,
    DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
    DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE,
    DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION,
    DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE,
    DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION,
    DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE,
    DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION,
    DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME,
    DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION,
    DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION,
    AccountTruthReplayResolver,
    PlanReader,
    QuoteRefresher,
    RiskRunner,
    StatePlanReader,
    StateRiskRunner,
)
from server.services.daily_decision_evidence_cycle import (
    record_cycle as persist_daily_evidence_cycle,
)
from server.services.daily_decision_evidence_cycle import (
    send_evidence_notification,
    send_no_action_notification,
)
from server.services.daily_decision_evidence_identity import (
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
    evidence_fingerprint,
    fingerprint_json,
    manual_ticket_candidate_fingerprint,
)
from server.services.daily_decision_evidence_orchestration import (
    finish_background_attempt,
    record_daily_candidate_background_alert,
    record_daily_candidate_preparation_alert,
    run_claimed_background_attempt,
    run_claimed_daily_candidate_preparation_check,
    send_daily_candidate_preparation_notification,
)
from server.services.daily_decision_evidence_values import (
    aware_datetime,
    candidate_count,
    count,
    daily_candidate_asset_scope_blockers,
    finite_float,
    in_daily_candidate_decision_window,
    is_new_paper_shadow_evidence,
    is_sha256,
    json_object_list,
    latest_paper_shadow_run,
    nonnegative_float,
    nonnegative_int,
    object_dict,
    object_list,
    paper_shadow_summary,
    plan_date,
    policy_allows_paper_shadow,
    positive_float,
    positive_int,
    risk_summary,
    shanghai_date,
    single_ref,
)
from server.services.daily_decision_policy_gates import (
    build_daily_candidate_base_gate,
    project_daily_candidate_financial_preflight,
    unavailable_daily_candidate_financial_preflight,
)
from server.services.daily_decision_preflight_operator import (
    build_preflight_gate,
    build_preflight_operator_checklist,
    build_preflight_operator_evidence_contract,
    build_preflight_operator_step,
    safe_preflight_blocker,
)
from server.services.daily_decision_preparation import (
    build_daily_candidate_preparation_check,
    verify_daily_candidate_preparation_check,
)
from server.services.daily_decision_production_outcome import (
    build_manual_order_ticket_candidate,
    project_production_outcome,
)
from server.services.daily_decision_strategy_gate import (
    build_daily_candidate_strategy_gate_binding,
    daily_candidate_strategy_operating_constraints_blockers,
    resolve_strategy_gate_binding,
)
from server.services.paper_shadow_run import run_paper_shadow_from_trading_plan

logger = logging.getLogger(__name__)

__all__ = [
    "AccountTruthReplayResolver",
    "DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE",
    "DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION",
    "DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE",
    "DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION",
    "DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE",
    "DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION",
    "DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION",
    "DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION",
    "DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS",
    "DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION",
    "DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS",
    "DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE",
    "DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION",
    "DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE",
    "DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION",
    "DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE",
    "DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION",
    "DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME",
    "DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION",
    "DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION",
    "DailyDecisionEvidenceAutomationService",
    "PlanReader",
    "QuoteRefresher",
    "RiskRunner",
    "StatePlanReader",
    "StateRiskRunner",
    "build_daily_candidate_preparation_check",
    "build_daily_candidate_strategy_gate_binding",
    "build_daily_decision_evidence_automation_service",
    "daily_candidate_input_fingerprint",
    "daily_candidate_record_fingerprint",
    "daily_candidate_strategy_operating_constraints_blockers",
    "manual_ticket_candidate_fingerprint",
    "project_daily_candidate_background_schedule",
    "project_daily_candidate_financial_preflight",
    "run_daily_decision_evidence_automation_loop",
    "unavailable_daily_candidate_financial_preflight",
    "verify_daily_candidate_preparation_check",
]


class DailyDecisionEvidenceAutomationService:
    """Run risk and paper/shadow automatically without execution authority."""

    def __init__(
        self,
        *,
        db: Any,
        trading_controls: Any,
        notifier: Any,
        plan_reader: PlanReader,
        risk_runner: RiskRunner,
        account_truth_replay_resolver: AccountTruthReplayResolver | None = None,
    ) -> None:
        self._db = db
        self._trading_controls = trading_controls
        self._notifier = notifier
        self._plan_reader = plan_reader
        self._risk_runner = risk_runner
        self._account_truth_replay_resolver = (
            account_truth_replay_resolver or build_account_truth_replay_evidence
        )
        self._automation = AutomationControlService(
            db=db,
            trading_controls=trading_controls,
        )

    async def run_once(
        self,
        *,
        expected_plan_date: str | None = None,
    ) -> dict[str, Any]:
        """Advance one fail-closed, idempotent evidence cycle."""

        return await collect_daily_decision_evidence(
            db=self._db,
            automation=self._automation,
            plan_reader=self._plan_reader,
            risk_runner=self._risk_runner,
            record_cycle=self._record_cycle,
            send_notification=self._send_notification,
            run_paper_shadow=run_paper_shadow_from_trading_plan,
            expected_plan_date=expected_plan_date,
        )

    def _record_cycle(
        self,
        *,
        status: str,
        plan_date: str,
        decision_payload: dict[str, Any],
        trading_plan: dict[str, Any],
        started_at: str,
        risk_result: dict[str, Any] | None,
        paper_shadow_run: dict[str, Any] | None,
        candidate_count: int,
        limitations: list[str],
        additional_blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        return persist_daily_evidence_cycle(
            db=self._db,
            account_truth_replay_resolver=self._account_truth_replay_resolver,
            status=status,
            plan_date=plan_date,
            decision_payload=decision_payload,
            trading_plan=trading_plan,
            started_at=started_at,
            risk_result=risk_result,
            paper_shadow_run=paper_shadow_run,
            candidate_count=candidate_count,
            limitations=limitations,
            additional_blockers=additional_blockers,
        )

    async def _send_notification(
        self,
        *,
        plan_date: str,
        risk_summary: dict[str, Any],
        paper_shadow_run: dict[str, Any],
    ) -> dict[str, Any]:
        return await send_evidence_notification(
            notifier=self._notifier,
            timeout_seconds=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
            plan_date=plan_date,
            risk_summary=risk_summary,
            paper_shadow_run=paper_shadow_run,
        )

    async def _send_no_action_notification(
        self,
        *,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return await send_no_action_notification(
            notifier=self._notifier,
            timeout_seconds=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
            result=result,
        )


def build_daily_decision_evidence_automation_service(
    state: Any,
    *,
    plan_reader: StatePlanReader,
    risk_runner: StateRiskRunner,
    quote_refresher: QuoteRefresher,
) -> DailyDecisionEvidenceAutomationService:
    """Bind explicit application adapters to the background evidence service."""

    return compose_daily_decision_evidence_automation_service(
        state,
        plan_reader=plan_reader,
        risk_runner=risk_runner,
        quote_refresher=quote_refresher,
        service_type=DailyDecisionEvidenceAutomationService,
    )


async def _run_claimed_daily_candidate_preparation_check(
    *,
    state: Any,
    schedule: dict[str, Any],
) -> None:
    await run_claimed_daily_candidate_preparation_check(
        state=state,
        schedule=schedule,
        build_preparation_check=build_daily_candidate_preparation_check,
        verify_preparation_check=verify_daily_candidate_preparation_check,
        notification_timeout_seconds=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
    )


async def _send_daily_candidate_preparation_notification(
    *,
    notifier: Any,
    preparation: dict[str, Any],
) -> dict[str, Any]:
    return await send_daily_candidate_preparation_notification(
        notifier=notifier,
        preparation=preparation,
        timeout_seconds=DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS,
    )


async def run_daily_decision_evidence_automation_loop(
    *,
    state: Any,
    interval_seconds: float,
    plan_reader: StatePlanReader | None = None,
    risk_runner: StateRiskRunner | None = None,
    quote_refresher: QuoteRefresher | None = None,
    clock: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run at most once in the verified trading day's decision window."""
    from server.release_activation import wait_for_release_activation

    adapters = (plan_reader, risk_runner, quote_refresher)
    if any(adapter is not None for adapter in adapters) and not all(
        adapter is not None for adapter in adapters
    ):
        raise ValueError("daily decision evidence adapters must be supplied together")
    service: DailyDecisionEvidenceAutomationService | None = None
    interval = max(float(interval_seconds), 1.0)
    current_time = clock or (lambda: datetime.now(timezone.utc))
    while True:
        await wait_for_release_activation(sleep=sleep)
        try:
            schedule = project_daily_candidate_background_schedule(
                db=state.db,
                now=current_time(),
            )
            if schedule["preparation_check_due"]:
                roll_forward = await asyncio.to_thread(
                    roll_forward_daily_broker_statement_for_state,
                    state=state,
                    run_date=str(schedule["run_date"]),
                )
                # A changed file must first pass the independent collector's
                # stability delay and canonical staging.  Leave the once-only
                # preparation claim open until the next polling iteration.
                if roll_forward.status != "rolled_forward":
                    await _run_claimed_daily_candidate_preparation_check(
                        state=state,
                        schedule=schedule,
                    )
            if schedule["due"]:
                if service is None:
                    if plan_reader is None:
                        # Backward-compatible seam for tests that replace the
                        # factory entirely.
                        service = build_daily_decision_evidence_automation_service(  # type: ignore[call-arg]
                            state
                        )
                    else:
                        service = build_daily_decision_evidence_automation_service(
                            state,
                            plan_reader=plan_reader,
                            risk_runner=risk_runner,  # type: ignore[arg-type]
                            quote_refresher=quote_refresher,  # type: ignore[arg-type]
                        )
                await _run_claimed_background_attempt(
                    db=state.db,
                    service=service,
                    schedule=schedule,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected daily decision evidence automation failure")
        await sleep(interval)


# Compatibility aliases keep established imports and monkeypatch seams stable.
_bind_promoted_strategy_scan = bind_promoted_strategy_scan
_promoted_scan_cache_key = promoted_scan_cache_key
_background_schedule_result = build_background_schedule_result
_next_verified_trading_window = build_next_verified_trading_window
_next_trading_day = next_trading_day
_unavailable_next_reviewed_window = unavailable_next_reviewed_window
_run_claimed_background_attempt = run_claimed_background_attempt
_record_daily_candidate_preparation_alert = record_daily_candidate_preparation_alert
_record_daily_candidate_background_alert = record_daily_candidate_background_alert
_finish_background_attempt = finish_background_attempt
_policy_allows_paper_shadow = policy_allows_paper_shadow
_plan_date = plan_date
_candidate_count = candidate_count
_daily_candidate_asset_scope_blockers = daily_candidate_asset_scope_blockers
_daily_candidate_base_gate = build_daily_candidate_base_gate
_preflight_operator_checklist = build_preflight_operator_checklist
_preflight_operator_step = build_preflight_operator_step
_preflight_operator_evidence_contract = build_preflight_operator_evidence_contract
_preflight_gate = build_preflight_gate
_safe_preflight_blocker = safe_preflight_blocker
_evidence_fingerprint = evidence_fingerprint
_production_outcome = project_production_outcome
_strategy_gate_binding = resolve_strategy_gate_binding
_manual_order_ticket_candidate = build_manual_order_ticket_candidate
_fingerprint_json = fingerprint_json
_finite_float = finite_float
_positive_float = positive_float
_single_ref = single_ref
_is_sha256 = is_sha256
_aware_datetime = aware_datetime
_shanghai_date = shanghai_date
_in_daily_candidate_decision_window = in_daily_candidate_decision_window
_positive_int = positive_int
_nonnegative_int = nonnegative_int
_nonnegative_float = nonnegative_float
_risk_summary = risk_summary
_paper_shadow_summary = paper_shadow_summary
_latest_paper_shadow_run = latest_paper_shadow_run
_is_new_paper_shadow_evidence = is_new_paper_shadow_evidence
_object_dict = object_dict
_object_list = object_list
_json_object_list = json_object_list
_count = count
