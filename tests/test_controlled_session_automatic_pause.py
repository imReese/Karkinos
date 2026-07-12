from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.services.controlled_session_automatic_pause import (
    CONTROLLED_SESSION_PAUSE_REJECTION_EVENT_TYPE,
    ControlledSessionAutomaticPauseRejected,
    ControlledSessionAutomaticPauseService,
)
from server.services.controlled_session_runtime_rate_limiter import (
    ControlledSessionRateAdmissionRejected,
    ControlledSessionRuntimeRateLimiterService,
)

NOW = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)


def _session(*, fingerprint: str = "a" * 64) -> dict:
    return {
        "status": "current_enabled_bounded_session",
        "session_id": "session-a",
        "session_fingerprint": fingerprint,
        "reservation_id": "b" * 64,
        "session_authority_verified": True,
        "budget_reservation_verified": True,
        "upstream_gates_clear": True,
        "kill_switch_clear": True,
        "runtime_rate_limiter_enabled": True,
        "authorization_id": "capital-auth-1",
        "account_alias": "中信证券88**16",
        "strategy_id": "strategy-1",
        "order_ids": ["OMS-1"],
        "effective_at": (NOW - timedelta(seconds=1)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
        "max_order_rate_per_minute": 2,
        "private_session_token": "must-not-leak",
        "broker_password": "must-not-leak",
    }


def _gates(**updates) -> dict:
    gates = {
        "source_fingerprint": "c" * 64,
        "account_truth_status": "pass",
        "risk_gate_status": "passed",
        "reconciliation_status": "clear",
        "paper_shadow_status": "within_expectations",
        "gateway_health_status": "healthy",
        "market_data_status": "confirmed",
        "budget_status": "current_reserved_non_executing",
        "rate_limit_status": "clear",
        "kill_switch_enabled": False,
        "budget_exhausted": False,
        "daily_loss_limit_reached": False,
        "drawdown_limit_reached": False,
        "rejection_spike": False,
        "unexpected_account_change": False,
        "consecutive_errors": 0,
        "max_consecutive_errors": 2,
        "broker_token": "must-not-leak",
    }
    gates.update(updates)
    return gates


def _service(tmp_path, *, session=None, gates=None):
    db = AppDatabase(tmp_path / "controlled-session-pause.db")
    db.init_sync()
    current_session = session or _session()
    current_gates = gates or _gates()
    return db, ControlledSessionAutomaticPauseService(
        db=db,
        session_provider=lambda session_id: current_session,
        gate_provider=lambda session_id: current_gates,
        clock=lambda: NOW,
    )


def test_automatic_pause_is_default_closed_and_rejection_is_audited(tmp_path) -> None:
    db = AppDatabase(tmp_path / "closed-pause.db")
    db.init_sync()
    service = ControlledSessionAutomaticPauseService(db=db, clock=lambda: NOW)

    assert service.get_status()["automatic_pause_enabled"] is False
    assert service.get_status()["public_pause_endpoint_exposed"] is False
    with pytest.raises(ControlledSessionAutomaticPauseRejected) as exc_info:
        service.evaluate(session_id="session-a")

    evidence = exc_info.value.evidence
    assert "automatic_pause_session_provider_unavailable" in evidence["blockers"]
    assert evidence["pause_applied"] is False
    assert "must-not-leak" not in str(evidence)
    assert db.get_controlled_session_runtime_state_sync("session-a") is None
    events = db.list_events_sync(
        event_type=CONTROLLED_SESSION_PAUSE_REJECTION_EVENT_TYPE,
        limit=10,
    )
    assert len(events) == 1


def test_clear_gates_are_deterministic_sanitized_and_side_effect_free(tmp_path) -> None:
    db, service = _service(tmp_path)

    first = service.preview(session_id="session-a")
    second = service.evaluate(session_id="session-a")

    assert (
        first["pause_event_id"]
        == service.preview(session_id="session-a")["pause_event_id"]
    )
    assert first["status"] == "clear_no_pause"
    assert second["pause_applied"] is False
    assert "must-not-leak" not in str(first)
    assert db.get_controlled_session_runtime_state_sync("session-a") is None
    assert db.list_controlled_session_pause_events_sync() == []


@pytest.mark.parametrize(
    ("updates", "expected_reason"),
    [
        ({"source_fingerprint": "bad"}, "gate_source_fingerprint_invalid"),
        ({"account_truth_status": "stale"}, "account_truth_not_clear"),
        ({"risk_gate_status": "blocked"}, "risk_gate_not_clear"),
        ({"reconciliation_status": "open"}, "reconciliation_not_clear"),
        ({"paper_shadow_status": "diverged"}, "paper_shadow_divergence_not_clear"),
        ({"gateway_health_status": "degraded"}, "gateway_health_degraded"),
        ({"market_data_status": "stale"}, "market_data_not_current"),
        ({"budget_status": "unknown"}, "budget_not_current"),
        ({"rate_limit_status": "blocked"}, "rate_limit_not_clear"),
        ({"kill_switch_enabled": True}, "kill_switch_enabled"),
        ({"budget_exhausted": True}, "budget_exhausted"),
        ({"daily_loss_limit_reached": True}, "daily_loss_limit_reached"),
        ({"drawdown_limit_reached": True}, "drawdown_limit_reached"),
        ({"rejection_spike": True}, "rejection_spike"),
        ({"unexpected_account_change": True}, "unexpected_account_change"),
        ({"consecutive_errors": 2}, "consecutive_error_limit_reached"),
    ],
)
def test_each_hard_gate_persists_a_one_way_pause(
    tmp_path,
    updates: dict,
    expected_reason: str,
) -> None:
    db, service = _service(tmp_path, gates=_gates(**updates))

    result = service.evaluate(session_id="session-a")

    assert result["status"] == "paused"
    assert result["pause_applied"] is True
    assert expected_reason in result["reasons"]
    assert result["automatic_resume_enabled"] is False
    assert result["authorizes_broker_submission"] is False
    state = db.get_controlled_session_runtime_state_sync("session-a")
    assert state is not None and state["status"] == "paused"


def test_pause_is_idempotent_concurrent_and_never_auto_resumes(tmp_path) -> None:
    db, service = _service(tmp_path, gates=_gates(kill_switch_enabled=True))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: service.evaluate(session_id="session-a"),
                range(2),
            )
        )

    assert len(db.list_controlled_session_pause_events_sync()) == 1
    assert sorted(result["reused"] for result in results) == [False, True]

    service._gate_provider = lambda session_id: _gates()
    after_clear = service.evaluate(session_id="session-a")
    assert after_clear["status"] == "paused"
    assert after_clear["reused"] is True
    assert after_clear["reasons"] == ["kill_switch_enabled"]
    assert service.get_state("session-a")["status"] == "paused"
    assert len(db.list_controlled_session_pause_events_sync()) == 1


def test_paused_state_rejects_identity_drift_and_runtime_admission(tmp_path) -> None:
    db, pause_service = _service(
        tmp_path,
        gates=_gates(unexpected_account_change=True),
    )
    paused = pause_service.evaluate(session_id="session-a")

    conflicting = ControlledSessionAutomaticPauseService(
        db=db,
        session_provider=lambda session_id: _session(fingerprint="d" * 64),
        gate_provider=lambda session_id: _gates(),
        clock=lambda: NOW,
    )
    with pytest.raises(ControlledSessionAutomaticPauseRejected) as exc_info:
        conflicting.evaluate(session_id="session-a")
    assert (
        "automatic_pause_session_identity_conflict"
        in exc_info.value.evidence["blockers"]
    )

    rate_limiter = ControlledSessionRuntimeRateLimiterService(
        db=db,
        session_provider=lambda session_id: _session(),
        clock=lambda: NOW,
    )
    with pytest.raises(ControlledSessionRateAdmissionRejected) as rate_exc:
        rate_limiter.admit(
            session_id="session-a",
            order_id="OMS-1",
            request_id="1" * 64,
        )
    assert "runtime_session_paused" in rate_exc.value.evidence["review_blockers"]
    assert rate_exc.value.evidence["pause_event_id"] == paused["pause_event_id"]
    assert db.list_controlled_session_rate_admissions_sync() == []


def test_gate_provider_failure_pauses_identified_session_without_secret_leak(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "failed-provider-pause.db")
    db.init_sync()

    def fail(_session_id: str) -> dict:
        raise RuntimeError("broker_password=must-not-leak")

    service = ControlledSessionAutomaticPauseService(
        db=db,
        session_provider=lambda session_id: _session(),
        gate_provider=fail,
        clock=lambda: NOW,
    )

    result = service.evaluate(session_id="session-a")

    assert "gate_provider_unavailable" in result["reasons"]
    assert "must-not-leak" not in str(result)
    assert result["authorizes_broker_submission"] is False
