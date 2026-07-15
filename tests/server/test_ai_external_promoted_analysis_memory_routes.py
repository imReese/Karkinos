from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ai_runtime.external_promoted_analysis_memory import (
    ExternalPromotedAnalysisMemoryRejected,
)
from server.app import create_app
from server.routes.ai_external_promoted_analysis_memory import create_router
from tests.route_assertions import registered_app_routes


class FixtureValue:
    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        return self.payload


class FixtureService:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def _result(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return FixtureValue(
            {
                "promotion_id": "ai-external-promoted-analysis-memory-fixture",
                "review_id": "ai-external-promoted-analysis-review-fixture",
                "effective_status": "recall_eligible",
                "memory_recall_eligible": True,
                "automatic_recall_enabled": False,
                "retrieval_contract_available": True,
                "retrieval_contract_version": (
                    "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
                ),
                "legacy_phase_1_12_contract_modified": False,
                "external_model_invocation_count": 0,
                "decision_handoff_enabled": False,
                "trade_plan_created": False,
                "authority_effect": "none",
            }
        )

    def promote(self, review_id, request):
        return self._result("promote", review_id, request)

    def revoke(self, promotion_id, request):
        return self._result("revoke", promotion_id, request)

    def list(self, *, review_id, limit):
        self.calls.append(("list", review_id, limit))
        if self.error is not None:
            raise self.error
        return (self._result("listed"),)

    def get(self, promotion_id):
        return self._result("get", promotion_id)

    def replay(self, promotion_id):
        return self._result("replay", promotion_id)


def _client(monkeypatch, service):
    initialize_calls = []
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=object()),
    )

    def build(state, *, initialize):
        initialize_calls.append(initialize)
        return service

    monkeypatch.setattr(
        "server.routes.ai_external_promoted_analysis_memory."
        "build_external_promoted_analysis_memory_promotion_service",
        build,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app), initialize_calls


def _promotion_payload():
    return {
        "idempotency_key": "external-promoted-analysis-memory-route-001",
        "promoted_by": "human:reese",
        "rationale": "保留精确来源链，供未来显式重绑定。",
        "confirmation": (
            "promote_reviewed_promoted_memory_analysis_to_revocable_historical_"
            "memory_without_current_fact_decision_or_trade_authority"
        ),
    }


def _revocation_payload():
    return {
        "idempotency_key": "external-promoted-analysis-revocation-route-001",
        "revoked_by": "human:reese",
        "reason": "撤销召回资格但保留历史。",
        "confirmation": (
            "revoke_promoted_analysis_memory_recall_without_deleting_history_or_"
            "changing_trade_authority"
        ),
    }


@pytest.mark.unit
def test_promoted_analysis_memory_routes_require_exact_confirmations(monkeypatch):
    service = FixtureService()
    client, _ = _client(monkeypatch, service)
    promotion = _promotion_payload()
    promotion["confirmation"] = "wrong"
    revocation = _revocation_payload()
    revocation["confirmation"] = "wrong"

    assert (
        client.post(
            "/api/ai/external-promoted-memory-analysis-reviews/review/"
            "memory-promotions",
            json=promotion,
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/ai/external-promoted-analysis-memory-promotions/promotion/"
            "revocations",
            json=revocation,
        ).status_code
        == 422
    )
    assert service.calls == []


@pytest.mark.unit
def test_promoted_analysis_memory_routes_are_explicit_local_and_read_lazy(
    monkeypatch,
):
    service = FixtureService()
    client, initialize_calls = _client(monkeypatch, service)

    promoted = client.post(
        "/api/ai/external-promoted-memory-analysis-reviews/review/" "memory-promotions",
        json=_promotion_payload(),
    )
    assert promoted.status_code == 200
    assert promoted.json()["memory_recall_eligible"] is True
    assert promoted.json()["automatic_recall_enabled"] is False
    assert promoted.json()["retrieval_contract_available"] is True
    assert promoted.json()["retrieval_contract_version"] == (
        "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
    )
    assert promoted.json()["legacy_phase_1_12_contract_modified"] is False
    assert promoted.json()["external_model_invocation_count"] == 0
    assert promoted.json()["decision_handoff_enabled"] is False
    assert promoted.json()["trade_plan_created"] is False
    assert promoted.json()["authority_effect"] == "none"

    revoked = client.post(
        "/api/ai/external-promoted-analysis-memory-promotions/promotion/" "revocations",
        json=_revocation_payload(),
    )
    listed = client.get(
        "/api/ai/external-promoted-analysis-memory-promotions",
        params={"review_id": "review", "limit": 10},
    )
    fetched = client.get(
        "/api/ai/external-promoted-analysis-memory-promotions/promotion"
    )
    replayed = client.get(
        "/api/ai/external-promoted-analysis-memory-promotions/promotion/replay"
    )

    assert revoked.status_code == 200
    assert listed.status_code == fetched.status_code == replayed.status_code == 200
    assert listed.json()["automatic_recall_enabled"] is False
    assert listed.json()["retrieval_contract_available"] is True
    assert listed.json()["retrieval_contract_version"] == (
        "karkinos.ai.external_promoted_analysis_memory_retrieval.v1"
    )
    assert listed.json()["legacy_phase_1_12_contract_modified"] is False
    assert listed.json()["provider_invocation_count"] == 0
    assert initialize_calls == [True, True, False, False, False]


@pytest.mark.unit
def test_promoted_analysis_memory_routes_map_domain_errors(monkeypatch):
    service = FixtureService(
        error=ExternalPromotedAnalysisMemoryRejected("source review drifted")
    )
    client, _ = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/external-promoted-memory-analysis-reviews/review/" "memory-promotions",
        json=_promotion_payload(),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "source review drifted"


@pytest.mark.unit
def test_main_app_registers_promoted_analysis_memory_routes():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }

    assert (
        "/api/ai/external-promoted-memory-analysis-reviews/{review_id}/"
        "memory-promotions",
        "POST",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-promotions/{promotion_id}/"
        "revocations",
        "POST",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-promotions",
        "GET",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-promotions/{promotion_id}/" "replay",
        "GET",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-retrievals",
        "POST",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-retrievals",
        "GET",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-retrievals/{retrieval_id}",
        "GET",
    ) in routes
    assert (
        "/api/ai/external-promoted-analysis-memory-retrievals/{retrieval_id}/replay",
        "GET",
    ) in routes
