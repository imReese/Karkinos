from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from server.services.capital_authorization import (
    CapitalAuthorizationContext,
    CapitalAuthorizationLimits,
    CapitalAuthorizationPolicy,
    evaluate_capital_authorization,
)


def _policy(
    now: datetime,
    *,
    mode: str = "manual_each_order",
) -> CapitalAuthorizationPolicy:
    return CapitalAuthorizationPolicy(
        authorization_id="auth-001",
        policy_version="owner-policy-v1",
        mode=mode,
        enabled=True,
        authorized_by="owner",
        connector_ids=("broker-readiness-1",),
        evidence_connector_ids=("broker-readonly-1",),
        execution_gateway_ids=("broker-execution-1",),
        account_aliases=("primary",),
        strategy_ids=("etf-rotation",),
        symbols=("510300.SH",),
        effective_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        limits=CapitalAuthorizationLimits(
            max_authorized_capital=Decimal("50000"),
            max_order_value=Decimal("10000"),
            max_position_change_value=Decimal("10000"),
            max_daily_turnover=Decimal("30000"),
            max_daily_loss=Decimal("1000"),
            max_drawdown_pct=Decimal("0.05"),
            max_order_rate_per_minute=2,
            max_consecutive_errors=2,
        ),
        evidence_refs=("operator_authorization:auth-001",),
    )


def _context(now: datetime) -> CapitalAuthorizationContext:
    return CapitalAuthorizationContext(
        now=now,
        connector_id="broker-readiness-1",
        account_alias="primary",
        strategy_id="etf-rotation",
        symbol="510300.SH",
        order_value=Decimal("8000"),
        position_change_value=Decimal("8000"),
        current_authorized_exposure=Decimal("10000"),
        daily_turnover_used=Decimal("5000"),
        current_daily_loss=Decimal("100"),
        current_drawdown_pct=Decimal("0.01"),
        order_rate_per_minute=0,
        consecutive_errors=0,
        available_cash=Decimal("100000"),
        account_capital_limit=Decimal("60000"),
        strategy_capital_limit=Decimal("40000"),
        symbol_capital_limit=Decimal("30000"),
        liquidity_capital_limit=Decimal("25000"),
        market_data_status="confirmed",
        account_truth_status="pass",
        risk_gate_status="passed",
        paper_shadow_status="within_expectations",
        reconciliation_status="clear",
        connector_health_status="healthy",
        connector_can_submit=True,
        kill_switch_enabled=False,
        order_fingerprint="order-fingerprint-1",
        manual_confirmation_fingerprint="order-fingerprint-1",
        evidence_refs=("risk:risk-001", "reconciliation:recon-001"),
        evidence_connector_id="broker-readonly-1",
        execution_gateway_id="broker-execution-1",
        evidence_connector_health_status="healthy",
        evidence_connector_can_submit=False,
        execution_gateway_health_status="healthy",
        execution_gateway_can_submit=True,
        connector_account_binding_status="verified",
    )


def test_disabled_authorization_fails_closed_without_execution_authority() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)

    decision = evaluate_capital_authorization(
        CapitalAuthorizationPolicy(),
        _context(now),
    )

    assert decision.allowed is False
    assert decision.blocked_reasons == (
        "authorization_disabled",
        "authorization_mode_disabled",
    )
    assert decision.remaining_budget == ()
    assert decision.to_dict()["safety"] == {
        "does_not_submit_broker_order": True,
        "does_not_cancel_broker_order": True,
        "does_not_mutate_oms": True,
        "does_not_mutate_production_ledger": True,
        "does_not_enable_or_expand_authority": True,
    }


def test_manual_each_order_allows_only_matching_confirmed_order() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)

    decision = evaluate_capital_authorization(_policy(now), _context(now))

    assert decision.allowed is True
    assert decision.blocked_reasons == ()
    assert dict(decision.effective_limits)["effective_capital"] == "30000"
    assert dict(decision.effective_limits)["effective_order_value"] == "10000"
    assert dict(decision.remaining_budget) == {
        "authorized_capital_after_order": "12000",
        "available_cash_after_order": "92000",
        "liquidity_after_order": "17000",
        "daily_turnover_after_order": "17000",
        "daily_loss": "900",
        "drawdown_pct": "0.04",
        "orders_per_minute": "2",
        "consecutive_errors": "2",
    }
    assert decision.evidence_refs == (
        "operator_authorization:auth-001",
        "risk:risk-001",
        "reconciliation:recon-001",
    )


def test_manual_each_order_rejects_stale_confirmation_fingerprint() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    context = replace(
        _context(now), manual_confirmation_fingerprint="older-order-fingerprint"
    )

    decision = evaluate_capital_authorization(_policy(now), context)

    assert decision.allowed is False
    assert "manual_confirmation_mismatch" in decision.blocked_reasons


def test_session_bounded_uses_strictest_capital_limit() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    context = replace(
        _context(now),
        current_authorized_exposure=Decimal("25000"),
        order_value=Decimal("6000"),
        position_change_value=Decimal("6000"),
        manual_confirmation_fingerprint="",
    )

    decision = evaluate_capital_authorization(
        _policy(now, mode="session_bounded"),
        context,
    )

    assert decision.allowed is False
    assert "authorized_capital_exceeded" in decision.blocked_reasons
    assert dict(decision.effective_limits)["effective_capital"] == "30000"
    assert dict(decision.remaining_budget)["authorized_capital_after_order"] == "0"
    assert "manual_confirmation_mismatch" not in decision.blocked_reasons


def test_expiry_kill_switch_and_reconciliation_fail_closed() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    policy = replace(_policy(now), expires_at=now)
    context = replace(
        _context(now),
        kill_switch_enabled=True,
        reconciliation_status="mismatch",
    )

    decision = evaluate_capital_authorization(policy, context)

    assert decision.allowed is False
    assert "authorization_expired" in decision.blocked_reasons
    assert "kill_switch_enabled" in decision.blocked_reasons
    assert "reconciliation_not_clear" in decision.blocked_reasons


def test_enabled_authorization_with_missing_identity_and_time_fails_closed() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    policy = replace(
        _policy(now),
        authorization_id="",
        policy_version="",
        authorized_by="",
        effective_at=datetime(2026, 7, 10, 9, 0),
        expires_at=datetime(2026, 7, 10, 10, 0),
    )

    decision = evaluate_capital_authorization(policy, _context(now))

    assert decision.allowed is False
    assert "missing_authorization_id" in decision.blocked_reasons
    assert "missing_policy_version" in decision.blocked_reasons
    assert "missing_authorized_by" in decision.blocked_reasons
    assert "invalid_authorization_time" in decision.blocked_reasons


@pytest.mark.parametrize(
    ("field_name", "unsafe_value", "expected_reason"),
    [
        ("market_data_status", "stale", "market_data_not_current"),
        ("account_truth_status", "degraded", "account_truth_not_clear"),
        ("risk_gate_status", "blocked", "risk_gate_not_passed"),
        ("paper_shadow_status", "diverged", "paper_shadow_not_clear"),
        ("reconciliation_status", "mismatch", "reconciliation_not_clear"),
        (
            "evidence_connector_health_status",
            "degraded",
            "evidence_connector_not_healthy",
        ),
        (
            "evidence_connector_can_submit",
            True,
            "evidence_connector_exposes_submit_capability",
        ),
        (
            "execution_gateway_can_submit",
            False,
            "execution_gateway_submit_capability_unavailable",
        ),
        (
            "execution_gateway_health_status",
            "degraded",
            "execution_gateway_not_healthy",
        ),
        (
            "connector_account_binding_status",
            "unverified",
            "connector_account_binding_not_verified",
        ),
        ("kill_switch_enabled", True, "kill_switch_enabled"),
    ],
)
def test_each_upstream_safety_gate_fails_closed(
    field_name: str,
    unsafe_value: str | bool,
    expected_reason: str,
) -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    context = replace(_context(now), **{field_name: unsafe_value})

    decision = evaluate_capital_authorization(_policy(now), context)

    assert decision.allowed is False
    assert expected_reason in decision.blocked_reasons


def test_decision_fingerprint_is_deterministic_and_input_sensitive() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    policy = _policy(now)
    context = _context(now)

    first = evaluate_capital_authorization(policy, context)
    rerun = evaluate_capital_authorization(policy, context)
    changed = evaluate_capital_authorization(
        policy,
        replace(context, order_value=Decimal("8001")),
    )

    assert first.input_fingerprint == rerun.input_fingerprint
    assert first.input_fingerprint != changed.input_fingerprint


def test_dual_connector_scope_is_required_and_legacy_connector_cannot_authorize() -> (
    None
):
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    policy = replace(
        _policy(now),
        evidence_connector_ids=(),
        execution_gateway_ids=(),
        connector_ids=("broker-readiness-1",),
    )

    decision = evaluate_capital_authorization(policy, _context(now))

    assert decision.allowed is False
    assert "evidence_connector_not_authorized" in decision.blocked_reasons
    assert "execution_gateway_not_authorized" in decision.blocked_reasons
    assert decision.to_dict()["safety"]["does_not_enable_or_expand_authority"] is True


def test_evidence_connector_and_execution_gateway_roles_cannot_overlap() -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    policy = replace(
        _policy(now),
        evidence_connector_ids=("shared-connector",),
        execution_gateway_ids=("shared-connector",),
    )
    context = replace(
        _context(now),
        evidence_connector_id="shared-connector",
        execution_gateway_id="shared-connector",
    )

    decision = evaluate_capital_authorization(policy, context)

    assert decision.allowed is False
    assert "connector_roles_not_separated" in decision.blocked_reasons
    assert "connector_role_scope_overlap" in decision.blocked_reasons
