from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.services.controlled_session_automatic_pause import (
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_live_gates import (
    CONTROLLED_SESSION_LIVE_GATE_REJECTION_EVENT_TYPE,
    ControlledSessionAutomaticPauseOrchestratorService,
    ControlledSessionLiveGateRejected,
    ControlledSessionLiveGateSnapshotService,
)
from server.services.controlled_session_runtime_authority import (
    ControlledSessionRuntimeAuthorityService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
)
from server.services.trading_controls import (
    AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    TradingControlState,
)

NOW = datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc)
SESSION_ID = "a" * 64
SESSION_FINGERPRINT = "b" * 64
RESERVATION_ID = "c" * 64
ATTESTATION_ID = "d" * 64
ENVELOPE_FINGERPRINT = "e" * 64
TOKEN = "live-gate-token-00000000000000000000000000001"
SALT = "ab" * 16


def _attestation() -> dict:
    return {
        "status": "current_verified_non_executing",
        "attestation_id": ATTESTATION_ID,
        "envelope_fingerprint": ENVELOPE_FINGERPRINT,
        "current_envelope": {
            "orders": [
                {
                    "order_id": "OMS-1",
                    "symbol": "510300.SH",
                    "instrument_type": "etf",
                    "gateway_gates": {
                        "status": "pass",
                        "gates": {
                            "risk": {
                                "status": "pass",
                                "evidence_ref": "risk:decision-1",
                            },
                            "paper_shadow": {
                                "status": "pass",
                                "evidence_ref": "paper_shadow:run-1",
                            },
                        },
                    },
                }
            ],
            "capital_evaluation": {
                "effective_limits": {"max_consecutive_errors": 3},
                "remaining_budget": {
                    "daily_loss": "100",
                    "drawdown_pct": "0.10",
                },
            },
            "session_start_account_truth": {
                "status": "pass",
                "account_truth_fingerprint": "1" * 64,
            },
            "prior_execution_reconciliation": {
                "status": "pass",
                "batch_reconciliation_fingerprint": "2" * 64,
            },
            "execution_gateway": {
                "runtime_gateway_verified": True,
            },
            "execution_gateway_verifications": [
                {
                    "status": "pass",
                    "verification_fingerprint": "3" * 64,
                }
            ],
        },
        "blockers": [],
    }


def _persist_session(db: AppDatabase) -> None:
    start = NOW - timedelta(seconds=1)
    expires = NOW + timedelta(minutes=10)
    reservation = db.reserve_controlled_session_budget_sync(
        reservation={
            "reservation_id": RESERVATION_ID,
            "attestation_id": ATTESTATION_ID,
            "envelope_fingerprint": ENVELOPE_FINGERPRINT,
            "capital_evaluation_input_fingerprint": "4" * 64,
            "authorization_id": "capital-auth-1",
            "policy_version": "policy-v1",
            "account_alias": "中信证券88**16",
            "strategy_id": "strategy-1",
            "trading_day": "2026-07-12",
            "requested_start_at": start.isoformat(),
            "requested_expires_at": expires.isoformat(),
            "reserved_gross_units": 100,
            "reserved_buy_units": 100,
            "reserved_turnover_units": 100,
            "reserved_order_count": 2,
            "capital_capacity_units": 1_000_000,
            "cash_capacity_units": 1_000_000,
            "turnover_capacity_units": 1_000_000,
            "order_count_capacity": 10,
            "reserved_by_symbol_units": {"510300.SH": 100},
            "symbol_capacity_units": {"510300.SH": 1_000_000},
            "payload": {},
            "created_at": NOW.isoformat(),
        }
    )
    assert reservation["status"] == "reserved"
    issued = db.issue_controlled_session_sync(
        session={
            "session_id": SESSION_ID,
            "session_fingerprint": SESSION_FINGERPRINT,
            "issuance_fingerprint": "5" * 64,
            "reservation_id": RESERVATION_ID,
            "attestation_id": ATTESTATION_ID,
            "envelope_fingerprint": ENVELOPE_FINGERPRINT,
            "authorization_id": "capital-auth-1",
            "account_alias": "中信证券88**16",
            "strategy_id": "strategy-1",
            "operator_id": "local-owner",
            "operator_approval_id": "6" * 64,
            "order_ids": ["OMS-1", "OMS-2"],
            "requested_start_at": start.isoformat(),
            "requested_expires_at": expires.isoformat(),
            "effective_at_epoch_ms": int(start.timestamp() * 1000),
            "expires_at_epoch_ms": int(expires.timestamp() * 1000),
            "max_order_rate_per_minute": 2,
            "token_salt": SALT,
            "token_hash": hashlib.sha256(f"{SALT}:{TOKEN}".encode()).hexdigest(),
            "payload": {},
            "created_at": NOW.isoformat(),
        }
    )
    assert issued["status"] == "enabled"
    db.upsert_latest_quote_sync(
        symbol="510300.SH",
        asset_type="etf",
        price=4.0,
        quote_timestamp=NOW.isoformat(),
        quote_source="synthetic-test",
        provider_name="synthetic-test",
        provider_status="live",
        quote_status="live",
        captured_at=NOW.isoformat(),
    )


def _environment(tmp_path, *, automatic_ttl_seconds: int = 600):
    db = AppDatabase(tmp_path / "controlled-session-live-gates.db")
    db.init_sync()
    current_time = [NOW]
    attestations = {ATTESTATION_ID: _attestation()}
    reservations = {
        RESERVATION_ID: {
            "resolution_status": "current_reserved_non_executing",
            "reservation_id": RESERVATION_ID,
            "attestation_id": ATTESTATION_ID,
            "envelope_fingerprint": ENVELOPE_FINGERPRINT,
            "authorization_id": "capital-auth-1",
            "account_alias": "中信证券88**16",
            "strategy_id": "strategy-1",
        }
    }
    controls = TradingControlState(
        db=db,
        clock=lambda: current_time[0] - timedelta(seconds=1),
    )
    automatic_trading = controls.set_automatic_trading(
        enabled=True,
        reason="bounded session test",
        operator_id="test-owner",
        expected_revision=0,
        ttl_seconds=automatic_ttl_seconds,
        acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    )
    assert automatic_trading["status"] == "enabled"
    _persist_session(db)
    authority = ControlledSessionRuntimeAuthorityService(
        db=db,
        reservation_provider=lambda value: reservations.get(value, {}),
        attestation_provider=lambda value: attestations.get(value, {}),
        clock=lambda: current_time[0],
    )
    live_gates = ControlledSessionLiveGateSnapshotService(
        db=db,
        session_monitor_provider=authority.resolve_for_monitoring,
        reservation_provider=lambda value: reservations.get(value, {}),
        attestation_provider=lambda value: attestations.get(value, {}),
        trading_controls=controls,
        clock=lambda: current_time[0],
    )
    automatic_pause = ControlledSessionAutomaticPauseService(
        db=db,
        session_provider=authority.resolve_for_monitoring,
        gate_provider=live_gates.resolve_gate_snapshot,
        clock=lambda: current_time[0],
    )
    orchestrator = ControlledSessionAutomaticPauseOrchestratorService(
        runtime_authority=authority,
        live_gates=live_gates,
        automatic_pause=automatic_pause,
    )
    return {
        "db": db,
        "clock": current_time,
        "attestations": attestations,
        "reservations": reservations,
        "controls": controls,
        "authority": authority,
        "live_gates": live_gates,
        "automatic_pause": automatic_pause,
        "orchestrator": orchestrator,
    }


def _record_admission(db: AppDatabase, index: int) -> None:
    observed = NOW - timedelta(milliseconds=2 - index)
    gate_snapshot = db.latest_controlled_session_gate_snapshot_sync(SESSION_ID)
    assert gate_snapshot is not None
    gate_values = json.loads(gate_snapshot["gate_snapshot_json"])
    result = db.admit_controlled_session_order_sync(
        admission={
            "admission_id": str(index + 7) * 64,
            "session_id": SESSION_ID,
            "session_fingerprint": SESSION_FINGERPRINT,
            "reservation_id": RESERVATION_ID,
            "authorization_id": "capital-auth-1",
            "account_alias": "中信证券88**16",
            "strategy_id": "strategy-1",
            "order_id": f"OMS-{index + 1}",
            "request_id": str(index + 1) * 64,
            "gate_snapshot_id": gate_snapshot["snapshot_id"],
            "gate_snapshot_fingerprint": gate_snapshot["snapshot_fingerprint"],
            "gate_snapshot_observed_at": gate_snapshot["observed_at"],
            "gate_snapshot_max_age_seconds": 30,
            "automatic_trading_revision": gate_values["automatic_trading_revision"],
            "automatic_trading_control_fingerprint": gate_values[
                "automatic_trading_control_fingerprint"
            ],
            "max_order_rate_per_minute": 2,
            "admitted_at_epoch_ms": int(observed.timestamp() * 1000),
            "admitted_at": observed.isoformat(),
            "payload": {},
            "created_at": observed.isoformat(),
        }
    )
    assert result["status"] == "admitted"


def test_clear_snapshot_is_persisted_sanitized_and_idempotent(tmp_path) -> None:
    env = _environment(tmp_path)

    first = env["live_gates"].capture(session_id=SESSION_ID)
    retry = env["live_gates"].capture(session_id=SESSION_ID)

    assert first["status"] == "clear"
    assert first["gate_snapshot"]["market_data_status"] == "current"
    assert first["gate_snapshot"]["kill_switch_enabled"] is False
    assert first["gate_snapshot"]["automatic_trading_enabled"] is True
    assert first["gate_snapshot"]["automatic_trading_revision"] == 1
    assert first["gate_snapshot"]["budget_exhausted"] is False
    assert retry["database_id"] == first["database_id"]
    assert retry["reused"] is True
    assert "token" not in str(first).lower()
    assert len(env["db"].list_controlled_session_gate_snapshots_sync()) == 1
    status = env["live_gates"].get_status()
    assert status["automatic_trading_provider_configured"] is True
    assert status["automatic_trading_effective_enabled"] is True
    assert status["automatic_trading_gate"]["status"] == "enabled"
    evaluation = env["orchestrator"].evaluate(session_id=SESSION_ID)
    assert evaluation["status"] == "clear_no_pause"
    assert env["db"].get_controlled_session_runtime_state_sync(SESSION_ID) is None


def test_source_drift_still_identifies_and_pauses_persisted_session(tmp_path) -> None:
    env = _environment(tmp_path)
    env["attestations"][ATTESTATION_ID] = {
        "status": "blocked",
        "blockers": ["account_truth_source_changed"],
    }

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    assert result["status"] == "paused"
    gates = result["gate_snapshot"]["gate_snapshot"]
    assert gates["unexpected_account_change"] is True
    assert result["pause_evaluation"]["pause_applied"] is True
    assert "account_truth_not_clear" in result["pause_evaluation"]["reasons"]
    assert env["authority"].resolve_current(SESSION_ID)["status"] == "blocked"


@pytest.mark.parametrize("failure", ["stale_market", "kill_switch"])
def test_stale_market_or_kill_switch_triggers_durable_pause(
    tmp_path,
    failure: str,
) -> None:
    env = _environment(tmp_path)
    if failure == "stale_market":
        env["clock"][0] = NOW + timedelta(seconds=121)
    else:
        env["controls"].set_kill_switch(True, "operator emergency stop")

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    assert result["status"] == "paused"
    reasons = result["pause_evaluation"]["reasons"]
    assert (
        "market_data_not_current" in reasons
        if failure == "stale_market"
        else "kill_switch_enabled" in reasons
    )
    assert result["broker_submission_enabled"] is False


def test_automatic_trading_disable_blocks_and_durably_pauses_session(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    disabled = env["controls"].set_automatic_trading(
        enabled=False,
        reason="operator disabled unattended admission",
        operator_id="test-owner",
        expected_revision=1,
        acknowledgement=AUTOMATIC_TRADING_DISABLE_ACKNOWLEDGEMENT,
    )

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    assert disabled["status"] == "disabled"
    assert result["gate_snapshot"]["status"] == "blocked"
    assert "automatic_trading_disabled" in result["gate_snapshot"]["blockers"]
    assert "automatic_trading_disabled" in result["pause_evaluation"]["reasons"]
    assert result["pause_evaluation"]["pause_applied"] is True
    assert env["live_gates"].get_status()["contract_status"] == (
        "blocked_by_automatic_trading_control"
    )

    reenabled = env["controls"].set_automatic_trading(
        enabled=True,
        reason="new operator review",
        operator_id="test-owner",
        expected_revision=2,
        ttl_seconds=600,
        acknowledgement=AUTOMATIC_TRADING_ENABLE_ACKNOWLEDGEMENT,
    )
    after_reenable = env["orchestrator"].evaluate(session_id=SESSION_ID)

    assert reenabled["status"] == "enabled"
    assert after_reenable["status"] == "paused"
    assert after_reenable["pause_evaluation"]["reused"] is True
    assert env["automatic_pause"].get_state(SESSION_ID)["status"] == "paused"


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_blocker"),
    [
        (
            "expired",
            "expired",
            "automatic_trading_control_expired",
        ),
        (
            "unavailable",
            "unavailable",
            "automatic_trading_status_unavailable",
        ),
    ],
)
def test_expired_or_unavailable_automatic_trading_gate_blocks_and_pauses(
    tmp_path,
    failure: str,
    expected_status: str,
    expected_blocker: str,
) -> None:
    env = _environment(
        tmp_path,
        automatic_ttl_seconds=60 if failure == "expired" else 600,
    )
    if failure == "expired":
        env["clock"][0] = NOW + timedelta(seconds=60)
    else:
        env["live_gates"]._trading_controls = object()

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    gates = result["gate_snapshot"]["gate_snapshot"]
    assert result["gate_snapshot"]["status"] == "blocked"
    assert gates["automatic_trading_status"] == expected_status
    assert expected_blocker in result["gate_snapshot"]["blockers"]
    assert expected_blocker in result["pause_evaluation"]["reasons"]
    assert result["pause_evaluation"]["pause_applied"] is True
    assert result["broker_submission_enabled"] is False


def test_rate_and_order_budget_exhaustion_pause_before_another_admission(
    tmp_path,
) -> None:
    env = _environment(tmp_path)
    gate_observed_at = NOW - timedelta(milliseconds=3)
    automatic_trading = env["controls"].automatic_trading_snapshot(now=NOW)
    gate_values = {
        "fixture_gate_status": "clear",
        "automatic_trading_status": automatic_trading["status"],
        "automatic_trading_configured_enabled": automatic_trading["configured_enabled"],
        "automatic_trading_enabled": automatic_trading["enabled"],
        "automatic_trading_revision": automatic_trading["revision"],
        "automatic_trading_control_fingerprint": automatic_trading[
            "control_fingerprint"
        ],
        "automatic_trading_blockers": automatic_trading["blockers"],
    }
    first_gate = env["db"].record_controlled_session_gate_snapshot_sync(
        snapshot={
            "snapshot_id": "7" * 64,
            "snapshot_fingerprint": "8" * 64,
            "session_id": SESSION_ID,
            "session_fingerprint": SESSION_FINGERPRINT,
            "source_fingerprint": "9" * 64,
            "observed_at_epoch_ms": int(gate_observed_at.timestamp() * 1000),
            "observed_at": gate_observed_at.isoformat(),
            "status": "clear",
            "gate_snapshot": gate_values,
            "source_evidence": {"fixture": True},
            "blockers": [],
            "payload": {
                "status": "clear",
                "gate_snapshot": gate_values,
                "broker_submission_enabled": False,
            },
            "created_at": gate_observed_at.isoformat(),
        }
    )
    assert first_gate["status"] == "clear"
    _record_admission(env["db"], 0)
    _record_admission(env["db"], 1)

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    gates = result["gate_snapshot"]["gate_snapshot"]
    assert gates["rate_limit_status"] == "reached"
    assert gates["budget_exhausted"] is True
    assert "budget_exhausted" in result["pause_evaluation"]["reasons"]
    assert "rate_limit_not_clear" in result["pause_evaluation"]["reasons"]


def test_rejection_spike_and_consecutive_errors_pause(tmp_path) -> None:
    env = _environment(tmp_path)
    for index in range(3):
        timestamp = NOW - timedelta(milliseconds=3 - index)
        env["db"].append_event_sync(
            event_type=CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
            timestamp=timestamp.isoformat(),
            entity_type="controlled_session_rate_admission",
            entity_id=str(index + 1) * 64,
            source="controlled_session_runtime_rate_limiter",
            source_ref="",
            payload={"session_id": SESSION_ID, "status": "rejected"},
        )

    result = env["orchestrator"].evaluate(session_id=SESSION_ID)

    gates = result["gate_snapshot"]["gate_snapshot"]
    assert gates["rejection_spike"] is True
    assert gates["consecutive_errors"] == 3
    assert "rejection_spike" in result["pause_evaluation"]["reasons"]
    assert "consecutive_error_limit_reached" in (result["pause_evaluation"]["reasons"])


def test_snapshot_freshness_and_authenticated_self_check(tmp_path) -> None:
    env = _environment(tmp_path)
    snapshot = env["live_gates"].capture(session_id=SESSION_ID)
    assert env["live_gates"].latest(SESSION_ID)["resolution_status"] == "current"
    env["clock"][0] = NOW + timedelta(seconds=31)
    assert env["live_gates"].latest(SESSION_ID)["resolution_status"] == "stale"

    with pytest.raises(ControlledSessionLiveGateRejected):
        env["orchestrator"].evaluate_authenticated(
            session_id=SESSION_ID,
            session_token="wrong-live-gate-token-0000000000000000000001",
        )
    authenticated = env["orchestrator"].evaluate_authenticated(
        session_id=SESSION_ID,
        session_token=TOKEN,
    )
    assert authenticated["session_id"] == SESSION_ID
    assert snapshot["broker_submission_enabled"] is False


def test_missing_monitoring_identity_is_rejected_and_audited(tmp_path) -> None:
    env = _environment(tmp_path)

    with pytest.raises(ControlledSessionLiveGateRejected):
        env["live_gates"].capture(session_id="f" * 64)

    events = env["db"].list_events_sync(
        event_type=CONTROLLED_SESSION_LIVE_GATE_REJECTION_EVENT_TYPE,
        limit=10,
    )
    assert len(events) == 1
    assert env["db"].list_oms_orders_sync() == []
    assert env["db"].list_fills_sync() == []
