"""Stable contracts for after-close AI shadow research automation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from typing import Any
from zoneinfo import ZoneInfo

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research import (
    STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
    STRATEGY_RESEARCH_MAX_CANDIDATES,
    STRATEGY_RESEARCH_MAX_PROVIDER_CALLS,
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
)
from server.models import BacktestRequest

SHADOW_RESEARCH_POLICY_ID = "ai_shadow_research"
SHADOW_RESEARCH_POLICY_SCHEMA = "karkinos.ai.shadow_research_policy.v2"
SHADOW_RESEARCH_API_SCHEMA = "karkinos.ai.shadow_research_automation.v1"
SHADOW_RESEARCH_RUN_TYPE = "ai_shadow_research"
SHADOW_RESEARCH_RUNTIME_CONTRACT = "karkinos.ai.shadow_research_runtime.v10"
SHADOW_RESEARCH_REQUIRED_MARKET_UNIVERSE_TRUTH_SCHEMA = (
    "karkinos.market_universe_truth.v2"
)
SHADOW_RESEARCH_REQUIRED_PANEL_SCHEMA = "karkinos.research_panel_snapshot.v2"
SHADOW_RESEARCH_POLICY_CONFIRMATION = (
    "authorize_five_sequentialis_after_shadow_research_close_deepseek_strategy_research_without_"
    "daily_token_budget_or_strategy_or_trade_authority"
)
SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION = (
    "authorizeis_after_shadow_research_close_deepseek_strategy_research_without_strategy_or_trade_"
    "authority"
)
SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED = "unbounded_daily"
SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED = "legacy_bounded_daily"
SHADOW_RESEARCH_PAUSE_CONFIRMATION = "pauseis_after_shadow_research_close_ai_strategy_research_without_changing_trading_authority"
SHADOW_RESEARCH_PROMOTION_CONFIRMATION = "approve_evidence_bound_candidate_for_paper_shadow_only_without_production_or_trade_authority"
SHADOW_RESEARCH_RETRY_CONFIRMATION = (
    "authorize_one_additional_complete_five_round_ten_call_strategy_research_"
    "retry_without_strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_CORRECTED_PANEL_REARM_CONFIRMATION = (
    "authorize_one_corrected_full_market_40_stock_panel_five_round_ten_call_"
    "research_without_strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_corrected_panel_first_critique_"
    "citation_resume_without_strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_CITATION_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_citation_contract_retry_without_"
    "strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_OUTPUT_TRUNCATION_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_output_truncation_retry_without_"
    "strategy_trade_or_capital_authority"
)
SHADOW_RESEARCH_TIMEOUT_RESUME_CALL_EXTENSION_CONFIRMATION = (
    "authorize_one_additional_deepseek_call_for_partial_fifth_round_timeout_"
    "resume_without_strategy_trade_or_capital_authority"
)
CITATION_CONTRACT_RETRYABLE_FAILURE_CODES = ("provider_citation_not_in_bound_input",)
OUTPUT_TRUNCATION_RETRYABLE_FAILURE_CODES = ("provider_output_truncated",)
TIMEOUT_RESUME_RETRYABLE_FAILURE_CODES = ("provider_timeout",)
TIMEOUT_RESUME_COMPLETED_ITERATIONS = 4
TIMEOUT_RESUME_ITERATION = 5
CORRECTED_PANEL_CITATION_RESUME_ITERATION = 1
CORRECTED_PANEL_CITATION_RESUME_STAGE = "critique"
CORRECTED_PANEL_CITATION_FAILURE_CODE = "critique_citation_outside_binding"
CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE = "strategy_critique_not_complete"
SHADOW_RESEARCH_TIMEZONE = ZoneInfo("Asia/Shanghai")
SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION = (
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION
)
SHADOW_RESEARCH_MAX_PROVIDER_CALLS = STRATEGY_RESEARCH_MAX_PROVIDER_CALLS
SHADOW_RESEARCH_MAX_CANDIDATES = STRATEGY_RESEARCH_MAX_CANDIDATES
PROVIDER_FREE_RETRYABLE_FAILURE_CODES = (
    "account_evidence_binding_mismatch",
    "ai_runtime_role_identity_conflict",
    "research_account_binding_required",
    "research_account_capital_evidence_not_passing",
    "research_account_evidence_identity_mismatch",
    "research_account_evidence_not_authoritative",
    "research_account_total_equity_invalid",
    "research_account_truth_binding_not_reconciled",
    "research_initial_cash_exceeds_current_account_equity",
    "research_initial_cash_invalid",
    "reviewed_fee_schedule_current_reconciliation_blocked",
)
LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES = (
    "strategy_research_citation_catalog_too_large",
)


class ShadowResearchRejected(ValueError):
    """Fail-closed shadow research policy or evidence rejection."""


@dataclass(frozen=True)
class ShadowResearchPolicy:
    enabled: bool = False
    after_close_time: str = "15:30"
    max_provider_calls_per_market_date: int = SHADOW_RESEARCH_MAX_PROVIDER_CALLS
    daily_token_budget: int | None = None
    max_candidates_per_run: int = SHADOW_RESEARCH_MAX_CANDIDATES
    baseline_backtest_result_id: int | None = None
    require_complete_account_evidence: bool = True
    research_question: str = (
        "基于冻结的最新持久化行情、账户证据与基线回测，提出可证伪、低换手、"
        "包含明确风险退出条件的 Formula DSL 策略改进假设。"
    )
    updated_by: str = "human:owner"
    authorization: str = ""

    def __post_init__(self) -> None:
        try:
            parsed = time.fromisoformat(self.after_close_time)
        except ValueError as exc:
            raise ShadowResearchRejected("after_close_time_invalid") from exc
        if parsed.second or parsed.microsecond:
            raise ShadowResearchRejected("after_close_time_must_be_minute_precision")
        if not (
            1
            <= self.max_provider_calls_per_market_date
            <= SHADOW_RESEARCH_MAX_PROVIDER_CALLS
        ):
            raise ShadowResearchRejected("provider_call_limit_out_of_range")
        if self.daily_token_budget is not None and (
            isinstance(self.daily_token_budget, bool)
            or self.daily_token_budget < SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION
        ):
            raise ShadowResearchRejected("legacy_daily_token_budget_out_of_range")
        if not 1 <= self.max_candidates_per_run <= SHADOW_RESEARCH_MAX_CANDIDATES:
            raise ShadowResearchRejected("candidate_limit_out_of_range")
        if self.max_provider_calls_per_market_date < self.max_candidates_per_run * 2:
            raise ShadowResearchRejected(
                "provider_call_limit_cannot_cover_sequential_iterations"
            )
        if self.daily_token_budget is not None and self.daily_token_budget < (
            SHADOW_RESEARCH_PROVIDER_TOKEN_RESERVATION * self.max_candidates_per_run * 2
        ):
            raise ShadowResearchRejected(
                "legacy_daily_token_budget_cannot_cover_reserved_calls"
            )
        if (
            self.baseline_backtest_result_id is not None
            and self.baseline_backtest_result_id <= 0
        ):
            raise ShadowResearchRejected("baseline_backtest_result_id_invalid")
        if not self.research_question.strip():
            raise ShadowResearchRejected("research_question_required")
        if not self.updated_by.strip():
            raise ShadowResearchRejected("updated_by_required")
        if self.enabled:
            required_authorization = (
                SHADOW_RESEARCH_POLICY_CONFIRMATION
                if self.daily_token_budget is None
                else SHADOW_RESEARCH_LEGACY_BOUNDED_POLICY_CONFIRMATION
            )
            if self.authorization != required_authorization:
                raise PermissionError(
                    "standing shadow research requires exact owner authorization"
                )

    @property
    def token_budget_mode(self) -> str:
        return (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if self.daily_token_budget is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SHADOW_RESEARCH_POLICY_SCHEMA,
            "policy_id": SHADOW_RESEARCH_POLICY_ID,
            "enabled": self.enabled,
            "after_close_time": self.after_close_time,
            "timezone": "Asia/Shanghai",
            "max_provider_calls_per_market_date": self.max_provider_calls_per_market_date,
            "daily_token_budget": self.daily_token_budget,
            "token_budget_mode": self.token_budget_mode,
            "max_candidates_per_run": self.max_candidates_per_run,
            "baseline_backtest_result_id": self.baseline_backtest_result_id,
            "require_complete_account_evidence": self.require_complete_account_evidence,
            "research_question": self.research_question,
            "updated_by": self.updated_by,
            "authorization_recorded": self.enabled,
            "authorization": self.authorization if self.enabled else "",
            "automatic_strategy_replacement_enabled": False,
            "broker_submission_enabled": False,
            "production_strategy_mutation_enabled": False,
            "human_paper_shadow_approval_required": True,
        }

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "ShadowResearchPolicy":
        value = dict(raw or {})
        raw_daily_token_budget = (
            value.get("daily_token_budget") if "daily_token_budget" in value else None
        )
        daily_token_budget = (
            int(raw_daily_token_budget) if raw_daily_token_budget is not None else None
        )
        expected_token_budget_mode = (
            SHADOW_RESEARCH_TOKEN_BUDGET_MODE_UNBOUNDED
            if daily_token_budget is None
            else SHADOW_RESEARCH_TOKEN_BUDGET_MODE_LEGACY_BOUNDED
        )
        if value.get("token_budget_mode") not in (
            None,
            expected_token_budget_mode,
        ):
            raise ShadowResearchRejected("token_budget_mode_conflicts_with_policy")
        return cls(
            enabled=bool(value.get("enabled", False)),
            after_close_time=str(value.get("after_close_time") or "15:30"),
            max_provider_calls_per_market_date=int(
                value.get("max_provider_calls_per_market_date")
                or SHADOW_RESEARCH_MAX_PROVIDER_CALLS
            ),
            daily_token_budget=daily_token_budget,
            max_candidates_per_run=int(
                value.get("max_candidates_per_run") or SHADOW_RESEARCH_MAX_CANDIDATES
            ),
            baseline_backtest_result_id=(
                int(value["baseline_backtest_result_id"])
                if value.get("baseline_backtest_result_id") is not None
                else None
            ),
            require_complete_account_evidence=bool(
                value.get("require_complete_account_evidence", True)
            ),
            research_question=str(
                value.get("research_question") or cls.research_question
            ),
            updated_by=str(value.get("updated_by") or "human:owner"),
            authorization=str(value.get("authorization") or ""),
        )


@dataclass(frozen=True)
class PreparedBaseline:
    seed_result_id: int
    market_date: str
    snapshot: dict[str, Any]
    request: BacktestRequest
    result: dict[str, Any]
    cost_model_reference: str
    fee_schedule_evidence: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(
            {
                "seed_result_id": self.seed_result_id,
                "config": self.request.model_dump(mode="json"),
                "dataset_snapshot_id": self.snapshot["snapshot_id"],
                "metrics": self.result["metrics_json"],
                "cost_summary": self.result["cost_summary_json"],
                "cost_model_reference": self.cost_model_reference,
                "fee_schedule_evidence": self.fee_schedule_evidence,
            }
        )


def require_corrected_panel_rearm_evidence(
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise ShadowResearchRejected("corrected_panel_rearm_evidence_missing")
    payload = dict(evidence)
    expected_fingerprint = str(payload.pop("evidence_fingerprint", ""))
    if (
        payload.get("schema_version") != "karkinos.ai.corrected_panel_rearm_evidence.v1"
        or payload.get("runtime_contract") != SHADOW_RESEARCH_RUNTIME_CONTRACT
        or payload.get("market_universe_truth_schema_version")
        != SHADOW_RESEARCH_REQUIRED_MARKET_UNIVERSE_TRUTH_SCHEMA
        or payload.get("research_panel_schema_version")
        != SHADOW_RESEARCH_REQUIRED_PANEL_SCHEMA
        or int(payload.get("research_panel_member_count") or 0) != 40
        or int(payload.get("required_trading_date_count") or 0) <= 0
        or payload.get("receipt_bound_history") is not True
        or payload.get("stock_only") is not True
        or payload.get("provider_contacted_during_build") is not False
        or payload.get("authorizes_strategy_promotion") is not False
        or payload.get("authorizes_order_creation") is not False
        or payload.get("changes_capital_authority") is not False
        or not str(payload.get("market_date") or "")
        or not str(payload.get("prepared_baseline_fingerprint") or "")
        or not str(payload.get("dataset_snapshot_id") or "").startswith("sha256:")
        or not str(payload.get("market_universe_truth_fingerprint") or "").startswith(
            "sha256:"
        )
        or not str(payload.get("market_universe_snapshot_id") or "").startswith(
            "sha256:"
        )
        or not str(payload.get("research_panel_fingerprint") or "").startswith(
            "sha256:"
        )
        or expected_fingerprint != content_fingerprint(payload)
    ):
        raise ShadowResearchRejected("corrected_panel_rearm_evidence_invalid")
    return {**payload, "evidence_fingerprint": expected_fingerprint}


def build_shadow_research_iteration_context(
    *,
    iteration_number: int,
    total_iterations: int,
    previous_iteration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    parent_iteration = None
    if iteration_number == 1:
        if previous_iteration is not None:
            raise ShadowResearchRejected("initial_iteration_parent_forbidden")
    else:
        if not isinstance(previous_iteration, Mapping):
            raise ShadowResearchRejected("sequential_iteration_parent_missing")
        hypotheses = previous_iteration.get("hypotheses")
        draft = previous_iteration.get("draft")
        candidate = previous_iteration.get("candidate")
        if not all(
            isinstance(item, Mapping) for item in (hypotheses, draft, candidate)
        ):
            raise ShadowResearchRejected("sequential_iteration_parent_invalid")
        comparison = candidate.get("comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        candidate_metrics = comparison.get("candidate")
        candidate_metrics = (
            candidate_metrics if isinstance(candidate_metrics, Mapping) else {}
        )
        deltas = comparison.get("deltas")
        deltas = deltas if isinstance(deltas, Mapping) else {}
        gate = comparison.get("promotion_gate")
        gate = gate if isinstance(gate, Mapping) else {}
        critique = comparison.get("deepseek_critique")
        critique = critique if isinstance(critique, Mapping) else {}
        parent_core = {
            "iteration_number": iteration_number - 1,
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "session_id": str(hypotheses.get("session_id") or ""),
            "draft_id": str(draft.get("draft_id") or ""),
            "formula_fingerprint": str(draft.get("formula_fingerprint") or ""),
            "backtest_run_id": str(candidate.get("backtest_run_id") or ""),
            "critique_id": str(candidate.get("critique_id") or ""),
            "strategy": {
                "economic_hypothesis": draft.get("economic_hypothesis"),
                "formula_ast": draft.get("formula_ast"),
                "parameter_values": draft.get("parameter_values") or {},
                "parameter_ranges": draft.get("parameter_ranges") or {},
                "risk_impact": draft.get("risk_impact"),
                "failure_conditions": list(draft.get("failure_conditions") or []),
                "limitations": list(draft.get("limitations") or []),
            },
            "evaluation": {
                "total_return": candidate_metrics.get("total_return"),
                "sharpe": candidate_metrics.get("sharpe"),
                "max_drawdown": candidate_metrics.get("max_drawdown"),
                "oos_fold_count": candidate_metrics.get("oos_fold_count"),
                "mean_oos_return": candidate_metrics.get("mean_oos_return"),
                "worst_oos_return": candidate_metrics.get("worst_oos_return"),
                "oos_validation_status": candidate_metrics.get("oos_validation_status"),
                "total_return_delta": deltas.get("total_return"),
                "sharpe_delta": deltas.get("sharpe"),
                "max_drawdown_delta": deltas.get("max_drawdown"),
                "recommendation": candidate.get("recommendation"),
                "promotion_gate_status": gate.get("status"),
                "promotion_gate_blockers": list(gate.get("blockers") or []),
                "promotion_gate_fingerprint": gate.get("evidence_fingerprint"),
            },
            "critique": {
                key: critique.get(key)
                for key in (
                    "supported_claims",
                    "contradicted_claims",
                    "evidence_gaps",
                    "cost_turnover_sensitivity",
                    "concentration_risk",
                    "sample_dependence",
                    "possible_overfitting",
                    "recommended_ablations",
                    "recommended_walk_forward_stress_tests",
                    "explicit_failure_conditions",
                    "uncertainty",
                    "citations",
                )
                if key in critique
            },
        }
        parent_iteration = {
            **parent_core,
            "parent_artifact_fingerprint": "sha256:" + content_fingerprint(parent_core),
        }
    context_core = {
        "schema_version": STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
        "iteration_number": iteration_number,
        "total_iterations": total_iterations,
        "parent_iteration": parent_iteration,
        "required_behavior": {
            "draft_count": 1,
            "must_change_formula_from_parent": iteration_number > 1,
            "must_use_parent_backtest_and_critique": iteration_number > 1,
            "authority_effect": "none",
        },
    }
    return {
        **context_core,
        "context_fingerprint": "sha256:" + content_fingerprint(context_core),
    }


def build_shadow_research_iteration_lineage(
    iteration_context: Mapping[str, Any],
    *,
    current_formula_fingerprint: Any,
) -> dict[str, Any]:
    parent = iteration_context.get("parent_iteration")
    parent = parent if isinstance(parent, Mapping) else {}
    return {
        "schema_version": STRATEGY_RESEARCH_ITERATION_CONTEXT_CONTRACT,
        "iteration_number": iteration_context.get("iteration_number"),
        "total_iterations": iteration_context.get("total_iterations"),
        "formula_fingerprint": current_formula_fingerprint,
        "parent_candidate_id": parent.get("candidate_id"),
        "parent_draft_id": parent.get("draft_id"),
        "parent_formula_fingerprint": parent.get("formula_fingerprint"),
        "iteration_context_fingerprint": iteration_context.get("context_fingerprint"),
        "sequential_feedback_bound": bool(parent)
        or iteration_context.get("iteration_number") == 1,
    }


def shadow_research_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def shadow_research_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    return list(decoded) if isinstance(decoded, list) else []
