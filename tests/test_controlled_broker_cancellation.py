from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.controlled_broker_cancellation import (
    CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    ControlledBrokerCancellationRejected,
    ControlledBrokerCancellationService,
)
from server.services.oms import OmsService
from server.services.operator_approval import OperatorApprovalService
from server.services.per_order_confirmation import build_order_fingerprint

NOW = datetime(2026, 7, 17, 4, 0, tzinfo=timezone.utc)
RELEASE_EVIDENCE_ID = "f" * 64
RELEASE_EVIDENCE_FINGERPRINT = "a" * 64


class DeterministicCancelGateway:
    gateway_id = "fixture-controlled-gateway-1"
    evidence_connector_id = "fixture-readonly-1"
    account_alias = "main-cn-account"
    account_binding_status = "verified"

    def __init__(self) -> None:
        self.capabilities = {
            "can_cancel_orders": True,
            "can_query_orders": True,
            "supports_idempotent_client_order_id": True,
        }
        self.health_status = "healthy"
        self.health_captured_at = NOW
        self.health_source_fingerprint = "b" * 64
        self.cancel_calls = 0
        self.query_calls = 0
        self.cancel_result: dict | Exception | None = None
        self.query_result: dict | Exception | None = None
        self.cancel_started: Event | None = None
        self.cancel_release: Event | None = None

    def get_health(self) -> dict:
        return {
            "status": self.health_status,
            "captured_at": self.health_captured_at.isoformat(),
            "source_fingerprint": self.health_source_fingerprint,
            "credential_echo": "must-never-enter-cancellation-evidence",
        }

    def cancel_order(
        self,
        *,
        client_order_id: str,
        cancel_command_id: str,
        command_fingerprint: str,
    ) -> dict:
        self.cancel_calls += 1
        if self.cancel_started is not None:
            self.cancel_started.set()
        if self.cancel_release is not None:
            assert self.cancel_release.wait(timeout=2)
        if isinstance(self.cancel_result, Exception):
            raise self.cancel_result
        if isinstance(self.cancel_result, dict):
            return dict(self.cancel_result)
        return {
            "status": "partial_cancelled",
            "client_order_id": client_order_id,
            "broker_order_id": "BROKER-CONTROLLED-CANCEL-1",
            "cancel_command_id": cancel_command_id,
            "command_fingerprint": command_fingerprint,
            "filled_quantity": "40",
            "cancelled_quantity": "60",
            "definitive": True,
            "credential_echo": "must-never-enter-cancellation-evidence",
        }

    def query_order(self, client_order_id: str) -> dict:
        self.query_calls += 1
        if isinstance(self.query_result, Exception):
            raise self.query_result
        if isinstance(self.query_result, dict):
            return dict(self.query_result)
        return {
            "status": "cancelled",
            "client_order_id": client_order_id,
            "broker_order_id": "BROKER-CONTROLLED-CANCEL-1",
            "order_fingerprint": "d" * 64,
            "filled_quantity": "40",
            "cancelled_quantity": "60",
            "definitive": True,
            "private_session": "must-never-enter-cancellation-evidence",
        }


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="fixture-owner",
        key_id="fixture-owner-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


def _environment(tmp_path: Path) -> dict:
    clock = [NOW]
    db = AppDatabase(tmp_path / "controlled-cancel.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="controlled-cancel-order-1",
        symbol="600519",
        side="buy",
        asset_class="stock",
        quantity=100,
        order_type="limit",
        limit_price=10,
        source="controlled_cancel_test",
        source_ref="decision-1",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact order",
        actor="fixture-owner",
    )
    submit_intent_id = hashlib.sha256(b"controlled-cancel-intent").hexdigest()
    submit_fingerprint = hashlib.sha256(b"controlled-cancel-submit").hexdigest()
    prepared = db.prepare_controlled_broker_submit_intent_sync(
        intent={
            "submit_intent_id": submit_intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
            "order_fingerprint": build_order_fingerprint(order),
            "confirmation_id": "c" * 64,
            "dossier_fingerprint": "d" * 64,
            "gateway_id": "fixture-controlled-gateway-1",
            "gateway_verification_fingerprint": "e" * 64,
            "release_evidence_id": RELEASE_EVIDENCE_ID,
            "release_evidence_fingerprint": RELEASE_EVIDENCE_FINGERPRINT,
            "client_order_id": "KARK-controlled-cancel-client-1",
            "operator_id": "fixture-owner",
            "operator_approval_id": "1" * 64,
            "order_snapshot": {
                key: order.get(key)
                for key in (
                    "symbol",
                    "side",
                    "asset_class",
                    "quantity",
                    "order_type",
                    "limit_price",
                )
            },
            "prepared_at_epoch_ms": int(NOW.timestamp() * 1000),
            "prepared_at": NOW.isoformat(),
            "payload": {
                "submit_intent_id": submit_intent_id,
                "submit_fingerprint": submit_fingerprint,
                "order_id": order["order_id"],
                "account_alias": "main-cn-account",
            },
            "created_at": NOW.isoformat(),
        }
    )
    assert prepared["external_call_permitted"] is True
    finalized = db.finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=submit_intent_id,
        status="submitted",
        broker_order_id="BROKER-CONTROLLED-CANCEL-1",
        broker_status="accepted",
        result={
            "status": "accepted",
            "submitted": True,
            "definitive": True,
            "client_order_id": "KARK-controlled-cancel-client-1",
            "order_fingerprint": build_order_fingerprint(order),
            "broker_order_id": "BROKER-CONTROLLED-CANCEL-1",
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 1,
        finalized_at=(NOW + timedelta(milliseconds=1)).isoformat(),
    )
    assert finalized["status"] == "submitted"

    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    approvals = OperatorApprovalService(
        db=db,
        trusted_identities=[identity],
        clock=lambda: clock[0],
        nonce_factory=lambda: "controlled-cancel-nonce-000000000000000001",
    )
    gateway = DeterministicCancelGateway()
    release = {
        "status": "current_clear_signed_release",
        "release_evidence_id": RELEASE_EVIDENCE_ID,
        "evidence_fingerprint": RELEASE_EVIDENCE_FINGERPRINT,
        "gateway_id": gateway.gateway_id,
        "account_alias": gateway.account_alias,
        "operator_identity_verified": True,
        "execution_mode": "manual_each_order",
        "automatic_execution_allowed": False,
        "strategy_direct_submission_allowed": False,
        "broker_agreement_reviewed": True,
        "connector_tested": True,
        "program_trading_reporting_reviewed": True,
        "risk_controls_reviewed": True,
        "effective_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
    }
    service = ControlledBrokerCancellationService(
        db=db,
        gateways=[gateway],
        release_evidence_provider=lambda evidence_id: release,
        trusted_operator_identities=[identity],
        clock=lambda: clock[0],
    )
    env = {
        "db": db,
        "oms": oms,
        "order": order,
        "submit_intent_id": submit_intent_id,
        "clock": clock,
        "private_key": private_key,
        "identity": identity,
        "approvals": approvals,
        "gateway": gateway,
        "release": release,
        "service": service,
    }
    _record_lifecycle(env)
    return env


def _record_lifecycle(
    env: dict,
    *,
    status: str = "partially_filled",
    filled: int = 40,
    cancelled: int = 0,
    source_sequence: int = 1,
    captured_at: datetime = NOW,
) -> dict:
    fills = []
    if filled:
        fills.append(
            {
                "broker_trade_id": f"FIXTURE-CANCEL-{source_sequence}",
                "broker_order_id": "BROKER-CONTROLLED-CANCEL-1",
                "client_order_id": "KARK-controlled-cancel-client-1",
                "symbol": "600519",
                "side": "buy",
                "quantity": str(filled),
                "price": "10",
                "fee": "1",
                "tax": "0",
                "transfer_fee": "0",
                "net_amount": str(-(filled * 10 + 1)),
                "filled_at": (captured_at - timedelta(seconds=2)).isoformat(),
            }
        )
    payload = {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "fixture_broker",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-controlled-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "main-cn-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": source_sequence,
        "orders": [
            {
                "broker_order_id": "BROKER-CONTROLLED-CANCEL-1",
                "client_order_id": "KARK-controlled-cancel-client-1",
                "symbol": "600519",
                "side": "buy",
                "status": status,
                "order_quantity": "100",
                "cumulative_filled_quantity": str(filled),
                "cancelled_quantity": str(cancelled),
                "average_fill_price": "10" if filled else None,
                "submitted_at": (captured_at - timedelta(seconds=5)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": fills,
    }
    preview = preview_broker_order_lifecycle_export(
        json.dumps(payload),
        source_name="deterministic controlled cancellation fixture",
        clock=lambda: captured_at,
    )
    assert preview["ready_to_record"] is True, preview["blockers"]
    return BrokerOrderLifecycleEvidenceRepository(Path(env["db"]._path)).record(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )


def _approval(env: dict, preview: dict, *, recovery: bool = False) -> dict:
    action = (
        "query_exact_broker_cancellation_outcome"
        if recovery
        else "cancel_exact_controlled_broker_order"
    )
    artifact_type = (
        "controlled_broker_cancellation_recovery"
        if recovery
        else "controlled_broker_cancellation"
    )
    fingerprint = preview["recovery_fingerprint" if recovery else "cancel_fingerprint"]
    challenge = env["approvals"].create_challenge(
        operator_id="fixture-owner",
        key_id="fixture-owner-key-1",
        action=action,
        artifact_type=artifact_type,
        artifact_fingerprint=fingerprint,
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    approval = env["approvals"].verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    return {**approval, "proof_signature_base64": signature_base64}


def _cancel(env: dict, preview: dict, approval: dict) -> dict:
    return env["service"].cancel(
        submit_intent_id=env["submit_intent_id"],
        cancel_fingerprint=preview["cancel_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )


def _recover(env: dict, preview: dict, approval: dict) -> dict:
    return env["service"].recover(
        cancel_command_id=preview["cancel_command_id"],
        recovery_fingerprint=preview["recovery_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    )


def _protected_state(env: dict) -> dict:
    with sqlite3.connect(env["db"]._path) as conn:
        return {
            "oms_order": tuple(
                conn.execute(
                    "SELECT status, payload_json FROM oms_orders WHERE order_id = ?",
                    (env["order"]["order_id"],),
                ).fetchone()
            ),
            "oms_transitions": conn.execute(
                "SELECT COUNT(*) FROM oms_transitions"
            ).fetchone()[0],
            "fills": conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],
            "risk": conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0],
            "lifecycle": conn.execute(
                "SELECT COUNT(*) FROM broker_order_lifecycle_observations"
            ).fetchone()[0],
        }


def test_default_closed_preview_is_read_only_without_gateway_or_release(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerCancellationService(db=env["db"], clock=lambda: NOW)
    with sqlite3.connect(env["db"]._path) as conn:
        before = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name = 'controlled_broker_cancellation_commands'
            """).fetchone()[0]

    status = service.get_status()
    preview = service.preview(submit_intent_id=env["submit_intent_id"])

    assert status["contract_status"].startswith("disabled_waiting")
    assert status["default_broker_cancellation_enabled"] is False
    assert status["strategy_direct_cancellation_enabled"] is False
    assert status["ai_direct_cancellation_enabled"] is False
    assert preview["ready"] is False
    assert "controlled_broker_cancel_gateway_not_registered" in preview["blockers"]
    assert preview["broker_cancel_performed"] is False
    with sqlite3.connect(env["db"]._path) as conn:
        after = conn.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'table' AND name = 'controlled_broker_cancellation_commands'
            """).fetchone()[0]
    assert before == after == 0


def test_signed_exact_cancel_calls_gateway_once_without_mutating_financial_facts(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    approval = _approval(env, preview)
    before = _protected_state(env)

    result = _cancel(env, preview, approval)

    assert preview["status"] == "ready_for_final_signature"
    assert result["status"] == "cancel_requested"
    assert result["broker_cancel_request_sent"] is True
    assert result["cancellation_proven"] is False
    assert result["canonical_lifecycle_mutated"] is False
    assert result["oms_mutated"] is False
    assert result["production_ledger_mutated"] is False
    assert result["capital_authority_changed"] is False
    assert env["gateway"].cancel_calls == 1
    assert _protected_state(env) == before
    persisted = env["service"].get_command(result["cancel_command_id"])
    assert persisted["status"] == "cancel_requested"
    assert persisted["external_call_performed"] is False


def test_duplicate_restart_and_concurrent_cancel_never_repeat_external_effect(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    approval = _approval(env, preview)
    env["gateway"].cancel_started = Event()
    env["gateway"].cancel_release = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_cancel, env, preview, approval)
        assert env["gateway"].cancel_started.wait(timeout=2)
        second = executor.submit(_cancel, env, preview, approval)
        second_result = second.result(timeout=2)
        env["gateway"].cancel_release.set()
        first_result = first.result(timeout=2)

    restarted = ControlledBrokerCancellationService(
        db=AppDatabase(env["db"]._path),
        gateways=[env["gateway"]],
        release_evidence_provider=lambda evidence_id: env["release"],
        trusted_operator_identities=[env["identity"]],
        clock=lambda: env["clock"][0],
    ).cancel(
        submit_intent_id=env["submit_intent_id"],
        cancel_fingerprint=preview["cancel_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
    )

    assert env["gateway"].cancel_calls == 1
    assert first_result["status"] == "cancel_requested"
    assert second_result["external_call_performed"] is False
    assert restarted["reused"] is True
    assert restarted["external_call_performed"] is False


def test_timeout_is_unknown_and_only_signed_query_recovery_is_allowed(tmp_path) -> None:
    env = _environment(tmp_path)
    env["gateway"].cancel_result = TimeoutError("private gateway detail")
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    approval = _approval(env, preview)
    cancelled = _cancel(env, preview, approval)
    env["clock"][0] = NOW + timedelta(seconds=31)
    recovery_preview = env["service"].preview_recovery(
        cancel_command_id=cancelled["cancel_command_id"]
    )
    recovery_approval = _approval(env, recovery_preview, recovery=True)
    before = _protected_state(env)

    recovered = _recover(env, recovery_preview, recovery_approval)
    replay = _recover(env, recovery_preview, recovery_approval)

    assert cancelled["status"] == "cancellation_unknown"
    assert recovery_preview["status"] == "ready_for_query_signature"
    assert recovered["recovery_query_performed"] is True
    assert recovered["query_result"]["status"] == "cancelled"
    assert recovered["query_result_authoritative"] is False
    assert recovered["cancellation_proven"] is False
    assert replay["reused"] is True
    assert replay["recovery_query_performed"] is False
    assert env["gateway"].cancel_calls == 1
    assert env["gateway"].query_calls == 1
    assert _protected_state(env) == before


def test_restart_from_prepared_claim_queries_without_recancel(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    approval = _approval(env, preview)
    prepared = env["service"]._store.prepare(
        preview=preview,
        operator_approval_id=approval["approval_id"],
        prepared_at_epoch_ms=int(NOW.timestamp() * 1000),
        prepared_at=NOW.isoformat(),
    )
    assert prepared["status"] == "prepared"
    env["clock"][0] = NOW + timedelta(seconds=31)
    restarted = ControlledBrokerCancellationService(
        db=AppDatabase(env["db"]._path),
        gateways=[env["gateway"]],
        release_evidence_provider=lambda evidence_id: env["release"],
        trusted_operator_identities=[env["identity"]],
        clock=lambda: env["clock"][0],
    )
    recovery_preview = restarted.preview_recovery(
        cancel_command_id=preview["cancel_command_id"]
    )
    recovery_approval = _approval(env, recovery_preview, recovery=True)

    recovered = restarted.recover(
        cancel_command_id=preview["cancel_command_id"],
        recovery_fingerprint=recovery_preview["recovery_fingerprint"],
        operator_approval_id=recovery_approval["approval_id"],
        operator_proof_signature_base64=recovery_approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_BROKER_CANCELLATION_RECOVERY_ACKNOWLEDGEMENT,
    )

    assert recovered["recovery_query_performed"] is True
    assert env["gateway"].cancel_calls == 0
    assert env["gateway"].query_calls == 1


def test_lifecycle_drift_and_terminal_evidence_fail_closed_without_gateway_call(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    approval = _approval(env, preview)
    _record_lifecycle(
        env,
        status="cancelled",
        filled=40,
        cancelled=60,
        source_sequence=2,
        captured_at=NOW + timedelta(seconds=10),
    )

    with pytest.raises(ControlledBrokerCancellationRejected) as exc_info:
        _cancel(env, preview, approval)

    assert "controlled_broker_cancel_fingerprint_mismatch" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert env["gateway"].cancel_calls == 0
    current = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    assert "manual_broker_cancel_lifecycle_not_cancellable" in current["blockers"]


def test_definitive_gateway_rejection_never_enables_retry_and_kill_switch_does_not_block(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    env["db"].set_runtime_control_sync(
        "kill_switch",
        {"enabled": True, "reason": "risk containment"},
    )
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    env["gateway"].cancel_result = {
        "status": "rejected",
        "client_order_id": preview["identity"]["client_order_id"],
        "broker_order_id": preview["identity"]["broker_order_id"],
        "cancel_command_id": preview["cancel_command_id"],
        "command_fingerprint": preview["cancel_fingerprint"],
        "definitive": True,
        "reason": "fixture rejection",
    }
    approval = _approval(env, preview)

    first = _cancel(env, preview, approval)
    replay = _cancel(env, preview, approval)

    assert preview["ready"] is True
    assert first["status"] == "cancel_rejected"
    assert first["cancellation_retry_enabled"] is False
    assert replay["reused"] is True
    assert env["gateway"].cancel_calls == 1


def test_wrong_signature_and_sensitive_gateway_fields_are_sanitized(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = env["service"].preview(submit_intent_id=env["submit_intent_id"])
    challenge = env["approvals"].create_challenge(
        operator_id="fixture-owner",
        key_id="fixture-owner-key-1",
        action="submit_confirmed_broker_order",
        artifact_type="controlled_broker_submission",
        artifact_fingerprint=preview["cancel_fingerprint"],
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    wrong = env["approvals"].verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    with pytest.raises(ControlledBrokerCancellationRejected) as exc_info:
        env["service"].cancel(
            submit_intent_id=env["submit_intent_id"],
            cancel_fingerprint=preview["cancel_fingerprint"],
            operator_approval_id=wrong["approval_id"],
            operator_proof_signature_base64=signature_base64,
            acknowledgement=CONTROLLED_BROKER_CANCELLATION_ACKNOWLEDGEMENT,
        )
    assert "controlled_broker_cancel_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert signature_base64 not in str(exc_info.value.evidence)
    assert env["gateway"].cancel_calls == 0

    approval = _approval(env, preview)
    _cancel(env, preview, approval)
    database_text = Path(env["db"]._path).read_bytes().decode("utf-8", errors="ignore")
    assert "must-never-enter-cancellation-evidence" not in database_text
    assert "private gateway detail" not in database_text
