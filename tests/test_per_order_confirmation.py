from __future__ import annotations

import base64
import json
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
from server.services.execution_batch_reconciliation import (
    EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    ExecutionBatchReconciliationService,
)
from server.services.oms import OmsService
from server.services.operator_approval import OperatorApprovalService
from server.services.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PER_ORDER_CONFIRMATION_EVENT_TYPE,
    PerOrderConfirmationRejected,
    PerOrderConfirmationService,
    build_order_fingerprint,
)
from server.services.trading_controls import TradingControlState

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


def _gateway_evidence() -> dict:
    return {
        "account_truth": {
            "gate_status": "pass",
            "evidence_ref": "account-truth:review-1",
        },
        "research_evidence": {
            "gate_status": "pass",
            "evidence_ref": "research:bundle-1",
        },
        "risk": {
            "gate_status": "passed",
            "evidence_ref": "risk:decision-1",
        },
        "paper_shadow": {
            "divergence_status": "within_expectations",
            "evidence_ref": "paper-shadow:run-1",
        },
    }


def _connector(now: datetime = NOW) -> FakeReadOnlyBrokerConnector:
    return FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="qmt-readonly-confirmation",
            source_name="synthetic QMT readonly export",
            account_id="private-per-order-account-id-must-not-leak",
            account_alias="qmt-review",
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


def _ready_environment(tmp_path, *, now: datetime = NOW) -> dict:
    db = AppDatabase(tmp_path / "per-order-confirmation.db")
    db.init_sync()
    shanghai_day = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    db.upsert_market_calendar_snapshot_sync(
        build_static_market_calendar_snapshot(
            exchange="SSE",
            year=int(shanghai_day[:4]),
            provider="synthetic_test_calendar",
            open_dates=[shanghai_day],
            fetched_at=now.isoformat(),
        )
    )
    connector = _connector(now)
    BrokerConnectorSoakService(
        db=db,
        connectors=[connector],
        clock=lambda: now,
    ).capture()
    prior_order_id = "prior-manual-order-1"
    db.upsert_oms_order_sync(
        {
            "order_id": prior_order_id,
            "intent_key": "prior-manual-order-1",
            "symbol": "510300.SH",
            "side": "buy",
            "asset_class": "fund",
            "quantity": 100.0,
            "order_type": "limit",
            "limit_price": 4.0,
            "status": "cancelled",
            "broker_submission_enabled": False,
            "source": "prior_manual_batch_test",
            "payload": {"execution_mode": "manual"},
        }
    )
    reconciliation_run_id = f"execution-reconciliation:{shanghai_day}"
    db.upsert_execution_reconciliation_run_sync(
        run_id=reconciliation_run_id,
        run_date=shanghai_day,
        status="clear",
        item_count=1,
        open_item_count=0,
        payload={"source": "synthetic-test"},
        items=[
            {
                "order_id": prior_order_id,
                "item_status": "cancelled",
                "suggested_action": "no_action",
                "detail": "clear prior manual batch",
                "payload": {
                    "oms_status": "cancelled",
                    "execution_mode": "manual",
                },
            }
        ],
    )
    batch_service = ExecutionBatchReconciliationService(db=db, clock=lambda: now)
    batch_preview = batch_service.preview(
        batch_id="prior-manual-batch-1",
        order_ids=[prior_order_id],
        reconciliation_run_id=reconciliation_run_id,
    )
    batch = batch_service.record(
        batch_id="prior-manual-batch-1",
        order_ids=[prior_order_id],
        reconciliation_run_id=reconciliation_run_id,
        batch_reconciliation_fingerprint=batch_preview[
            "batch_reconciliation_fingerprint"
        ],
        operator_label="local-owner",
        acknowledgement=EXECUTION_BATCH_RECONCILIATION_ACKNOWLEDGEMENT,
    )
    batch_ref = (
        "execution_batch_reconciliation:" f"{batch['batch_reconciliation_fingerprint']}"
    )
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key=f"daily:{shanghai_day}:510300.SH:buy",
        symbol="510300.SH",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="limit",
        limit_price=4.0,
        source="daily_trading_plan",
        source_ref=f"paper-shadow:{shanghai_day}",
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
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator reviewed paper/shadow evidence",
        actor="local-unverified-test",
    )
    order_fingerprint = build_order_fingerprint(order)
    policy = CapitalAuthorizationPolicy(
        authorization_id="auth-review-1",
        policy_version="policy-v1",
        mode="manual_each_order",
        enabled=True,
        authorized_by="local-unverified-test",
        connector_ids=("qmt-readonly-confirmation",),
        evidence_connector_ids=("qmt-readonly-confirmation",),
        execution_gateway_ids=("qmt-execution-disabled",),
        account_aliases=("qmt-review",),
        strategy_ids=("etf_rotation",),
        symbols=("510300.SH",),
        effective_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=1),
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
        evidence_refs=("operator-review:local",),
    )
    context = CapitalAuthorizationContext(
        now=now,
        connector_id="qmt-readonly-confirmation",
        account_alias="qmt-review",
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
        order_fingerprint=order_fingerprint,
        manual_confirmation_fingerprint=order_fingerprint,
        evidence_refs=("risk:decision-1", "paper-shadow:run-1", batch_ref),
        evidence_connector_id="qmt-readonly-confirmation",
        execution_gateway_id="qmt-execution-disabled",
        evidence_connector_health_status="healthy",
        evidence_connector_can_submit=False,
        execution_gateway_health_status="healthy",
        execution_gateway_can_submit=True,
        connector_account_binding_status="verified",
    )
    evaluation = CapitalAuthorizationAuditService(
        db=db,
        clock=lambda: now,
    ).record_evaluation(policy=policy, context=context)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trusted_identity = TrustedOperatorIdentityConfig(
        operator_id="local-owner",
        key_id="owner-key-1",
        public_key_base64=base64.b64encode(public_key).decode("ascii"),
        enabled=True,
    )
    controls = TradingControlState(db=db)
    service = PerOrderConfirmationService(
        db=db,
        connectors=[connector],
        trusted_operator_identities=[trusted_identity],
        trading_controls=controls,
        clock=lambda: now,
    )
    return {
        "db": db,
        "connector": connector,
        "controls": controls,
        "service": service,
        "order": order,
        "evaluation": evaluation,
        "batch": batch,
        "private_key": private_key,
        "trusted_identity": trusted_identity,
    }


def _operator_approval(env: dict, artifact_fingerprint: str) -> dict:
    approval_service = OperatorApprovalService(
        db=env["db"],
        trusted_identities=[env["trusted_identity"]],
        clock=lambda: NOW,
    )
    challenge = approval_service.create_challenge(
        operator_id="local-owner",
        key_id="owner-key-1",
        action="attest_per_order_dossier",
        artifact_type="per_order_dossier",
        artifact_fingerprint=artifact_fingerprint,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    return approval_service.verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=base64.b64encode(signature).decode("ascii"),
    )


def _signed_stage1_promotion(version: int = 1) -> dict:
    fingerprints = (
        ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
        if version == 1
        else ("e" * 64, "f" * 64, "0" * 64, "1" * 64)
    )
    dossier, operational, account_truth, acceptance = fingerprints
    return {
        "connector_id": "qmt-readonly-confirmation",
        "dossier_fingerprint": dossier,
        "operational_evidence": {
            "status": "clear",
            "source_fingerprint": operational,
            "selected_trading_day_count": 20,
        },
        "account_truth_evidence": {
            "status": "clear",
            "source_fingerprint": account_truth,
        },
        "acceptance": {
            "status": "recorded_verified_owner_acceptance",
            "acceptance_id": acceptance,
            "recorded_at": NOW.isoformat(),
            "operator_label": "local-owner",
            "operator_identity_verified": True,
            "authorizes_execution": False,
        },
        "promotion_ready": True,
        "owner_acceptance_recorded": True,
        "account_truth_reconciliation_linked": True,
        "promotion_blockers": [],
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }


def test_dossier_binds_all_review_evidence_but_keeps_submission_blocked(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert dossier["review_status"] == "review_ready_non_submitting"
    assert dossier["review_blockers"] == []
    assert dossier["capital_evaluation"]["status"] == "pass"
    assert dossier["gateway_gates"]["status"] == "pass"
    assert dossier["connector_soak"]["latest_soak_status"] == "healthy"
    assert dossier["prior_execution_reconciliation"]["status"] == "pass"
    assert dossier["kill_switch"]["status"] == "pass"
    assert dossier["submission_status"] == "blocked"
    assert "stage1_operational_soak_incomplete" in dossier["hard_submission_blockers"]
    assert "stage1_owner_acceptance_missing" in dossier["hard_submission_blockers"]
    assert (
        "execution_gateway_runtime_not_verified" in dossier["hard_submission_blockers"]
    )
    assert dossier["connector_soak"]["evidence_connector_can_submit"] is False
    assert dossier["execution_gateway"] == {
        "schema_version": "karkinos.execution_gateway_binding.v1",
        "gateway_id": "qmt-execution-disabled",
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
        not in dossier["hard_submission_blockers"]
    )
    assert "runtime_execution_authority_disabled" in dossier["hard_submission_blockers"]
    assert dossier["operator_identity_verified"] is False
    assert dossier["authorizes_execution"] is False
    assert dossier["safety"]["does_not_contact_broker"] is True
    assert "private-per-order-account-id-must-not-leak" not in json.dumps(dossier)


def test_exact_dossier_confirmation_is_append_only_reused_and_non_mutating(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order"]["order_id"]
    input_fingerprint = env["evaluation"]["input_fingerprint"]
    dossier = env["service"].preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    approval = _operator_approval(env, dossier["dossier_fingerprint"])

    first = env["service"].record_confirmation(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )
    rerun = env["service"].record_confirmation(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )

    assert first["status"] == "recorded_verified_identity"
    assert first["operator_identity_verified"] is True
    assert "operator_identity_unverified" not in first["hard_submission_blockers"]
    assert first["authorizes_execution"] is False
    assert first["broker_submission_enabled"] is False
    assert first["safety"]["does_not_mutate_oms"] is True
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert (
        len(env["db"].list_events_sync(event_type=PER_ORDER_CONFIRMATION_EVENT_TYPE))
        == 1
    )
    assert env["db"].get_oms_order_sync(order_id)["status"] == "manually_confirmed"
    refreshed = env["service"].preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    assert refreshed["dossier_fingerprint"] == dossier["dossier_fingerprint"]
    assert refreshed["confirmation"]["status"] == "recorded_verified_identity"


def test_dossier_confirmation_rejects_approval_for_another_artifact(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    wrong_approval = _operator_approval(env, "f" * 64)

    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        env["service"].record_confirmation(
            env["order"]["order_id"],
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            dossier_fingerprint=dossier["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=wrong_approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )

    assert exc_info.value.evidence["rejection_reasons"] == ["operator_approval_blocked"]
    assert exc_info.value.evidence["operator_identity_verified"] is False


def test_dossier_fingerprint_ignores_age_counter_but_changes_at_stale_boundary(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    current_time = [NOW]
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        clock=lambda: current_time[0],
    )
    order_id = env["order"]["order_id"]
    input_fingerprint = env["evaluation"]["input_fingerprint"]
    preview = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    approval = _operator_approval(env, preview["dossier_fingerprint"])
    current_time[0] = NOW + timedelta(seconds=5)

    confirmation = service.record_confirmation(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        dossier_fingerprint=preview["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )
    still_fresh = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    current_time[0] = NOW + timedelta(minutes=16)
    stale = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert confirmation["status"] == "recorded_verified_identity"
    assert still_fresh["dossier_fingerprint"] == preview["dossier_fingerprint"]
    assert stale["dossier_fingerprint"] != preview["dossier_fingerprint"]
    assert stale["connector_soak"]["freshness_status"] == "stale"


def test_stale_dossier_fingerprint_is_rejected_and_audited(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order"]["order_id"]
    dossier = env["service"].preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    approval = _operator_approval(env, dossier["dossier_fingerprint"])

    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        env["service"].record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            dossier_fingerprint="0" * 64,
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )

    evidence = exc_info.value.evidence
    assert evidence["status"] == "rejected"
    assert evidence["rejection_reasons"] == ["dossier_fingerprint_mismatch"]
    assert evidence["authorizes_execution"] is False
    assert env["db"].get_oms_order_sync(order_id)["status"] == "manually_confirmed"


def test_kill_switch_blocks_confirmation_and_rejection_is_audited(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    env["controls"].set_kill_switch(True, "operator emergency stop")
    order_id = env["order"]["order_id"]
    input_fingerprint = env["evaluation"]["input_fingerprint"]
    dossier = env["service"].preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert dossier["review_status"] == "blocked_review"
    assert "kill_switch_enabled" in dossier["review_blockers"]
    approval = _operator_approval(env, dossier["dossier_fingerprint"])
    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        env["service"].record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=input_fingerprint,
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            dossier_fingerprint=dossier["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )
    assert exc_info.value.evidence["rejection_reasons"] == ["dossier_review_blocked"]


def test_missing_capital_evaluation_and_gateway_evidence_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order"]["order_id"]
    order = env["db"].get_oms_order_sync(order_id)
    env["db"].upsert_oms_order_sync(
        {
            **order,
            "payload": {
                "schema_version": "karkinos.oms_order.v1",
                "gateway_evidence": {},
            },
        }
    )

    dossier = env["service"].preview_dossier(order_id)

    assert "capital_evaluation_missing" in dossier["review_blockers"]
    assert "gateway_evidence_missing:account_truth" in dossier["review_blockers"]
    assert "gateway_evidence_missing:risk" in dossier["review_blockers"]
    assert dossier["review_ready"] is False


def test_expired_capital_evaluation_and_stale_soak_evidence_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    later = NOW + timedelta(hours=2)
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        clock=lambda: later,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert "capital_authorization_expired" in dossier["review_blockers"]
    assert "connector_soak_evidence_not_fresh" in dossier["review_blockers"]
    assert dossier["connector_soak"]["freshness_status"] == "stale"
    assert dossier["review_ready"] is False


def test_order_term_drift_invalidates_recorded_capital_fingerprint(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    order_id = env["order"]["order_id"]
    order = env["db"].get_oms_order_sync(order_id)
    env["db"].upsert_oms_order_sync({**order, "quantity": 200})

    dossier = env["service"].preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert "capital_order_fingerprint_mismatch" in dossier["review_blockers"]
    assert (
        "capital_manual_confirmation_fingerprint_mismatch" in dossier["review_blockers"]
    )
    assert dossier["review_ready"] is False


def test_unconfirmed_order_open_reconciliation_and_missing_connector_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    oms = OmsService(db=env["db"])
    unconfirmed = oms.create_order_intent(
        intent_key="daily:2026-07-10:159915.SZ:buy",
        symbol="159915.SZ",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="limit",
        limit_price=2.0,
        source="daily_trading_plan",
    )
    env["db"].upsert_execution_reconciliation_run_sync(
        run_id="execution-reconciliation:2026-07-10",
        run_date="2026-07-10",
        status="open_items",
        item_count=1,
        open_item_count=1,
        payload={"source": "synthetic-test"},
        items=[],
    )
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[],
        trading_controls=env["controls"],
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(unconfirmed["order_id"])

    assert "oms_order_not_manually_confirmed" in dossier["review_blockers"]
    assert (
        "prior_batch_reconciliation_fingerprint_invalid" in dossier["review_blockers"]
    )
    assert "prior_batch_reconciliation_not_found" in dossier["review_blockers"]
    assert "connector_not_configured" in dossier["review_blockers"]
    assert dossier["review_ready"] is False


def test_order_fingerprint_is_stable_and_order_term_sensitive(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    order = env["db"].get_oms_order_sync(env["order"]["order_id"])

    first = build_order_fingerprint(order)
    same = build_order_fingerprint(dict(order))
    changed = build_order_fingerprint({**order, "quantity": 200})

    assert first == same
    assert first != changed


def test_status_makes_unverified_non_submitting_boundary_explicit(tmp_path) -> None:
    env = _ready_environment(tmp_path)

    status = env["service"].get_status()

    assert status["contract_status"] == "evidence_only_non_submitting"
    assert status["runtime_execution_authority"] == "disabled"
    assert status["operator_identity_verified"] is False
    assert status["broker_submission_enabled"] is False
    assert status["stage2_promotion_ready"] is False
    assert status["stage1_signed_promotion_binding"] == "required_per_dossier"


def test_signed_stage1_promotion_is_bound_but_does_not_remove_execution_blocks(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: _signed_stage1_promotion()
        ),
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    promotion = dossier["connector_soak"]["signed_promotion"]
    assert promotion == {
        "schema_version": "karkinos.per_order_stage1_promotion_binding.v1",
        "status": "ready",
        "connector_id": "qmt-readonly-confirmation",
        "dossier_fingerprint": "a" * 64,
        "operational_source_fingerprint": "b" * 64,
        "account_truth_source_fingerprint": "c" * 64,
        "acceptance_id": "d" * 64,
        "acceptance_recorded_at": NOW.isoformat(),
        "operator_label": "local-owner",
        "promotion_ready": True,
        "owner_acceptance_recorded": True,
        "account_truth_reconciliation_linked": True,
        "blockers": [],
        "authorizes_execution": False,
        "broker_submission_enabled": False,
    }
    assert (
        "stage1_account_truth_reconciliation_not_linked"
        not in dossier["hard_submission_blockers"]
    )
    assert "stage1_owner_acceptance_missing" not in dossier["hard_submission_blockers"]
    assert "stage1_promotion_not_ready" not in dossier["hard_submission_blockers"]
    assert (
        "execution_gateway_runtime_not_verified" in dossier["hard_submission_blockers"]
    )
    assert "runtime_execution_authority_disabled" in dossier["hard_submission_blockers"]
    assert "live_gateway_not_implemented" in dossier["hard_submission_blockers"]
    assert dossier["submission_status"] == "blocked"
    assert dossier["authorizes_execution"] is False


def test_signed_stage1_promotion_source_drift_invalidates_exact_order_dossier(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    current = [_signed_stage1_promotion()]
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=lambda connector_id: current[0],
        clock=lambda: NOW,
    )
    order_id = env["order"]["order_id"]
    input_fingerprint = env["evaluation"]["input_fingerprint"]
    batch_fingerprint = env["batch"]["batch_reconciliation_fingerprint"]
    first = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=batch_fingerprint,
    )
    approval = _operator_approval(env, first["dossier_fingerprint"])

    current[0] = _signed_stage1_promotion(version=2)
    drifted = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=batch_fingerprint,
    )

    assert drifted["dossier_fingerprint"] != first["dossier_fingerprint"]
    assert drifted["connector_soak"]["signed_promotion"]["acceptance_id"] == ("1" * 64)
    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        service.record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=input_fingerprint,
            prior_batch_reconciliation_fingerprint=batch_fingerprint,
            dossier_fingerprint=first["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )
    assert (
        "dossier_fingerprint_mismatch" in exc_info.value.evidence["rejection_reasons"]
    )
    assert "operator_approval_blocked" in exc_info.value.evidence["rejection_reasons"]
    assert exc_info.value.evidence["authorizes_execution"] is False


def test_missing_or_failed_signed_stage1_provider_fails_closed_without_details(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    missing = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    def failed_provider(connector_id: str) -> dict:
        raise RuntimeError("private broker detail must not leak")

    failed_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=failed_provider,
        clock=lambda: NOW,
    )
    malformed_promotion = _signed_stage1_promotion()
    malformed_promotion["operational_evidence"] = {
        **malformed_promotion["operational_evidence"],
        "selected_trading_day_count": 19,
    }
    malformed_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: malformed_promotion
        ),
        clock=lambda: NOW,
    )
    failed = failed_service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )
    malformed = malformed_service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
    )

    assert missing["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_evidence_provider_unavailable"
    ]
    assert failed["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_evidence_provider_failed"
    ]
    assert "private broker detail must not leak" not in json.dumps(failed)
    assert "stage1_promotion_not_ready" in failed["hard_submission_blockers"]
    assert failed["submission_status"] == "blocked"
    assert malformed["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_trading_day_count_invalid"
    ]
    assert "stage1_promotion_not_ready" in malformed["hard_submission_blockers"]
