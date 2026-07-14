from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_research import (
    EXTERNAL_BACKTEST_REPORT_CONFIRMATION,
    ExternalBacktestReportRejected,
)
from server.ai_runtime.store import IdempotencyConflict
from server.app import create_app
from server.routes.ai_external_research import create_router
from tests.route_assertions import registered_app_routes


class FixtureResult:
    def __init__(self, status: str = "completed") -> None:
        self.workflow = SimpleNamespace(status=SimpleNamespace(value=status))
        self._status = status

    def to_dict(self) -> dict:
        return {
            "schema_version": "karkinos.ai.external_backtest_report.v1",
            "workflow_status": self._status,
            "external_context_scope": "saved_backtest_research_evidence_only",
            "account_holdings_sent": False,
            "provider_side_tools_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
        }


class FixtureService:
    def __init__(self, *, status: str = "completed", error=None) -> None:
        self.result = FixtureResult(status)
        self.error = error
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _payload() -> dict:
    return {
        "idempotency_key": "external-route-001",
        "requested_by": "human:reese",
        "research_question": "这条保存的回测证据说明了什么？",
        "account_alias": "primary",
        "backtest_result_id": 5,
        "confirmation": EXTERNAL_BACKTEST_REPORT_CONFIRMATION,
    }


def _client(monkeypatch, service: FixtureService) -> TestClient:
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )
    monkeypatch.setattr(
        "server.routes.ai_external_research.build_external_backtest_report_service",
        lambda state: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


@pytest.mark.unit
def test_external_report_route_requires_exact_human_confirmation(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post(
        "/api/ai/external-research/backtest-reports",
        json=payload,
    )

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
def test_external_report_route_returns_non_authoritative_boundary(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/external-research/backtest-reports",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["external_context_scope"] == ("saved_backtest_research_evidence_only")
    assert body["account_holdings_sent"] is False
    assert body["provider_side_tools_enabled"] is False
    assert body["trade_plan_created"] is False
    assert body["authority_effect"] == "none"
    assert len(service.requests) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (IdempotencyConflict("conflict"), 409),
        (ExternalBacktestReportRejected("evidence incomplete"), 409),
        (PermissionError("confirmation missing"), 403),
        (ValueError("invalid"), 422),
    ],
)
def test_external_report_route_maps_fail_closed_errors(
    monkeypatch,
    error,
    status_code,
):
    client = _client(monkeypatch, FixtureService(error=error))

    response = client.post(
        "/api/ai/external-research/backtest-reports",
        json=_payload(),
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


@pytest.mark.unit
def test_external_report_route_surfaces_audited_workflow_failure(monkeypatch):
    client = _client(monkeypatch, FixtureService(status="failed"))

    response = client.post(
        "/api/ai/external-research/backtest-reports",
        json=_payload(),
    )

    assert response.status_code == 502
    assert response.json()["workflow_status"] == "failed"


@pytest.mark.unit
def test_main_app_registers_only_explicit_external_report_post_route():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }

    path = "/api/ai/external-research/backtest-reports"
    assert (path, "POST") in routes
    assert (path, "GET") not in routes
