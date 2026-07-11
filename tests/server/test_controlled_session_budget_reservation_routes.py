from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_session_budget_reservation as route_module
from server.app import create_app
from server.routes.controlled_session_budget_reservation import create_router
from server.services.controlled_session_budget_reservation import (
    CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    ControlledSessionBudgetReservationRejected,
)


class FakeControlledSessionBudgetReservationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "atomic_budget_reservation_non_executing",
            "runtime_session_authority": "disabled",
        }

    def preview(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {
            "review_status": "ready_for_atomic_reservation",
            "reservation_fingerprint": "b" * 64,
            "authorizes_execution": False,
        }

    def record(self, **kwargs):
        self.calls.append(("record", kwargs))
        if kwargs["reservation_fingerprint"] == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["budget_reservation_fingerprint_mismatch"],
                "authorizes_execution": False,
            }
            raise ControlledSessionBudgetReservationRejected(
                "stale reservation",
                evidence=evidence,
            )
        return {
            "status": "reserved",
            "reservation_id": kwargs["reservation_fingerprint"],
            "runtime_session_status": "not_issued",
            "authorizes_execution": False,
        }

    def list_reservations(self, *, limit: int):
        self.calls.append(("list", limit))
        return [{"status": "reserved", "authorizes_execution": False}]

    def resolve(self, reservation_id: str):
        self.calls.append(("resolve", reservation_id))
        return {
            "resolution_status": "current_reserved_non_executing",
            "reservation_id": reservation_id,
            "authorizes_execution": False,
        }


def _client(monkeypatch):
    service = FakeControlledSessionBudgetReservationService()
    monkeypatch.setattr(route_module, "_service", lambda: service)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_controlled_session_budget_routes_cover_non_executing_flow(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    attestation_id = "a" * 64
    reservation_id = "b" * 64

    status = client.get(
        "/api/automation/controlled-sessions/budget-reservations/status"
    )
    preview = client.post(
        "/api/automation/controlled-sessions/budget-reservations/preview",
        json={"attestation_id": attestation_id},
    )
    record = client.post(
        "/api/automation/controlled-sessions/budget-reservations/records",
        json={
            "attestation_id": attestation_id,
            "reservation_fingerprint": reservation_id,
            "acknowledgement": (CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT),
        },
    )
    listing = client.get(
        "/api/automation/controlled-sessions/budget-reservations/records?limit=10"
    )
    resolution = client.get(
        f"/api/automation/controlled-sessions/budget-reservations/records/{reservation_id}"
    )

    assert status.status_code == 200
    assert status.json()["runtime_session_authority"] == "disabled"
    assert preview.status_code == 200
    assert preview.json()["authorizes_execution"] is False
    assert record.status_code == 200
    assert record.json()["runtime_session_status"] == "not_issued"
    assert listing.status_code == 200
    assert resolution.status_code == 200
    assert resolution.json()["authorizes_execution"] is False
    assert ("list", 10) in service.calls


def test_controlled_session_budget_route_rejects_stale_and_credentials(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    path = "/api/automation/controlled-sessions/budget-reservations/records"
    payload = {
        "attestation_id": "a" * 64,
        "reservation_fingerprint": "0" * 64,
        "acknowledgement": CONTROLLED_SESSION_BUDGET_RESERVATION_ACKNOWLEDGEMENT,
    }

    rejected = client.post(path, json=payload)
    credential = client.post(path, json={**payload, "broker_password": "forbidden"})
    bad_ack = client.post(path, json={**payload, "acknowledgement": "issue_now"})
    bad_id = client.post(
        "/api/automation/controlled-sessions/budget-reservations/preview",
        json={"attestation_id": "invalid"},
    )

    assert rejected.status_code == 409
    assert rejected.json()["detail"]["authorizes_execution"] is False
    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert bad_id.status_code == 422
    assert len([call for call in service.calls if call[0] == "record"]) == 1


def test_route_service_wires_current_controlled_session_resolver(monkeypatch) -> None:
    fake_state = SimpleNamespace(db=object())
    envelope_service = SimpleNamespace(resolve_attestation=lambda value: {"id": value})
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        "server.routes.controlled_session_envelope._service",
        lambda: envelope_service,
    )

    service = route_module._service()

    assert service._db is fake_state.db
    assert service._attestation_provider("a" * 64) == {"id": "a" * 64}


def test_create_app_registers_controlled_session_budget_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/controlled-sessions/budget-reservations/status" in paths
    assert "/api/automation/controlled-sessions/budget-reservations/preview" in paths
    assert "/api/automation/controlled-sessions/budget-reservations/records" in paths
