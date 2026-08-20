from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.ai_runtime.strategy_research import (
    HYPOTHESIS_EXPORT_CONFIRMATION,
    STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
)
from server.app import create_app
from server.db import AppDatabase
from server.routes.ai_strategy_research import (
    ShadowResearchPolicyPayload,
    _strategy_research_model_timeout_seconds,
    create_router,
)
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_POLICY_CONFIRMATION,
)
from tests.route_assertions import registered_app_routes


class FixtureService:
    def __init__(self) -> None:
        self.requests = []

    async def generate_hypotheses(self, request):
        self.requests.append(request)
        return {
            "schema_version": "karkinos.ai.strategy_research_api.v1",
            "session_id": "session-route-001",
            "status": "completed",
            "failure_code": None,
            "drafts": [],
            "non_authoritative": True,
            "non_executable": True,
            "requires_human_review": True,
            "decision_input_created": False,
            "trade_plan_created": False,
            "authority_effect": "none",
        }


def _payload() -> dict:
    return {
        "idempotency_key": "strategy-route-001",
        "requested_by": "human:owner",
        "account_alias": "strategy-research-only",
        "research_question": "Should this formula be tested?",
        "selection": {
            "saved_backtest_result_id": 17,
            "universe": ["600000"],
            "asset_classes": ["stock"],
            "dataset_snapshot_id": "sha256:dataset-001",
            "start_date": "2025-01-02",
            "end_date": "2025-01-09",
            "frequency": "1d",
            "initial_cash": 100000,
            "cost_model_reference": (
                "karkinos.backtest.reviewed_account_fee_schedule.v1:"
                f"fee_review_{'a' * 32}:{'b' * 64}"
            ),
            "valuation_snapshot_id": "valuation-route-001",
            "ledger_cutoff_id": 88,
        },
        "confirmation": HYPOTHESIS_EXPORT_CONFIRMATION,
    }


def _client(monkeypatch, service: FixtureService, db=object()) -> TestClient:
    monkeypatch.setattr(
        "server.app.get_app_state",
        lambda: SimpleNamespace(db=db),
    )
    monkeypatch.setattr(
        "server.routes.ai_strategy_research._build_write_service",
        lambda state, external: service,
    )
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


@pytest.mark.unit
def test_hypothesis_route_requires_exact_human_export_confirmation(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _payload()
    payload.pop("confirmation")

    response = client.post("/api/ai/strategy-research/hypotheses", json=payload)

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid_selection",
    [
        {"valuation_snapshot_id": None},
        {"ledger_cutoff_id": None},
        {
            "cost_model_reference": (
                "karkinos.backtest.multi_asset_commission.default.v1"
            )
        },
    ],
)
def test_hypothesis_route_requires_real_account_and_reviewed_cost_binding(
    monkeypatch,
    invalid_selection,
):
    service = FixtureService()
    client = _client(monkeypatch, service)
    payload = _payload()
    payload["selection"].update(invalid_selection)

    response = client.post("/api/ai/strategy-research/hypotheses", json=payload)

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/ai/strategy-research/backtests",
            {
                "idempotency_key": "backtest-route-001",
                "requested_by": "human:owner",
                "session_id": "session-route-001",
                "draft_id": "draft-route-001",
            },
        ),
        (
            "/api/ai/strategy-research/critiques",
            {
                "idempotency_key": "critique-route-001",
                "requested_by": "human:owner",
                "session_id": "session-route-001",
                "draft_id": "draft-route-001",
                "backtest_run_id": "backtest-route-001",
            },
        ),
        (
            "/api/ai/strategy-research/sessions/session-route-001/reviews",
            {
                "idempotency_key": "review-route-001",
                "reviewer": "human:owner",
                "disposition": "needs_revision",
                "notes": "More evidence is required.",
            },
        ),
    ],
)
def test_each_follow_on_stage_requires_its_own_exact_confirmation(
    monkeypatch, path, payload
):
    service = FixtureService()
    client = _client(monkeypatch, service)

    response = client.post(path, json=payload)

    assert response.status_code == 422
    assert service.requests == []


@pytest.mark.unit
@pytest.mark.trading_safety
def test_hypothesis_route_returns_non_executable_no_authority_contract(monkeypatch):
    service = FixtureService()
    client = _client(monkeypatch, service)

    response = client.post(
        "/api/ai/strategy-research/hypotheses",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["non_authoritative"] is True
    assert body["non_executable"] is True
    assert body["decision_input_created"] is False
    assert body["trade_plan_created"] is False
    assert body["authority_effect"] == "none"
    assert len(service.requests) == 1


@pytest.mark.unit
def test_formula_catalog_get_is_pure_and_does_not_require_database(monkeypatch):
    client = _client(monkeypatch, FixtureService(), db=None)

    response = client.get("/api/ai/strategy-research/formula-catalog")

    assert response.status_code == 200
    body = response.json()
    assert "field" in body["enabled_operators"]
    assert body["arbitrary_code_allowed"] is False
    assert body["provider_side_tools_allowed"] is False
    assert body["authority_effect"] == "none"


@pytest.mark.unit
def test_session_get_does_not_create_missing_database(monkeypatch, tmp_path):
    db_path = tmp_path / "must-not-be-created.db"
    client = _client(
        monkeypatch,
        FixtureService(),
        db=SimpleNamespace(_path=db_path),
    )

    response = client.get("/api/ai/strategy-research/sessions/missing")

    assert response.status_code == 404
    assert not db_path.exists()


@pytest.mark.unit
@pytest.mark.trading_safety
def test_shadow_status_get_is_provider_free_and_does_not_initialize_shadow_tables(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "app.db"
    db = AppDatabase(db_path)
    db.init_sync()
    with sqlite3.connect(db_path) as conn:
        before = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    client = _client(monkeypatch, FixtureService(), db=db)

    response = client.get("/api/ai/strategy-research/shadow-automation")

    assert response.status_code == 200
    body = response.json()
    assert body["policy"]["enabled"] is False
    assert body["candidates"] == []
    assert body["daily_selections"] == []
    assert body["daily_backups"] == []
    assert body["daily_winner_candidate_id"] is None
    assert body["broker_submission_enabled"] is False
    with sqlite3.connect(db_path) as conn:
        after = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert after == before
    assert not any(name.startswith("ai_shadow_research_") for name in after)


@pytest.mark.unit
def test_shadow_policy_accepts_five_sequential_iterations_without_daily_budget():
    payload = {
        "enabled": True,
        "after_close_time": "15:30",
        "max_provider_calls_per_market_date": 10,
        "daily_token_budget": None,
        "token_budget_mode": "unbounded_daily",
        "max_candidates_per_run": 5,
        "baseline_backtest_result_id": 8,
        "require_complete_account_evidence": True,
        "research_question": "Generate five sequential revisions.",
        "updated_by": "human:owner",
        "confirmation": SHADOW_RESEARCH_POLICY_CONFIRMATION,
    }

    assert (
        ShadowResearchPolicyPayload.model_validate(payload).max_candidates_per_run == 5
    )
    with pytest.raises(ValidationError):
        ShadowResearchPolicyPayload.model_validate(
            {**payload, "max_provider_calls_per_market_date": 11}
        )
    with pytest.raises(ValidationError):
        ShadowResearchPolicyPayload.model_validate(
            {**payload, "max_candidates_per_run": 6}
        )
    with pytest.raises(ValidationError):
        ShadowResearchPolicyPayload.model_validate(
            {**payload, "max_provider_calls_per_market_date": 9}
        )
    with pytest.raises(ValidationError):
        ShadowResearchPolicyPayload.model_validate(
            {
                **payload,
                "daily_token_budget": STRATEGY_RESEARCH_PROVIDER_TOKEN_RESERVATION,
            }
        )


@pytest.mark.unit
def test_main_app_registers_explicit_strategy_research_routes_only():
    app = create_app({"live_auto_start": False})
    routes = {
        (route.path, method)
        for route in registered_app_routes(app)
        for method in getattr(route, "methods", set())
    }

    assert ("/api/ai/strategy-research/formula-catalog", "GET") in routes
    assert ("/api/ai/strategy-research/hypotheses", "POST") in routes
    assert ("/api/ai/strategy-research/backtests", "POST") in routes
    assert ("/api/ai/strategy-research/critiques", "POST") in routes
    assert ("/api/ai/strategy-research/shadow-automation", "GET") in routes
    assert (
        "/api/ai/strategy-research/shadow-automation/policy",
        "PUT",
    ) in routes
    assert ("/api/ai/strategy-research/shadow-automation/run", "POST") in routes
    assert (
        "/api/ai/strategy-research/shadow-candidates/{candidate_id}/paper-shadow-approvals",
        "POST",
    ) in routes
    assert ("/api/ai/strategy-research/hypotheses", "GET") not in routes
    assert not any(
        "submit" in path or "cancel" in path
        for path, _ in routes
        if "strategy-research" in path
    )


@pytest.mark.unit
def test_deepseek_strategy_research_timeout_is_five_minutes():
    deepseek = SimpleNamespace(provider_id="DeepSeek")
    other_provider = SimpleNamespace(provider_id="compatible-provider")

    assert _strategy_research_model_timeout_seconds(deepseek) == 300.0
    assert _strategy_research_model_timeout_seconds(other_provider) == 180.0
    assert _strategy_research_model_timeout_seconds(None) == 180.0
