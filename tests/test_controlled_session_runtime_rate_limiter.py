from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from server.db import AppDatabase
from server.services.controlled_session_runtime_rate_limiter import (
    CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE,
    ControlledSessionRateAdmissionRejected,
    ControlledSessionRuntimeRateLimiterService,
)

NOW = datetime(2026, 7, 12, 6, 0, tzinfo=timezone.utc)
SESSION_TOKEN = "runtime-rate-token-000000000000000000000000001"


def _session(
    session_id: str,
    *,
    rate: int = 2,
    order_ids: tuple[str, ...] = ("OMS-1", "OMS-2", "OMS-3"),
    authorization_id: str = "capital-auth-1",
    account_alias: str = "中信证券88**16",
    status: str = "current_enabled_bounded_session",
    authority_verified: bool = True,
    limiter_enabled: bool = True,
    reservation_verified: bool = True,
    upstream_gates_clear: bool = True,
    kill_switch_clear: bool = True,
    effective_at: datetime = NOW - timedelta(seconds=1),
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> dict:
    fingerprint_seed = "a" if session_id.endswith("a") else "b"
    reservation_seed = "c" if session_id.endswith("a") else "d"
    return {
        "status": status,
        "session_id": session_id,
        "session_fingerprint": fingerprint_seed * 64,
        "reservation_id": reservation_seed * 64,
        "authorization_id": authorization_id,
        "account_alias": account_alias,
        "strategy_id": "strategy-1",
        "order_ids": list(order_ids),
        "effective_at": effective_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "max_order_rate_per_minute": rate,
        "session_authority_verified": authority_verified,
        "persistent_session_state_verified": True,
        "runtime_authentication_verified": True,
        "budget_reservation_verified": reservation_verified,
        "upstream_gates_clear": upstream_gates_clear,
        "kill_switch_clear": kill_switch_clear,
        "runtime_rate_limiter_enabled": limiter_enabled,
        "private_session_token": "must-not-leak",
        "broker_password": "must-not-leak",
    }


def _service(tmp_path, sessions: dict[str, dict], current_time=None):
    db = AppDatabase(tmp_path / "controlled-session-rate-limit.db")
    db.init_sync()
    for session in sessions.values():
        _persist_runtime_session(db, session)
    clock = current_time or [NOW]
    service = ControlledSessionRuntimeRateLimiterService(
        db=db,
        session_provider=lambda session_id, session_token: (
            sessions.get(session_id, {"status": "missing"})
            if session_token == SESSION_TOKEN
            else {"status": "blocked"}
        ),
        clock=lambda: clock[0],
    )
    return db, service


def _persist_runtime_session(db: AppDatabase, session: dict) -> None:
    reservation = {
        "reservation_id": session["reservation_id"],
        "attestation_id": ("1" if session["session_id"].endswith("a") else "2") * 64,
        "envelope_fingerprint": "e" * 64,
        "capital_evaluation_input_fingerprint": "f" * 64,
        "authorization_id": session["authorization_id"],
        "policy_version": "policy-v1",
        "account_alias": session["account_alias"],
        "strategy_id": session["strategy_id"],
        "trading_day": "2026-07-12",
        "requested_start_at": session["effective_at"],
        "requested_expires_at": session["expires_at"],
        "reserved_gross_units": 0,
        "reserved_buy_units": 0,
        "reserved_turnover_units": 0,
        "reserved_order_count": 1,
        "capital_capacity_units": 1_000_000_000,
        "cash_capacity_units": 1_000_000_000,
        "turnover_capacity_units": 1_000_000_000,
        "order_count_capacity": 1000,
        "reserved_by_symbol_units": {"510300.SH": 0},
        "symbol_capacity_units": {"510300.SH": 1_000_000_000},
        "payload": {},
        "created_at": NOW.isoformat(),
    }
    reserved = db.reserve_controlled_session_budget_sync(reservation=reservation)
    assert reserved["status"] == "reserved"
    effective_at = datetime.fromisoformat(session["effective_at"])
    expires_at = datetime.fromisoformat(session["expires_at"])
    issued = db.issue_controlled_session_sync(
        session={
            "session_id": session["session_id"],
            "session_fingerprint": session["session_fingerprint"],
            "issuance_fingerprint": (
                "3" if session["session_id"].endswith("a") else "4"
            )
            * 64,
            "reservation_id": session["reservation_id"],
            "attestation_id": reservation["attestation_id"],
            "envelope_fingerprint": reservation["envelope_fingerprint"],
            "authorization_id": session["authorization_id"],
            "account_alias": session["account_alias"],
            "strategy_id": session["strategy_id"],
            "operator_id": "local-owner",
            "operator_approval_id": "5" * 64,
            "order_ids": session["order_ids"],
            "requested_start_at": session["effective_at"],
            "requested_expires_at": session["expires_at"],
            "effective_at_epoch_ms": int(effective_at.timestamp() * 1000),
            "expires_at_epoch_ms": int(expires_at.timestamp() * 1000),
            "max_order_rate_per_minute": max(
                1,
                int(session["max_order_rate_per_minute"]),
            ),
            "token_salt": "ab" * 16,
            "token_hash": "6" * 64,
            "payload": {},
            "created_at": NOW.isoformat(),
        }
    )
    assert issued["status"] == "enabled"


def _admit(
    service: ControlledSessionRuntimeRateLimiterService,
    *,
    session_id: str = "session-a",
    order_id: str = "OMS-1",
    request_id: str = "1" * 64,
) -> dict:
    return service.admit(
        session_id=session_id,
        session_token=SESSION_TOKEN,
        order_id=order_id,
        request_id=request_id,
    )


def test_rate_limiter_is_closed_without_authenticated_session_provider(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "closed-rate-limit.db")
    db.init_sync()
    service = ControlledSessionRuntimeRateLimiterService(db=db, clock=lambda: NOW)

    status = service.get_status()
    preview = service.preview(
        session_id="session-a",
        session_token=SESSION_TOKEN,
        order_id="OMS-1",
        request_id="1" * 64,
    )

    assert status["contract_status"] == (
        "disabled_waiting_for_authenticated_session_issuance"
    )
    assert status["runtime_admission_enabled"] is False
    assert status["public_admission_endpoint_exposed"] is False
    assert preview["status"] == "blocked"
    assert "authenticated_runtime_session_provider_unavailable" in preview["blockers"]
    assert preview["runtime_admission_granted"] is False
    assert preview["authorizes_broker_submission"] is False
    assert db.list_controlled_session_rate_admissions_sync() == []


def test_preview_is_deterministic_sanitized_and_side_effect_free(tmp_path) -> None:
    sessions = {"session-a": _session("session-a")}
    db, service = _service(tmp_path, sessions)

    first = service.preview(
        session_id="session-a",
        session_token=SESSION_TOKEN,
        order_id="OMS-1",
        request_id="1" * 64,
    )
    second = service.preview(
        session_id="session-a",
        session_token=SESSION_TOKEN,
        order_id="OMS-1",
        request_id="1" * 64,
    )

    assert first["admission_id"] == second["admission_id"]
    assert first["status"] == "ready_for_atomic_admission"
    assert first["max_order_rate_per_minute"] == 2
    assert first["runtime_admission_granted"] is False
    assert "must-not-leak" not in str(first)
    assert db.list_controlled_session_rate_admissions_sync() == []


def test_atomic_admission_is_persisted_and_exact_retry_is_idempotent(tmp_path) -> None:
    sessions = {"session-a": _session("session-a")}
    db, service = _service(tmp_path, sessions)

    first = _admit(service)
    retry = _admit(service)

    assert first["status"] == "admitted"
    assert first["runtime_admission_granted"] is True
    assert first["runtime_session_issued"] is True
    assert first["authorizes_broker_submission"] is False
    assert first["admitted_before"] == 0
    assert first["admitted_after"] == 1
    assert retry["database_id"] == first["database_id"]
    assert retry["reused"] is True
    assert len(db.list_controlled_session_rate_admissions_sync()) == 1


def test_sliding_window_limit_and_exact_boundary(tmp_path) -> None:
    current_time = [NOW]
    sessions = {"session-a": _session("session-a", rate=2)}
    db, service = _service(tmp_path, sessions, current_time)
    _admit(service, order_id="OMS-1", request_id="1" * 64)
    _admit(service, order_id="OMS-2", request_id="2" * 64)

    with pytest.raises(ControlledSessionRateAdmissionRejected) as exc_info:
        _admit(service, order_id="OMS-3", request_id="3" * 64)

    assert "runtime_order_rate_limit_reached" in (
        exc_info.value.evidence["transaction_blockers"]
    )
    assert exc_info.value.evidence["admitted_before"] == 2
    current_time[0] = NOW + timedelta(seconds=60)
    sessions["session-a"] = _session(
        "session-a",
        rate=2,
        order_ids=("OMS-1", "OMS-2", "OMS-3", "OMS-4"),
    )
    boundary = _admit(service, order_id="OMS-4", request_id="4" * 64)
    assert boundary["status"] == "admitted"
    assert len(db.list_controlled_session_rate_admissions_sync()) == 3


def test_concurrent_last_slot_admits_only_one_order(tmp_path) -> None:
    sessions = {"session-a": _session("session-a", rate=1)}
    db, service = _service(tmp_path, sessions)
    barrier = Barrier(2)

    def admit(values: tuple[str, str]) -> tuple[str, list[str]]:
        order_id, request_id = values
        barrier.wait()
        try:
            _admit(service, order_id=order_id, request_id=request_id)
        except ControlledSessionRateAdmissionRejected as exc:
            return "rejected", exc.evidence["transaction_blockers"]
        return "admitted", []

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(admit, (("OMS-1", "1" * 64), ("OMS-2", "2" * 64))))

    assert sorted(status for status, _ in results) == ["admitted", "rejected"]
    blockers = next(items for status, items in results if status == "rejected")
    assert "runtime_order_rate_limit_reached" in blockers
    assert len(db.list_controlled_session_rate_admissions_sync()) == 1


def test_overlapping_sessions_share_strictest_account_rate(tmp_path) -> None:
    sessions = {
        "session-a": _session("session-a", rate=2, order_ids=("OMS-1",)),
        "session-b": _session("session-b", rate=1, order_ids=("OMS-2",)),
    }
    db, service = _service(tmp_path, sessions)
    _admit(service, session_id="session-a", order_id="OMS-1", request_id="1" * 64)

    with pytest.raises(ControlledSessionRateAdmissionRejected) as exc_info:
        _admit(
            service,
            session_id="session-b",
            order_id="OMS-2",
            request_id="2" * 64,
        )

    assert "runtime_order_rate_limit_reached" in (
        exc_info.value.evidence["transaction_blockers"]
    )
    assert len(db.list_controlled_session_rate_admissions_sync()) == 1


@pytest.mark.parametrize(
    ("session_update", "expected_blocker"),
    [
        ({"status": "paused"}, "runtime_session_not_current_or_enabled"),
        (
            {"session_authority_verified": False},
            "runtime_session_authority_not_verified",
        ),
        (
            {"budget_reservation_verified": False},
            "runtime_session_budget_reservation_not_verified",
        ),
        ({"upstream_gates_clear": False}, "runtime_session_upstream_gates_not_clear"),
        ({"kill_switch_clear": False}, "runtime_session_kill_switch_not_clear"),
        (
            {"runtime_rate_limiter_enabled": False},
            "runtime_rate_limiter_not_enabled_by_session",
        ),
        ({"expires_at": NOW.isoformat()}, "runtime_session_expired"),
    ],
)
def test_session_pause_authority_drift_and_expiry_fail_closed(
    tmp_path,
    session_update: dict,
    expected_blocker: str,
) -> None:
    current = _session("session-a")
    current.update(session_update)
    db, service = _service(tmp_path, {"session-a": current})

    with pytest.raises(ControlledSessionRateAdmissionRejected) as exc_info:
        _admit(service)

    assert expected_blocker in exc_info.value.evidence["review_blockers"]
    assert exc_info.value.evidence["runtime_admission_granted"] is False
    assert exc_info.value.evidence["authorizes_broker_submission"] is False
    assert db.list_controlled_session_rate_admissions_sync() == []


def test_order_and_request_reuse_fail_closed_and_are_audited(tmp_path) -> None:
    sessions = {"session-a": _session("session-a", rate=10)}
    db, service = _service(tmp_path, sessions)
    _admit(service, order_id="OMS-1", request_id="1" * 64)

    with pytest.raises(ControlledSessionRateAdmissionRejected) as order_error:
        _admit(service, order_id="OMS-1", request_id="2" * 64)
    with pytest.raises(ControlledSessionRateAdmissionRejected) as request_error:
        _admit(service, order_id="OMS-2", request_id="1" * 64)

    assert "runtime_rate_order_already_admitted" in (
        order_error.value.evidence["transaction_blockers"]
    )
    assert "runtime_rate_request_id_reused" in (
        request_error.value.evidence["transaction_blockers"]
    )
    assert len(db.list_controlled_session_rate_admissions_sync()) == 1
    assert (
        len(
            db.list_events_sync(event_type=CONTROLLED_SESSION_RATE_REJECTION_EVENT_TYPE)
        )
        == 2
    )


def test_provider_failure_and_unsafe_rate_are_sanitized_and_blocked(tmp_path) -> None:
    db = AppDatabase(tmp_path / "failed-provider-rate-limit.db")
    db.init_sync()

    def failed_provider(session_id: str, session_token: str) -> dict:
        raise RuntimeError("private session token must not leak")

    failed_service = ControlledSessionRuntimeRateLimiterService(
        db=db,
        session_provider=failed_provider,
        clock=lambda: NOW,
    )
    failed = failed_service.preview(
        session_id="session-a",
        session_token=SESSION_TOKEN,
        order_id="OMS-1",
        request_id="1" * 64,
    )
    _, unsafe_service = _service(
        tmp_path / "unsafe",
        {"session-a": _session("session-a", rate=601)},
    )
    unsafe = unsafe_service.preview(
        session_id="session-a",
        session_token=SESSION_TOKEN,
        order_id="OMS-1",
        request_id="2" * 64,
    )

    assert "authenticated_runtime_session_provider_failed" in failed["blockers"]
    assert "private session token" not in str(failed)
    assert "runtime_session_rate_limit_invalid" in unsafe["blockers"]
    assert failed["authorizes_broker_submission"] is False
    assert unsafe["runtime_admission_granted"] is False
