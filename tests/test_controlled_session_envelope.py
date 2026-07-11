from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.broker_connector_soak import BrokerConnectorSoakService
from server.services.capital_authorization import (
    CapitalAuthorizationContext,
    CapitalAuthorizationLimits,
    CapitalAuthorizationPolicy,
)
from server.services.capital_authorization_audit import (
    CapitalAuthorizationAuditService,
)
from server.services.controlled_session_envelope import (
    CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE,
    ControlledSessionAttestationRejected,
    ControlledSessionEnvelopeService,
)
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    ExecutionBatchReconciliationService,
)
from server.services.oms import OmsService
from server.services.operator_approval import OperatorApprovalService
from server.services.trading_controls import TradingControlState

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


def _gateway_evidence() -> dict:
    return {
        "account_truth": {
            "gate_status": "pass",
            "evidence_ref": "account-truth:session-review-1",
        },
        "research_evidence": {
            "gate_status": "pass",
            "evidence_ref": "research:session-bundle-1",
        },
        "risk": {
            "gate_status": "passed",
            "evidence_ref": "risk:session-decision-1",
        },
        "paper_shadow": {
            "divergence_status": "within_expectations",
            "evidence_ref": "paper-shadow:session-run-1",
        },
    }


def _connector(now: datetime = NOW) -> FakeReadOnlyBrokerConnector:
    return FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="qmt-readonly-session",
            source_name="synthetic QMT readonly export",
            account_id="private-session-account-id-must-not-leak",
            account_alias="qmt-session-review",
            captured_at=now.isoformat(),
            health=BrokerConnectorHealth(
                status="healthy",
                checked_at=now.isoformat(),
            ),
            cash=BrokerCashFact(
                currency="CNY",
                balance=Decimal("100000"),
                available=Decimal("90000"),
            ),
        )
    )


def _ready_environment(tmp_path) -> dict:
    db = AppDatabase(tmp_path / "controlled-session-envelope.db")
    db.init_sync()
    db.upsert_market_calendar_snapshot_sync(
        build_static_market_calendar_snapshot(
            exchange="SSE",
            year=2026,
            provider="synthetic_test_calendar",
            open_dates=["2026-07-10"],
            fetched_at=NOW.isoformat(),
        )
    )
    connector = _connector()
    BrokerConnectorSoakService(
        db=db,
        connectors=[connector],
        clock=lambda: NOW,
    ).capture()
    prior_order_id = "prior-session-order-1"
    db.upsert_oms_order_sync(
        {
            "order_id": prior_order_id,
            "intent_key": prior_order_id,
            "symbol": "510300.SH",
            "side": "buy",
            "asset_class": "fund",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 4.0,
            "status": "cancelled",
            "broker_submission_enabled": False,
            "source": "prior_session_batch_test",
            "payload": {"execution_mode": "manual"},
        }
    )
    reconciliation_run_id = "execution-reconciliation:2026-07-10"
    db.upsert_execution_reconciliation_run_sync(
        run_id=reconciliation_run_id,
        run_date="2026-07-10",
        status="clear",
        item_count=1,
        open_item_count=0,
        payload={"source": "synthetic-test"},
        items=[
            {
                "order_id": prior_order_id,
                "item_status": "cancelled",
                "suggested_action": "no_action",
                "detail": "clear prior session batch",
                "payload": {
                    "oms_status": "cancelled",
                    "execution_mode": "manual",
                },
            }
        ],
    )
    batch_service = ExecutionBatchReconciliationService(db=db, clock=lambda: NOW)
    batch_preview = batch_service.preview(
        batch_id="prior-session-batch-1",
        order_ids=[prior_order_id],
        reconciliation_run_id=reconciliation_run_id,
    )
    batch = batch_service.record(
        batch_id="prior-session-batch-1",
        order_ids=[prior_order_id],
        reconciliation_run_id=reconciliation_run_id,
        batch_reconciliation_fingerprint=batch_preview[
            "batch_reconciliation_fingerprint"
        ],
        operator_label="local-session-owner",
        acknowledgement=EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    )
    batch_ref = (
        "execution_batch_reconciliation:" f"{batch['batch_reconciliation_fingerprint']}"
    )
    oms = OmsService(db=db)
    orders: list[dict] = []
    for symbol, quantity, limit_price in (
        ("510300.SH", 100, 4.0),
        ("159915.SZ", 200, 3.0),
    ):
        order = oms.create_order_intent(
            intent_key=f"session:2026-07-10:{symbol}:buy",
            symbol=symbol,
            side="buy",
            asset_class="fund",
            quantity=quantity,
            order_type="limit",
            limit_price=limit_price,
            source="daily_trading_plan",
            source_ref="paper-shadow:session-run-1",
        )
        order = db.upsert_oms_order_sync(
            {
                **order,
                "payload": {
                    "schema_version": "karkinos.oms_order.v1",
                    "manual_confirmation_required": True,
                    "does_not_submit_broker_order": True,
                    "gateway_evidence": _gateway_evidence(),
                },
            }
        )
        orders.append(order)
    policy = CapitalAuthorizationPolicy(
        authorization_id="session-review-auth-1",
        policy_version="session-policy-v1",
        mode="session_bounded",
        enabled=True,
        authorized_by="local-unverified-session-owner",
        connector_ids=("qmt-readonly-session",),
        evidence_connector_ids=("qmt-readonly-session",),
        execution_gateway_ids=("qmt-execution-session-disabled",),
        account_aliases=("qmt-session-review",),
        strategy_ids=("etf_rotation",),
        symbols=("510300.SH", "159915.SZ"),
        effective_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
        limits=CapitalAuthorizationLimits(
            max_authorized_capital=Decimal("20000"),
            max_order_value=Decimal("5000"),
            max_position_change_value=Decimal("5000"),
            max_daily_turnover=Decimal("10000"),
            max_daily_loss=Decimal("1000"),
            max_drawdown_pct=Decimal("0.05"),
            max_order_rate_per_minute=2,
            max_consecutive_errors=2,
        ),
        evidence_refs=("operator-session-review:local",),
    )
    context = CapitalAuthorizationContext(
        now=NOW,
        connector_id="qmt-readonly-session",
        account_alias="qmt-session-review",
        strategy_id="etf_rotation",
        symbol="510300.SH",
        order_value=Decimal("400"),
        position_change_value=Decimal("400"),
        current_authorized_exposure=Decimal("0"),
        daily_turnover_used=Decimal("0"),
        current_daily_loss=Decimal("0"),
        current_drawdown_pct=Decimal("0"),
        order_rate_per_minute=0,
        consecutive_errors=0,
        available_cash=Decimal("90000"),
        account_capital_limit=Decimal("50000"),
        strategy_capital_limit=Decimal("20000"),
        symbol_capital_limit=Decimal("10000"),
        liquidity_capital_limit=Decimal("5000"),
        market_data_status="confirmed",
        account_truth_status="pass",
        risk_gate_status="passed",
        paper_shadow_status="within_expectations",
        reconciliation_status="clear",
        connector_health_status="healthy",
        connector_can_submit=True,
        kill_switch_enabled=False,
        evidence_refs=("risk:session-decision-1", batch_ref),
        evidence_connector_id="qmt-readonly-session",
        execution_gateway_id="qmt-execution-session-disabled",
        evidence_connector_health_status="healthy",
        evidence_connector_can_submit=False,
        execution_gateway_health_status="healthy",
        execution_gateway_can_submit=True,
        connector_account_binding_status="verified",
    )
    evaluation = CapitalAuthorizationAuditService(
        db=db,
        clock=lambda: NOW,
    ).record_evaluation(policy=policy, context=context)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trusted_identity = TrustedOperatorIdentityConfig(
        operator_id="local-session-owner",
        key_id="session-owner-key-1",
        public_key_base64=base64.b64encode(public_key).decode("ascii"),
        enabled=True,
    )
    controls = TradingControlState(db=db)
    service = ControlledSessionEnvelopeService(
        db=db,
        connectors=[connector],
        trusted_operator_identities=[trusted_identity],
        trading_controls=controls,
        clock=lambda: NOW,
    )
    return {
        "db": db,
        "connector": connector,
        "controls": controls,
        "service": service,
        "orders": orders,
        "order_ids": [order["order_id"] for order in orders],
        "evaluation": evaluation,
        "batch": batch,
        "start_at": NOW,
        "expires_at": NOW + timedelta(minutes=10),
        "private_key": private_key,
        "trusted_identity": trusted_identity,
    }


def _preview(env: dict, *, service=None, **overrides):
    return (service or env["service"]).preview_envelope(
        capital_evaluation_input_fingerprint=overrides.get(
            "capital_evaluation_input_fingerprint",
            env["evaluation"]["input_fingerprint"],
        ),
        prior_batch_reconciliation_fingerprint=overrides.get(
            "prior_batch_reconciliation_fingerprint",
            env["batch"]["batch_reconciliation_fingerprint"],
        ),
        order_ids=overrides.get("order_ids", env["order_ids"]),
        requested_start_at=overrides.get("requested_start_at", env["start_at"]),
        requested_expires_at=overrides.get("requested_expires_at", env["expires_at"]),
    )


def _operator_approval(env: dict, artifact_fingerprint: str) -> dict:
    approval_service = OperatorApprovalService(
        db=env["db"],
        trusted_identities=[env["trusted_identity"]],
        clock=lambda: NOW,
    )
    challenge = approval_service.create_challenge(
        operator_id="local-session-owner",
        key_id="session-owner-key-1",
        action="attest_controlled_session_envelope",
        artifact_type="controlled_session_envelope",
        artifact_fingerprint=artifact_fingerprint,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    return approval_service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def test_session_envelope_projects_conservative_budget_and_stays_non_executing(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)

    envelope = _preview(env)

    assert envelope["review_status"] == "review_ready_non_executing"
    assert envelope["review_blockers"] == []
    budget = envelope["budget_projection"]
    assert budget["calculation_mode"] == ("conservative_gross_without_buy_sell_netting")
    assert budget["projected_gross_order_value"] == "1000"
    assert budget["projected_buy_value"] == "1000"
    assert budget["remaining_authorized_capital_after_projection"] == "9000"
    assert budget["reserved"] is False
    assert envelope["runtime_session_status"] == "not_issued"
    assert envelope["submission_status"] == "blocked"
    assert (
        "atomic_budget_reservation_not_implemented"
        in envelope["hard_submission_blockers"]
    )
    assert (
        "automatic_pause_controller_not_implemented"
        in envelope["hard_submission_blockers"]
    )
    assert (
        "stage2_per_order_bridge_not_promoted" in envelope["hard_submission_blockers"]
    )
    assert (
        "execution_gateway_runtime_not_verified" in envelope["hard_submission_blockers"]
    )
    assert envelope["connector_soak"]["evidence_connector_can_submit"] is False
    assert envelope["execution_gateway"] == {
        "schema_version": "karkinos.execution_gateway_binding.v1",
        "gateway_id": "qmt-execution-session-disabled",
        "declared_health_status": "healthy",
        "declared_can_submit_orders": True,
        "account_binding_status": "verified",
        "runtime_verification_status": "unverified",
        "broker_contacted": False,
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }
    assert (
        "prior_batch_reconciliation_not_bound_or_clear"
        not in envelope["hard_submission_blockers"]
    )
    assert envelope["safety"]["does_not_issue_or_enable_runtime_session"] is True
    assert "private-session-account-id-must-not-leak" not in str(envelope)


def test_exact_session_attestation_is_append_only_reused_and_has_no_side_effects(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    envelope = _preview(env)
    approval = _operator_approval(env, envelope["envelope_fingerprint"])

    first = env["service"].record_attestation(
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        order_ids=env["order_ids"],
        requested_start_at=env["start_at"],
        requested_expires_at=env["expires_at"],
        envelope_fingerprint=envelope["envelope_fingerprint"],
        operator_label="local-session-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    )
    rerun = env["service"].record_attestation(
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        order_ids=env["order_ids"],
        requested_start_at=env["start_at"],
        requested_expires_at=env["expires_at"],
        envelope_fingerprint=envelope["envelope_fingerprint"],
        operator_label="local-session-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    )

    assert first["status"] == "recorded_verified_identity"
    assert first["operator_identity_verified"] is True
    assert "operator_identity_unverified" not in first["hard_submission_blockers"]
    assert first["runtime_session_status"] == "not_issued"
    assert first["authorizes_execution"] is False
    assert first["broker_submission_enabled"] is False
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert (
        len(
            env["db"].list_events_sync(
                event_type=CONTROLLED_SESSION_ATTESTATION_EVENT_TYPE
            )
        )
        == 1
    )
    assert {
        env["db"].get_oms_order_sync(order_id)["status"]
        for order_id in env["order_ids"]
    } == {"awaiting_manual_confirmation"}


def test_session_attestation_rejects_approval_for_another_artifact(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    envelope = _preview(env)
    wrong_approval = _operator_approval(env, "f" * 64)

    with pytest.raises(ControlledSessionAttestationRejected) as exc_info:
        env["service"].record_attestation(
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            order_ids=env["order_ids"],
            requested_start_at=env["start_at"],
            requested_expires_at=env["expires_at"],
            envelope_fingerprint=envelope["envelope_fingerprint"],
            operator_label="local-session-owner",
            operator_approval_id=wrong_approval["approval_id"],
            acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        )

    assert exc_info.value.evidence["rejection_reasons"] == ["operator_approval_blocked"]
    assert exc_info.value.evidence["operator_identity_verified"] is False


def test_session_attestation_rejects_stale_fingerprint_and_blocked_envelope(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    current = _preview(env)
    current_approval = _operator_approval(env, current["envelope_fingerprint"])

    with pytest.raises(ControlledSessionAttestationRejected) as stale_error:
        env["service"].record_attestation(
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            order_ids=env["order_ids"],
            requested_start_at=env["start_at"],
            requested_expires_at=env["expires_at"],
            envelope_fingerprint="0" * 64,
            operator_label="local-session-owner",
            operator_approval_id=current_approval["approval_id"],
            acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        )
    assert stale_error.value.evidence["rejection_reasons"] == [
        "envelope_fingerprint_mismatch"
    ]

    env["controls"].set_kill_switch(True, "operator pause")
    blocked = _preview(env)
    blocked_approval = _operator_approval(env, blocked["envelope_fingerprint"])
    with pytest.raises(ControlledSessionAttestationRejected) as blocked_error:
        env["service"].record_attestation(
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            order_ids=env["order_ids"],
            requested_start_at=env["start_at"],
            requested_expires_at=env["expires_at"],
            envelope_fingerprint=blocked["envelope_fingerprint"],
            operator_label="local-session-owner",
            operator_approval_id=blocked_approval["approval_id"],
            acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
        )
    assert blocked_error.value.evidence["rejection_reasons"] == [
        "envelope_review_blocked"
    ]


def test_session_window_duplicate_orders_and_naive_times_fail_closed(tmp_path) -> None:
    env = _ready_environment(tmp_path)

    envelope = _preview(
        env,
        order_ids=[env["order_ids"][0], env["order_ids"][0]],
        requested_start_at=NOW.replace(tzinfo=None),
        requested_expires_at=(NOW + timedelta(minutes=31)).replace(tzinfo=None),
    )

    assert "session_order_ids_invalid_or_duplicate" in envelope["review_blockers"]
    assert "session_start_timezone_missing" in envelope["review_blockers"]
    assert "session_expiry_timezone_missing" in envelope["review_blockers"]
    assert "session_duration_exceeded" in envelope["review_blockers"]


def test_session_budget_blocks_oversized_order_and_turnover(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order_ids"][0]
    order = env["db"].get_oms_order_sync(order_id)
    env["db"].upsert_oms_order_sync({**order, "quantity": 3000})

    envelope = _preview(env)

    assert f"session_order_value_exceeded:{order_id}" in envelope["review_blockers"]
    assert "session_authorized_capital_exceeded" in envelope["review_blockers"]
    assert "session_daily_turnover_exceeded" in envelope["review_blockers"]
    assert envelope["review_ready"] is False


def test_market_order_missing_gateway_evidence_and_symbol_scope_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order_ids"][0]
    order = env["db"].get_oms_order_sync(order_id)
    env["db"].upsert_oms_order_sync(
        {
            **order,
            "symbol": "600519.SH",
            "order_type": "market",
            "limit_price": None,
            "payload": {"gateway_evidence": {}},
        }
    )

    envelope = _preview(env)

    assert f"order_symbol_not_authorized:{order_id}" in envelope["review_blockers"]
    assert f"order_value_unavailable:{order_id}" in envelope["review_blockers"]
    assert f"gateway_evidence_missing:risk:{order_id}" in envelope["review_blockers"]


def test_session_envelope_fingerprint_is_stable_until_freshness_boundary(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    current_time = [NOW]
    service = ControlledSessionEnvelopeService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        clock=lambda: current_time[0],
    )
    first = _preview(env, service=service)
    approval = _operator_approval(env, first["envelope_fingerprint"])
    current_time[0] = NOW + timedelta(seconds=5)
    attestation = service.record_attestation(
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        order_ids=env["order_ids"],
        requested_start_at=env["start_at"],
        requested_expires_at=env["expires_at"],
        envelope_fingerprint=first["envelope_fingerprint"],
        operator_label="local-session-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=CONTROLLED_SESSION_ACKNOWLEDGEMENT,
    )
    still_fresh = _preview(env, service=service)
    current_time[0] = NOW + timedelta(minutes=16)
    stale = _preview(
        env,
        service=service,
        requested_start_at=NOW + timedelta(minutes=16),
        requested_expires_at=NOW + timedelta(minutes=20),
    )

    assert attestation["status"] == "recorded_verified_identity"
    assert attestation["operator_identity_verified"] is True
    assert still_fresh["envelope_fingerprint"] == first["envelope_fingerprint"]
    assert stale["envelope_fingerprint"] != first["envelope_fingerprint"]
    assert "connector_soak_evidence_not_fresh" in stale["review_blockers"]


def test_session_requires_session_bounded_capital_evaluation_and_bound_reconciliation(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    env["db"].upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:2026-07-10",
        run_date="2026-07-10",
        status="open_items",
        item_count=1,
        open_item_count=1,
        payload={"source": "synthetic-test"},
        items=[],
    )

    missing_capital = _preview(
        env,
        capital_evaluation_input_fingerprint="f" * 64,
    )

    assert "capital_evaluation_not_found" in missing_capital["review_blockers"]
    assert (
        "prior_batch_reconciliation_source_changed"
        in missing_capital["review_blockers"]
    )


def test_controlled_session_status_exposes_no_runtime_actions(tmp_path) -> None:
    env = _ready_environment(tmp_path)

    status = env["service"].get_status()

    assert status["contract_status"] == "proposal_only_non_executing"
    assert status["runtime_session_authority"] == "disabled"
    assert status["session_issue_enabled"] is False
    assert status["session_resume_enabled"] is False
    assert status["broker_submission_enabled"] is False
    assert status["automatic_scale_up_enabled"] is False
    assert status["signature_verification_configured"] is True
