from __future__ import annotations

import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.controlled_broker_submission import (
    CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
    ControlledBrokerSubmissionRejected,
    ControlledBrokerSubmissionService,
)
from server.services.oms import OmsService
from server.services.operator_approval import OperatorApprovalService
from server.services.per_order_confirmation import build_order_fingerprint
from server.services.trading_controls import TradingControlState

NOW = datetime(2026, 7, 13, 2, 0, tzinfo=timezone.utc)
CONFIRMATION_ID = "c" * 64
DOSSIER_FINGERPRINT = "d" * 64
GATEWAY_VERIFICATION_FINGERPRINT = "e" * 64
RELEASE_EVIDENCE_ID = "f" * 64
RELEASE_EVIDENCE_FINGERPRINT = "a" * 64


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-submit-owner",
        key_id="submit-owner-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


class FakeWriteGateway:
    gateway_id = "qmt-controlled-write-1"
    evidence_connector_id = "qmt-readonly-1"
    account_alias = "primary-review"
    account_binding_status = "verified"

    def __init__(self) -> None:
        self.capabilities = {
            "can_cancel_orders": True,
            "can_dry_run_orders": True,
            "can_query_orders": True,
            "can_submit_orders": True,
            "supports_idempotent_client_order_id": True,
        }
        self.health_status = "healthy"
        self.health_captured_at = NOW
        self.health_source_fingerprint = "b" * 64
        self.submit_calls = 0
        self.query_calls = 0
        self.last_submit_order: dict = {}
        self.submit_result: dict | Exception | None = None
        self.query_result: dict | Exception | None = None
        self.submit_started: Event | None = None
        self.submit_release: Event | None = None

    def get_health(self) -> dict:
        return {
            "status": self.health_status,
            "captured_at": self.health_captured_at.isoformat(),
            "source_fingerprint": self.health_source_fingerprint,
            "private_session": "must-not-leak",
        }

    def dry_run_order(self, order: dict) -> dict:
        return {
            "status": "accepted",
            "order_fingerprint": order["order_fingerprint"],
            "client_order_id": order["client_order_id"],
            "payload_fingerprint": _fingerprint(order),
            "submitted": False,
            "broker_order_id": "",
            "side_effect_count": 0,
            "private_payload": "must-not-leak",
        }

    def submit_order(self, order: dict) -> dict:
        self.submit_calls += 1
        self.last_submit_order = dict(order)
        if self.submit_started is not None:
            self.submit_started.set()
        if self.submit_release is not None:
            assert self.submit_release.wait(timeout=2)
        if isinstance(self.submit_result, Exception):
            raise self.submit_result
        if isinstance(self.submit_result, dict):
            return dict(self.submit_result)
        return {
            "status": "accepted",
            "submitted": True,
            "definitive": True,
            "client_order_id": order["client_order_id"],
            "order_fingerprint": order["order_fingerprint"],
            "broker_order_id": "BROKER-ORDER-1",
            "credential_echo": "must-not-leak",
        }

    def query_order(self, client_order_id: str) -> dict:
        self.query_calls += 1
        if isinstance(self.query_result, Exception):
            raise self.query_result
        if isinstance(self.query_result, dict):
            return dict(self.query_result)
        return {
            "status": "accepted",
            "submitted": True,
            "definitive": True,
            "client_order_id": client_order_id,
            "order_fingerprint": self.last_submit_order["order_fingerprint"],
            "broker_order_id": "BROKER-ORDER-RECOVERED",
        }


class SequencedTradingControls:
    def __init__(self, clear_reads: int) -> None:
        self.clear_reads = clear_reads
        self.calls = 0

    def snapshot(self):
        self.calls += 1
        enabled = self.calls > self.clear_reads
        return SimpleNamespace(
            kill_switch_enabled=enabled,
            reason="test race" if enabled else "",
            updated_at=NOW.isoformat(),
        )


def _environment(tmp_path, *, controls=None) -> dict:
    clock = [NOW]
    db = AppDatabase(tmp_path / "controlled-broker-submission.db")
    db.init_sync()
    oms = OmsService(db=db)
    order = oms.create_order_intent(
        intent_key="controlled-submit-intent-1",
        symbol="510300.SH",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="limit",
        limit_price=4,
        source="manual_confirmation_test",
        source_ref="decision-1",
    )
    order = oms.transition_order(
        order["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact order",
        actor="local-submit-owner",
    )
    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    approvals = OperatorApprovalService(
        db=db,
        trusted_identities=[identity],
        clock=lambda: clock[0],
        nonce_factory=lambda: "controlled-submit-nonce-00000000000000000001",
    )
    gateway = FakeWriteGateway()
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

    def confirmation_provider(confirmation_id: str) -> dict:
        current_order = db.get_oms_order_sync(order["order_id"]) or order
        return {
            "status": "current_verified_non_authorizing_confirmation",
            "confirmation_id": confirmation_id,
            "order_id": order["order_id"],
            "dossier_fingerprint": DOSSIER_FINGERPRINT,
            "operator_id": "local-submit-owner",
            "current_dossier": {
                "order_fingerprint": build_order_fingerprint(current_order),
                "execution_gateway_verification": {
                    "status": "pass",
                    "runtime_gateway_verified": True,
                    "gateway_id": gateway.gateway_id,
                    "verification_fingerprint": (GATEWAY_VERIFICATION_FINGERPRINT),
                },
                "capital_evaluation": {
                    "status": "pass",
                    "scope": {
                        "account_alias": gateway.account_alias,
                    },
                },
                "review_blockers": [],
                "hard_submission_blockers": [
                    "runtime_execution_authority_disabled",
                    "live_gateway_not_implemented",
                    "broker_submission_disabled",
                ],
            },
            "blockers": [],
            "authorizes_execution": False,
            "broker_submission_enabled": False,
        }

    trading_controls = controls or TradingControlState(db=db)
    service = ControlledBrokerSubmissionService(
        db=db,
        gateways=[gateway],
        confirmation_provider=confirmation_provider,
        release_evidence_provider=lambda evidence_id: release,
        trusted_operator_identities=[identity],
        trading_controls=trading_controls,
        clock=lambda: clock[0],
    )
    return {
        "db": db,
        "oms": oms,
        "order": order,
        "clock": clock,
        "private_key": private_key,
        "identity": identity,
        "approvals": approvals,
        "gateway": gateway,
        "release": release,
        "service": service,
    }


def _approval(env: dict, fingerprint: str) -> dict:
    challenge = env["approvals"].create_challenge(
        operator_id="local-submit-owner",
        key_id="submit-owner-key-1",
        action="submit_confirmed_broker_order",
        artifact_type="controlled_broker_submission",
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


def _preview(env: dict) -> dict:
    return env["service"].preview(
        order_id=env["order"]["order_id"],
        confirmation_id=CONFIRMATION_ID,
        release_evidence_id=RELEASE_EVIDENCE_ID,
    )


def _submit(env: dict, preview: dict, approval: dict) -> dict:
    return env["service"].submit(
        order_id=env["order"]["order_id"],
        confirmation_id=CONFIRMATION_ID,
        release_evidence_id=RELEASE_EVIDENCE_ID,
        submit_fingerprint=preview["submit_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
    )


def _direct_submit_intent(order: dict, *, seed: str) -> dict:
    fingerprint = build_order_fingerprint(order)
    intent_id = hashlib.sha256(f"intent:{seed}".encode()).hexdigest()
    submit_fingerprint = hashlib.sha256(f"submit:{seed}".encode()).hexdigest()
    return {
        "submit_intent_id": intent_id,
        "submit_fingerprint": submit_fingerprint,
        "order_id": order["order_id"],
        "order_fingerprint": fingerprint,
        "confirmation_id": hashlib.sha256(f"confirm:{seed}".encode()).hexdigest(),
        "dossier_fingerprint": hashlib.sha256(f"dossier:{seed}".encode()).hexdigest(),
        "gateway_id": "qmt-controlled-write-1",
        "gateway_verification_fingerprint": hashlib.sha256(
            f"gateway:{seed}".encode()
        ).hexdigest(),
        "release_evidence_id": hashlib.sha256(
            f"release-id:{seed}".encode()
        ).hexdigest(),
        "release_evidence_fingerprint": hashlib.sha256(
            f"release:{seed}".encode()
        ).hexdigest(),
        "client_order_id": f"KARK-{submit_fingerprint[:32]}",
        "operator_id": "local-submit-owner",
        "operator_approval_id": hashlib.sha256(f"approval:{seed}".encode()).hexdigest(),
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
            "submit_intent_id": intent_id,
            "submit_fingerprint": submit_fingerprint,
            "order_id": order["order_id"],
        },
        "created_at": NOW.isoformat(),
    }


def test_default_closed_without_write_gateway_or_release_evidence(tmp_path) -> None:
    env = _environment(tmp_path)
    service = ControlledBrokerSubmissionService(
        db=env["db"],
        confirmation_provider=lambda value: {},
        trusted_operator_identities=[env["identity"]],
        trading_controls=TradingControlState(db=env["db"]),
        clock=lambda: NOW,
    )

    status = service.get_status()
    preview = service.preview(
        order_id=env["order"]["order_id"],
        confirmation_id=CONFIRMATION_ID,
        release_evidence_id=RELEASE_EVIDENCE_ID,
    )

    assert status["contract_status"].startswith("disabled_waiting")
    assert status["default_broker_submission_enabled"] is False
    assert preview["ready"] is False
    assert "controlled_broker_submit_gateway_not_registered" in preview["blockers"]
    assert (
        "controlled_broker_submit_release_provider_unavailable" in preview["blockers"]
    )
    assert env["db"].list_controlled_broker_submit_intents_sync() == []
    assert env["gateway"].submit_calls == 0


def test_signed_submit_calls_gateway_once_and_exact_retry_only_reads_result(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    approval = _approval(env, preview["submit_fingerprint"])

    submitted = _submit(env, preview, approval)
    retry = _submit(env, preview, approval)

    assert preview["status"] == "ready_for_final_signature"
    assert submitted["status"] == "submitted"
    assert submitted["submitted_to_broker"] is True
    assert submitted["broker_order_id"] == "BROKER-ORDER-1"
    assert submitted["external_call_performed"] is True
    assert retry["status"] == "submitted"
    assert retry["reused"] is True
    assert retry["external_call_performed"] is False
    assert env["gateway"].submit_calls == 1
    assert env["gateway"].query_calls == 0
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "submitted"
    )
    assert [
        item["to_status"]
        for item in env["db"].list_oms_transitions_sync(env["order"]["order_id"])
    ][-2:] == ["submission_pending", "submitted"]
    assert "credential_echo" not in str(submitted)
    assert "must-not-leak" not in str(submitted)
    assert env["db"].get_ledger_entries_sync() == []


def test_explicit_broker_rejection_is_terminal_and_not_retried(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    env["gateway"].submit_result = {
        "status": "rejected",
        "submitted": False,
        "definitive": True,
        "client_order_id": preview["client_order_id"],
        "order_fingerprint": preview["order_fingerprint"],
        "broker_order_id": "",
    }
    approval = _approval(env, preview["submit_fingerprint"])

    rejected = _submit(env, preview, approval)
    retry = _submit(env, preview, approval)

    assert rejected["status"] == "rejected"
    assert rejected["submitted_to_broker"] is False
    assert retry["reused"] is True
    assert env["gateway"].submit_calls == 1
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "rejected"
    )
    assert env["db"].get_ledger_entries_sync() == []


def test_invalid_gateway_identifiers_stay_unknown_and_are_sanitized(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    env["gateway"].submit_result = {
        "status": "accepted",
        "submitted": True,
        "definitive": True,
        "client_order_id": preview["client_order_id"],
        "order_fingerprint": preview["order_fingerprint"],
        "broker_order_id": "secret\npassword=must-not-leak",
        "credential_echo": "must-not-leak",
    }
    approval = _approval(env, preview["submit_fingerprint"])

    result = _submit(env, preview, approval)

    assert result["status"] == "submission_unknown"
    assert result["broker_order_id"] == ""
    assert "must-not-leak" not in str(result)
    assert env["gateway"].submit_calls == 1
    assert env["db"].get_ledger_entries_sync() == []


def test_unknown_submit_never_resubmits_and_recovers_by_query_after_wait(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    env["gateway"].submit_result = TimeoutError("private broker timeout")
    approval = _approval(env, preview["submit_fingerprint"])

    unknown = _submit(env, preview, approval)
    retry = _submit(env, preview, approval)
    too_early = env["service"].recover(submit_intent_id=unknown["submit_intent_id"])

    assert unknown["status"] == "submission_unknown"
    assert unknown["submission_outcome_unknown"] is True
    assert retry["status"] == "submission_unknown"
    assert retry["external_call_performed"] is False
    assert too_early["status"] == "recovery_wait_required"
    assert env["gateway"].submit_calls == 1
    assert env["gateway"].query_calls == 0

    env["clock"][0] = NOW + timedelta(seconds=31)
    recovered = env["service"].recover(submit_intent_id=unknown["submit_intent_id"])

    assert recovered["status"] == "submitted"
    assert recovered["broker_order_id"] == "BROKER-ORDER-RECOVERED"
    assert recovered["external_call_performed"] is False
    assert env["gateway"].submit_calls == 1
    assert env["gateway"].query_calls == 1
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "submitted"
    )
    assert env["db"].get_ledger_entries_sync() == []


def test_definitive_not_found_after_wait_closes_unknown_without_resubmit(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    env["gateway"].submit_result = TimeoutError("timeout")
    approval = _approval(env, preview["submit_fingerprint"])
    unknown = _submit(env, preview, approval)
    env["clock"][0] = NOW + timedelta(seconds=31)
    env["gateway"].query_result = {
        "status": "not_found",
        "submitted": False,
        "definitive": True,
        "client_order_id": preview["client_order_id"],
        "order_fingerprint": preview["order_fingerprint"],
        "broker_order_id": "",
    }

    recovered = env["service"].recover(submit_intent_id=unknown["submit_intent_id"])

    assert recovered["status"] == "rejected"
    assert env["gateway"].submit_calls == 1
    assert env["gateway"].query_calls == 1
    assert env["db"].get_ledger_entries_sync() == []


def test_kill_switch_change_after_prepare_blocks_external_call(tmp_path) -> None:
    controls = SequencedTradingControls(clear_reads=2)
    env = _environment(tmp_path, controls=controls)
    preview = _preview(env)
    approval = _approval(env, preview["submit_fingerprint"])

    rejected = _submit(env, preview, approval)

    assert rejected["status"] == "rejected"
    assert rejected["external_call_performed"] is False
    assert rejected["gateway_result"]["status"] == "rejected_before_gateway_call"
    assert env["gateway"].submit_calls == 0
    assert env["db"].get_oms_order_sync(env["order"]["order_id"])["status"] == (
        "rejected"
    )
    assert env["db"].get_ledger_entries_sync() == []


def test_concurrent_exact_submit_grants_only_one_external_call(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    approval = _approval(env, preview["submit_fingerprint"])
    env["gateway"].submit_started = Event()
    env["gateway"].submit_release = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_submit, env, preview, approval)
        assert env["gateway"].submit_started.wait(timeout=2)
        second = executor.submit(_submit, env, preview, approval)
        second_result = second.result(timeout=2)
        env["gateway"].submit_release.set()
        first_result = first.result(timeout=2)

    persisted = env["service"].get_intent(preview["submit_intent_id"])
    assert env["gateway"].submit_calls == 1
    assert first_result["external_call_performed"] is True
    assert second_result["external_call_performed"] is False
    assert second_result["status"] == "prepared"
    assert persisted["status"] == "submitted"
    assert env["db"].get_ledger_entries_sync() == []


def test_atomic_interlock_allows_only_one_different_order_intent(tmp_path) -> None:
    env = _environment(tmp_path)
    second = env["oms"].create_order_intent(
        intent_key="controlled-submit-intent-2",
        symbol="159915.SZ",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="limit",
        limit_price=2,
        source="manual_confirmation_test",
        source_ref="decision-2",
    )
    second = env["oms"].transition_order(
        second["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed second exact order",
        actor="local-submit-owner",
    )
    intents = [
        _direct_submit_intent(env["order"], seed="first"),
        _direct_submit_intent(second, seed="second"),
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda intent: env["db"].prepare_controlled_broker_submit_intent_sync(
                    intent=intent
                ),
                intents,
            )
        )

    permitted = [row for row in results if row["external_call_permitted"]]
    blocked = [row for row in results if row["status"] == "rejected"]
    assert len(permitted) == 1
    assert len(blocked) == 1
    assert blocked[0]["blockers"] == [
        "controlled_broker_submit_unreconciled_intent_exists"
    ]
    statuses = {
        env["db"].get_oms_order_sync(order["order_id"])["status"]
        for order in (env["order"], second)
    }
    assert statuses == {"manually_confirmed", "submission_pending"}
    status = env["service"].get_status()
    assert status["contract_status"] == (
        "blocked_by_unreconciled_controlled_submission"
    )
    assert status["submission_interlock"]["unresolved_count"] == 1
    assert env["gateway"].submit_calls == 0
    assert env["db"].get_ledger_entries_sync() == []


def test_definitive_rejection_clears_interlock_but_unknown_does_not(tmp_path) -> None:
    env = _environment(tmp_path)
    second = env["oms"].create_order_intent(
        intent_key="controlled-submit-intent-after-rejection",
        symbol="159915.SZ",
        side="buy",
        asset_class="fund",
        quantity=100,
        order_type="limit",
        limit_price=2,
        source="manual_confirmation_test",
        source_ref="decision-after-rejection",
    )
    second = env["oms"].transition_order(
        second["order_id"],
        to_status="manually_confirmed",
        reason="operator confirmed exact follow-up order",
        actor="local-submit-owner",
    )
    first_intent = _direct_submit_intent(env["order"], seed="rejected-first")
    prepared = env["db"].prepare_controlled_broker_submit_intent_sync(
        intent=first_intent
    )
    assert prepared["external_call_permitted"] is True
    finalized = env["db"].finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=first_intent["submit_intent_id"],
        status="rejected",
        broker_order_id="",
        broker_status="rejected",
        result={
            "status": "rejected",
            "submitted": False,
            "definitive": True,
        },
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 1,
        finalized_at=(NOW + timedelta(milliseconds=1)).isoformat(),
    )
    assert finalized["status"] == "rejected"
    assert env["service"].get_status()["submission_interlock"]["blocked"] is False

    follow_up = env["db"].prepare_controlled_broker_submit_intent_sync(
        intent=_direct_submit_intent(second, seed="after-rejection")
    )

    assert follow_up["external_call_permitted"] is True
    unknown = env["db"].finalize_controlled_broker_submit_intent_sync(
        submit_intent_id=follow_up["intent"]["submit_intent_id"],
        status="submission_unknown",
        broker_order_id="",
        broker_status="gateway_submit_exception",
        result={"status": "gateway_submit_exception", "submitted": None},
        actor="controlled-broker-submission",
        finalized_at_epoch_ms=int(NOW.timestamp() * 1000) + 2,
        finalized_at=(NOW + timedelta(milliseconds=2)).isoformat(),
    )
    assert unknown["status"] == "submission_unknown"
    assert env["service"].get_status()["submission_interlock"]["blocked"] is True
    assert env["db"].get_ledger_entries_sync() == []


def test_wrong_final_signature_domain_and_retry_conflict_fail_closed(tmp_path) -> None:
    env = _environment(tmp_path)
    preview = _preview(env)
    challenge = env["approvals"].create_challenge(
        operator_id="local-submit-owner",
        key_id="submit-owner-key-1",
        action="attest_per_order_dossier",
        artifact_type="per_order_dossier",
        artifact_fingerprint=preview["submit_fingerprint"],
    )
    signature = env["private_key"].sign(
        base64.b64decode(challenge["signing_payload_base64"])
    )
    signature_base64 = base64.b64encode(signature).decode("ascii")
    wrong = env["approvals"].verify_signature(
        challenge_id=challenge["challenge_id"],
        signature_base64=signature_base64,
    )
    with pytest.raises(ControlledBrokerSubmissionRejected) as exc_info:
        env["service"].submit(
            order_id=env["order"]["order_id"],
            confirmation_id=CONFIRMATION_ID,
            release_evidence_id=RELEASE_EVIDENCE_ID,
            submit_fingerprint=preview["submit_fingerprint"],
            operator_approval_id=wrong["approval_id"],
            operator_proof_signature_base64=signature_base64,
            acknowledgement=CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
        )
    assert "controlled_broker_submit_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert signature_base64 not in str(exc_info.value.evidence)
    assert env["gateway"].submit_calls == 0

    approval = _approval(env, preview["submit_fingerprint"])
    submitted = _submit(env, preview, approval)
    with pytest.raises(ControlledBrokerSubmissionRejected) as conflict:
        env["service"].submit(
            order_id=env["order"]["order_id"],
            confirmation_id=CONFIRMATION_ID,
            release_evidence_id=RELEASE_EVIDENCE_ID,
            submit_fingerprint="9" * 64,
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=CONTROLLED_BROKER_SUBMISSION_ACKNOWLEDGEMENT,
        )
    assert submitted["status"] == "submitted"
    assert conflict.value.evidence["blockers"] == [
        "controlled_broker_submit_retry_conflict"
    ]
    assert env["gateway"].submit_calls == 1
