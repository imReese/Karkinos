from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_budget_reservation import (
    CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    ControlledSessionBudgetReservationService,
)
from server.services.controlled_session_runtime_authority import (
    CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
    ControlledSessionRuntimeAuthorityRejected,
    ControlledSessionRuntimeAuthorityService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    ControlledSessionRateAdmissionRejected,
    ControlledSessionRuntimeRateLimiterService,
)
from server.services.operator_approval import OperatorApprovalService

NOW = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
TOKEN = "runtime-session-token-000000000000000000000001"
REPLACEMENT_TOKEN = "runtime-session-token-000000000000000000000002"
SALT = "ab" * 16


def _identity(private_key: Ed25519PrivateKey) -> TrustedOperatorIdentityConfig:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorIdentityConfig(
        operator_id="local-session-owner",
        key_id="session-owner-key-1",
        algorithm="ed25519",
        public_key_base64=base64.b64encode(public_bytes).decode("ascii"),
        enabled=True,
    )


def _attestation(
    *,
    attestation_id: str = "a" * 64,
    envelope_fingerprint: str = "e" * 64,
    start_at: datetime = NOW - timedelta(seconds=1),
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> dict:
    return {
        "status": "current_verified_non_executing",
        "attestation_id": attestation_id,
        "envelope_fingerprint": envelope_fingerprint,
        "operator_label": "local-session-owner",
        "current_envelope": {
            "requested_start_at": start_at.isoformat(),
            "requested_expires_at": expires_at.isoformat(),
            "order_ids": ["OMS-1", "OMS-2"],
            "capital_evaluation": {
                "input_fingerprint": "c" * 64,
                "authorization_id": "capital-auth-1",
                "policy_version": "policy-v1",
                "scope": {
                    "account_alias": "中信证券88**16",
                    "strategy_id": "strategy-1",
                },
            },
            "budget_projection": {
                "projected_gross_order_value": "600",
                "projected_buy_value": "600",
                "effective_capital": "1000",
                "current_authorized_exposure": "0",
                "available_cash": "1000",
                "remaining_daily_turnover_after_projection": "400",
                "order_count": 2,
                "projected_rate_capacity": 20,
                "max_order_rate_per_minute": 2,
                "projected_by_symbol": {"510300.SH": "600"},
            },
            "per_symbol_runtime_limits": {
                "status": "pass",
                "requested_limits": {"510300.SH": "1000"},
            },
        },
        "blockers": [],
        "authorizes_execution": False,
    }


def _environment(tmp_path, *, current_time=None, capacity: str = "1000"):
    clock = current_time or [NOW]
    db = AppDatabase(tmp_path / "controlled-session-runtime-authority.db")
    db.init_sync()
    private_key = Ed25519PrivateKey.generate()
    identity = _identity(private_key)
    initial_attestation = _attestation()
    initial_budget = initial_attestation["current_envelope"]["budget_projection"]
    initial_budget.update(
        {
            "effective_capital": capacity,
            "available_cash": capacity,
            "remaining_daily_turnover_after_projection": str(int(capacity) - 600),
        }
    )
    initial_attestation["current_envelope"]["per_symbol_runtime_limits"] = {
        "status": "pass",
        "requested_limits": {"510300.SH": capacity},
    }
    attestations = {"a" * 64: initial_attestation}
    attestation_provider = lambda value: attestations.get(
        value,
        {"status": "blocked", "blockers": ["not_found"]},
    )
    budget_service = ControlledSessionBudgetReservationService(
        db=db,
        attestation_provider=attestation_provider,
        clock=lambda: clock[0],
    )
    budget_preview = budget_service.preview(attestation_id="a" * 64)
    reservation = budget_service.record(
        attestation_id="a" * 64,
        reservation_fingerprint=budget_preview["reservation_fingerprint"],
        acknowledgement=CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    )
    authority = ControlledSessionRuntimeAuthorityService(
        db=db,
        reservation_provider=budget_service.resolve,
        attestation_provider=attestation_provider,
        trusted_operator_identities=[identity],
        clock=lambda: clock[0],
        token_factory=iter(
            [
                TOKEN,
                REPLACEMENT_TOKEN,
                "runtime-session-token-000000000000000000000003",
                "runtime-session-token-000000000000000000000004",
            ]
        ).__next__,
        salt_factory=lambda: SALT,
    )
    approvals = OperatorApprovalService(
        db=db,
        trusted_identities=[identity],
        clock=lambda: clock[0],
        nonce_factory=lambda: "deterministic-runtime-session-nonce-000000000001",
    )
    return {
        "db": db,
        "clock": clock,
        "private_key": private_key,
        "identity": identity,
        "attestations": attestations,
        "budget_service": budget_service,
        "reservation": reservation,
        "authority": authority,
        "approvals": approvals,
    }


def _approval(env: dict, *, action: str, artifact_type: str, fingerprint: str) -> dict:
    challenge = env["approvals"].create_challenge(
        operator_id="local-session-owner",
        key_id="session-owner-key-1",
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


def _issue(env: dict) -> dict:
    preview = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    approval = _approval(
        env,
        action="issue_controlled_session",
        artifact_type="controlled_session_issuance",
        fingerprint=preview["issuance_fingerprint"],
    )
    return env["authority"].issue(
        reservation_id=env["reservation"]["reservation_id"],
        issuance_fingerprint=preview["issuance_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
    )


def _replacement_reservation(
    env: dict,
    *,
    attestation_id: str = "b" * 64,
    envelope_fingerprint: str = "f" * 64,
    gross: str = "300",
    max_rate: int = 1,
    capacity: str = "1000",
    duration_minutes: int = 5,
    order_ids: list[str] | None = None,
    projected_by_symbol: dict[str, str] | None = None,
) -> dict:
    current = env["clock"][0]
    attestation = _attestation(
        attestation_id=attestation_id,
        envelope_fingerprint=envelope_fingerprint,
        start_at=current - timedelta(seconds=1),
        expires_at=current + timedelta(minutes=duration_minutes),
    )
    selected_orders = order_ids or ["OMS-1", "OMS-2"]
    symbol_projection = projected_by_symbol or {"510300.SH": gross}
    attestation["current_envelope"]["order_ids"] = selected_orders
    budget = attestation["current_envelope"]["budget_projection"]
    budget.update(
        {
            "projected_gross_order_value": gross,
            "projected_buy_value": gross,
            "effective_capital": capacity,
            "available_cash": capacity,
            "remaining_daily_turnover_after_projection": str(
                int(capacity) - int(gross)
            ),
            "order_count": len(selected_orders),
            "projected_rate_capacity": max_rate * 10,
            "max_order_rate_per_minute": max_rate,
            "projected_by_symbol": symbol_projection,
        }
    )
    attestation["current_envelope"]["per_symbol_runtime_limits"] = {
        "status": "pass",
        "requested_limits": {symbol: capacity for symbol in sorted(symbol_projection)},
    }
    env["attestations"][attestation_id] = attestation
    preview = env["budget_service"].preview(attestation_id=attestation_id)
    return env["budget_service"].record(
        attestation_id=attestation_id,
        reservation_fingerprint=preview["reservation_fingerprint"],
        acknowledgement=CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    )


def _pause(env: dict, issued: dict) -> dict:
    gates = {
        "source_fingerprint": "8" * 64,
        "account_truth_status": "pass",
        "risk_gate_status": "passed",
        "reconciliation_status": "clear",
        "paper_shadow_status": "within_expectations",
        "gateway_health_status": "healthy",
        "market_data_status": "confirmed",
        "budget_status": "current_reserved_non_executing",
        "rate_limit_status": "clear",
        "kill_switch_enabled": True,
        "budget_exhausted": False,
        "daily_loss_limit_reached": False,
        "drawdown_limit_reached": False,
        "rejection_spike": False,
        "unexpected_account_change": False,
        "consecutive_errors": 0,
        "max_consecutive_errors": 2,
    }
    service = ControlledSessionAutomaticPauseService(
        db=env["db"],
        session_provider=env["authority"].resolve_current,
        gate_provider=lambda session_id: gates,
        clock=lambda: env["clock"][0],
    )
    return service.evaluate(session_id=issued["session_id"])


def _record_recovery_snapshot(
    env: dict,
    issued: dict,
    *,
    marker: str,
    status: str = "clear",
) -> dict:
    observed_at = env["clock"][0]
    snapshot_id = marker * 64
    snapshot_fingerprint = chr(ord(marker) + 2) * 64
    payload = {
        "snapshot_id": snapshot_id,
        "snapshot_fingerprint": snapshot_fingerprint,
        "session_id": issued["session_id"],
        "session_fingerprint": issued["session_fingerprint"],
        "status": status,
        "blockers": [] if status == "clear" else ["test_gate_blocked"],
        "observed_at": observed_at.isoformat(),
        "broker_submission_enabled": False,
    }
    return env["db"].record_controlled_session_gate_snapshot_sync(
        snapshot={
            "snapshot_id": snapshot_id,
            "snapshot_fingerprint": snapshot_fingerprint,
            "session_id": issued["session_id"],
            "session_fingerprint": issued["session_fingerprint"],
            "source_fingerprint": "9" * 64,
            "observed_at_epoch_ms": int(observed_at.timestamp() * 1000),
            "observed_at": observed_at.isoformat(),
            "status": status,
            "gate_snapshot": {"all_hard_gates_clear": True},
            "source_evidence": {"source_fingerprint": "9" * 64},
            "blockers": [] if status == "clear" else ["test_gate_blocked"],
            "payload": payload,
            "created_at": observed_at.isoformat(),
        }
    )


def test_issuance_preview_is_deterministic_and_requires_separate_signature(
    tmp_path,
) -> None:
    env = _environment(tmp_path)

    first = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    second = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )

    assert first["status"] == "ready_for_signed_issue"
    assert first["issuance_fingerprint"] == second["issuance_fingerprint"]
    assert first["required_operator_approval"] == {
        "action": "issue_controlled_session",
        "artifact_type": "controlled_session_issuance",
        "artifact_fingerprint": first["issuance_fingerprint"],
    }
    assert first["runtime_session_issued"] is False
    assert first["broker_submission_enabled"] is False
    assert env["db"].list_controlled_session_runtime_sessions_sync() == []


def test_issue_returns_token_once_stores_only_hash_and_authenticates(tmp_path) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    preview = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    approval = _approval(
        env,
        action="issue_controlled_session",
        artifact_type="controlled_session_issuance",
        fingerprint=preview["issuance_fingerprint"],
    )
    retry = env["authority"].issue(
        reservation_id=env["reservation"]["reservation_id"],
        issuance_fingerprint=preview["issuance_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
    )

    assert issued["status"] == "enabled"
    assert issued["session_token"] == TOKEN
    assert issued["session_token_issued"] is True
    assert issued["broker_submission_enabled"] is False
    assert retry["reused"] is True
    assert retry["session_token"] == ""
    assert retry["session_token_issued"] is False
    row = env["db"].get_controlled_session_runtime_session_sync(issued["session_id"])
    assert row is not None
    assert row["token_hash"] != TOKEN
    assert TOKEN not in str(row)
    assert (
        env["authority"].authenticate(issued["session_id"], TOKEN)[
            "runtime_authentication_verified"
        ]
        is True
    )
    blocked = env["authority"].authenticate(
        issued["session_id"],
        "wrong-runtime-session-token-00000000000000000001",
    )
    assert blocked["blockers"] == ["runtime_session_authentication_failed"]
    assert TOKEN not in str(env["authority"].list_sessions())


def test_wrong_action_approval_and_source_drift_fail_closed_and_are_audited(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    wrong = _approval(
        env,
        action="attest_controlled_session_envelope",
        artifact_type="controlled_session_envelope",
        fingerprint=preview["issuance_fingerprint"],
    )

    with pytest.raises(ControlledSessionRuntimeAuthorityRejected) as exc_info:
        env["authority"].issue(
            reservation_id=env["reservation"]["reservation_id"],
            issuance_fingerprint=preview["issuance_fingerprint"],
            operator_approval_id=wrong["approval_id"],
            operator_proof_signature_base64=wrong["proof_signature_base64"],
            acknowledgement=CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
        )

    assert "runtime_session_issue_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert (
        len(
            env["db"].list_events_sync(
                event_type=CONTROLLED_SESSION_RUNTIME_AUTHORITY_REJECTION_EVENT_TYPE,
                limit=10,
            )
        )
        == 1
    )

    issued = _issue(env)
    env["attestations"]["a" * 64] = {
        "status": "blocked",
        "blockers": ["source_changed"],
    }
    current = env["authority"].resolve_current(issued["session_id"])
    assert current["status"] == "blocked"
    assert "runtime_session_reservation_not_current" in current["blockers"]
    monitoring = env["authority"].resolve_for_monitoring(issued["session_id"])
    assert monitoring["status"] == "monitorable_bounded_session"
    assert monitoring["monitoring_identity_verified"] is True
    authenticated_monitoring = env["authority"].authenticate_for_monitoring(
        issued["session_id"],
        TOKEN,
    )
    assert authenticated_monitoring["runtime_authentication_verified"] is True
    assert authenticated_monitoring["runtime_authority_enabled"] is False


def test_public_approval_id_without_private_signature_proof_cannot_issue(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    approval = _approval(
        env,
        action="issue_controlled_session",
        artifact_type="controlled_session_issuance",
        fingerprint=preview["issuance_fingerprint"],
    )
    wrong_proof = base64.b64encode(b"0" * 64).decode("ascii")

    with pytest.raises(ControlledSessionRuntimeAuthorityRejected) as exc_info:
        env["authority"].issue(
            reservation_id=env["reservation"]["reservation_id"],
            issuance_fingerprint=preview["issuance_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=wrong_proof,
            acknowledgement=CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
        )

    assert "runtime_session_issue_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert wrong_proof not in str(exc_info.value.evidence)
    assert env["db"].list_controlled_session_runtime_sessions_sync() == []


def test_concurrent_exact_issue_creates_one_session_and_one_token_response(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    preview = env["authority"].preview_issuance(
        reservation_id=env["reservation"]["reservation_id"]
    )
    approval = _approval(
        env,
        action="issue_controlled_session",
        artifact_type="controlled_session_issuance",
        fingerprint=preview["issuance_fingerprint"],
    )

    def issue(_: int) -> dict:
        return env["authority"].issue(
            reservation_id=env["reservation"]["reservation_id"],
            issuance_fingerprint=preview["issuance_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=CONTROLLED_SESSION_ISSUANCE_ACKNOWLEDGEMENT,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(issue, range(2)))

    assert len(env["db"].list_controlled_session_runtime_sessions_sync()) == 1
    assert sorted(result["reused"] for result in results) == [False, True]
    assert sum(result["session_token_issued"] for result in results) == 1


def test_signed_revocation_is_one_way_idempotent_and_blocks_authentication(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    preview = env["authority"].preview_revocation(
        session_id=issued["session_id"],
        reason_code="manual_operator_stop",
    )
    approval = _approval(
        env,
        action="revoke_controlled_session",
        artifact_type="controlled_session_revocation",
        fingerprint=preview["revocation_fingerprint"],
    )

    revoked = env["authority"].revoke(
        session_id=issued["session_id"],
        reason_code="manual_operator_stop",
        revocation_fingerprint=preview["revocation_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    )
    retry = env["authority"].revoke(
        session_id=issued["session_id"],
        reason_code="manual_operator_stop",
        revocation_fingerprint=preview["revocation_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    )

    assert revoked["status"] == "revoked"
    assert revoked["automatic_resume_enabled"] is False
    assert retry["reused"] is True
    assert len(env["db"].list_controlled_session_revocations_sync()) == 1
    current = env["authority"].authenticate(issued["session_id"], TOKEN)
    assert current["status"] == "blocked"
    assert "runtime_session_not_enabled" in current["blockers"]
    assert current["broker_submission_enabled"] is False

    conflicting_preview = env["authority"].preview_revocation(
        session_id=issued["session_id"],
        reason_code="risk_review",
    )
    conflicting_approval = _approval(
        env,
        action="revoke_controlled_session",
        artifact_type="controlled_session_revocation",
        fingerprint=conflicting_preview["revocation_fingerprint"],
    )
    with pytest.raises(ControlledSessionRuntimeAuthorityRejected) as exc_info:
        env["authority"].revoke(
            session_id=issued["session_id"],
            reason_code="risk_review",
            revocation_fingerprint=conflicting_preview["revocation_fingerprint"],
            operator_approval_id=conflicting_approval["approval_id"],
            operator_proof_signature_base64=conflicting_approval[
                "proof_signature_base64"
            ],
            acknowledgement=CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
        )
    assert (
        "runtime_session_revocation_conflict"
        in exc_info.value.evidence["transaction_blockers"]
    )
    assert len(env["db"].list_controlled_session_revocations_sync()) == 1


def test_expiry_blocks_authentication_without_mutating_or_auto_renewing(
    tmp_path,
) -> None:
    current_time = [NOW]
    env = _environment(tmp_path, current_time=current_time)
    issued = _issue(env)

    current_time[0] = NOW + timedelta(minutes=10)
    expired = env["authority"].authenticate(issued["session_id"], TOKEN)

    assert expired["status"] == "blocked"
    assert "runtime_session_expired" in expired["blockers"]
    assert expired["automatic_resume_enabled"] is False
    row = env["db"].get_controlled_session_runtime_session_sync(issued["session_id"])
    assert row is not None and row["status"] == "enabled"
    assert env["db"].list_oms_orders_sync() == []
    assert env["db"].list_fills_sync() == []


def test_atomic_admission_rechecks_revocation_against_stale_authenticated_provider(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    stale_authenticated = env["authority"].authenticate(issued["session_id"], TOKEN)
    assert stale_authenticated["status"] == "current_enabled_bounded_session"

    preview = env["authority"].preview_revocation(
        session_id=issued["session_id"],
        reason_code="operational_concern",
    )
    approval = _approval(
        env,
        action="revoke_controlled_session",
        artifact_type="controlled_session_revocation",
        fingerprint=preview["revocation_fingerprint"],
    )
    env["authority"].revoke(
        session_id=issued["session_id"],
        reason_code="operational_concern",
        revocation_fingerprint=preview["revocation_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_REVOCATION_ACKNOWLEDGEMENT,
    )

    limiter = ControlledSessionRuntimeRateLimiterService(
        db=env["db"],
        session_provider=lambda session_id, session_token: stale_authenticated,
        clock=lambda: NOW,
    )
    with pytest.raises(ControlledSessionRateAdmissionRejected) as exc_info:
        limiter.admit(
            session_id=issued["session_id"],
            session_token=TOKEN,
            order_id="OMS-1",
            request_id="7" * 64,
        )

    assert (
        "runtime_session_not_enabled" in exc_info.value.evidence["transaction_blockers"]
    )
    assert env["db"].list_controlled_session_rate_admissions_sync() == []


def test_persisted_session_identity_drives_pause_and_blocks_token_authentication(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    gates = {
        "source_fingerprint": "8" * 64,
        "account_truth_status": "pass",
        "risk_gate_status": "passed",
        "reconciliation_status": "clear",
        "paper_shadow_status": "within_expectations",
        "gateway_health_status": "healthy",
        "market_data_status": "confirmed",
        "budget_status": "current_reserved_non_executing",
        "rate_limit_status": "clear",
        "kill_switch_enabled": True,
        "budget_exhausted": False,
        "daily_loss_limit_reached": False,
        "drawdown_limit_reached": False,
        "rejection_spike": False,
        "unexpected_account_change": False,
        "consecutive_errors": 0,
        "max_consecutive_errors": 2,
    }
    pause_service = ControlledSessionAutomaticPauseService(
        db=env["db"],
        session_provider=env["authority"].resolve_current,
        gate_provider=lambda session_id: gates,
        clock=lambda: NOW,
    )

    paused = pause_service.evaluate(session_id=issued["session_id"])
    authenticated = env["authority"].authenticate(issued["session_id"], TOKEN)

    assert paused["status"] == "paused"
    assert "kill_switch_enabled" in paused["reasons"]
    assert authenticated["status"] == "blocked"
    assert "runtime_session_paused" in authenticated["blockers"]
    assert authenticated["runtime_authority_enabled"] is False


def test_signed_replacement_atomically_retires_paused_session_and_returns_token_once(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    paused = _pause(env, issued)
    assert paused["status"] == "paused"

    env["clock"][0] = NOW + timedelta(seconds=1)
    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="2")
    reservation = _replacement_reservation(env)

    bypass = env["authority"].preview_issuance(
        reservation_id=reservation["reservation_id"]
    )
    assert (
        "runtime_session_paused_scope_requires_signed_replacement" in bypass["blockers"]
    )

    preview = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert preview["status"] == "ready_for_signed_replacement"
    assert preview["predecessor_will_be_revoked_atomically"] is True
    assert preview["required_operator_approval"] == {
        "action": "replace_paused_controlled_session",
        "artifact_type": "controlled_session_replacement",
        "artifact_fingerprint": preview["replacement_fingerprint"],
    }
    approval = _approval(
        env,
        action="replace_paused_controlled_session",
        artifact_type="controlled_session_replacement",
        fingerprint=preview["replacement_fingerprint"],
    )
    replaced = env["authority"].replace_paused(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
        replacement_fingerprint=preview["replacement_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
    )
    retry = env["authority"].replace_paused(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
        replacement_fingerprint=preview["replacement_fingerprint"],
        operator_approval_id=approval["approval_id"],
        operator_proof_signature_base64=approval["proof_signature_base64"],
        acknowledgement=CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
    )

    assert replaced["status"] == "enabled"
    assert replaced["session_id"] != issued["session_id"]
    assert replaced["session_token"] == REPLACEMENT_TOKEN
    assert replaced["session_token_issued"] is True
    assert replaced["broker_submission_enabled"] is False
    assert retry["reused"] is True
    assert retry["session_token"] == ""
    assert retry["session_token_issued"] is False
    replacement_row = env["db"].get_controlled_session_runtime_session_sync(
        replaced["session_id"]
    )
    assert replacement_row["token_hash"] != REPLACEMENT_TOKEN
    assert REPLACEMENT_TOKEN not in str(replacement_row)
    assert (
        env["db"].get_controlled_session_runtime_session_sync(issued["session_id"])[
            "status"
        ]
        == "revoked"
    )
    assert env["authority"].authenticate(issued["session_id"], TOKEN)["status"] == (
        "blocked"
    )
    assert (
        env["authority"].authenticate(replaced["session_id"], REPLACEMENT_TOKEN)[
            "runtime_authentication_verified"
        ]
        is True
    )
    assert len(env["authority"].list_replacements()) == 1
    assert any(
        item.get("reason_code") == "signed_replacement_after_pause_review"
        for item in env["authority"].list_revocations()
    )
    assert TOKEN not in str(env["authority"].list_replacements())
    assert REPLACEMENT_TOKEN not in str(env["authority"].list_replacements())
    assert env["db"].list_oms_orders_sync() == []
    assert env["db"].list_fills_sync() == []


def test_replacement_requires_stable_fresh_post_pause_clear_evidence(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    _pause(env, issued)
    env["clock"][0] = NOW + timedelta(seconds=1)
    reservation = _replacement_reservation(env)

    missing = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert (
        "runtime_session_replacement_recovery_snapshots_missing" in missing["blockers"]
    )

    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=30)
    _record_recovery_snapshot(env, issued, marker="2")
    unstable = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert "runtime_session_replacement_recovery_not_stable" in unstable["blockers"]

    env["clock"][0] = NOW + timedelta(seconds=31)
    _record_recovery_snapshot(env, issued, marker="3", status="blocked")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="4")
    interrupted = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert (
        "runtime_session_replacement_recovery_snapshots_missing"
        in interrupted["blockers"]
    )

    env["clock"][0] = NOW + timedelta(seconds=100)
    stale = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert "runtime_session_replacement_recovery_snapshot_stale" in stale["blockers"]
    assert env["authority"].list_replacements() == []


def test_replacement_transaction_rechecks_newer_blocked_snapshot(tmp_path) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    _pause(env, issued)
    env["clock"][0] = NOW + timedelta(seconds=1)
    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="2")
    reservation = _replacement_reservation(env)
    preview = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    approval = _approval(
        env,
        action="replace_paused_controlled_session",
        artifact_type="controlled_session_replacement",
        fingerprint=preview["replacement_fingerprint"],
    )

    env["clock"][0] = NOW + timedelta(seconds=62)
    _record_recovery_snapshot(env, issued, marker="3", status="blocked")
    env["authority"].preview_replacement = lambda **kwargs: preview
    with pytest.raises(ControlledSessionRuntimeAuthorityRejected) as exc_info:
        env["authority"].replace_paused(
            predecessor_session_id=issued["session_id"],
            reservation_id=reservation["reservation_id"],
            replacement_fingerprint=preview["replacement_fingerprint"],
            operator_approval_id=approval["approval_id"],
            operator_proof_signature_base64=approval["proof_signature_base64"],
            acknowledgement=CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
        )
    assert "runtime_session_replacement_recovery_snapshot_superseded" in (
        exc_info.value.evidence["transaction_blockers"]
    )
    assert env["authority"].list_replacements() == []
    assert (
        env["db"].get_controlled_session_runtime_session_sync(issued["session_id"])[
            "status"
        ]
        == "enabled"
    )


def test_replacement_rejects_wider_rate_and_wrong_operator_action(tmp_path) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    _pause(env, issued)
    env["clock"][0] = NOW + timedelta(seconds=1)
    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="2")
    reservation = _replacement_reservation(env, max_rate=3)
    widened = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )
    assert "runtime_session_replacement_rate_widened" in widened["blockers"]

    narrower = _replacement_reservation(
        env,
        attestation_id="c" * 64,
        envelope_fingerprint="d" * 64,
        gross="100",
        max_rate=1,
    )
    preview = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=narrower["reservation_id"],
    )
    wrong = _approval(
        env,
        action="issue_controlled_session",
        artifact_type="controlled_session_issuance",
        fingerprint=preview["replacement_fingerprint"],
    )
    with pytest.raises(ControlledSessionRuntimeAuthorityRejected) as exc_info:
        env["authority"].replace_paused(
            predecessor_session_id=issued["session_id"],
            reservation_id=narrower["reservation_id"],
            replacement_fingerprint=preview["replacement_fingerprint"],
            operator_approval_id=wrong["approval_id"],
            operator_proof_signature_base64=wrong["proof_signature_base64"],
            acknowledgement=CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
        )
    assert "runtime_session_replace_operator_approval_blocked" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert wrong["proof_signature_base64"] not in str(exc_info.value.evidence)
    assert env["authority"].list_replacements() == []


@pytest.mark.parametrize(
    ("replacement_kwargs", "expected_blocker"),
    [
        (
            {"gross": "700"},
            "runtime_session_replacement_budget_widened:reserved_gross_units",
        ),
        (
            {"order_ids": ["OMS-1", "OMS-2", "OMS-3"]},
            "runtime_session_replacement_order_scope_widened",
        ),
        (
            {
                "projected_by_symbol": {
                    "159915.SZ": "150",
                    "510300.SH": "150",
                }
            },
            "runtime_session_replacement_symbol_scope_widened",
        ),
        (
            {"duration_minutes": 11},
            "runtime_session_replacement_duration_widened",
        ),
    ],
)
def test_replacement_rejects_every_widening_dimension(
    tmp_path,
    replacement_kwargs: dict,
    expected_blocker: str,
) -> None:
    env = _environment(tmp_path, capacity="2000")
    issued = _issue(env)
    _pause(env, issued)
    env["clock"][0] = NOW + timedelta(seconds=1)
    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="2")
    reservation = _replacement_reservation(
        env,
        capacity="2000",
        **replacement_kwargs,
    )

    preview = env["authority"].preview_replacement(
        predecessor_session_id=issued["session_id"],
        reservation_id=reservation["reservation_id"],
    )

    assert expected_blocker in preview["blockers"]
    assert preview["ready"] is False
    assert env["authority"].list_replacements() == []


def test_concurrent_conflicting_replacements_allow_only_one_atomic_handoff(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    issued = _issue(env)
    _pause(env, issued)
    env["clock"][0] = NOW + timedelta(seconds=1)
    _record_recovery_snapshot(env, issued, marker="1")
    env["clock"][0] = NOW + timedelta(seconds=61)
    _record_recovery_snapshot(env, issued, marker="2")
    reservations = [
        _replacement_reservation(
            env,
            attestation_id=character * 64,
            envelope_fingerprint=fingerprint * 64,
            gross="100",
            max_rate=1,
        )
        for character, fingerprint in (("b", "e"), ("c", "f"))
    ]
    previews = [
        env["authority"].preview_replacement(
            predecessor_session_id=issued["session_id"],
            reservation_id=reservation["reservation_id"],
        )
        for reservation in reservations
    ]
    approvals = [
        _approval(
            env,
            action="replace_paused_controlled_session",
            artifact_type="controlled_session_replacement",
            fingerprint=preview["replacement_fingerprint"],
        )
        for preview in previews
    ]

    def replace(index: int) -> dict:
        return env["authority"].replace_paused(
            predecessor_session_id=issued["session_id"],
            reservation_id=reservations[index]["reservation_id"],
            replacement_fingerprint=previews[index]["replacement_fingerprint"],
            operator_approval_id=approvals[index]["approval_id"],
            operator_proof_signature_base64=approvals[index]["proof_signature_base64"],
            acknowledgement=CONTROLLED_SESSION_REPLACEMENT_ACKNOWLEDGEMENT,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(replace, index) for index in range(2)]
    successes = []
    failures = []
    for future in futures:
        try:
            successes.append(future.result())
        except ControlledSessionRuntimeAuthorityRejected as exc:
            failures.append(exc.evidence)

    assert len(successes) == 1
    assert len(failures) == 1
    assert len(env["authority"].list_replacements()) == 1
    assert len(env["db"].list_controlled_session_runtime_sessions_sync()) == 2
    assert env["db"].list_oms_orders_sync() == []
    assert env["db"].list_fills_sync() == []
