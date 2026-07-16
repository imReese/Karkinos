from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_submission_ledger_correction as route_module
from server.app import create_app
from server.routes.controlled_submission_ledger_correction import create_router
from tests.route_assertions import registered_app_routes


class FakeControlledSubmissionLedgerCorrectionService:
    def get_status(self):
        return {
            "contract_status": "signed_append_only_correction_available",
            "arbitrary_financial_input_enabled": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
        }

    def preview(self, **kwargs):
        return {
            **kwargs,
            "correction_fingerprint": "1" * 64,
            "review_ready": True,
            "production_ledger_mutated": False,
        }

    def apply(self, **kwargs):
        return {
            **kwargs,
            "correction_id": "2" * 64,
            "status": "applied",
            "production_ledger_mutated": True,
            "original_ledger_entries_deleted": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
        }

    def list_corrections(self, *, limit: int):
        return [{"correction_id": "2" * 64, "limit": limit}]

    def get_correction(self, correction_id: str):
        return {"correction_id": correction_id, "status": "applied"}


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        route_module,
        "_service",
        lambda: FakeControlledSubmissionLedgerCorrectionService(),
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_routes_require_separate_signature_and_forbid_financial_inputs(
    monkeypatch,
) -> None:
    client = _client(monkeypatch)
    prefix = "/api/automation/controlled-ledger-corrections"
    posting_id = "3" * 64
    preview_body = {
        "reason_code": "operator_confirmed_mapping_error",
        "operator_id": "local-operator",
    }

    status = client.get(f"{prefix}/status")
    assert status.status_code == 200
    assert status.json()["arbitrary_financial_input_enabled"] is False
    assert status.json()["broker_submission_enabled"] is False
    preview = client.post(
        f"{prefix}/postings/{posting_id}/preview",
        json=preview_body,
    )
    assert preview.status_code == 200
    assert preview.json()["production_ledger_mutated"] is False
    corrected = client.post(
        f"{prefix}/postings/{posting_id}/corrections",
        json={
            **preview_body,
            "correction_fingerprint": "1" * 64,
            "operator_approval_id": "4" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": ("apply_exact_compensating_ledger_correction_once"),
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["original_ledger_entries_deleted"] is False
    assert corrected.json()["broker_submission_enabled"] is False
    assert corrected.json()["broker_cancel_enabled"] is False
    assert client.get(f"{prefix}/corrections?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/corrections/{'2' * 64}").status_code == 200

    missing_signature = client.post(
        f"{prefix}/postings/{posting_id}/corrections",
        json={
            **preview_body,
            "correction_fingerprint": "1" * 64,
            "operator_approval_id": "4" * 64,
            "acknowledgement": ("apply_exact_compensating_ledger_correction_once"),
        },
    )
    assert missing_signature.status_code == 422
    arbitrary_financial_input = client.post(
        f"{prefix}/postings/{posting_id}/preview",
        json={**preview_body, "cash_delta": 1000, "quantity": 100},
    )
    assert arbitrary_financial_input.status_code == 422
    credential = client.post(
        f"{prefix}/postings/{posting_id}/preview",
        json={**preview_body, "broker_password": "must-not-be-accepted"},
    )
    assert credential.status_code == 422


def test_create_app_registers_correction_without_strategy_or_broker_actions() -> None:
    app = create_app({"live_auto_start": False})
    methods_by_path: dict[str, set[str]] = {}
    for route in registered_app_routes(app):
        if route.path.startswith("/api/automation/controlled-ledger-corrections"):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path == {
        "/api/automation/controlled-ledger-corrections/status": {"GET"},
        "/api/automation/controlled-ledger-corrections/postings/{posting_id}/preview": {
            "POST"
        },
        "/api/automation/controlled-ledger-corrections/postings/{posting_id}/corrections": {
            "POST"
        },
        "/api/automation/controlled-ledger-corrections/corrections": {"GET"},
        "/api/automation/controlled-ledger-corrections/corrections/{correction_id}": {
            "GET"
        },
    }
    assert all("strategy" not in path for path in methods_by_path)
    assert all(
        "/submit" not in path and "/cancel" not in path for path in methods_by_path
    )
