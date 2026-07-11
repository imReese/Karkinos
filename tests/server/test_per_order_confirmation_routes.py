from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.per_order_confirmation as route_module
from server.app import create_app
from server.routes.per_order_confirmation import create_router
from server.services.per_order_confirmation import (
    PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
    PerOrderConfirmationRejected,
)


class FakePerOrderConfirmationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "contract_status": "evidence_only_non_submitting",
            "broker_submission_enabled": False,
        }

    def preview_dossier(
        self,
        order_id: str,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
    ):
        self.calls.append(
            (
                "preview",
                (
                    order_id,
                    capital_evaluation_input_fingerprint,
                    prior_batch_reconciliation_fingerprint,
                ),
            )
        )
        if order_id == "missing":
            raise KeyError("OMS order not found: missing")
        return {
            "order_id": order_id,
            "dossier_fingerprint": "d" * 64,
            "review_status": "review_ready_non_submitting",
            "submission_status": "blocked",
            "authorizes_execution": False,
        }

    def record_confirmation(
        self,
        order_id: str,
        *,
        capital_evaluation_input_fingerprint: str,
        prior_batch_reconciliation_fingerprint: str,
        dossier_fingerprint: str,
        operator_label: str,
        operator_approval_id: str,
        acknowledgement: str,
    ):
        self.calls.append(
            (
                "confirm",
                (
                    order_id,
                    capital_evaluation_input_fingerprint,
                    prior_batch_reconciliation_fingerprint,
                    dossier_fingerprint,
                    operator_label,
                    operator_approval_id,
                    acknowledgement,
                ),
            )
        )
        if dossier_fingerprint == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["dossier_fingerprint_mismatch"],
                "authorizes_execution": False,
            }
            raise PerOrderConfirmationRejected(
                "stale dossier",
                evidence=evidence,
            )
        return {
            "status": "recorded_verified_identity",
            "order_id": order_id,
            "operator_identity_verified": True,
            "authorizes_execution": False,
            "broker_submission_enabled": False,
        }

    def list_confirmations(self, order_id: str, *, limit: int):
        self.calls.append(("list", (order_id, limit)))
        return [
            {
                "order_id": order_id,
                "status": "recorded_verified_identity",
                "authorizes_execution": False,
            }
        ]


def _client(monkeypatch) -> tuple[TestClient, FakePerOrderConfirmationService]:
    service = FakePerOrderConfirmationService()
    monkeypatch.setattr(
        "server.routes.per_order_confirmation._service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service


def test_per_order_confirmation_routes_preview_record_list_and_status(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)
    capital_fingerprint = "a" * 64

    status = client.get("/api/automation/controlled-bridge/status")
    preview = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/dossier/preview",
        json={
            "capital_evaluation_input_fingerprint": capital_fingerprint,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
        },
    )
    confirmation = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": capital_fingerprint,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )
    listing = client.get(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations?limit=10"
    )

    assert status.status_code == 200
    assert status.json()["broker_submission_enabled"] is False
    assert preview.status_code == 200
    assert preview.json()["submission_status"] == "blocked"
    assert confirmation.status_code == 200
    assert confirmation.json()["status"] == "recorded_verified_identity"
    assert confirmation.json()["operator_identity_verified"] is True
    assert confirmation.json()["authorizes_execution"] is False
    assert listing.status_code == 200
    assert listing.json()[0]["authorizes_execution"] is False
    assert ("list", ("OMS-1", 10)) in service.calls


def test_per_order_confirmation_route_maps_audited_rejection_to_conflict(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": "a" * 64,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
            "dossier_fingerprint": "0" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "rejected"
    assert response.json()["detail"]["authorizes_execution"] is False


def test_per_order_confirmation_routes_reject_credentials_and_bad_acknowledgement(
    monkeypatch,
) -> None:
    client, service = _client(monkeypatch)

    credential = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": "a" * 64,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
            "broker_password": "must-not-be-accepted",
        },
    )
    bad_ack = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": "a" * 64,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": "submit_now",
        },
    )
    missing_batch = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": "a" * 64,
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "operator_approval_id": "c" * 64,
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )
    missing_approval = client.post(
        "/api/automation/controlled-bridge/orders/OMS-1/confirmations",
        json={
            "capital_evaluation_input_fingerprint": "a" * 64,
            "prior_batch_reconciliation_fingerprint": "b" * 64,
            "dossier_fingerprint": "d" * 64,
            "operator_label": "local-owner",
            "acknowledgement": PER_ORDER_CONFIRMATION_ACKNOWLEDGEMENT,
        },
    )

    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert missing_batch.status_code == 422
    assert missing_approval.status_code == 422
    assert not any(call[0] == "confirm" for call in service.calls)


def test_per_order_confirmation_preview_missing_order_returns_not_found(
    monkeypatch,
) -> None:
    client, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/controlled-bridge/orders/missing/dossier/preview",
        json={},
    )

    assert response.status_code == 404


def test_create_app_registers_per_order_confirmation_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/controlled-bridge/status" in paths
    assert (
        "/api/automation/controlled-bridge/orders/{order_id}/dossier/preview" in paths
    )
    assert "/api/automation/controlled-bridge/orders/{order_id}/confirmations" in paths


def test_route_service_wires_current_stage1_promotion_evidence(monkeypatch) -> None:
    connector = SimpleNamespace(connector_id="readonly-1")
    fake_state = SimpleNamespace(
        db=object(),
        config=SimpleNamespace(
            broker_connectors=[object()],
            trusted_operator_identities=[object()],
        ),
        trading_controls=object(),
    )
    captured: dict[str, object] = {}

    class FakePromotionService:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def preview_dossier(self, connector_id: str) -> dict:
            captured["connector_id"] = connector_id
            return {"connector_id": connector_id, "promotion_ready": False}

    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    monkeypatch.setattr(
        route_module, "build_broker_connectors", lambda config: [connector]
    )
    monkeypatch.setattr(
        route_module,
        "BrokerConnectorSoakPromotionService",
        FakePromotionService,
    )
    monkeypatch.setattr(
        route_module,
        "build_latest_account_truth_promotion_evidence",
        lambda state: {"state_matches": state is fake_state},
    )

    service = route_module._service()
    promotion = service._broker_soak_promotion_evidence_provider("readonly-1")
    account_truth = captured["account_truth_evidence_provider"]()

    assert promotion == {"connector_id": "readonly-1", "promotion_ready": False}
    assert captured["db"] is fake_state.db
    assert captured["connectors"] == [connector]
    assert captured["trusted_operator_identities"] == [
        fake_state.config.trusted_operator_identities[0]
    ]
    assert captured["connector_id"] == "readonly-1"
    assert account_truth == {"state_matches": True}
