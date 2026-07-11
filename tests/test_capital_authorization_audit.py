from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from server.db import AppDatabase
from server.services.capital_authorization import (
    CapitalAuthorizationContext,
    CapitalAuthorizationLimits,
    CapitalAuthorizationPolicy,
)
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_TYPE,
    CapitalAuthorizationAuditService,
)


def _policy(now: datetime) -> CapitalAuthorizationPolicy:
    return CapitalAuthorizationPolicy(
        authorization_id="auth-audit-001",
        policy_version="owner-policy-v1",
        mode="manual_each_order",
        enabled=True,
        authorized_by="owner",
        connector_ids=("broker-1",),
        evidence_connector_ids=("broker-readonly-1",),
        execution_gateway_ids=("broker-execution-1",),
        account_aliases=("primary",),
        strategy_ids=("etf-rotation",),
        symbols=("510300.SH",),
        effective_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
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
        evidence_refs=("operator_authorization:auth-audit-001",),
    )


def _context(now: datetime) -> CapitalAuthorizationContext:
    return CapitalAuthorizationContext(
        now=now,
        connector_id="broker-1",
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


def test_preview_does_not_persist_or_enable_execution(tmp_path) -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    service = CapitalAuthorizationAuditService(db=db, clock=lambda: now)

    preview = service.preview(policy=_policy(now), context=_context(now))

    assert preview["allowed"] is True
    assert preview["persisted"] is False
    assert preview["does_not_enable_execution"] is True
    assert preview["runtime_authority_status"] == "disabled"
    assert preview["operator_identity_verified"] is False
    assert db.list_events_sync(event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE) == []


def test_record_evaluation_is_append_only_and_idempotent_by_input(tmp_path) -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    service = CapitalAuthorizationAuditService(db=db, clock=lambda: now)

    first = service.record_evaluation(policy=_policy(now), context=_context(now))
    rerun = service.record_evaluation(policy=_policy(now), context=_context(now))

    assert first["persisted"] is True
    assert first["reused"] is False
    assert first["decision"]["allowed"] is True
    assert first["does_not_enable_execution"] is True
    assert first["broker_submission_enabled"] is False
    assert rerun["evaluation_id"] == first["evaluation_id"]
    assert rerun["reused"] is True
    assert len(service.list_evaluations()) == 1


def test_status_keeps_runtime_authority_disabled_after_allowed_evaluation(
    tmp_path,
) -> None:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    service = CapitalAuthorizationAuditService(db=db, clock=lambda: now)
    service.record_evaluation(policy=_policy(now), context=_context(now))

    status = service.get_status()

    assert status["runtime_authority_status"] == "disabled"
    assert status["execution_authority_enabled"] is False
    assert status["broker_submission_enabled"] is False
    assert status["automatic_resume_enabled"] is False
    assert status["automatic_scale_up_enabled"] is False
    assert status["config_can_grant_execution_authority"] is False
    assert status["operator_identity_verified"] is False
    assert status["latest_evaluation"]["decision"]["allowed"] is True
