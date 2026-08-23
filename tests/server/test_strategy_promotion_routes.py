from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.db import AppDatabase
from server.routes.strategy_promotion import create_router
from server.services.strategy_promotion_pipeline import (
    STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
)


def _client_for_db(monkeypatch, db: AppDatabase) -> TestClient:
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
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
        "strategy_advancement_gate": _passed_gate() if promotable else None,
    }


def _passed_gate() -> dict:
    return StrategyAdvancementGate(
        status="pass",
        blockers=(),
        checks=tuple(
            {
                "name": name,
                "status": "pass",
                "blocker": None,
                "evidence": {},
            }
            for name in STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
        ),
    ).to_json_dict()


def _promotion_command(*, promotable: bool = True) -> dict:
    return {
        "target_stage": "paper_shadow",
        "readiness": _readiness(promotable=promotable),
        "actor": "human:owner",
        "review_note": "Reviewed deterministic evidence.",
        "confirmation": STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
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
        json=_promotion_command(promotable=False),
    )

    assert response.status_code == 409
    assert "missing readiness requirements" in response.json()["detail"]


def test_strategy_promotion_route_blocks_non_evidence_owned_strategy(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    response = client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json=_promotion_command(),
    )

    assert response.status_code == 409
    assert "evidence_owned_candidate_approval_missing" in response.json()["detail"]

    states = client.get("/api/strategy-promotion/states")
    assert states.status_code == 200
    assert states.json()[0]["strategy_id"] == "dual_ma"
    assert states.json()[0]["gate_status"] == "blocked"


def test_strategy_promotion_route_requires_exact_human_command_and_gate(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)

    missing_confirmation = client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json={
            "target_stage": "paper_shadow",
            "readiness": _readiness(),
            "actor": "human:owner",
            "review_note": "Reviewed deterministic evidence.",
        },
    )
    forged = _promotion_command()
    forged["readiness"].pop("strategy_advancement_gate")
    forged_response = client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json=forged,
    )

    assert missing_confirmation.status_code == 422
    assert forged_response.status_code == 409
    assert "strategy_advancement_gate_not_passed" in forged_response.json()["detail"]
    assert (
        client.get("/api/strategy-promotion/states").json()[0]["gate_status"]
        == "blocked"
    )


def test_strategy_promotion_route_records_pause_lifecycle_event(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    client.post(
        "/api/strategy-promotion/dual_ma/promote",
        json=_promotion_command(),
    )

    missing_confirmation = client.post(
        "/api/strategy-promotion/dual_ma/lifecycle",
        json={
            "target_stage": "paused",
            "reason": "operator paused after paper/shadow divergence review",
            "actor": "operator",
        },
    )
    assert missing_confirmation.status_code == 422

    response = client.post(
        "/api/strategy-promotion/dual_ma/lifecycle",
        json={
            "target_stage": "paused",
            "reason": "operator paused after paper/shadow divergence review",
            "actor": "operator",
            "confirmation": (
                "pause_or_retire_strategy_without_execution_or_capital_authority"
            ),
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
        json=_promotion_command(),
    )

    response = client.post(
        "/api/strategy-promotion/dual_ma/lifecycle",
        json={
            "target_stage": "controlled_bridge_pilot",
            "reason": "operator requested pilot",
            "actor": "operator",
            "confirmation": (
                "pause_or_retire_strategy_without_execution_or_capital_authority"
            ),
        },
    )

    assert response.status_code == 409
    assert "controlled bridge pilot is disabled by default" in response.json()["detail"]

    states = client.get("/api/strategy-promotion/states")
    assert states.status_code == 200
    assert states.json()[0]["stage"] == "research"
    assert states.json()[0]["gate_status"] == "blocked"
    assert states.json()[0]["live_like_enabled"] is False

    events = client.get("/api/strategy-promotion/dual_ma/events")
    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "controlled_bridge_pilot_rejected"
