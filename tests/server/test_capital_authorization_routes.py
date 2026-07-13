from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import TrustedOperatorIdentityConfig
from server.db import AppDatabase
from server.routes.capital_authorization import create_router
from server.services.capital_authorization_audit import (
    CAPITAL_AUTHORIZATION_EVENT_TYPE,
)
from tests.route_assertions import registered_app_routes


def _client_for_db(monkeypatch, db: AppDatabase, *, config=None) -> TestClient:
    fake_state = SimpleNamespace(db=db, config=config)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _evaluation_payload() -> dict:
    now = datetime(2026, 7, 10, 9, 30, tzinfo=timezone.utc)
    return {
        "policy": {
            "authorization_id": "auth-route-001",
            "policy_version": "owner-policy-v1",
            "mode": "manual_each_order",
            "enabled": True,
            "authorized_by": "owner",
            "connector_ids": ["broker-1"],
            "evidence_connector_ids": ["broker-readonly-1"],
            "execution_gateway_ids": ["broker-execution-1"],
            "account_aliases": ["primary"],
            "strategy_ids": ["etf-rotation"],
            "symbols": ["510300.SH"],
            "effective_at": (now - timedelta(minutes=1)).isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
            "limits": {
                "max_authorized_capital": "50000",
                "max_order_value": "10000",
                "max_position_change_value": "10000",
                "max_daily_turnover": "30000",
                "max_daily_loss": "1000",
                "max_drawdown_pct": "0.05",
                "max_order_rate_per_minute": 2,
                "max_consecutive_errors": 2,
            },
            "evidence_refs": ["operator_authorization:auth-route-001"],
        },
        "context": {
            "now": now.isoformat(),
            "connector_id": "broker-1",
            "account_alias": "primary",
            "strategy_id": "etf-rotation",
            "symbol": "510300.SH",
            "order_value": "8000",
            "position_change_value": "8000",
            "current_authorized_exposure": "10000",
            "daily_turnover_used": "5000",
            "current_daily_loss": "100",
            "current_drawdown_pct": "0.01",
            "order_rate_per_minute": 0,
            "consecutive_errors": 0,
            "available_cash": "100000",
            "account_capital_limit": "60000",
            "strategy_capital_limit": "40000",
            "symbol_capital_limit": "30000",
            "liquidity_capital_limit": "25000",
            "market_data_status": "confirmed",
            "account_truth_status": "pass",
            "risk_gate_status": "passed",
            "paper_shadow_status": "within_expectations",
            "reconciliation_status": "clear",
            "connector_health_status": "healthy",
            "connector_can_submit": True,
            "kill_switch_enabled": False,
            "order_fingerprint": "order-fingerprint-1",
            "manual_confirmation_fingerprint": "order-fingerprint-1",
            "evidence_refs": ["risk:risk-001", "reconciliation:recon-001"],
            "evidence_connector_id": "broker-readonly-1",
            "execution_gateway_id": "broker-execution-1",
            "evidence_connector_health_status": "healthy",
            "evidence_connector_can_submit": False,
            "execution_gateway_health_status": "healthy",
            "execution_gateway_can_submit": True,
            "connector_account_binding_status": "verified",
        },
    }


def test_capital_authority_preview_is_read_only(tmp_path, monkeypatch) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/automation/capital-authority/preview",
        json=_evaluation_payload(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["allowed"] is True
    assert payload["persisted"] is False
    assert payload["does_not_enable_execution"] is True
    assert payload["runtime_authority_status"] == "disabled"
    assert payload["operator_identity_verified"] is False
    assert db.list_events_sync(event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE) == []


def test_capital_authority_evaluation_audit_and_status_remain_disabled(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    first = client.post(
        "/api/automation/capital-authority/evaluations",
        json=_evaluation_payload(),
    )
    rerun = client.post(
        "/api/automation/capital-authority/evaluations",
        json=_evaluation_payload(),
    )
    listing = client.get("/api/automation/capital-authority/evaluations")
    status = client.get("/api/automation/capital-authority/status")

    assert first.status_code == 200
    assert first.json()["persisted"] is True
    assert first.json()["reused"] is False
    assert rerun.status_code == 200
    assert rerun.json()["evaluation_id"] == first.json()["evaluation_id"]
    assert rerun.json()["reused"] is True
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert status.status_code == 200
    assert status.json()["runtime_authority_status"] == "disabled"
    assert status.json()["execution_authority_enabled"] is False
    assert status.json()["broker_submission_enabled"] is False


def test_capital_authority_payload_rejects_credential_fields(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    payload = _evaluation_payload()
    payload["policy"]["broker_password"] = "must-not-be-accepted"

    response = client.post(
        "/api/automation/capital-authority/evaluations",
        json=payload,
    )

    assert response.status_code == 422
    assert db.list_events_sync(event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE) == []


def test_capital_authority_v2_requires_dual_connector_identity_fields(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    payload = _evaluation_payload()
    del payload["context"]["execution_gateway_id"]
    del payload["context"]["connector_account_binding_status"]

    response = client.post(
        "/api/automation/capital-authority/evaluations",
        json=payload,
    )

    assert response.status_code == 422
    assert db.list_events_sync(event_type=CAPITAL_AUTHORIZATION_EVENT_TYPE) == []


def test_operator_approval_routes_challenge_verify_and_list_without_authority(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    config = SimpleNamespace(
        trusted_operator_identities=[
            TrustedOperatorIdentityConfig(
                operator_id="local-owner",
                key_id="owner-key-1",
                public_key_base64=base64.b64encode(public_key).decode("ascii"),
                enabled=True,
            )
        ]
    )
    client = _client_for_db(monkeypatch, db, config=config)
    challenge_request = {
        "operator_id": "local-owner",
        "key_id": "owner-key-1",
        "action": "attest_per_order_dossier",
        "artifact_type": "per_order_dossier",
        "artifact_fingerprint": "a" * 64,
        "ttl_seconds": 180,
    }

    status = client.get("/api/automation/capital-authority/operator-approvals/status")
    challenge = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json=challenge_request,
    )
    challenge_payload = challenge.json()
    signature = private_key.sign(
        base64.b64decode(challenge_payload["signing_payload_base64"])
    )
    verified = client.post(
        "/api/automation/capital-authority/operator-approvals/verifications",
        json={
            "challenge_id": challenge_payload["challenge_id"],
            "signature_base64": base64.b64encode(signature).decode("ascii"),
        },
    )
    approvals = client.get(
        "/api/automation/capital-authority/operator-approvals?limit=10"
    )
    promotion_challenge = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json={
            **challenge_request,
            "action": "accept_broker_connector_soak_promotion",
            "artifact_type": "broker_connector_soak_promotion_dossier",
            "artifact_fingerprint": "b" * 64,
        },
    )
    issuance_challenge = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json={
            **challenge_request,
            "action": "issue_controlled_session",
            "artifact_type": "controlled_session_issuance",
            "artifact_fingerprint": "c" * 64,
        },
    )
    revocation_challenge = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json={
            **challenge_request,
            "action": "revoke_controlled_session",
            "artifact_type": "controlled_session_revocation",
            "artifact_fingerprint": "d" * 64,
        },
    )

    assert status.status_code == 200
    assert status.json()["enabled_identity_count"] == 1
    assert status.json()["private_key_storage_enabled"] is False
    assert (
        "accept_broker_connector_soak_promotion" in status.json()["supported_actions"]
    )
    assert "issue_controlled_session" in status.json()["supported_actions"]
    assert "replace_paused_controlled_session" in status.json()["supported_actions"]
    assert "revoke_controlled_session" in status.json()["supported_actions"]
    assert challenge.status_code == 200
    assert challenge_payload["authorizes_execution"] is False
    assert verified.status_code == 200
    assert verified.json()["operator_identity_verified"] is True
    assert verified.json()["authorizes_execution"] is False
    assert "signature_base64" not in verified.json()
    assert approvals.status_code == 200
    assert approvals.json()[0]["approval_id"] == challenge_payload["challenge_id"]
    assert "signature_base64" not in approvals.json()[0]
    assert promotion_challenge.status_code == 200
    assert promotion_challenge.json()["artifact_type"] == (
        "broker_connector_soak_promotion_dossier"
    )
    assert issuance_challenge.status_code == 200
    assert issuance_challenge.json()["artifact_type"] == ("controlled_session_issuance")
    assert revocation_challenge.status_code == 200
    assert revocation_challenge.json()["artifact_type"] == (
        "controlled_session_revocation"
    )


def test_operator_approval_routes_reject_credentials_and_bad_signature(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "capital-authority.db")
    db.init_sync()
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    config = SimpleNamespace(
        trusted_operator_identities=[
            TrustedOperatorIdentityConfig(
                operator_id="local-owner",
                key_id="owner-key-1",
                public_key_base64=base64.b64encode(public_key).decode("ascii"),
                enabled=True,
            )
        ]
    )
    client = _client_for_db(monkeypatch, db, config=config)
    request = {
        "operator_id": "local-owner",
        "key_id": "owner-key-1",
        "action": "attest_per_order_dossier",
        "artifact_type": "per_order_dossier",
        "artifact_fingerprint": "a" * 64,
    }

    credential = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json={**request, "private_key": "must-not-be-accepted"},
    )
    challenge = client.post(
        "/api/automation/capital-authority/operator-approvals/challenges",
        json=request,
    ).json()
    bad_signature = client.post(
        "/api/automation/capital-authority/operator-approvals/verifications",
        json={
            "challenge_id": challenge["challenge_id"],
            "signature_base64": base64.b64encode(b"0" * 64).decode("ascii"),
        },
    )

    assert credential.status_code == 422
    assert bad_signature.status_code == 409
    assert bad_signature.json()["detail"]["operator_identity_verified"] is False
    assert bad_signature.json()["detail"]["authorizes_execution"] is False


def test_create_app_registers_capital_authority_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/capital-authority/status" in paths
    assert "/api/automation/capital-authority/preview" in paths
    assert "/api/automation/capital-authority/evaluations" in paths
    assert "/api/automation/capital-authority/operator-approvals/status" in paths
    assert "/api/automation/capital-authority/operator-approvals/challenges" in paths
    assert "/api/automation/capital-authority/operator-approvals/verifications" in paths
    assert "/api/automation/capital-authority/operator-approvals" in paths
