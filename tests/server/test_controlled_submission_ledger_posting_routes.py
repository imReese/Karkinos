from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.routes.controlled_submission_ledger_posting as route_module
from server.app import create_app
from server.routes.controlled_submission_ledger_posting import create_router
from tests.route_assertions import registered_app_routes


class FakeControlledSubmissionLedgerPostingService:
    def get_status(self):
        return {
            "contract_status": "signed_exactly_once_posting_available",
            "automatic_posting_enabled": False,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
        }

    def preview(self, **kwargs):
        return {
            **kwargs,
            "posting_fingerprint": "1" * 64,
            "review_ready": True,
            "production_ledger_mutated": False,
        }

    def apply(self, **kwargs):
        return {
            **kwargs,
            "posting_id": "2" * 64,
            "status": "applied",
            "production_ledger_mutated": True,
            "broker_submission_enabled": False,
            "broker_cancel_enabled": False,
        }

    def list_postings(self, *, limit: int):
        return [{"posting_id": "2" * 64, "limit": limit}]

    def get_posting(self, posting_id: str):
        return {"posting_id": posting_id, "status": "applied"}


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        route_module,
        "_service",
        lambda: FakeControlledSubmissionLedgerPostingService(),
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_routes_require_separate_signature_and_forbid_broker_credentials(
    monkeypatch,
) -> None:
    client = _client(monkeypatch)
    prefix = "/api/automation/controlled-ledger-posting"
    clearance_id = "3" * 64

    status = client.get(f"{prefix}/status")
    assert status.status_code == 200
    assert status.json()["automatic_posting_enabled"] is False
    assert status.json()["broker_submission_enabled"] is False
    preview = client.post(f"{prefix}/clearances/{clearance_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["production_ledger_mutated"] is False
    posted = client.post(
        f"{prefix}/clearances/{clearance_id}/postings",
        json={
            "posting_fingerprint": "1" * 64,
            "operator_approval_id": "4" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "apply_exact_reconciled_ledger_posting_once",
        },
    )
    assert posted.status_code == 200
    assert posted.json()["production_ledger_mutated"] is True
    assert posted.json()["broker_submission_enabled"] is False
    assert posted.json()["broker_cancel_enabled"] is False
    assert client.get(f"{prefix}/postings?limit=7").json()[0]["limit"] == 7
    assert client.get(f"{prefix}/postings/{'2' * 64}").status_code == 200

    missing_signature = client.post(
        f"{prefix}/clearances/{clearance_id}/postings",
        json={
            "posting_fingerprint": "1" * 64,
            "operator_approval_id": "4" * 64,
            "acknowledgement": "apply_exact_reconciled_ledger_posting_once",
        },
    )
    assert missing_signature.status_code == 422
    credential = client.post(
        f"{prefix}/clearances/{clearance_id}/postings",
        json={
            "posting_fingerprint": "1" * 64,
            "operator_approval_id": "4" * 64,
            "operator_proof_signature_base64": "A" * 88,
            "acknowledgement": "apply_exact_reconciled_ledger_posting_once",
            "broker_password": "must-not-be-accepted",
        },
    )
    assert credential.status_code == 422


def test_create_app_registers_ledger_posting_without_strategy_or_broker_actions() -> (
    None
):
    app = create_app({"live_auto_start": False})
    methods_by_path: dict[str, set[str]] = {}
    for route in registered_app_routes(app):
        if route.path.startswith("/api/automation/controlled-ledger-posting"):
            methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path == {
        "/api/automation/controlled-ledger-posting/status": {"GET"},
        "/api/automation/controlled-ledger-posting/clearances/{clearance_id}/preview": {
            "POST"
        },
        "/api/automation/controlled-ledger-posting/clearances/{clearance_id}/postings": {
            "POST"
        },
        "/api/automation/controlled-ledger-posting/postings": {"GET"},
        "/api/automation/controlled-ledger-posting/postings/{posting_id}": {"GET"},
    }
    assert all("strategy" not in path for path in methods_by_path)
    assert all(
        "submit" not in path and "cancel" not in path for path in methods_by_path
    )
