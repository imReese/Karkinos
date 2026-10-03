"""Independent shadow publication and future measurement through real HTTP/DB."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes import research_observations as routes
from server.services.research_observations import ResearchObservationService
from tests.server.test_research_observation_inputs import (
    DAYS,
    NOW,
    calendar,
    dataset,
    formula_source,
    source,
)

pytestmark = pytest.mark.product_smoke


@pytest.fixture
def journey(tmp_path, monkeypatch):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    current = [NOW]
    db._market_calendar._now = lambda tz=None: datetime(2026, 9, 1, tzinfo=timezone.utc)
    db.upsert_market_calendar_snapshot_sync(calendar())
    db.update_market_calendar_verification_sync(
        exchange="SSE",
        year=2026,
        source_fingerprint="a" * 64,
        verification_status="verified",
        official_source_url="https://example.test/calendar",
        official_source_fingerprint="b" * 64,
        verified_by="synthetic fixture",
    )
    _, ref = dataset(tmp_path / "research")
    row = source(ref)
    result_id = asyncio.run(
        db.save_backtest_result(
            config_json=row["config_json"],
            metrics_json=row["metrics_json"],
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    service = ResearchObservationService(db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: service)
    monkeypatch.setattr(
        "data.manager.DataManager.get_bars",
        lambda *args, **kwargs: pytest.fail("No provider fallback"),
    )
    app = FastAPI()
    app.include_router(routes.create_router())
    with TestClient(app) as client:
        yield client, service, current, ref, result_id


def start(client, result_id):
    request = {
        "request_id": str(uuid4()),
        "source_backtest_result_id": result_id,
        "horizon_sessions": 1,
    }
    response = client.post("/api/research-observations", json=request)
    assert response.status_code == 200, response.text
    return response.json(), request


def test_publish_restart_pause_and_measure_exact_future_interval(
    journey, tmp_path, monkeypatch
):
    client, service, current, ref, result_id = journey
    started, start_request = start(client, result_id)
    identity = started["id"]
    path = f"/api/research-observations/{identity}"
    assert started["version"] == 0
    advance = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "dataset_id": ref.dataset_id,
    }
    response = client.post(path + "/advance", json=advance)
    assert response.status_code == 200, response.text
    published = response.json()
    assert published["publication_id"] is not None, published
    detail = client.get(path).json()
    assert detail["source"]["source_code_verified"] is False
    assert detail["source"]["cost_assumptions"]["slippage_bps"] == "12.5"
    publication = detail["publications"][0]
    assert publication["published_at"] == NOW.isoformat()
    assert publication["payload"]["reference_session"] == DAYS[5].isoformat()
    assert publication["payload"]["end_session"] == DAYS[6].isoformat()
    assert publication["payload"]["risk_decision"]["status"] == "allowed"
    assert publication["payload"]["contains_fills"] is False
    assert detail["outcomes"] == []

    pause = client.post(
        path + "/pause",
        json={"request_id": str(uuid4()), "expected_version": published["version"]},
    )
    assert pause.status_code == 200, pause.text
    reopened = ResearchObservationService(service.db, clock=lambda: current[0])
    monkeypatch.setattr(routes, "_service", lambda: reopened)
    assert (
        client.post("/api/research-observations", json=start_request).json() == started
    )
    assert client.post(path + "/advance", json=advance).json() == published
    assert client.get(path).json()["lifecycle"] == "paused"

    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(tmp_path / "research", days=DAYS[:7], cutoff=current[0])
    measured = client.post(
        path + "/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": pause.json()["version"],
            "dataset_id": future.dataset_id,
        },
    )
    assert measured.status_code == 200, measured.text
    assert measured.json()["publication_id"] is None
    assert len(measured.json()["outcome_keys"]) == 1, measured.json()
    detail = client.get(path).json()
    assert detail["lifecycle"] == "paused"
    assert detail["publications"] == [publication]
    outcome = detail["outcomes"][0]
    assert outcome["dataset_id"] == future.dataset_id
    assert outcome["payload"]["status"] == "measured"
    assert Decimal(outcome["payload"]["weighted_price_response"]) == 0
    assert client.get("/api/research-observations").json()[0] == detail


def test_same_session_revision_stale_version_and_code_change_fail_closed(
    journey, monkeypatch
):
    client, _, _, ref, result_id = journey
    started, _ = start(client, result_id)
    path = f"/api/research-observations/{started['id']}"
    request = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "dataset_id": ref.dataset_id,
    }
    first = client.post(path + "/advance", json=request)
    assert first.status_code == 200, first.text
    assert first.json()["publication_id"]
    conflict = client.post(
        path + "/advance", json={**request, "request_id": str(uuid4())}
    )
    assert conflict.status_code == 409
    duplicate = client.post(
        path + "/advance",
        json={**request, "request_id": str(uuid4()), "expected_version": 1},
    )
    assert (
        duplicate.json()["last_blocker"]["code"]
        == "observation_session_already_published"
    )
    monkeypatch.setattr(
        "server.services.research_observations.observation_code_binding",
        lambda: {"changed": True},
    )
    changed = client.post(
        path + "/advance",
        json={**request, "request_id": str(uuid4()), "expected_version": 2},
    )
    assert changed.json()["last_blocker"]["code"] == "observation_code_changed"
    detail = client.get(path).json()
    assert len(detail["publications"]) == 1
    assert detail["outcomes"] == []


def test_http_policy_rejects_nonfinite_weights_and_unknown_fields(journey):
    client, _, _, _, result_id = journey
    base = {"request_id": str(uuid4()), "source_backtest_result_id": result_id}
    for extra in (
        {"max_symbol_weight": "NaN"},
        {"max_gross_weight": "Infinity"},
        {"horizon_sessions": 0},
        {"account_id": "not allowed"},
    ):
        assert (
            client.post(
                "/api/research-observations", json={**base, **extra}
            ).status_code
            == 422
        )
    assert client.get("/api/research-observations").json() == []


def test_formula_source_starts_without_ai_or_account_and_binds_new_formal_dataset(
    journey,
):
    client, service, _, ref, _ = journey
    row = formula_source()
    result_id = asyncio.run(
        service.db.save_backtest_result(
            config_json=json.dumps(row["config_json"]),
            metrics_json=json.dumps(row["metrics_json"]),
            initial_cash=100_000,
            final_equity=100_000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    started, _ = start(client, result_id)
    path = f"/api/research-observations/{started['id']}"
    response = client.post(
        path + "/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": ref.dataset_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["publication_id"], response.json()
    detail = client.get(path).json()
    assert detail["source"]["source_dataset_kind"] == "analytics_snapshot"
    assert detail["source"]["source_historical_pit_verified"] is False
    assert detail["policy"]["entry_weight"] == "1"
    assert (
        detail["source"]["formula_binding"]["formula_ast"]["position_size"]["value"]
        == 0.02
    )
    assert detail["publications"][0]["dataset_id"] == ref.dataset_id


def test_missing_dataset_is_a_durable_blocker_and_new_request_can_recover(journey):
    client, _, _, ref, result_id = journey
    started, _ = start(client, result_id)
    path = f"/api/research-observations/{started['id']}"
    missing = {
        "request_id": str(uuid4()),
        "expected_version": 0,
        "dataset_id": "sha256:" + "0" * 64,
    }
    response = client.post(path + "/advance", json=missing)
    assert response.status_code == 200, response.text
    blocked = response.json()
    assert blocked["publication_id"] is None
    assert blocked["last_blocker"]
    assert client.get(path).json()["publications"] == []
    recovered = client.post(
        path + "/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "dataset_id": ref.dataset_id,
        },
    )
    assert recovered.json()["publication_id"], recovered.text
    assert client.post(path + "/advance", json=missing).json() == blocked
    assert client.get(path).json()["last_blocker"] is None


def test_real_cross_produces_capped_target_and_nonzero_future_response(
    journey, tmp_path
):
    client, _, current, _, result_id = journey
    closes = dict(
        zip(DAYS, ("12", "11", "10", "9", "12", "10", "11", "11"), strict=True)
    )
    _, today = dataset(tmp_path / "research", closes=closes)
    started, _ = start(client, result_id)
    path = f"/api/research-observations/{started['id']}"
    publication = client.post(
        path + "/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 0,
            "dataset_id": today.dataset_id,
        },
    )
    assert publication.json()["publication_id"], publication.text
    payload = client.get(path).json()["publications"][0]["payload"]
    assert payload["forecasts"][0]["action"] == "enter"
    assert Decimal(payload["desired_weights"]["600000"]) == 1
    assert Decimal(payload["target_weights"]["600000"]) == Decimal("0.25")
    assert Decimal(payload["rebalance_weight_deltas"]["600000"]) == Decimal("0.25")
    assert payload["risk_decision"]["status"] == "allowed"
    assert payload["risk_decision"]["authorizes_execution"] is False
    current[0] = datetime(2026, 9, 22, 8, tzinfo=timezone.utc)
    _, future = dataset(
        tmp_path / "research", days=DAYS[:7], closes=closes, cutoff=current[0]
    )
    response = client.post(
        path + "/advance",
        json={
            "request_id": str(uuid4()),
            "expected_version": 1,
            "dataset_id": future.dataset_id,
        },
    )
    assert response.status_code == 200, response.text
    outcome = client.get(path).json()["outcomes"][0]["payload"]
    assert Decimal(outcome["observations"][0]["price_return"]) == Decimal("0.1")
    assert Decimal(outcome["weighted_price_response"]) == Decimal("0.025")
