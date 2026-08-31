"""Stable contracts for daily decision evidence automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from zoneinfo import ZoneInfo

DAILY_DECISION_EVIDENCE_AUTOMATION_SCHEMA_VERSION = (
    "karkinos.daily_decision_evidence_automation.v3"
)
DAILY_DECISION_EVIDENCE_AUTOMATION_RUN_TYPE = "daily_decision_evidence"
DAILY_DECISION_EVIDENCE_AUTOMATION_TASK_NAME = "daily-decision-evidence-automation"
DAILY_CANDIDATE_BACKGROUND_ATTEMPT_RUN_TYPE = "daily_candidate_background_attempt"
DAILY_CANDIDATE_PREPARATION_CHECK_RUN_TYPE = "daily_candidate_preparation_check"
DAILY_CANDIDATE_BACKGROUND_SCHEDULE_SCHEMA_VERSION = (
    "karkinos.daily_candidate_background_schedule.v3"
)
DAILY_CANDIDATE_PREPARATION_CHECK_SCHEMA_VERSION = (
    "karkinos.daily_candidate_preparation_check.v1"
)
DAILY_CANDIDATE_NEXT_REVIEWED_WINDOW_SCHEMA_VERSION = (
    "karkinos.daily_candidate_next_reviewed_window.v1"
)
DAILY_CANDIDATE_DECISION_WINDOW_SCHEMA_VERSION = (
    "karkinos.daily_candidate_decision_window.v1"
)
DAILY_CANDIDATE_DECISION_WINDOW_START_MINUTE = 9 * 60 + 35
DAILY_CANDIDATE_DECISION_WINDOW_END_MINUTE = 9 * 60 + 45
DAILY_CANDIDATE_PREPARATION_WINDOW_START_MINUTE = 8 * 60 + 45
DAILY_CANDIDATE_MAX_QUOTE_AGE_SECONDS = 300
DAILY_CANDIDATE_NOTIFICATION_TIMEOUT_SECONDS = 10
DAILY_CANDIDATE_INPUT_IDENTITY_SCHEMA_VERSION = (
    "karkinos.daily_candidate_input_identity.v2"
)
DAILY_CANDIDATE_FINANCIAL_PREFLIGHT_SCHEMA_VERSION = (
    "karkinos.daily_candidate_financial_preflight.v1"
)
DAILY_CANDIDATE_STRATEGY_GATE_BINDING_SCHEMA_VERSION = (
    "karkinos.daily_candidate_strategy_gate_binding.v2"
)
DAILY_CANDIDATE_MANUAL_TICKET_SCHEMA_VERSION = (
    "karkinos.manual_order_ticket_candidate.v2"
)
DAILY_STRATEGY_PROMOTION_BINDING_SCHEMA_VERSION = (
    "karkinos.ai.daily_strategy_promotion_binding.v2"
)
DAILY_STRATEGY_OPERATING_CONSTRAINTS_SCHEMA_VERSION = (
    "karkinos.ai.strategy_operating_constraints.v1"
)

TRUSTED_MARKET_STATUSES = {"complete", "confirmed", "fresh", "live", "pass"}
TERMINAL_EVIDENCE_STATUSES = {
    "no_candidates",
    "no_risk_passed_order_intents",
    "paper_shadow_completed",
}
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
VERIFIED_CALENDAR_STATUSES = {"accepted", "confirmed", "verified"}
PRODUCTION_RECORD_FIELDS = (
    "schema_version",
    "input_identity_schema_version",
    "input_fingerprint",
    "input_snapshot",
    "candidate_count",
    "risk",
    "paper_shadow",
    "execution_closure",
    "production_gate",
    "decision_outcome",
    "manual_ticket_candidate_count",
    "manual_order_ticket_candidates",
    "no_action_reasons",
    "strategy_bindings",
    "profitability_claim",
    "manual_confirmation_required",
    "broker_submission_enabled",
    "does_not_submit_broker_order",
    "does_not_mutate_production_ledger",
    "limitations",
)

PlanReader = Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
RiskRunner = Callable[[], Awaitable[dict[str, Any]]]
AccountTruthReplayResolver = Callable[..., dict[str, Any]]
StatePlanReader = Callable[[Any], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]
StateRiskRunner = Callable[[Any], Awaitable[dict[str, Any]]]
QuoteRefresher = Callable[..., Awaitable[Any]]
