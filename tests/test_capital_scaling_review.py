from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from server.db import AppDatabase
from server.services.capital_scaling_review import (
    CapitalScalingEvidence,
    CapitalScalingReview,
    CapitalScalingTier,
    CapitalScalingTierLimits,
    evaluate_capital_scaling_review,
)
from server.services.capital_scaling_review_audit import (
    CAPITAL_SCALING_EVALUATION_EVENT_TYPE,
    CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE,
    CapitalScalingReviewAuditService,
    CapitalScalingReviewDecisionRejected,
)

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


def _tier(
    tier_id: str,
    capital: str,
    *,
    order: str,
    turnover: str,
    daily_loss: str,
    drawdown: str = "0.05",
) -> CapitalScalingTier:
    return CapitalScalingTier(
        tier_id=tier_id,
        policy_version=f"{tier_id}-policy-v1",
        limits=CapitalScalingTierLimits(
            max_authorized_capital=Decimal(capital),
            max_order_value=Decimal(order),
            max_daily_turnover=Decimal(turnover),
            max_daily_loss=Decimal(daily_loss),
            max_drawdown_pct=Decimal(drawdown),
        ),
    )


def _evidence() -> CapitalScalingEvidence:
    return CapitalScalingEvidence(
        review_window_start=NOW - timedelta(days=35),
        review_window_end=NOW,
        reviewed_trading_days=25,
        order_count=100,
        filled_order_count=98,
        rejected_order_count=1,
        partial_fill_count=4,
        critical_incident_count=0,
        policy_violation_count=0,
        unresolved_reconciliation_count=0,
        p95_reconciliation_latency_minutes=Decimal("15"),
        average_slippage_bps=Decimal("5"),
        p95_slippage_bps=Decimal("12"),
        after_cost_return_pct=Decimal("0.08"),
        max_drawdown_pct=Decimal("0.02"),
        capacity_utilization_pct=Decimal("0.60"),
        liquidity_utilization_pct=Decimal("0.50"),
        paper_shadow_divergence_count=0,
        broker_disconnect_count=0,
        evidence_refs=(
            "account_truth:account-window",
            "broker_soak:fixture-soak-20-days",
            "execution_reconciliation:review-window",
            "paper_shadow:divergence-summary",
            "after_cost:execution-quality",
            "risk:drawdown-review",
            "incident:operations-review",
            "capacity:liquidity-review",
            "operating_sample:review-window",
            "execution_scope:review-window",
        ),
    )


def _review(evidence: CapitalScalingEvidence | None = None) -> CapitalScalingReview:
    return CapitalScalingReview(
        current_tier=_tier(
            "pilot-1",
            "10000",
            order="2000",
            turnover="20000",
            daily_loss="500",
        ),
        proposed_tier=_tier(
            "pilot-2",
            "20000",
            order="3000",
            turnover="30000",
            daily_loss="800",
        ),
        evidence=evidence or _evidence(),
    )


def test_strong_evidence_only_requests_new_human_authorization() -> None:
    decision = evaluate_capital_scaling_review(_review())

    assert decision.review_status == "eligible_for_human_scale_up_review"
    assert decision.recommended_action == "request_new_authorization_for_scale_up"
    assert decision.eligible_for_scale_up_review is True
    assert decision.scale_up_blockers == ()
    assert "max_authorized_capital" in dict(decision.tier_delta)["widened_fields"]
    payload = decision.to_dict()
    assert payload["safety"]["authority_change_applied"] is False
    assert payload["evidence_source_resolution_status"] == (
        "declared_refs_not_resolved"
    )
    assert payload["safety"]["automatic_scale_up_enabled"] is False
    assert payload["safety"]["does_not_issue_capital_authorization"] is True


def test_insufficient_sample_or_missing_provenance_holds_scale_up() -> None:
    evidence = replace(
        _evidence(),
        reviewed_trading_days=10,
        order_count=20,
        filled_order_count=19,
        rejected_order_count=0,
        evidence_refs=("risk:drawdown-review",),
    )

    decision = evaluate_capital_scaling_review(_review(evidence))

    assert decision.recommended_action == "hold"
    assert "reviewed_trading_days_insufficient" in decision.scale_up_blockers
    assert "reviewed_order_count_insufficient" in decision.scale_up_blockers
    assert "required_evidence_missing:broker_soak" in decision.scale_up_blockers
    assert decision.eligible_for_scale_up_review is False


def test_critical_incident_policy_violation_or_reconciliation_gap_disables() -> None:
    evidence = replace(
        _evidence(),
        critical_incident_count=1,
        policy_violation_count=1,
        unresolved_reconciliation_count=1,
    )

    decision = evaluate_capital_scaling_review(_review(evidence))

    assert decision.recommended_action == "disable"
    assert set(decision.disable_triggers) == {
        "critical_incident_observed",
        "policy_violation_observed",
        "unresolved_reconciliation_observed",
    }
    assert decision.to_dict()["safety"]["does_not_mutate_runtime_limits"] is True


def test_degraded_execution_quality_recommends_scale_down_without_applying_it() -> None:
    evidence = replace(
        _evidence(),
        filled_order_count=85,
        rejected_order_count=10,
        p95_slippage_bps=Decimal("60"),
        after_cost_return_pct=Decimal("-0.03"),
        capacity_utilization_pct=Decimal("1.10"),
    )

    decision = evaluate_capital_scaling_review(_review(evidence))

    assert decision.recommended_action == "scale_down"
    assert "rejection_rate_degraded" in decision.scale_down_triggers
    assert "p95_slippage_degraded" in decision.scale_down_triggers
    assert "after_cost_result_negative" in decision.scale_down_triggers
    assert "capacity_overloaded" in decision.scale_down_triggers
    assert decision.to_dict()["safety"]["authority_change_applied"] is False


def test_drawdown_at_current_tier_limit_recommends_disable() -> None:
    evidence = replace(_evidence(), max_drawdown_pct=Decimal("0.05"))

    decision = evaluate_capital_scaling_review(_review(evidence))

    assert decision.recommended_action == "disable"
    assert "current_tier_drawdown_limit_reached" in decision.disable_triggers


def test_invalid_evidence_fails_closed_to_hold() -> None:
    evidence = replace(
        _evidence(),
        review_window_start=NOW.replace(tzinfo=None),
        review_window_end=(NOW - timedelta(days=1)).replace(tzinfo=None),
        filled_order_count=101,
        average_slippage_bps=Decimal("20"),
        p95_slippage_bps=Decimal("10"),
    )

    decision = evaluate_capital_scaling_review(_review(evidence))

    assert decision.review_status == "blocked_invalid_evidence"
    assert decision.recommended_action == "hold"
    assert "review_window_timezone_missing" in decision.input_errors
    assert "filled_order_count_exceeds_orders" in decision.input_errors
    assert "p95_slippage_below_average" in decision.input_errors


def test_legacy_v1_review_contract_is_not_canonical() -> None:
    legacy = replace(_review(), schema_version="karkinos.capital_scaling_review.v1")

    decision = evaluate_capital_scaling_review(legacy)

    assert decision.review_status == "blocked_invalid_evidence"
    assert decision.recommended_action == "hold"
    assert "unsupported_schema_version" in decision.input_errors
    assert decision.does_not_issue_capital_authorization is True


def test_same_tier_cannot_be_scale_up_candidate_and_fingerprint_is_sensitive() -> None:
    review = _review()
    same_tier = replace(review, proposed_tier=review.current_tier)

    same = evaluate_capital_scaling_review(same_tier)
    changed = evaluate_capital_scaling_review(
        _review(replace(_evidence(), average_slippage_bps=Decimal("6")))
    )
    original = evaluate_capital_scaling_review(review)

    assert same.recommended_action == "hold"
    assert "proposed_tier_does_not_expand_any_limit" in same.scale_up_blockers
    assert changed.input_fingerprint != original.input_fingerprint
    assert evaluate_capital_scaling_review(review).input_fingerprint == (
        original.input_fingerprint
    )


def test_evaluation_and_hold_decision_are_append_only_and_non_mutating_when_sources_unresolved(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-review.db")
    db.init_sync()
    service = CapitalScalingReviewAuditService(db=db, clock=lambda: NOW)

    evaluation = service.record_evaluation(review=_review())
    rerun = service.record_evaluation(review=_review())
    first = service.record_review_decision(
        evaluation_fingerprint=evaluation["evaluation_fingerprint"],
        chosen_action="hold",
        operator_label="local-owner",
        acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    )
    decision_rerun = service.record_review_decision(
        evaluation_fingerprint=evaluation["evaluation_fingerprint"],
        chosen_action="hold",
        operator_label="local-owner",
        acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    )

    assert evaluation["decision"]["eligible_for_scale_up_review"] is False
    assert evaluation["decision"]["recommended_action"] == "hold"
    assert evaluation["evidence_source_resolution_status"] == (
        "blocked_unresolved_sources"
    )
    assert (
        evaluation["evidence_resolution"]["all_required_sources_resolved_clear"]
        is False
    )
    assert (
        evaluation["review_input_fingerprint"] != evaluation["evaluation_fingerprint"]
    )
    assert rerun["event_id"] == evaluation["event_id"]
    assert rerun["reused"] is True
    assert first["status"] == "recorded_unverified_identity"
    assert first["requests_new_authorization"] is False
    assert first["new_authorization_issued"] is False
    assert first["authority_change_applied"] is False
    assert first["operator_identity_verified"] is False
    assert decision_rerun["event_id"] == first["event_id"]
    assert decision_rerun["reused"] is True
    assert (
        len(db.list_events_sync(event_type=CAPITAL_SCALING_EVALUATION_EVENT_TYPE)) == 1
    )
    assert (
        len(db.list_events_sync(event_type=CAPITAL_SCALING_REVIEW_DECISION_EVENT_TYPE))
        == 1
    )


def test_human_decision_cannot_exceed_evidence_recommendation_and_is_audited(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-review.db")
    db.init_sync()
    service = CapitalScalingReviewAuditService(db=db, clock=lambda: NOW)
    hold_review = _review(
        replace(
            _evidence(), reviewed_trading_days=5, order_count=10, filled_order_count=10
        )
    )
    evaluation = service.record_evaluation(review=hold_review)

    with pytest.raises(CapitalScalingReviewDecisionRejected) as exc_info:
        service.record_review_decision(
            evaluation_fingerprint=evaluation["input_fingerprint"],
            chosen_action="request_new_authorization_for_scale_up",
            operator_label="local-owner",
            acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
        )

    evidence = exc_info.value.evidence
    assert evidence["status"] == "rejected"
    assert evidence["rejection_reasons"] == [
        "chosen_action_exceeds_evidence_recommendation"
    ]
    assert evidence["new_authorization_issued"] is False
    assert evidence["authority_change_applied"] is False


def test_human_can_choose_hold_when_persisted_sources_are_unresolved(tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-review.db")
    db.init_sync()
    service = CapitalScalingReviewAuditService(db=db, clock=lambda: NOW)
    evaluation = service.record_evaluation(review=_review())

    decision = service.record_review_decision(
        evaluation_fingerprint=evaluation["evaluation_fingerprint"],
        chosen_action="hold",
        operator_label="local-owner",
        acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    )

    assert decision["status"] == "recorded_unverified_identity"
    assert decision["chosen_action"] == "hold"
    assert decision["requests_new_authorization"] is False
    assert decision["authority_change_applied"] is False


def test_unresolved_persisted_sources_prevent_scale_up_request_and_are_audited(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-review.db")
    db.init_sync()
    service = CapitalScalingReviewAuditService(db=db, clock=lambda: NOW)
    evaluation = service.record_evaluation(review=_review())

    with pytest.raises(CapitalScalingReviewDecisionRejected) as exc_info:
        service.record_review_decision(
            evaluation_fingerprint=evaluation["evaluation_fingerprint"],
            chosen_action="request_new_authorization_for_scale_up",
            operator_label="local-owner",
            acknowledgement=CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
        )

    assert evaluation["decision"]["recommended_action"] == "hold"
    assert "persisted_evidence_source_not_found:after_cost:execution-quality" in (
        evaluation["decision"]["scale_up_blockers"]
    )
    assert exc_info.value.evidence["status"] == "rejected"
    assert exc_info.value.evidence["authority_change_applied"] is False
    assert exc_info.value.evidence["new_authorization_issued"] is False


def test_status_exposes_review_only_no_auto_scale_boundary(tmp_path) -> None:
    db = AppDatabase(tmp_path / "capital-scaling-review.db")
    db.init_sync()

    status = CapitalScalingReviewAuditService(db=db).get_status()

    assert status["review_contract_status"] == "evidence_only"
    assert status["automatic_scale_up_enabled"] is False
    assert status["evidence_source_resolution_status"] == (
        "persisted_fail_closed_resolution"
    )
    assert status["resolvable_evidence_kinds"] == [
        "account_truth",
        "broker_soak",
        "execution_reconciliation",
        "paper_shadow",
        "after_cost",
        "risk",
        "incident",
        "capacity",
        "operating_sample",
        "execution_scope",
    ]
    assert status["unsupported_evidence_kinds"] == []
    assert status["authority_change_enabled"] is False
    assert status["new_authorization_issue_enabled"] is False
    assert status["runtime_limit_mutation_enabled"] is False
    assert status["automatic_protective_recommendations_enabled"] is True
    assert status["automatic_protective_mutation_enabled"] is False
