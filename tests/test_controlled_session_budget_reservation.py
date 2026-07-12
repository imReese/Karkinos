from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from server.db import AppDatabase
from server.services.controlled_session_budget_reservation import (
    CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    CONTROLLED_SESSION_BUDGET_RESERVATION_REJECTION_EVENT_TYPE,
    ControlledSessionBudgetReservationRejected,
    ControlledSessionBudgetReservationService,
)

NOW = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)


def _attestation(
    attestation_id: str,
    *,
    gross: str = "600",
    buy: str = "600",
    effective_capital: str = "1000",
    current_exposure: str = "0",
    cash: str = "1000",
    remaining_turnover_after: str = "400",
    order_count: int = 2,
    rate_capacity: int = 4,
    projected_by_symbol: dict[str, str] | None = None,
    symbol_limits: dict[str, str] | None = None,
    start_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> dict:
    return {
        "status": "current_verified_non_executing",
        "attestation_id": attestation_id,
        "envelope_fingerprint": ("e" if attestation_id[0] != "e" else "f") * 64,
        "current_envelope": {
            "requested_start_at": start_at.isoformat(),
            "requested_expires_at": expires_at.isoformat(),
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
                "projected_gross_order_value": gross,
                "projected_buy_value": buy,
                "effective_capital": effective_capital,
                "current_authorized_exposure": current_exposure,
                "available_cash": cash,
                "remaining_daily_turnover_after_projection": (remaining_turnover_after),
                "order_count": order_count,
                "projected_rate_capacity": rate_capacity,
                "projected_by_symbol": projected_by_symbol or {"510300.SH": gross},
            },
            "per_symbol_runtime_limits": {
                "status": "pass",
                "requested_limits": symbol_limits or {"510300.SH": "1000"},
                "authorizes_execution": False,
            },
        },
        "blockers": [],
        "authorizes_execution": False,
    }


def _service(tmp_path, attestations: dict[str, dict], current_time=None):
    db = AppDatabase(tmp_path / "controlled-session-budget.db")
    db.init_sync()
    clock = current_time or [NOW]
    service = ControlledSessionBudgetReservationService(
        db=db,
        attestation_provider=lambda attestation_id: attestations.get(
            attestation_id,
            {"status": "blocked", "blockers": ["not_found"]},
        ),
        clock=lambda: clock[0],
    )
    return db, service


def _record(service, attestation_id: str) -> dict:
    preview = service.preview(attestation_id=attestation_id)
    return service.record(
        attestation_id=attestation_id,
        reservation_fingerprint=preview["reservation_fingerprint"],
        acknowledgement=CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    )


def test_budget_reservation_preview_is_deterministic_and_non_executing(
    tmp_path,
) -> None:
    attestation_id = "a" * 64
    db, service = _service(
        tmp_path,
        {attestation_id: _attestation(attestation_id, gross="0.00001", buy="0")},
    )

    first = service.preview(attestation_id=attestation_id)
    second = service.preview(attestation_id=attestation_id)

    assert first["reservation_fingerprint"] == second["reservation_fingerprint"]
    assert first["review_status"] == "ready_for_atomic_reservation"
    assert first["money_unit_scale"] == 10_000
    assert first["runtime_session_status"] == "not_issued"
    assert first["budget_reserved"] is False
    assert first["authorizes_execution"] is False
    assert first["safety"]["does_not_contact_broker"] is True
    assert db.list_controlled_session_budget_reservations_sync() == []


def test_budget_amount_rounds_up_while_capacity_rounds_down(tmp_path) -> None:
    attestation_id = "a" * 64
    db, service = _service(
        tmp_path,
        {
            attestation_id: _attestation(
                attestation_id,
                gross="0.00009",
                buy="0",
                effective_capital="0.00009",
                cash="1",
                remaining_turnover_after="1",
            )
        },
    )

    with pytest.raises(ControlledSessionBudgetReservationRejected) as exc_info:
        _record(service, attestation_id)

    assert "atomic_capital_budget_unavailable" in (
        exc_info.value.evidence["transaction_blockers"]
    )
    assert db.list_controlled_session_budget_reservations_sync() == []


def test_budget_reservation_is_persisted_idempotently_and_resolves(tmp_path) -> None:
    attestation_id = "a" * 64
    db, service = _service(
        tmp_path,
        {attestation_id: _attestation(attestation_id)},
    )

    first = _record(service, attestation_id)
    rerun = _record(service, attestation_id)
    resolved = service.resolve(first["reservation_id"])

    assert first["status"] == "reserved"
    assert first["budget_reserved"] is True
    assert first["runtime_session_status"] == "not_issued"
    assert first["broker_submission_enabled"] is False
    assert first["authorizes_execution"] is False
    assert first["safety"]["does_reserve_bounded_budget"] is True
    assert rerun["database_id"] == first["database_id"]
    assert rerun["reused"] is True
    assert resolved["resolution_status"] == "current_reserved_non_executing"
    assert resolved["authorizes_execution"] is False
    assert len(db.list_controlled_session_budget_reservations_sync()) == 1


def test_atomic_concurrent_reservations_cannot_double_spend_capital(tmp_path) -> None:
    first_id = "a" * 64
    second_id = "b" * 64
    attestations = {
        first_id: _attestation(first_id),
        second_id: _attestation(second_id),
    }
    db, service = _service(tmp_path, attestations)
    barrier = Barrier(2)

    def reserve(attestation_id: str) -> tuple[str, list[str]]:
        preview = service.preview(attestation_id=attestation_id)
        barrier.wait()
        try:
            service.record(
                attestation_id=attestation_id,
                reservation_fingerprint=preview["reservation_fingerprint"],
                acknowledgement=(CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT),
            )
        except ControlledSessionBudgetReservationRejected as exc:
            return "rejected", exc.evidence["transaction_blockers"]
        return "reserved", []

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, (first_id, second_id)))

    assert sorted(status for status, _ in results) == ["rejected", "reserved"]
    rejected = next(blockers for status, blockers in results if status == "rejected")
    assert "atomic_capital_budget_unavailable" in rejected
    assert len(db.list_controlled_session_budget_reservations_sync()) == 1


def test_atomic_concurrent_reservations_cannot_double_spend_symbol_budget(
    tmp_path,
) -> None:
    first_id = "a" * 64
    second_id = "b" * 64
    common = {
        "gross": "600",
        "buy": "600",
        "effective_capital": "5000",
        "cash": "5000",
        "remaining_turnover_after": "4400",
        "rate_capacity": 10,
        "projected_by_symbol": {"510300.SH": "600"},
        "symbol_limits": {"510300.SH": "1000"},
    }
    db, service = _service(
        tmp_path,
        {
            first_id: _attestation(first_id, **common),
            second_id: _attestation(second_id, **common),
        },
    )
    barrier = Barrier(2)

    def reserve(attestation_id: str) -> tuple[str, list[str]]:
        preview = service.preview(attestation_id=attestation_id)
        barrier.wait()
        try:
            service.record(
                attestation_id=attestation_id,
                reservation_fingerprint=preview["reservation_fingerprint"],
                acknowledgement=(CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT),
            )
        except ControlledSessionBudgetReservationRejected as exc:
            return "rejected", exc.evidence["transaction_blockers"]
        return "reserved", []

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, (first_id, second_id)))

    assert sorted(status for status, _ in results) == ["rejected", "reserved"]
    blockers = next(items for status, items in results if status == "rejected")
    assert "atomic_symbol_budget_unavailable:510300.SH" in blockers
    assert "atomic_capital_budget_unavailable" not in blockers
    assert len(db.list_controlled_session_budget_reservations_sync()) == 1


def test_disjoint_symbols_reserve_independently_inside_shared_capital(tmp_path) -> None:
    first_id = "a" * 64
    second_id = "b" * 64
    common = {
        "gross": "600",
        "buy": "600",
        "effective_capital": "5000",
        "cash": "5000",
        "remaining_turnover_after": "4400",
        "rate_capacity": 10,
    }
    db, service = _service(
        tmp_path,
        {
            first_id: _attestation(
                first_id,
                **common,
                projected_by_symbol={"510300.SH": "600"},
                symbol_limits={"510300.SH": "1000"},
            ),
            second_id: _attestation(
                second_id,
                **common,
                projected_by_symbol={"159915.SZ": "600"},
                symbol_limits={"159915.SZ": "1000"},
            ),
        },
    )

    first = _record(service, first_id)
    second = _record(service, second_id)

    assert first["reserved_budget"]["by_symbol"] == {"510300.SH": "600"}
    assert second["reserved_budget"]["by_symbol"] == {"159915.SZ": "600"}
    assert second["aggregate_after"]["overlapping_by_symbol_units"] == {
        "159915.SZ": 6_000_000
    }
    assert len(db.list_controlled_session_budget_reservations_sync()) == 2


def test_overlapping_legacy_reservation_without_symbol_evidence_fails_closed(
    tmp_path,
) -> None:
    first_id = "a" * 64
    second_id = "b" * 64
    common = {
        "gross": "100",
        "buy": "100",
        "effective_capital": "5000",
        "cash": "5000",
        "remaining_turnover_after": "4900",
        "rate_capacity": 10,
        "projected_by_symbol": {"510300.SH": "100"},
        "symbol_limits": {"510300.SH": "1000"},
    }
    db, service = _service(
        tmp_path,
        {
            first_id: _attestation(first_id, **common),
            second_id: _attestation(second_id, **common),
        },
    )
    _record(service, first_id)
    with sqlite3.connect(db._path) as conn:
        conn.execute("""
            UPDATE controlled_session_budget_reservations
            SET reserved_by_symbol_json = '{}', symbol_capacity_json = '{}'
            """)
        conn.commit()

    with pytest.raises(ControlledSessionBudgetReservationRejected) as exc_info:
        _record(service, second_id)

    assert "atomic_existing_symbol_budget_evidence_missing:510300.SH" in (
        exc_info.value.evidence["transaction_blockers"]
    )
    assert len(db.list_controlled_session_budget_reservations_sync()) == 1


def test_atomic_reservation_checks_cash_turnover_and_order_count(tmp_path) -> None:
    cases = [
        (
            "cash",
            {"gross": "300", "buy": "300", "cash": "500"},
            "atomic_cash_budget_unavailable",
        ),
        (
            "turnover",
            {"gross": "600", "remaining_turnover_after": "0"},
            "atomic_daily_turnover_budget_unavailable",
        ),
        (
            "orders",
            {"gross": "100", "buy": "100", "order_count": 3, "rate_capacity": 4},
            "atomic_order_count_budget_unavailable",
        ),
    ]
    for index, (_, overrides, expected) in enumerate(cases):
        case_path = tmp_path / str(index)
        first_id = (chr(ord("a") + index * 2)) * 64
        second_id = (chr(ord("b") + index * 2)) * 64
        common = {
            "gross": "100",
            "buy": "100",
            "effective_capital": "1000",
            "cash": "1000",
            "remaining_turnover_after": "900",
            "order_count": 2,
            "rate_capacity": 4,
        }
        common.update(overrides)
        db, service = _service(
            case_path,
            {
                first_id: _attestation(first_id, **common),
                second_id: _attestation(second_id, **common),
            },
        )
        _record(service, first_id)
        with pytest.raises(ControlledSessionBudgetReservationRejected) as exc_info:
            _record(service, second_id)
        assert expected in exc_info.value.evidence["transaction_blockers"]
        assert len(db.list_controlled_session_budget_reservations_sync()) == 1


def test_reservation_revalidates_attestation_and_expiry(tmp_path) -> None:
    attestation_id = "a" * 64
    current_time = [NOW]
    attestations = {attestation_id: _attestation(attestation_id)}
    _, service = _service(tmp_path, attestations, current_time)
    preview = service.preview(attestation_id=attestation_id)
    attestations[attestation_id] = {
        "status": "blocked",
        "blockers": ["account_truth_source_changed"],
    }

    with pytest.raises(ControlledSessionBudgetReservationRejected) as exc_info:
        service.record(
            attestation_id=attestation_id,
            reservation_fingerprint=preview["reservation_fingerprint"],
            acknowledgement=CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
        )

    assert "budget_reservation_fingerprint_mismatch" in (
        exc_info.value.evidence["rejection_reasons"]
    )
    assert "attestation:account_truth_source_changed" in (
        exc_info.value.evidence["review_blockers"]
    )
    assert exc_info.value.evidence["authorizes_execution"] is False


def test_rejected_reservation_is_audited_and_cannot_accept_credentials(
    tmp_path,
) -> None:
    attestation_id = "a" * 64
    db, service = _service(
        tmp_path,
        {attestation_id: _attestation(attestation_id)},
    )
    preview = service.preview(attestation_id=attestation_id)

    with pytest.raises(ControlledSessionBudgetReservationRejected) as exc_info:
        service.record(
            attestation_id=attestation_id,
            reservation_fingerprint="0" * 64,
            acknowledgement=CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
        )

    evidence = exc_info.value.evidence
    assert evidence["persisted"] is True
    assert evidence["budget_reserved"] is False
    assert evidence["authorizes_execution"] is False
    assert preview["reservation_fingerprint"] != "0" * 64
    assert (
        len(
            db.list_events_sync(
                event_type=CONTROLLED_SESSION_BUDGET_RESERVATION_REJECTION_EVENT_TYPE
            )
        )
        == 1
    )
