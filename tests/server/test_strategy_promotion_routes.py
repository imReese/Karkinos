from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.db import AppDatabase
from server.routes.strategy_promotion import create_router
from server.services.research.strategy_promotion_pipeline import (
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
    state = db.get_strategy_promotion_state_sync("dual_ma")
    assert state is not None
    assert state["stage"] == "research"
    assert state["gate_status"] == "blocked"
    assert [
        event["event_type"]
        for event in db.list_strategy_promotion_events_sync("dual_ma")
    ] == ["readiness_evaluated"]


@pytest.mark.parametrize(
    ("target", "actor", "review_note", "detail"),
    [
        (
            "other_strategy",
            "human:owner",
            "Reviewed deterministic evidence.",
            "readiness strategy_id does not match promotion target",
        ),
        (
            "dual_ma",
            "automation:test",
            "Reviewed deterministic evidence.",
            "automated_decision_cannot_create_human_approval",
        ),
        (
            "dual_ma",
            "policy:test",
            "Reviewed deterministic evidence.",
            "automated_decision_cannot_create_human_approval",
        ),
        (
            "dual_ma",
            "   ",
            "Reviewed deterministic evidence.",
            "paper/shadow promotion reviewer is required",
        ),
        (
            "dual_ma",
            "human:owner",
            "   ",
            "paper/shadow promotion review note is required",
        ),
    ],
)
def test_rejected_promotion_command_preserves_existing_state_and_events(
    tmp_path, monkeypatch, target, actor, review_note, detail
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    db.upsert_strategy_promotion_state_sync(
        strategy_id="dual_ma",
        stage="paper_shadow",
        gate_status="paper_shadow_enabled",
        live_like_enabled=False,
        missing_requirements=[],
        backtest_result_id=7,
        payload={"human_review": {"reviewer": "human:owner"}},
    )
    db.record_strategy_promotion_event_sync(
        strategy_id="dual_ma",
        event_type="promoted_to_paper_shadow",
        from_stage="research",
        to_stage="paper_shadow",
        actor="human:owner",
    )
    before_state = db.get_strategy_promotion_state_sync("dual_ma")
    before_events = db.list_strategy_promotion_events_sync("dual_ma")
    client = _client_for_db(monkeypatch, db)
    command = _promotion_command()
    command.update(actor=actor, review_note=review_note)

    response = client.post(f"/api/strategy-promotion/{target}/promote", json=command)

    assert response.status_code == 409
    assert response.json()["detail"] == detail
    assert db.get_strategy_promotion_state_sync("dual_ma") == before_state
    assert db.list_strategy_promotion_events_sync("dual_ma") == before_events
    if target != "dual_ma":
        assert db.get_strategy_promotion_state_sync(target) is None
        assert db.list_strategy_promotion_events_sync(target) == []


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


@pytest.mark.parametrize(
    ("target_stage", "detail", "expected_events"),
    [
        (
            "live_like",
            "live-like promotion is disabled by default",
            ["live_like_promotion_rejected"],
        ),
        (
            "unsupported_stage",
            "unsupported promotion target: unsupported_stage",
            [],
        ),
    ],
)
def test_non_paper_promotion_preserves_its_rejection_audit(
    tmp_path, monkeypatch, target_stage, detail, expected_events
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    command = _promotion_command()
    command["target_stage"] = target_stage

    response = client.post("/api/strategy-promotion/dual_ma/promote", json=command)

    assert response.status_code == 409
    assert response.json()["detail"] == detail
    assert db.get_strategy_promotion_state_sync("dual_ma") is None
    assert [
        event["event_type"]
        for event in db.list_strategy_promotion_events_sync("dual_ma")
    ] == expected_events


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
    assert db.get_strategy_promotion_state_sync("dual_ma") is None
    assert db.list_strategy_promotion_events_sync("dual_ma") == []
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


def test_strategy_promotion_route_reinstates_retired_strategy(
    tmp_path,
    monkeypatch,
) -> None:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    client = _client_for_db(monkeypatch, db)
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline._require_ai_shadow_readiness_binding",
        lambda db, readiness: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    strat_id = "ai_formula_shadow:candidate_champion"
    readiness = {**_readiness(promotable=True), "strategy_id": strat_id}
    cmd = {**_promotion_command(), "readiness": readiness}
    promote_res = client.post(
        f"/api/strategy-promotion/{strat_id}/promote",
        json=cmd,
    )
    assert promote_res.status_code == 200

    client.post(
        f"/api/strategy-promotion/{strat_id}/lifecycle",
        json={
            "target_stage": "retired",
            "reason": "temporarily retired",
            "actor": "operator",
            "confirmation": (
                "pause_or_retire_strategy_without_execution_or_capital_authority"
            ),
        },
    )

    # 1. Reinstating non-existent strategy returns 409
    bad_res = client.post(
        "/api/strategy-promotion/non_existent/reinstate",
        json={
            "reason": "restore champion",
            "actor": "operator",
            "confirmation": (
                "reinstate_verified_strategy_to_paper_shadow_without_execution_or_capital_authority"
            ),
        },
    )
    assert bad_res.status_code == 409
    assert "no historical promotion record found" in bad_res.json()["detail"]

    # 2. Reinstating valid retired strategy succeeds
    res = client.post(
        f"/api/strategy-promotion/{strat_id}/reinstate",
        json={
            "reason": "challenger withdrawn, restore incumbent champion",
            "actor": "operator",
            "confirmation": (
                "reinstate_verified_strategy_to_paper_shadow_without_execution_or_capital_authority"
            ),
        },
    )
    assert res.status_code == 200, res.json()
    body = res.json()
    assert body["stage"] == "paper_shadow"
    assert body["gate_status"] == "paper_shadow_enabled"
    assert body["payload"]["reinstatement"]["reinstated_reason"] == (
        "challenger withdrawn, restore incumbent champion"
    )

    events = client.get(f"/api/strategy-promotion/{strat_id}/events")
    assert events.status_code == 200
    assert events.json()[-1]["event_type"] == "reinstated_to_paper_shadow"
