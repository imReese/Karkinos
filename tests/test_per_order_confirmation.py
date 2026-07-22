from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseReviewRepository,
    preview_broker_adapter_release_manifest,
)
from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    FakeReadOnlyBrokerConnector,
)
from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)
from data.market_calendar import build_static_market_calendar_snapshot
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.broker_connector_soak import (
    BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
    BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
    BROKER_CONNECTOR_SOAK_EVENT_TYPE,
    BrokerConnectorSoakService,
)
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
from server.services.execution_gateway_verification import (
    EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    ExecutionGatewayVerificationService,
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
GATEWAY_VERIFICATION_FINGERPRINT = "e" * 64


def _gateway_evidence() -> dict:
    return {
        "account_truth": {
            "gate_status": "pass",
            "evidence_ref": "account_truth:import-run-1",
        },
        "research_evidence": {
            "gate_status": "pass",
            "evidence_ref": "decision_action:1",
        },
        "risk": {
            "gate_status": "passed",
            "evidence_ref": "risk:decision-1",
        },
        "paper_shadow": {
            "divergence_status": "within_expectations",
            "evidence_ref": "paper_shadow:run-1",
        },
    }


def _clear_account_truth_evidence() -> dict:
    return {
        "status": "clear",
        "source_fingerprint": "a" * 64,
        "import_run_id": "import-run-1",
        "captured_at": NOW.isoformat(),
        "data_freshness_status": "fresh",
        "reconciliation_status": "clear",
        "gate_status": "pass",
        "unresolved_mismatch_count": 0,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
        "persisted_facts_only": True,
        "provider_contact_performed": False,
    }


def _record_gateway_source_evidence(db: AppDatabase, now: datetime) -> None:
    db.upsert_action_task_sync(
        source_signal_id=101,
        symbol="510300.SH",
        title="fixture controlled order",
        detail="deterministic per-order lineage fixture",
        direction="buy",
        urgency="normal",
        target_weight=0.01,
        price=4.0,
        strategy_id="etf_rotation",
        timestamp=now.isoformat(),
        asset_class="fund",
    )
    db.append_event_sync(
        event_type="risk.signal.recorded",
        timestamp=now.isoformat(),
        entity_type="risk_signal",
        entity_id="decision-1",
        source="risk_decisions",
        source_ref="decision-1",
        payload={
            "intent": {
                "intent_id": "fixture-intent-1",
                "strategy_id": "etf_rotation",
                "source_signal_id": 101,
                "symbol": "510300.SH",
                "side": "buy",
            },
            "decision": {
                "decision_id": "decision-1",
                "timestamp": now.isoformat(),
                "passed": True,
                "symbol": "510300.SH",
                "side": "buy",
                "severity": "info",
            },
        },
    )
    db.upsert_paper_shadow_run_sync(
        run_id="run-1",
        plan_date=now.astimezone(timezone(timedelta(hours=8))).date().isoformat(),
        input_fingerprint="b" * 64,
        status="within_expectations",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=1,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        limitations=[],
        payload={
            "schema_version": "karkinos.paper_shadow_run.v1",
            "run_id": "run-1",
            "orders": [
                {
                    "order_id": "SHADOW-FIXTURE-1",
                    "status": "filled",
                    "divergence_status": "within_expectations",
                    "order_intent": {
                        "action_ref": "action:1",
                        "symbol": "510300.SH",
                        "side": "buy",
                        "estimated_quantity": 100.0,
                        "estimated_price": 4.0,
                        "strategy_refs": ["strategy:etf_rotation"],
                        "risk_refs": ["risk:decision-1"],
                    },
                }
            ],
            "does_not_submit_broker_order": True,
            "does_not_mutate_production_ledger": True,
        },
    )


def _connector(now: datetime = NOW) -> FakeReadOnlyBrokerConnector:
    return FakeReadOnlyBrokerConnector(
        BrokerConnectorSnapshot(
            connector_id="fixture-readonly-confirmation",
            source_name="synthetic deterministic readonly export",
            account_id="private-per-order-account-id-must-not-leak",
            account_alias="fixture-review",
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


class _RuntimeExecutionGateway:
    gateway_id = "fixture-execution-disabled"
    evidence_connector_id = "fixture-readonly-confirmation"
    account_alias = "fixture-review"
    account_binding_status = "verified"

    def __init__(self) -> None:
        self.capabilities = {
            "can_cancel_orders": True,
            "can_dry_run_orders": True,
            "can_query_fills": True,
            "can_query_orders": True,
            "can_submit_orders": True,
            "supports_idempotent_client_order_id": True,
        }
        self.dry_run_calls = 0
        self.submit_calls = 0

    def get_health(self) -> dict:
        return {
            "status": "healthy",
            "captured_at": NOW.isoformat(),
            "source_fingerprint": "b" * 64,
        }

    def dry_run_order(self, order: dict) -> dict:
        self.dry_run_calls += 1
        payload_fingerprint = hashlib.sha256(
            json.dumps(order, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "status": "accepted",
            "order_fingerprint": order["order_fingerprint"],
            "client_order_id": order["client_order_id"],
            "payload_fingerprint": payload_fingerprint,
            "submitted": False,
            "broker_order_id": "",
            "side_effect_count": 0,
        }


def _clear_gateway_verification(order: dict, *, version: int = 1) -> dict:
    return {
        "status": "clear",
        "verification_fingerprint": GATEWAY_VERIFICATION_FINGERPRINT,
        "verification_id": ("f" if version == 1 else "9") * 64,
        "gateway_id": "fixture-execution-disabled",
        "evidence_connector_id": "fixture-readonly-confirmation",
        "account_alias": "fixture-review",
        "order_id": order["order_id"],
        "order_fingerprint": build_order_fingerprint(order),
        "order_contract": {
            "symbol": "510300.SH",
            "side": "buy",
            "asset_class": "fund",
            "quantity": "100",
            "order_type": "limit",
            "limit_price": "4",
        },
        "recorded_at": NOW.isoformat(),
        "runtime_gateway_verified": True,
        "runtime_verification_status": "verified_non_submitting_dry_run",
        "blockers": [],
        "runtime_execution_authority": "disabled",
        "broker_submission_enabled": False,
        "authorizes_execution": False,
    }


def _adapter_release_manifest() -> dict:
    return {
        "schema_version": "karkinos.broker_adapter_release_manifest.v1",
        "release_evidence_ref": "fixture-per-order-adapter-release-v1",
        "collector_id": "fixture-readonly-confirmation",
        "deployment_id": "fixture-per-order-deployment-v1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "8" * 64,
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-execution-disabled",
        "account_alias": "fixture-review",
        "adapter_authorization_ref": "test-only-owner-authorization",
        "collection_modes": ["callback", "poll"],
        "capabilities": {
            "can_read_account": False,
            "can_read_cash": False,
            "can_read_positions": False,
            "can_read_orders": True,
            "can_read_fills": True,
            "can_read_market_session": False,
            "can_read_heartbeat": True,
            "can_submit_orders": False,
            "can_cancel_orders": False,
        },
        "boundaries": {
            "runtime_auth_material_external": True,
            "strategy_imports_adapter": False,
            "ai_imports_adapter": False,
            "core_imports_provider_sdk": False,
            "writes_oms": False,
            "writes_production_ledger": False,
            "writes_risk_state": False,
            "writes_kill_switch": False,
            "writes_capital_authority": False,
            "default_registered": False,
        },
        "review_refs": {
            "adapter_adr": "fixture-adr-v1",
            "capability_matrix": "fixture-capability-matrix-v1",
            "threat_model": "fixture-threat-model-v1",
            "deployment_runbook": "fixture-deployment-runbook-v1",
            "rollback_runbook": "fixture-rollback-runbook-v1",
            "privacy_review": "fixture-privacy-review-v1",
        },
        "limitations": ["Deterministic per-order confirmation fixture only."],
    }


def _record_observing_adapter_release(db: AppDatabase, now: datetime) -> dict:
    preview = preview_broker_adapter_release_manifest(
        json.dumps(_adapter_release_manifest()),
        source_name="deterministic per-order adapter release fixture",
    )
    conformance = run_deterministic_broker_adapter_conformance(
        preview,
        run_id="fixture-per-order-conformance-v1",
    )
    BrokerAdapterConformanceRepository(db._path).record_report(
        conformance,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )
    review = BrokerAdapterReleaseReviewRepository(db._path).record_review(
        preview,
        review_id="fixture-per-order-release-review-v1",
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=now.isoformat(),
        reason_ref="fixture-release-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    lifecycle = {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "deterministic_fixture",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-execution-disabled",
        "account_id": "private-adapter-account-id-must-not-leak",
        "account_alias": "fixture-review",
        "captured_at": now.isoformat(),
        "source_sequence": 1,
        "orders": [
            {
                "broker_order_id": "FIXTURE-ADAPTER-ORDER-1",
                "client_order_id": "KARK-fixture-adapter-order-1",
                "symbol": "510300.SH",
                "side": "buy",
                "status": "open",
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": (now - timedelta(seconds=2)).isoformat(),
                "updated_at": (now - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": [],
    }
    collector_payload = {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": "fixture-per-order-collector-run-v1",
        "collector_id": "fixture-readonly-confirmation",
        "deployment_id": "fixture-per-order-deployment-v1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "8" * 64,
        "release_evidence_ref": "fixture-per-order-adapter-release-v1",
        "release_review_status": "reviewed",
        "adapter_authorization_ref": "test-only-owner-authorization",
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-execution-disabled",
        "account_id": "private-adapter-account-id-must-not-leak",
        "account_alias": "fixture-review",
        "collection_mode": "callback",
        "source_contact_status": "read_only_contact",
        "connection_status": "connected",
        "batch_status": "complete",
        "cursor": {"previous": 0, "current": 1},
        "captured_at": now.isoformat(),
        "event_count": 1,
        "callbacks_received": 1,
        "duplicate_callbacks_dropped": 0,
        "out_of_order_callbacks_dropped": 0,
        "lifecycle": lifecycle,
    }
    collector_preview = preview_broker_order_lifecycle_collector_batch(
        json.dumps(collector_payload),
        source_name="deterministic per-order collector fixture",
        clock=lambda: now,
    )
    collector = BrokerOrderLifecycleCollectorRepository(db._path).ingest(
        collector_preview,
        acknowledgement=(BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT),
    )
    return {"preview": preview, "review": review, "collector": collector}


def _ready_environment(
    tmp_path,
    *,
    now: datetime = NOW,
    with_adapter_release: bool = True,
) -> dict:
    db = AppDatabase(tmp_path / "per-order-confirmation.db")
    db.init_sync()
    _record_gateway_source_evidence(db, now)
    adapter_release = (
        _record_observing_adapter_release(db, now) if with_adapter_release else {}
    )
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
        connector_ids=("fixture-readonly-confirmation",),
        evidence_connector_ids=("fixture-readonly-confirmation",),
        execution_gateway_ids=("fixture-execution-disabled",),
        account_aliases=("fixture-review",),
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
        connector_id="fixture-readonly-confirmation",
        account_alias="fixture-review",
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
        evidence_refs=(
            "account_truth:import-run-1",
            "decision_action:1",
            "risk:decision-1",
            "paper_shadow:run-1",
            batch_ref,
            ("execution_gateway_verification:" f"{GATEWAY_VERIFICATION_FINGERPRINT}"),
        ),
        evidence_connector_id="fixture-readonly-confirmation",
        execution_gateway_id="fixture-execution-disabled",
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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(order)
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: now,
    )
    return {
        "db": db,
        "connector": connector,
        "controls": controls,
        "service": service,
        "order": order,
        "evaluation": evaluation,
        "capital_policy": policy,
        "capital_context": context,
        "batch": batch,
        "gateway_verification_fingerprint": GATEWAY_VERIFICATION_FINGERPRINT,
        "adapter_release": adapter_release,
        "private_key": private_key,
        "trusted_identity": trusted_identity,
        "account_truth_evidence_provider": _clear_account_truth_evidence,
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
        "connector_id": "fixture-readonly-confirmation",
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    assert dossier["review_status"] == "review_ready_non_submitting"
    assert dossier["review_blockers"] == []
    assert dossier["capital_evaluation"]["status"] == "pass"
    assert dossier["gateway_gates"]["status"] == "pass"
    assert dossier["broker_adapter_release"]["status"] == "pass"
    assert dossier["broker_adapter_release"]["expected_scope"] == {
        "collector_id": "fixture-readonly-confirmation",
        "gateway_id": "fixture-execution-disabled",
        "account_alias": "fixture-review",
    }
    assert dossier["broker_adapter_release"]["release"]["review_status"] == ("accepted")
    assert dossier["broker_adapter_release"]["release"]["conformance_status"] == (
        "clear"
    )
    assert dossier["broker_adapter_release"]["release"]["status"] == (
        "observing_readonly"
    )
    assert dossier["broker_adapter_release"]["provider_contact_performed"] is False
    assert dossier["connector_soak"]["latest_soak_status"] == "healthy"
    assert dossier["prior_execution_reconciliation"]["status"] == "pass"
    assert dossier["kill_switch"]["status"] == "pass"
    assert dossier["submission_status"] == "blocked"
    assert (
        "broker_soak_operational_evidence_incomplete"
        in dossier["hard_submission_blockers"]
    )
    assert "broker_soak_owner_acceptance_missing" in dossier["hard_submission_blockers"]
    assert (
        "execution_gateway_runtime_not_verified"
        not in dossier["hard_submission_blockers"]
    )
    assert dossier["connector_soak"]["evidence_connector_can_submit"] is False
    assert dossier["execution_gateway"]["gateway_id"] == "fixture-execution-disabled"
    assert dossier["execution_gateway"]["runtime_gateway_verified"] is True
    assert dossier["execution_gateway"]["runtime_verification_status"] == (
        "verified_non_submitting_dry_run"
    )
    assert dossier["execution_gateway"]["broker_submission_enabled"] is False
    assert dossier["execution_gateway_verification"]["status"] == "pass"
    assert (
        dossier["execution_gateway_verification"]["order_id"]
        == env["order"]["order_id"]
    )
    assert dossier["execution_gateway_verification"]["authorizes_execution"] is False
    assert (
        "prior_batch_reconciliation_not_bound_or_clear"
        not in dossier["hard_submission_blockers"]
    )
    assert "runtime_execution_authority_disabled" in dossier["hard_submission_blockers"]
    assert dossier["operator_identity_verified"] is False
    assert dossier["authorizes_execution"] is False
    assert dossier["safety"]["does_not_contact_broker"] is True
    assert "private-per-order-account-id-must-not-leak" not in json.dumps(dossier)
    assert "private-adapter-account-id-must-not-leak" not in json.dumps(dossier)


def test_gateway_gate_refs_resolve_to_exact_persisted_order_lineage(tmp_path) -> None:
    env = _ready_environment(tmp_path)

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    gateway = dossier["gateway_gates"]
    assert dossier["schema_version"] == "karkinos.per_order_confirmation_dossier.v5"
    assert gateway["schema_version"] == "karkinos.per_order_gateway_gate_summary.v2"
    assert gateway["status"] == "pass"
    assert gateway["blockers"] == []
    assert {
        gate: evidence["source_identifier"]
        for gate, evidence in gateway["gates"].items()
    } == {
        "account_truth": "import-run-1",
        "research_evidence": "1",
        "risk": "decision-1",
        "paper_shadow": "run-1",
    }
    assert all(
        evidence["resolution_status"] == "resolved_clear"
        and evidence["source_fingerprint"]
        for evidence in gateway["gates"].values()
    )
    assert gateway["persisted_facts_only"] is True
    assert gateway["provider_contact_performed"] is False
    assert gateway["authorizes_execution"] is False


def test_nonempty_spoofed_gateway_ref_fails_closed(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    order = env["db"].get_oms_order_sync(env["order"]["order_id"])
    payload = json.loads(order["payload_json"])
    payload["gateway_evidence"]["risk"] = {
        "gate_status": "passed",
        "evidence_ref": "risk:forged-decision",
    }
    env["db"].upsert_oms_order_sync({**order, "payload": payload})

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    assert "gateway_evidence_capital_ref_mismatch:risk" in dossier["review_blockers"]
    assert "gateway_evidence_source_not_found:risk" in dossier["review_blockers"]
    assert dossier["gateway_gates"]["gates"]["risk"]["raw_status"] == "passed"
    assert dossier["gateway_gates"]["gates"]["risk"]["status"] == "blocked"
    assert (
        "gateway_evidence_source_not_found:risk" in dossier["hard_submission_blockers"]
    )
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


def test_paper_shadow_order_scope_drift_invalidates_exact_dossier(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    kwargs = {
        "capital_evaluation_input_fingerprint": env["evaluation"]["input_fingerprint"],
        "prior_batch_reconciliation_fingerprint": env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        "execution_gateway_verification_fingerprint": env[
            "gateway_verification_fingerprint"
        ],
    }
    before = env["service"].preview_dossier(env["order"]["order_id"], **kwargs)
    run = env["db"].get_paper_shadow_run_sync("run-1")
    payload = json.loads(run["payload_json"])
    payload["orders"][0]["order_intent"]["estimated_quantity"] = 200.0
    env["db"].upsert_paper_shadow_run_sync(
        run_id="run-1",
        plan_date=run["plan_date"],
        input_fingerprint=run["input_fingerprint"],
        status=run["status"],
        order_intent_count=run["order_intent_count"],
        simulated_order_count=run["simulated_order_count"],
        simulated_fill_count=run["simulated_fill_count"],
        divergence_status=run["divergence_status"],
        next_manual_review_step=run["next_manual_review_step"],
        limitations=json.loads(run["limitations_json"]),
        payload=payload,
    )

    drifted = env["service"].preview_dossier(env["order"]["order_id"], **kwargs)

    blocker = "gateway_evidence_scope_mismatch:paper_shadow:quantity"
    assert blocker in drifted["review_blockers"]
    assert blocker in drifted["hard_submission_blockers"]
    assert drifted["dossier_fingerprint"] != before["dossier_fingerprint"]
    assert drifted["review_ready"] is False
    assert drifted["authorizes_execution"] is False


def test_account_truth_source_identity_drift_fails_closed(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    drifted_account_truth = {
        **_clear_account_truth_evidence(),
        "import_run_id": "newer-import-run",
        "source_fingerprint": "c" * 64,
    }
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=lambda: drifted_account_truth,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    blocker = "gateway_evidence_source_identity_mismatch:account_truth"
    assert blocker in dossier["review_blockers"]
    assert blocker in dossier["hard_submission_blockers"]
    assert dossier["gateway_gates"]["gates"]["account_truth"]["status"] == ("blocked")
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


def test_account_truth_source_provider_failure_is_sanitized(tmp_path) -> None:
    env = _ready_environment(tmp_path)

    def failed_provider() -> dict:
        raise RuntimeError("private Account Truth source must not leak")

    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=failed_provider,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    blocker = "gateway_evidence_provider_failed:account_truth"
    assert blocker in dossier["review_blockers"]
    assert blocker in dossier["hard_submission_blockers"]
    assert "private Account Truth source must not leak" not in json.dumps(dossier)
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    approval = _operator_approval(env, dossier["dossier_fingerprint"])

    first = env["service"].record_confirmation(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    wrong_approval = _operator_approval(env, "f" * 64)

    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        env["service"].record_confirmation(
            env["order"]["order_id"],
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            execution_gateway_verification_fingerprint=(
                env["gateway_verification_fingerprint"]
            ),
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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    approval = _operator_approval(env, preview["dossier_fingerprint"])
    current_time[0] = NOW + timedelta(seconds=5)

    confirmation = service.record_confirmation(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    current_time[0] = NOW + timedelta(minutes=16)
    stale = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    approval = _operator_approval(env, dossier["dossier_fingerprint"])

    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        env["service"].record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
            prior_batch_reconciliation_fingerprint=env["batch"][
                "batch_reconciliation_fingerprint"
            ],
            execution_gateway_verification_fingerprint=(
                env["gateway_verification_fingerprint"]
            ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
            execution_gateway_verification_fingerprint=(
                env["gateway_verification_fingerprint"]
            ),
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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: later,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
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
        account_truth_evidence_provider=_clear_account_truth_evidence,
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
    assert status["controlled_bridge_promotion_ready"] is False
    assert status["broker_adapter_release_binding"] == "required_per_dossier"
    assert status["broker_soak_promotion_binding"] == "required_per_dossier"
    assert status["execution_gateway_verification_binding"] == ("required_per_dossier")


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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    promotion = dossier["connector_soak"]["signed_promotion"]
    assert promotion == {
        "schema_version": "karkinos.per_order_broker_soak_promotion_binding.v1",
        "status": "ready",
        "connector_id": "fixture-readonly-confirmation",
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
        "broker_soak_account_truth_reconciliation_not_linked"
        not in dossier["hard_submission_blockers"]
    )
    assert (
        "broker_soak_owner_acceptance_missing"
        not in dossier["hard_submission_blockers"]
    )
    assert "broker_soak_promotion_not_ready" not in dossier["hard_submission_blockers"]
    assert (
        "execution_gateway_runtime_not_verified"
        not in dossier["hard_submission_blockers"]
    )
    assert "runtime_execution_authority_disabled" in dossier["hard_submission_blockers"]
    assert "live_gateway_not_implemented" in dossier["hard_submission_blockers"]
    assert dossier["submission_status"] == "blocked"
    assert dossier["authorizes_execution"] is False


def test_adapter_release_revocation_invalidates_exact_dossier_and_blocks_review(
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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    kwargs = {
        "capital_evaluation_input_fingerprint": env["evaluation"]["input_fingerprint"],
        "prior_batch_reconciliation_fingerprint": env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        "execution_gateway_verification_fingerprint": env[
            "gateway_verification_fingerprint"
        ],
    }
    current = service.preview_dossier(env["order"]["order_id"], **kwargs)
    approval = _operator_approval(env, current["dossier_fingerprint"])

    BrokerAdapterReleaseReviewRepository(env["db"]._path).record_review(
        env["adapter_release"]["preview"],
        review_id="fixture-per-order-release-revoked-v1",
        decision="revoked",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=(NOW + timedelta(minutes=1)).isoformat(),
        reason_ref="fixture-release-revoked",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    revoked = service.preview_dossier(env["order"]["order_id"], **kwargs)

    assert current["review_ready"] is True
    assert current["broker_adapter_release"]["status"] == "pass"
    assert revoked["dossier_fingerprint"] != current["dossier_fingerprint"]
    assert revoked["review_status"] == "blocked_review"
    assert revoked["broker_adapter_release"]["status"] == "blocked"
    assert revoked["broker_adapter_release"]["release"]["review_status"] == ("revoked")
    assert "broker_adapter_release_review_not_accepted" in revoked["review_blockers"]
    assert (
        "broker_adapter_release_not_observing_readonly"
        in revoked["hard_submission_blockers"]
    )
    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        service.record_confirmation(
            env["order"]["order_id"],
            **kwargs,
            dossier_fingerprint=current["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )
    assert "dossier_fingerprint_mismatch" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert "dossier_review_blocked" in exc_info.value.evidence["rejection_reasons"]
    assert exc_info.value.evidence["authorizes_execution"] is False


def test_adapter_release_binding_requires_exact_capital_scope(tmp_path) -> None:
    env = _ready_environment(tmp_path)
    mismatched_policy = replace(
        env["capital_policy"],
        authorization_id="auth-review-other-gateway",
        execution_gateway_ids=("other-execution-gateway",),
    )
    mismatched_context = replace(
        env["capital_context"],
        execution_gateway_id="other-execution-gateway",
    )
    evaluation = CapitalAuthorizationAuditService(
        db=env["db"],
        clock=lambda: NOW,
    ).record_evaluation(policy=mismatched_policy, context=mismatched_context)

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=evaluation["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=env[
            "gateway_verification_fingerprint"
        ],
    )

    assert dossier["broker_adapter_release"]["expected_scope"]["gateway_id"] == (
        "other-execution-gateway"
    )
    assert dossier["broker_adapter_release"]["matching_release_count"] == 0
    assert "broker_adapter_release_scope_not_found" in dossier["review_blockers"]
    assert "broker_adapter_release_scope_not_found" in (
        dossier["hard_submission_blockers"]
    )
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


def test_newer_exact_release_without_collector_never_falls_back_to_old_pass(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    manifest = {
        **_adapter_release_manifest(),
        "release_evidence_ref": "fixture-per-order-adapter-release-v2",
        "deployment_id": "fixture-per-order-deployment-v2",
        "collector_version": "fixture-v2",
        "deployment_fingerprint": "9" * 64,
    }
    preview = preview_broker_adapter_release_manifest(
        json.dumps(manifest),
        source_name="newer deterministic per-order adapter release fixture",
    )
    conformance = run_deterministic_broker_adapter_conformance(
        preview,
        run_id="fixture-per-order-conformance-v2",
    )
    BrokerAdapterConformanceRepository(env["db"]._path).record_report(
        conformance,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )
    BrokerAdapterReleaseReviewRepository(env["db"]._path).record_review(
        preview,
        review_id="fixture-per-order-release-review-v2",
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=(NOW + timedelta(minutes=1)).isoformat(),
        reason_ref="fixture-new-release-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=env[
            "gateway_verification_fingerprint"
        ],
    )

    binding = dossier["broker_adapter_release"]
    assert binding["matching_release_count"] == 2
    assert binding["release"]["release_evidence_ref"] == (
        "fixture-per-order-adapter-release-v2"
    )
    assert binding["release"]["collector_status"] == "not_started"
    assert "broker_adapter_release_collector_not_recorded" in (
        dossier["review_blockers"]
    )
    assert "broker_adapter_release_not_observing_readonly" in (
        dossier["hard_submission_blockers"]
    )
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


def test_missing_adapter_release_evidence_fails_closed_without_provider_contact(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path, with_adapter_release=False)

    dossier = env["service"].preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=env[
            "gateway_verification_fingerprint"
        ],
    )

    binding = dossier["broker_adapter_release"]
    assert binding["status"] == "blocked"
    assert binding["release"] is None
    assert binding["provider_contact_performed"] is False
    assert binding["persisted_evidence_only"] is True
    assert "broker_adapter_readiness_evidence_store_unavailable" in (
        dossier["review_blockers"]
    )
    assert "broker_adapter_release_scope_not_found" in (
        dossier["hard_submission_blockers"]
    )
    assert dossier["review_ready"] is False
    assert dossier["authorizes_execution"] is False


def test_recorded_confirmation_resolves_current_sources_for_submit_boundary(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    for offset in range(1, 20):
        observed_at = NOW - timedelta(days=offset)
        env["db"].append_event_sync(
            event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
            timestamp=observed_at.isoformat(),
            entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
            entity_id=hashlib.sha256(f"resolver-soak-{offset}".encode()).hexdigest(),
            source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
            source_ref="fixture-readonly-confirmation",
            payload={
                "connector_id": "fixture-readonly-confirmation",
                "trading_day": observed_at.date().isoformat(),
                "observed_at": observed_at.isoformat(),
                "soak_status": "healthy",
                "qualifies_for_healthy_soak_day": True,
                "execution_reconciliation": {"status": "clear"},
                "broker_submission_enabled": False,
            },
        )
    env["db"].append_event_sync(
        event_type=BROKER_CONNECTOR_SOAK_EVENT_TYPE,
        timestamp=NOW.isoformat(),
        entity_type=BROKER_CONNECTOR_SOAK_EVENT_ENTITY_TYPE,
        entity_id=hashlib.sha256(b"resolver-soak-current").hexdigest(),
        source=BROKER_CONNECTOR_SOAK_EVENT_SOURCE,
        source_ref="fixture-readonly-confirmation",
        payload={
            "connector_id": "fixture-readonly-confirmation",
            "trading_day": NOW.date().isoformat(),
            "observed_at": NOW.isoformat(),
            "source_captured_at": NOW.isoformat(),
            "soak_status": "healthy",
            "qualifies_for_healthy_soak_day": True,
            "execution_reconciliation": {"status": "clear"},
            "broker_submission_enabled": False,
        },
    )
    current_promotion = [_signed_stage1_promotion()]
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=(
            lambda connector_id: current_promotion[0]
        ),
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    order_id = env["order"]["order_id"]
    kwargs = {
        "capital_evaluation_input_fingerprint": env["evaluation"]["input_fingerprint"],
        "prior_batch_reconciliation_fingerprint": env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        "execution_gateway_verification_fingerprint": env[
            "gateway_verification_fingerprint"
        ],
    }
    dossier = service.preview_dossier(order_id, **kwargs)
    approval = _operator_approval(env, dossier["dossier_fingerprint"])
    confirmation = service.record_confirmation(
        order_id,
        **kwargs,
        dossier_fingerprint=dossier["dossier_fingerprint"],
        operator_label="local-owner",
        operator_approval_id=approval["approval_id"],
        acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    )

    resolved = service.resolve_confirmation(confirmation["confirmation_id"])

    assert (
        resolved["status"] == "current_verified_non_authorizing_confirmation"
    ), resolved["unexpected_hard_blockers"]
    assert resolved["confirmation_id"] == confirmation["confirmation_id"]
    assert (
        resolved["prior_batch_reconciliation_fingerprint"]
        == kwargs["prior_batch_reconciliation_fingerprint"]
    )
    assert resolved["unexpected_hard_blockers"] == []
    assert resolved["authorizes_execution"] is False
    assert resolved["broker_submission_enabled"] is False

    current_promotion[0] = _signed_stage1_promotion(version=2)
    drifted = service.resolve_confirmation(confirmation["confirmation_id"])
    assert drifted["status"] == "blocked"
    assert "per_order_confirmation_dossier_changed" in drifted["blockers"]
    assert drifted["authorizes_execution"] is False


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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    order_id = env["order"]["order_id"]
    input_fingerprint = env["evaluation"]["input_fingerprint"]
    batch_fingerprint = env["batch"]["batch_reconciliation_fingerprint"]
    first = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=batch_fingerprint,
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    approval = _operator_approval(env, first["dossier_fingerprint"])

    current[0] = _signed_stage1_promotion(version=2)
    drifted = service.preview_dossier(
        order_id,
        capital_evaluation_input_fingerprint=input_fingerprint,
        prior_batch_reconciliation_fingerprint=batch_fingerprint,
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    assert drifted["dossier_fingerprint"] != first["dossier_fingerprint"]
    assert drifted["connector_soak"]["signed_promotion"]["acceptance_id"] == ("1" * 64)
    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        service.record_confirmation(
            order_id,
            capital_evaluation_input_fingerprint=input_fingerprint,
            prior_batch_reconciliation_fingerprint=batch_fingerprint,
            execution_gateway_verification_fingerprint=(
                env["gateway_verification_fingerprint"]
            ),
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
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    def failed_provider(connector_id: str) -> dict:
        raise RuntimeError("private broker detail must not leak")

    failed_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        broker_soak_promotion_evidence_provider=failed_provider,
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
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
        execution_gateway_verification_provider=(
            lambda fingerprint: _clear_gateway_verification(env["order"])
        ),
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    failed = failed_service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )
    malformed = malformed_service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    assert missing["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_evidence_provider_unavailable"
    ]
    assert failed["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_evidence_provider_failed"
    ]
    assert "private broker detail must not leak" not in json.dumps(failed)
    assert "broker_soak_promotion_not_ready" in failed["hard_submission_blockers"]
    assert failed["submission_status"] == "blocked"
    assert malformed["connector_soak"]["signed_promotion"]["blockers"] == [
        "signed_promotion_trading_day_count_invalid"
    ]
    assert "broker_soak_promotion_not_ready" in malformed["hard_submission_blockers"]


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        (
            "gateway_id",
            "another-execution-gateway",
            "execution_gateway_verification_gateway_mismatch",
        ),
        (
            "evidence_connector_id",
            "another-readonly-connector",
            "execution_gateway_verification_connector_mismatch",
        ),
        (
            "account_alias",
            "another-account",
            "execution_gateway_verification_account_mismatch",
        ),
        (
            "order_id",
            "another-order",
            "execution_gateway_verification_order_mismatch",
        ),
        (
            "order_fingerprint",
            "7" * 64,
            "execution_gateway_verification_order_fingerprint_mismatch",
        ),
        (
            "order_contract",
            {
                "symbol": "510300.SH",
                "side": "buy",
                "asset_class": "fund",
                "quantity": "200",
                "order_type": "limit",
                "limit_price": "4",
            },
            "execution_gateway_verification_order_contract_mismatch",
        ),
    ],
)
def test_gateway_verification_scope_mismatch_blocks_exact_dossier(
    tmp_path,
    field: str,
    value: str,
    expected_blocker: str,
) -> None:
    env = _ready_environment(tmp_path)
    verification = _clear_gateway_verification(env["order"])
    verification[field] = value
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=lambda fingerprint: verification,
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=(
            env["gateway_verification_fingerprint"]
        ),
    )

    assert expected_blocker in dossier["review_blockers"]
    assert dossier["execution_gateway_verification"]["status"] == "blocked"
    assert (
        "execution_gateway_runtime_not_verified" in dossier["hard_submission_blockers"]
    )
    assert dossier["submission_status"] == "blocked"
    assert dossier["authorizes_execution"] is False


def test_gateway_verification_source_drift_invalidates_operator_approval(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    current = [_clear_gateway_verification(env["order"])]
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=lambda fingerprint: current[0],
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    kwargs = {
        "capital_evaluation_input_fingerprint": env["evaluation"]["input_fingerprint"],
        "prior_batch_reconciliation_fingerprint": env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        "execution_gateway_verification_fingerprint": env[
            "gateway_verification_fingerprint"
        ],
    }
    first = service.preview_dossier(env["order"]["order_id"], **kwargs)
    approval = _operator_approval(env, first["dossier_fingerprint"])
    current[0] = {
        **current[0],
        "status": "blocked",
        "runtime_gateway_verified": False,
        "runtime_verification_status": "blocked",
        "blockers": ["verification_source_changed"],
    }

    drifted = service.preview_dossier(env["order"]["order_id"], **kwargs)

    assert drifted["dossier_fingerprint"] != first["dossier_fingerprint"]
    assert (
        "execution_gateway_verification:verification_source_changed"
        in drifted["review_blockers"]
    )
    with pytest.raises(PerOrderConfirmationRejected) as exc_info:
        service.record_confirmation(
            env["order"]["order_id"],
            **kwargs,
            dossier_fingerprint=first["dossier_fingerprint"],
            operator_label="local-owner",
            operator_approval_id=approval["approval_id"],
            acknowledgement=PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        )
    assert (
        "dossier_fingerprint_mismatch" in exc_info.value.evidence["rejection_reasons"]
    )
    assert "dossier_review_blocked" in exc_info.value.evidence["rejection_reasons"]
    assert "operator_approval_blocked" in exc_info.value.evidence["rejection_reasons"]
    assert exc_info.value.evidence["authorizes_execution"] is False


def test_gateway_verification_provider_failures_are_sanitized_and_fail_closed(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)

    def failed_provider(fingerprint: str) -> dict:
        raise RuntimeError("private gateway credential must not leak")

    missing_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    failed_service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=failed_provider,
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )
    kwargs = {
        "capital_evaluation_input_fingerprint": env["evaluation"]["input_fingerprint"],
        "prior_batch_reconciliation_fingerprint": env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        "execution_gateway_verification_fingerprint": env[
            "gateway_verification_fingerprint"
        ],
    }

    missing = missing_service.preview_dossier(env["order"]["order_id"], **kwargs)
    failed = failed_service.preview_dossier(env["order"]["order_id"], **kwargs)

    assert missing["execution_gateway_verification"]["blockers"] == [
        "execution_gateway_verification_provider_unavailable"
    ]
    assert failed["execution_gateway_verification"]["blockers"] == [
        "execution_gateway_verification_provider_failed"
    ]
    assert "private gateway credential must not leak" not in json.dumps(failed)
    assert (
        "execution_gateway_runtime_not_verified" in failed["hard_submission_blockers"]
    )
    assert failed["authorizes_execution"] is False


def test_capital_evaluation_must_reference_exact_gateway_verification(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    requested = "9" * 64
    verification = {
        **_clear_gateway_verification(env["order"]),
        "verification_fingerprint": requested,
    }
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=lambda fingerprint: verification,
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=env["evaluation"]["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=requested,
    )

    assert (
        "capital_execution_gateway_verification_ref_mismatch"
        in dossier["review_blockers"]
    )
    assert dossier["execution_gateway_verification"]["status"] == "pass"
    assert dossier["review_ready"] is False


def test_recorded_runtime_verification_resolves_into_exact_per_order_dossier(
    tmp_path,
) -> None:
    env = _ready_environment(tmp_path)
    gateway = _RuntimeExecutionGateway()
    verifier = ExecutionGatewayVerificationService(
        db=env["db"],
        gateways=[gateway],
        clock=lambda: NOW,
    )
    order_contract = _clear_gateway_verification(env["order"])["order_contract"]
    verification_preview = verifier.preview(
        gateway_id=gateway.gateway_id,
        evidence_connector_id=gateway.evidence_connector_id,
        account_alias=gateway.account_alias,
        order_id=env["order"]["order_id"],
        order_fingerprint=build_order_fingerprint(env["order"]),
        order_contract=order_contract,
    )
    verification = verifier.record(
        gateway_id=gateway.gateway_id,
        evidence_connector_id=gateway.evidence_connector_id,
        account_alias=gateway.account_alias,
        order_id=env["order"]["order_id"],
        order_fingerprint=build_order_fingerprint(env["order"]),
        order_contract=order_contract,
        verification_fingerprint=verification_preview["verification_fingerprint"],
        acknowledgement=EXECUTION_GATEWAY_VERIFICATION_ACKNOWLEDGEMENT,
    )
    evidence_refs = tuple(
        ref
        for ref in env["capital_context"].evidence_refs
        if not ref.startswith("execution_gateway_verification:")
    ) + (
        "execution_gateway_verification:" f"{verification['verification_fingerprint']}",
    )
    current_context = replace(
        env["capital_context"],
        evidence_refs=evidence_refs,
    )
    current_evaluation = CapitalAuthorizationAuditService(
        db=env["db"],
        clock=lambda: NOW,
    ).record_evaluation(
        policy=env["capital_policy"],
        context=current_context,
    )
    service = PerOrderConfirmationService(
        db=env["db"],
        connectors=[env["connector"]],
        trusted_operator_identities=[env["trusted_identity"]],
        trading_controls=env["controls"],
        execution_gateway_verification_provider=verifier.resolve,
        account_truth_evidence_provider=_clear_account_truth_evidence,
        clock=lambda: NOW,
    )

    dossier = service.preview_dossier(
        env["order"]["order_id"],
        capital_evaluation_input_fingerprint=current_evaluation["input_fingerprint"],
        prior_batch_reconciliation_fingerprint=env["batch"][
            "batch_reconciliation_fingerprint"
        ],
        execution_gateway_verification_fingerprint=verification[
            "verification_fingerprint"
        ],
    )

    assert dossier["review_status"] == "review_ready_non_submitting"
    assert dossier["execution_gateway_verification"]["status"] == "pass"
    assert dossier["execution_gateway_verification"]["order_contract"] == (
        order_contract
    )
    assert (
        "execution_gateway_runtime_not_verified"
        not in dossier["hard_submission_blockers"]
    )
    assert "runtime_execution_authority_disabled" in dossier["hard_submission_blockers"]
    assert "broker_submission_disabled" in dossier["hard_submission_blockers"]
    assert dossier["authorizes_execution"] is False
    assert gateway.dry_run_calls >= 3
    assert gateway.submit_calls == 0
