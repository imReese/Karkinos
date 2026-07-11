from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app import create_app
from server.routes.capital_scaling_review import create_router
from server.services.capital_scaling_review_audit import (
    CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
    CapitalScalingReviewDecisionRejected,
)

NOW = datetime(2026, 7, 10, 8, 5, tzinfo=timezone.utc)


class FakeCapitalScalingReviewService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("status", None))
        return {
            "review_contract_status": "evidence_only",
            "automatic_scale_up_enabled": False,
            "authority_change_enabled": False,
        }

    def preview(self, *, review):
        self.calls.append(("preview", review))
        return {
            "recommended_action": "request_new_authorization_for_scale_up",
            "eligible_for_scale_up_review": True,
            "authority_change_applied": False,
        }

    def record_evaluation(self, *, review):
        self.calls.append(("evaluate", review))
        return {
            "input_fingerprint": "a" * 64,
            "persisted": True,
            "reused": False,
            "decision": {
                "recommended_action": "request_new_authorization_for_scale_up",
                "eligible_for_scale_up_review": True,
            },
            "authority_change_applied": False,
        }

    def list_evaluations(self, *, limit: int):
        self.calls.append(("list_evaluations", limit))
        return [{"input_fingerprint": "a" * 64, "authority_change_applied": False}]

    def record_review_decision(self, **kwargs):
        self.calls.append(("decision", kwargs))
        if kwargs["evaluation_fingerprint"] == "0" * 64:
            evidence = {
                "status": "rejected",
                "rejection_reasons": ["chosen_action_exceeds_evidence_recommendation"],
                "new_authorization_issued": False,
                "authority_change_applied": False,
            }
            raise CapitalScalingReviewDecisionRejected(
                "decision rejected",
                evidence=evidence,
            )
        if kwargs["evaluation_fingerprint"] == "f" * 64:
            raise KeyError("capital scaling evaluation not found")
        return {
            "status": "recorded_unverified_identity",
            "chosen_action": kwargs["chosen_action"],
            "requests_new_authorization": True,
            "new_authorization_issued": False,
            "authority_change_applied": False,
            "operator_identity_verified": False,
        }

    def list_review_decisions(self, *, limit: int):
        self.calls.append(("list_decisions", limit))
        return [{"chosen_action": "hold", "authority_change_applied": False}]


class FakeCapitalScalingEvidenceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_status(self):
        self.calls.append(("evidence_status", None))
        return {
            "evidence_contract_status": "read_only_append_only",
            "automatic_scale_up_enabled": False,
        }

    def preview_account_truth_snapshot(self):
        self.calls.append(("preview_account_truth", None))
        return {"status": "clear", "persisted": False}

    def record_account_truth_snapshot(self):
        self.calls.append(("record_account_truth", None))
        return {"status": "clear", "persisted": True, "reused": False}

    def list_account_truth_snapshots(self, *, limit: int):
        self.calls.append(("list_account_truth", limit))
        return [{"status": "clear", "persisted": True}]

    def preview_window(self, **kwargs):
        self.calls.append(("preview_window", kwargs))
        if kwargs["review_window_start"].tzinfo is None:
            raise ValueError("review_window_start must be timezone-aware")
        return {
            "status": "blocked",
            "persisted": False,
            "authority_change_applied": False,
        }

    def record_window(self, **kwargs):
        self.calls.append(("record_window", kwargs))
        if kwargs["review_window_start"].tzinfo is None:
            raise ValueError("review_window_start must be timezone-aware")
        return {
            "status": "blocked",
            "persisted": True,
            "authority_change_applied": False,
        }

    def list_windows(self, *, limit: int):
        self.calls.append(("list_windows", limit))
        return [{"status": "blocked", "authority_change_applied": False}]


def _client(
    monkeypatch,
) -> tuple[
    TestClient,
    FakeCapitalScalingReviewService,
    FakeCapitalScalingEvidenceService,
]:
    service = FakeCapitalScalingReviewService()
    evidence_service = FakeCapitalScalingEvidenceService()
    monkeypatch.setattr(
        "server.routes.capital_scaling_review._service",
        lambda: service,
    )
    monkeypatch.setattr(
        "server.routes.capital_scaling_review._evidence_service",
        lambda: evidence_service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), service, evidence_service


def _tier(tier_id: str, capital: str) -> dict:
    return {
        "tier_id": tier_id,
        "policy_version": f"{tier_id}-policy-v1",
        "limits": {
            "max_authorized_capital": capital,
            "max_order_value": "3000",
            "max_daily_turnover": "30000",
            "max_daily_loss": "800",
            "max_drawdown_pct": "0.05",
        },
    }


def _review_payload() -> dict:
    return {
        "current_tier": _tier("pilot-1", "10000"),
        "proposed_tier": _tier("pilot-2", "20000"),
        "evidence": {
            "review_window_start": (NOW - timedelta(days=35)).isoformat(),
            "review_window_end": NOW.isoformat(),
            "reviewed_trading_days": 25,
            "order_count": 100,
            "filled_order_count": 98,
            "rejected_order_count": 1,
            "partial_fill_count": 4,
            "critical_incident_count": 0,
            "policy_violation_count": 0,
            "unresolved_reconciliation_count": 0,
            "p95_reconciliation_latency_minutes": "15",
            "average_slippage_bps": "5",
            "p95_slippage_bps": "12",
            "after_cost_return_pct": "0.08",
            "max_drawdown_pct": "0.02",
            "capacity_utilization_pct": "0.60",
            "liquidity_utilization_pct": "0.50",
            "paper_shadow_divergence_count": 0,
            "broker_disconnect_count": 1,
            "evidence_refs": ["broker_soak:qmt:20-days"],
        },
    }


def test_capital_scaling_routes_status_preview_evaluate_list_and_decide(
    monkeypatch,
) -> None:
    client, service, _ = _client(monkeypatch)

    status = client.get("/api/automation/capital-scaling/status")
    preview = client.post(
        "/api/automation/capital-scaling/reviews/preview",
        json=_review_payload(),
    )
    evaluation = client.post(
        "/api/automation/capital-scaling/reviews/evaluations",
        json=_review_payload(),
    )
    evaluations = client.get(
        "/api/automation/capital-scaling/reviews/evaluations?limit=10"
    )
    decision = client.post(
        "/api/automation/capital-scaling/reviews/decisions",
        json={
            "evaluation_fingerprint": "a" * 64,
            "chosen_action": "request_new_authorization_for_scale_up",
            "operator_label": "local-owner",
            "acknowledgement": CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
        },
    )
    decisions = client.get("/api/automation/capital-scaling/reviews/decisions?limit=10")

    assert status.status_code == 200
    assert status.json()["automatic_scale_up_enabled"] is False
    assert preview.status_code == 200
    assert preview.json()["authority_change_applied"] is False
    assert evaluation.status_code == 200
    assert evaluation.json()["decision"]["eligible_for_scale_up_review"] is True
    assert evaluations.status_code == 200
    assert decision.status_code == 200
    assert decision.json()["new_authorization_issued"] is False
    assert decision.json()["authority_change_applied"] is False
    assert decisions.status_code == 200
    assert ("list_evaluations", 10) in service.calls
    assert ("list_decisions", 10) in service.calls


def test_capital_scaling_route_maps_rejected_decision_to_conflict(monkeypatch) -> None:
    client, _, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/capital-scaling/reviews/decisions",
        json={
            "evaluation_fingerprint": "0" * 64,
            "chosen_action": "request_new_authorization_for_scale_up",
            "operator_label": "local-owner",
            "acknowledgement": CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "rejected"
    assert response.json()["detail"]["authority_change_applied"] is False


def test_capital_scaling_route_returns_not_found_for_unknown_evaluation(
    monkeypatch,
) -> None:
    client, _, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/capital-scaling/reviews/decisions",
        json={
            "evaluation_fingerprint": "f" * 64,
            "chosen_action": "hold",
            "operator_label": "local-owner",
            "acknowledgement": CAPITAL_SCALING_REVIEW_ACKNOWLEDGEMENT,
        },
    )

    assert response.status_code == 404


def test_capital_scaling_routes_reject_credentials_and_bad_acknowledgement(
    monkeypatch,
) -> None:
    client, service, _ = _client(monkeypatch)

    credential = client.post(
        "/api/automation/capital-scaling/reviews/evaluations",
        json={**_review_payload(), "broker_password": "must-not-be-accepted"},
    )
    bad_ack = client.post(
        "/api/automation/capital-scaling/reviews/decisions",
        json={
            "evaluation_fingerprint": "a" * 64,
            "chosen_action": "request_new_authorization_for_scale_up",
            "operator_label": "local-owner",
            "acknowledgement": "apply_scale_up_now",
        },
    )

    assert credential.status_code == 422
    assert bad_ack.status_code == 422
    assert not any(call[0] in {"evaluate", "decision"} for call in service.calls)


def test_capital_scaling_evidence_routes_preview_record_and_list(monkeypatch) -> None:
    client, _, service = _client(monkeypatch)
    window = {
        "review_window_start": (NOW - timedelta(days=35)).isoformat(),
        "review_window_end": NOW.isoformat(),
        "max_boundary_gap_hours": 72,
    }

    status = client.get("/api/automation/capital-scaling/evidence/status")
    account_preview = client.get(
        "/api/automation/capital-scaling/evidence/account-truth-snapshots/preview"
    )
    account_record = client.post(
        "/api/automation/capital-scaling/evidence/account-truth-snapshots",
        json={"acknowledgement": "record_read_only_account_truth_snapshot"},
    )
    account_list = client.get(
        "/api/automation/capital-scaling/evidence/account-truth-snapshots?limit=10"
    )
    window_preview = client.post(
        "/api/automation/capital-scaling/evidence/windows/preview", json=window
    )
    window_record = client.post(
        "/api/automation/capital-scaling/evidence/windows", json=window
    )
    window_list = client.get(
        "/api/automation/capital-scaling/evidence/windows?limit=10"
    )

    assert status.status_code == 200
    assert status.json()["automatic_scale_up_enabled"] is False
    assert account_preview.status_code == 200
    assert account_record.status_code == 200
    assert account_record.json()["persisted"] is True
    assert account_list.status_code == 200
    assert window_preview.status_code == 200
    assert window_preview.json()["authority_change_applied"] is False
    assert window_record.status_code == 200
    assert window_record.json()["authority_change_applied"] is False
    assert window_list.status_code == 200
    assert ("list_account_truth", 10) in service.calls
    assert ("list_windows", 10) in service.calls


def test_capital_scaling_evidence_routes_reject_credentials(monkeypatch) -> None:
    client, _, service = _client(monkeypatch)
    window = {
        "review_window_start": (NOW - timedelta(days=35)).isoformat(),
        "review_window_end": NOW.isoformat(),
        "broker_password": "must-not-be-accepted",
    }

    window_response = client.post(
        "/api/automation/capital-scaling/evidence/windows", json=window
    )
    snapshot_response = client.post(
        "/api/automation/capital-scaling/evidence/account-truth-snapshots",
        json={
            "acknowledgement": "record_read_only_account_truth_snapshot",
            "broker_token": "must-not-be-accepted",
        },
    )

    assert window_response.status_code == 422
    assert snapshot_response.status_code == 422
    assert not any(
        call[0] in {"record_window", "record_account_truth"} for call in service.calls
    )


def test_capital_scaling_evidence_route_maps_invalid_window_to_validation_error(
    monkeypatch,
) -> None:
    client, _, _ = _client(monkeypatch)

    response = client.post(
        "/api/automation/capital-scaling/evidence/windows/preview",
        json={
            "review_window_start": "2026-06-01T00:00:00",
            "review_window_end": NOW.isoformat(),
        },
    )

    assert response.status_code == 422
    assert "timezone-aware" in response.json()["detail"]


def test_create_app_registers_capital_scaling_review_routes() -> None:
    app = create_app({"live_auto_start": False})
    paths = {route.path for route in app.routes}

    assert "/api/automation/capital-scaling/status" in paths
    assert "/api/automation/capital-scaling/reviews/preview" in paths
    assert "/api/automation/capital-scaling/reviews/evaluations" in paths
    assert "/api/automation/capital-scaling/reviews/decisions" in paths
    assert "/api/automation/capital-scaling/evidence/status" in paths
    assert "/api/automation/capital-scaling/evidence/account-truth-snapshots" in paths
    assert "/api/automation/capital-scaling/evidence/windows/preview" in paths
    assert "/api/automation/capital-scaling/evidence/windows" in paths
