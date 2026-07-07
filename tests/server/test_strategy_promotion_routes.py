from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.routes.strategy_promotion import create_router


def _client_for_db(monkeypatch, db: AppDatabase) -> TestClient:
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _readiness(*, promotable: bool = True) -> dict:
    return {
        "strategy_id": "dual_ma",
        "promotion_status": (
            "promotable_for_paper_review" if promotable else "not_promotable"
        ),
        "is_promotable": promotable,
        "missing_requirements": (
            [] if promotable else ["paper_shadow_divergence_review"]
        ),
        "backtest_result_id": 7,
    }


def test_strategy_promotion_route_blocks_missing_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json={
            "target_stage": "paper_shadow",
            "readiness": _readiness(promotable=False),
        },
    )

    assert response.status_code == 409
    assert "missing readiness requirements" in response.json()["detail"]


def test_strategy_promotion_route_promotes_ready_strategy_to_paper_shadow(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json={
            "target_stage": "paper_shadow",
            "readiness": _readiness(promotable=True),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "paper_shadow"
    assert payload["live_like_enabled"] is False

    states = client.get("/api/strategy-promotion/states")
    assert states.status_code == 200
    assert states.json()[0]["strategy_id"] == "dual_ma"


def test_strategy_promotion_route_records_pause_lifecycle_event(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json={
            "target_stage": "paper_shadow",
            "readiness": _readiness(promotable=True),
        },
    )

    response = client.post(
        "/api/strategy-promotion/dual_ma/lifecycle",
        json={
            "target_stage": "paused",
            "reason": "operator paused after paper/shadow divergence review",
            "actor": "operator",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "paused"
    assert payload["gate_status"] == "paused"
    assert payload["live_like_enabled"] is False
    assert payload["lifecycle"]["audit_only"] is True
    assert payload["payload"]["does_not_submit_broker_orders"] is True

    events = client.get("/api/strategy-promotion/dual_ma/events")
    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "lifecycle_paused"


def test_strategy_promotion_route_rejects_controlled_bridge_pilot_lifecycle(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json={
            "target_stage": "paper_shadow",
            "readiness": _readiness(promotable=True),
        },
    )

    response = client.post(
        "/api/strategy-promotion/dual_ma/lifecycle",
        json={
            "target_stage": "controlled_bridge_pilot",
            "reason": "operator requested pilot",
            "actor": "operator",
        },
    )

    assert response.status_code == 409
    assert "controlled bridge pilot is disabled by default" in response.json()["detail"]

    states = client.get("/api/strategy-promotion/states")
    assert states.status_code == 200
    assert states.json()[0]["stage"] == "paper_shadow"
    assert states.json()[0]["live_like_enabled"] is False

    events = client.get("/api/strategy-promotion/dual_ma/events")
    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "controlled_bridge_pilot_rejected"
