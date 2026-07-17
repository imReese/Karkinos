from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.per_order_confirmation as route_module
import server.services.current_per_order_dossier_factory as factory_module
from server.app import create_app
from server.routes.per_order_confirmation import create_router
from server.services.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PerOrderConfirmationRejected,
)
from tests.route_assertions import registered_app_routes


class FakeCurrentPerOrderDossierService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_candidates(self, *, limit: int):
        self.calls.append(("list", limit))
        return {
            "candidate_count": 1,
            "candidates": [{"order_id": "OMS-1", "review_ready": True}],
            "provider_contact_performed": False,
            "broker_submission_enabled": False,
        }

    def preview_current(self, order_id: str):
        self.calls.append(("preview", order_id))
        if order_id == "missing":
            raise KeyError("OMS order not found: missing")
        return {
            "order_id": order_id,
            "dossier_fingerprint": "d" * 64,
            "review_status": "review_ready_non_submitting",
            "provider_contact_performed": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
            "authorizes_execution": False,
        }

    def record_current_confirmation(
        self,
        order_id: str,
        *,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ):
        request = (
            order_id,
            dossier_fingerprint,
            operator_label,
            operator_approval_id,
            acknowledgement,
        )
        self.calls.append(("confirm", request))
        if dossier_fingerprint == "0" * 64:
            raise PerOrderConfirmationRejected(
                "stale dossier",
                evidence={
                    "status": "rejected",
                    "rejection_reasons": ["dossier_fingerprint_mismatch"],
                    "authorizes_execution": False,
                },
            )
        return {
            "status": "recorded_verified_identity",
            "order_id": order_id,
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
        }


def _client(monkeypatch) -> tuple[TestClient, FakeCurrentPerOrderDossierService]:
    service = FakeCurrentPerOrderDossierService()
    monkeypatch.setattr(
        "server.routes.per_order_confirmation._current_dossier_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_current_dossier_routes_resolve_preview_and_record_without_manual_refs(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    candidates = client.get(
        "/api/automation/controlled-bridge/dossiers/current?limit=7"
    )
    preview = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/dossier/current/preview"
    )
    confirmation = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/dossier/current/confirmations",
        json={
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )

    assert candidates.status_code == 200
    assert candidates.json()["candidate_count"] == 1
    assert preview.status_code == 200
    assert preview.json()["provider_contact_performed"] is False
    assert preview.json()["broker_submission_enabled"] is False
    assert preview.json()["broker_cancel_enabled"] is False
    assert confirmation.status_code == 200
    assert confirmation.json()["authorizes_execution"] is False
    assert ("list", 7) in service.calls
    assert ("preview", "OMS-1") in service.calls
    assert any(call[0] == "confirm" for call in service.calls)


def test_current_confirmation_route_rejects_credentials_stale_dossier_and_missing_order(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    path = (
        "/api/automation/controlled-bridge/orders/OMS-1/"
        "dossier/current/confirmations"
    )

    credentials = client.post(
        path,
        json={
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
            "broker_password": "must-not-be-accepted",
        },
    )
    stale = client.post(
        path,
        json={
            "dossier_fingerprint": "0" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )
    missing = client.post(
        "/api/automation/controlled-bridge/orders/missing/dossier/current/preview"
    )

    assert credentials.status_code == 422
    assert stale.status_code == 409
    assert stale.json()["detail"]["authorizes_execution"] is False
    assert missing.status_code == 404
    assert sum(call[0] == "confirm" for call in service.calls) == 1


def test_app_registers_current_dossier_routes_without_current_submit_or_cancel() -> (
    None
):
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in registered_app_routes(app)}

    assert "/api/automation/controlled-bridge/dossiers/current" in paths
    assert (
        "/api/automation/controlled-bridge/orders/{order_id}/dossier/current/preview"
        in paths
    )
    assert (
        "/api/automation/controlled-bridge/orders/{order_id}/dossier/current/confirmations"
        in paths
    )
    assert not any("dossier/current/submit" in path for path in paths)
    assert not any("dossier/current/cancel" in path for path in paths)


def test_current_route_service_uses_persisted_verification_without_runtime_gateway(
    monkeypatch,
) -> None:
    fake_db = object()
    fake_state = SimpleNamespace(
        db=fake_db,
        config=SimpleNamespace(
            broker_connectors=[],
            trusted_operator_identities=[],
        ),
        trading_controls=object(),
        execution_gateways=[object()],
    )
    captured: dict[str, object] = {}

    def persisted_resolver(db, fingerprint: str):
        captured["db"] = db
        captured["fingerprint"] = fingerprint
        return {
            "status": "blocked",
            "verification_fingerprint": fingerprint,
            "provider_contact_performed": False,
            "runtime_gateway_call_performed": False,
        }

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        factory_module,
        "resolve_persisted_execution_gateway_verification",
        persisted_resolver,
    )

    service = route_module._current_dossier_service()
    resolved = service._dossier_service._execution_gateway_verification_provider(
        "e" * 64
    )

    assert captured == {"db": fake_db, "fingerprint": "e" * 64}
    assert resolved["provider_contact_performed"] is False
    assert resolved["runtime_gateway_call_performed"] is False
