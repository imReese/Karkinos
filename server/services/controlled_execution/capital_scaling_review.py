"""Pure evidence-based capital scaling review without authority mutation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

CAPITAL_SCALING_REVIEW_SCHEMA_VERSION = "karkinos.capital_scaling_review.v2"
CAPITAL_SCALING_DECISION_SCHEMA_VERSION = "karkinos.capital_scaling_review_decision.v2"

MIN_REVIEWED_TRADING_DAYS = 20
MIN_REVIEWED_ORDERS = 50
MIN_FILL_RATE = Decimal("0.95")
MAX_SCALE_UP_REJECTION_RATE = Decimal("0.02")
MAX_SCALE_UP_AVERAGE_SLIPPAGE_BPS = Decimal("15")
MAX_SCALE_UP_P95_SLIPPAGE_BPS = Decimal("30")
MAX_SCALE_UP_RECONCILIATION_MINUTES = Decimal("30")
MAX_SCALE_UP_CAPACITY_UTILIZATION = Decimal("0.80")
MAX_SCALE_UP_LIQUIDITY_UTILIZATION = Decimal("0.80")
MAX_SCALE_UP_DIVERGENCE_COUNT = 1
MAX_SCALE_UP_DISCONNECT_COUNT = 2

_REQUIRED_EVIDENCE_PREFIXES = (
    "account_truth:",
    "broker_soak:",
    "execution_reconciliation:",
    "paper_shadow:",
    "after_cost:",
    "risk:",
    "incident:",
    "capacity:",
    "operating_sample:",
    "execution_scope:",
)


@dataclass(frozen=True)
class CapitalScalingTierLimits:
    max_authorized_capital: Decimal
    max_order_value: Decimal
    max_daily_turnover: Decimal
    max_daily_loss: Decimal
    max_drawdown_pct: Decimal


@dataclass(frozen=True)
class CapitalScalingTier:
    tier_id: str
    policy_version: str
    limits: CapitalScalingTierLimits


@dataclass(frozen=True)
class CapitalScalingEvidence:
    review_window_start: datetime
    review_window_end: datetime
    reviewed_trading_days: int
    order_count: int
    filled_order_count: int
    rejected_order_count: int
    partial_fill_count: int
    critical_incident_count: int
    policy_violation_count: int
    unresolved_reconciliation_count: int
    p95_reconciliation_latency_minutes: Decimal
    average_slippage_bps: Decimal
    p95_slippage_bps: Decimal
    after_cost_return_pct: Decimal
    max_drawdown_pct: Decimal
    capacity_utilization_pct: Decimal
    liquidity_utilization_pct: Decimal
    paper_shadow_divergence_count: int
    broker_disconnect_count: int
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapitalScalingReview:
    current_tier: CapitalScalingTier
    proposed_tier: CapitalScalingTier
    evidence: CapitalScalingEvidence
    schema_version: str = CAPITAL_SCALING_REVIEW_SCHEMA_VERSION


@dataclass(frozen=True)
class CapitalScalingReviewDecision:
    review_status: str
    recommended_action: str
    eligible_for_scale_up_review: bool
    input_errors: tuple[str, ...]
    scale_up_blockers: tuple[str, ...]
    scale_down_triggers: tuple[str, ...]
    disable_triggers: tuple[str, ...]
    tier_delta: tuple[tuple[str, Any], ...]
    metrics: tuple[tuple[str, Any], ...]
    evidence_refs: tuple[str, ...]
    input_fingerprint: str
    schema_version: str = CAPITAL_SCALING_DECISION_SCHEMA_VERSION
    evidence_source_resolution_status: str = "declared_refs_not_resolved"
    authority_change_applied: bool = False
    automatic_scale_up_enabled: bool = False
    does_not_issue_capital_authorization: bool = True
    does_not_mutate_runtime_limits: bool = True
    does_not_resume_execution: bool = True
    does_not_submit_broker_order: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "review_status": self.review_status,
            "recommended_action": self.recommended_action,
            "eligible_for_scale_up_review": self.eligible_for_scale_up_review,
            "input_errors": list(self.input_errors),
            "scale_up_blockers": list(self.scale_up_blockers),
            "scale_down_triggers": list(self.scale_down_triggers),
            "disable_triggers": list(self.disable_triggers),
            "tier_delta": dict(self.tier_delta),
            "metrics": dict(self.metrics),
            "evidence_refs": list(self.evidence_refs),
            "input_fingerprint": self.input_fingerprint,
            "evidence_source_resolution_status": (
                self.evidence_source_resolution_status
            ),
            "safety": {
                "authority_change_applied": self.authority_change_applied,
                "automatic_scale_up_enabled": self.automatic_scale_up_enabled,
                "does_not_issue_capital_authorization": (
                    self.does_not_issue_capital_authorization
                ),
                "does_not_mutate_runtime_limits": (self.does_not_mutate_runtime_limits),
                "does_not_resume_execution": self.does_not_resume_execution,
                "does_not_submit_broker_order": self.does_not_submit_broker_order,
            },
        }


def evaluate_capital_scaling_review(
    review: CapitalScalingReview,
) -> CapitalScalingReviewDecision:
    """Return deterministic recommendation evidence; never change authority."""

    evidence = review.evidence
    input_errors = _input_errors(review)
    tier_delta = _tier_delta(review.current_tier, review.proposed_tier)
    metrics = _metrics(evidence)
    disable_triggers = _disable_triggers(review, metrics)
    scale_down_triggers = _scale_down_triggers(evidence, metrics)
    scale_up_blockers = _scale_up_blockers(
        review,
        metrics=metrics,
        input_errors=input_errors,
        disable_triggers=disable_triggers,
        scale_down_triggers=scale_down_triggers,
        tier_delta=tier_delta,
    )

    eligible = not scale_up_blockers
    if input_errors:
        recommended_action = "hold"
        review_status = "blocked_invalid_evidence"
    elif disable_triggers:
        recommended_action = "disable"
        review_status = "protective_action_recommended"
    elif scale_down_triggers:
        recommended_action = "scale_down"
        review_status = "protective_action_recommended"
    elif eligible:
        recommended_action = "request_new_authorization_for_scale_up"
        review_status = "eligible_for_human_scale_up_review"
    else:
        recommended_action = "hold"
        review_status = "hold_for_more_or_better_evidence"

    return CapitalScalingReviewDecision(
        review_status=review_status,
        recommended_action=recommended_action,
        eligible_for_scale_up_review=eligible,
        input_errors=tuple(input_errors),
        scale_up_blockers=tuple(scale_up_blockers),
        scale_down_triggers=tuple(scale_down_triggers),
        disable_triggers=tuple(disable_triggers),
        tier_delta=tuple(tier_delta.items()),
        metrics=tuple(metrics.items()),
        evidence_refs=_dedupe(evidence.evidence_refs),
        input_fingerprint=_fingerprint(review),
    )


def _input_errors(review: CapitalScalingReview) -> list[str]:
    evidence = review.evidence
    errors: list[str] = []
    if review.schema_version != CAPITAL_SCALING_REVIEW_SCHEMA_VERSION:
        errors.append("unsupported_schema_version")
    for label, tier in (
        ("current", review.current_tier),
        ("proposed", review.proposed_tier),
    ):
        if not tier.tier_id.strip():
            errors.append(f"{label}_tier_id_missing")
        if not tier.policy_version.strip():
            errors.append(f"{label}_policy_version_missing")
        for name, value in asdict(tier.limits).items():
            if value <= 0:
                errors.append(f"{label}_tier_limit_invalid:{name}")
    if not _is_aware(evidence.review_window_start) or not _is_aware(
        evidence.review_window_end
    ):
        errors.append("review_window_timezone_missing")
    elif evidence.review_window_start >= evidence.review_window_end:
        errors.append("review_window_invalid")
    integer_values = {
        "reviewed_trading_days": evidence.reviewed_trading_days,
        "order_count": evidence.order_count,
        "filled_order_count": evidence.filled_order_count,
        "rejected_order_count": evidence.rejected_order_count,
        "partial_fill_count": evidence.partial_fill_count,
        "critical_incident_count": evidence.critical_incident_count,
        "policy_violation_count": evidence.policy_violation_count,
        "unresolved_reconciliation_count": (evidence.unresolved_reconciliation_count),
        "paper_shadow_divergence_count": (evidence.paper_shadow_divergence_count),
        "broker_disconnect_count": evidence.broker_disconnect_count,
    }
    for name, value in integer_values.items():
        if value < 0:
            errors.append(f"negative_metric:{name}")
    if evidence.filled_order_count > evidence.order_count:
        errors.append("filled_order_count_exceeds_orders")
    if evidence.rejected_order_count > evidence.order_count:
        errors.append("rejected_order_count_exceeds_orders")
    if (
        evidence.filled_order_count + evidence.rejected_order_count
        > evidence.order_count
    ):
        errors.append("terminal_order_counts_exceed_orders")
    nonnegative_decimals = {
        "p95_reconciliation_latency_minutes": (
            evidence.p95_reconciliation_latency_minutes
        ),
        "average_slippage_bps": evidence.average_slippage_bps,
        "p95_slippage_bps": evidence.p95_slippage_bps,
        "max_drawdown_pct": evidence.max_drawdown_pct,
        "capacity_utilization_pct": evidence.capacity_utilization_pct,
        "liquidity_utilization_pct": evidence.liquidity_utilization_pct,
    }
    for name, value in nonnegative_decimals.items():
        if value < 0:
            errors.append(f"negative_metric:{name}")
    if evidence.p95_slippage_bps < evidence.average_slippage_bps:
        errors.append("p95_slippage_below_average")
    return errors


def _metrics(evidence: CapitalScalingEvidence) -> dict[str, Any]:
    order_count = max(0, evidence.order_count)
    fill_rate = (
        Decimal(evidence.filled_order_count) / Decimal(order_count)
        if order_count
        else Decimal("0")
    )
    rejection_rate = (
        Decimal(evidence.rejected_order_count) / Decimal(order_count)
        if order_count
        else Decimal("0")
    )
    return {
        "reviewed_trading_days": evidence.reviewed_trading_days,
        "order_count": evidence.order_count,
        "fill_rate": _decimal_string(fill_rate),
        "rejection_rate": _decimal_string(rejection_rate),
        "partial_fill_count": evidence.partial_fill_count,
        "critical_incident_count": evidence.critical_incident_count,
        "policy_violation_count": evidence.policy_violation_count,
        "unresolved_reconciliation_count": (evidence.unresolved_reconciliation_count),
        "p95_reconciliation_latency_minutes": _decimal_string(
            evidence.p95_reconciliation_latency_minutes
        ),
        "average_slippage_bps": _decimal_string(evidence.average_slippage_bps),
        "p95_slippage_bps": _decimal_string(evidence.p95_slippage_bps),
        "after_cost_return_pct": _decimal_string(evidence.after_cost_return_pct),
        "max_drawdown_pct": _decimal_string(evidence.max_drawdown_pct),
        "capacity_utilization_pct": _decimal_string(evidence.capacity_utilization_pct),
        "liquidity_utilization_pct": _decimal_string(
            evidence.liquidity_utilization_pct
        ),
        "paper_shadow_divergence_count": (evidence.paper_shadow_divergence_count),
        "broker_disconnect_count": evidence.broker_disconnect_count,
    }


def _disable_triggers(
    review: CapitalScalingReview,
    metrics: dict[str, Any],
) -> list[str]:
    evidence = review.evidence
    triggers: list[str] = []
    if evidence.critical_incident_count > 0:
        triggers.append("critical_incident_observed")
    if evidence.policy_violation_count > 0:
        triggers.append("policy_violation_observed")
    if evidence.unresolved_reconciliation_count > 0:
        triggers.append("unresolved_reconciliation_observed")
    if evidence.max_drawdown_pct >= review.current_tier.limits.max_drawdown_pct:
        triggers.append("current_tier_drawdown_limit_reached")
    return triggers


def _scale_down_triggers(
    evidence: CapitalScalingEvidence,
    metrics: dict[str, Any],
) -> list[str]:
    rejection_rate = Decimal(str(metrics["rejection_rate"]))
    triggers: list[str] = []
    if rejection_rate > Decimal("0.05"):
        triggers.append("rejection_rate_degraded")
    if evidence.p95_slippage_bps > Decimal("50"):
        triggers.append("p95_slippage_degraded")
    if evidence.after_cost_return_pct < 0:
        triggers.append("after_cost_result_negative")
    if evidence.capacity_utilization_pct > 1:
        triggers.append("capacity_overloaded")
    if evidence.liquidity_utilization_pct > 1:
        triggers.append("liquidity_overloaded")
    if evidence.p95_reconciliation_latency_minutes > Decimal("60"):
        triggers.append("reconciliation_latency_degraded")
    if evidence.paper_shadow_divergence_count > 5:
        triggers.append("paper_shadow_divergence_degraded")
    if evidence.broker_disconnect_count > 3:
        triggers.append("broker_disconnect_rate_degraded")
    return triggers


def _scale_up_blockers(
    review: CapitalScalingReview,
    *,
    metrics: dict[str, Any],
    input_errors: list[str],
    disable_triggers: list[str],
    scale_down_triggers: list[str],
    tier_delta: dict[str, Any],
) -> list[str]:
    evidence = review.evidence
    blockers = list(input_errors)
    blockers.extend(disable_triggers)
    blockers.extend(scale_down_triggers)
    if not tier_delta["widened_fields"]:
        blockers.append("proposed_tier_does_not_expand_any_limit")
    if evidence.reviewed_trading_days < MIN_REVIEWED_TRADING_DAYS:
        blockers.append("reviewed_trading_days_insufficient")
    if evidence.order_count < MIN_REVIEWED_ORDERS:
        blockers.append("reviewed_order_count_insufficient")
    if Decimal(str(metrics["fill_rate"])) < MIN_FILL_RATE:
        blockers.append("fill_rate_below_threshold")
    if Decimal(str(metrics["rejection_rate"])) > MAX_SCALE_UP_REJECTION_RATE:
        blockers.append("rejection_rate_above_threshold")
    if evidence.average_slippage_bps > MAX_SCALE_UP_AVERAGE_SLIPPAGE_BPS:
        blockers.append("average_slippage_above_threshold")
    if evidence.p95_slippage_bps > MAX_SCALE_UP_P95_SLIPPAGE_BPS:
        blockers.append("p95_slippage_above_threshold")
    if evidence.after_cost_return_pct <= 0:
        blockers.append("after_cost_result_not_positive")
    if evidence.max_drawdown_pct >= review.current_tier.limits.max_drawdown_pct:
        blockers.append("drawdown_not_below_current_limit")
    if evidence.capacity_utilization_pct > MAX_SCALE_UP_CAPACITY_UTILIZATION:
        blockers.append("capacity_utilization_above_threshold")
    if evidence.liquidity_utilization_pct > MAX_SCALE_UP_LIQUIDITY_UTILIZATION:
        blockers.append("liquidity_utilization_above_threshold")
    if (
        evidence.p95_reconciliation_latency_minutes
        > MAX_SCALE_UP_RECONCILIATION_MINUTES
    ):
        blockers.append("reconciliation_latency_above_threshold")
    if evidence.paper_shadow_divergence_count > MAX_SCALE_UP_DIVERGENCE_COUNT:
        blockers.append("paper_shadow_divergence_above_threshold")
    if evidence.broker_disconnect_count > MAX_SCALE_UP_DISCONNECT_COUNT:
        blockers.append("broker_disconnect_count_above_threshold")
    for prefix in _REQUIRED_EVIDENCE_PREFIXES:
        if not any(ref.startswith(prefix) for ref in evidence.evidence_refs):
            blockers.append(f"required_evidence_missing:{prefix[:-1]}")
    return list(dict.fromkeys(blockers))


def _tier_delta(
    current: CapitalScalingTier,
    proposed: CapitalScalingTier,
) -> dict[str, Any]:
    current_limits = asdict(current.limits)
    proposed_limits = asdict(proposed.limits)
    widened = sorted(
        name for name, value in proposed_limits.items() if value > current_limits[name]
    )
    tightened = sorted(
        name for name, value in proposed_limits.items() if value < current_limits[name]
    )
    return {
        "current_tier_id": current.tier_id,
        "proposed_tier_id": proposed.tier_id,
        "current_policy_version": current.policy_version,
        "proposed_policy_version": proposed.policy_version,
        "widened_fields": widened,
        "tightened_fields": tightened,
        "unchanged": not widened and not tightened,
        "current_limits": {
            key: _decimal_string(value) for key, value in current_limits.items()
        },
        "proposed_limits": {
            key: _decimal_string(value) for key, value in proposed_limits.items()
        },
    }


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))
