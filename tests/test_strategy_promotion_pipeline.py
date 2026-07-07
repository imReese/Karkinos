from __future__ import annotations

from server.db import AppDatabase
from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline


def _service(tmp_path) -> StrategyPromotionPipeline:
    db = AppDatabase(tmp_path / "strategy-promotion.db")
    db.init_sync()
    return StrategyPromotionPipeline(db=db)


def _readiness(*, promotable: bool = True) -> dict:
    missing = [] if promotable else ["paper_shadow_divergence_review"]
    return {
        "strategy_id": "dual_ma",
        "promotion_status": (
            "promotable_for_paper_review" if promotable else "not_promotable"
        ),
        "is_promotable": promotable,
        "missing_requirements": missing,
        "backtest_result_id": 7,
    }


def test_pipeline_persists_blocked_research_state(tmp_path) -> None:
    service = _service(tmp_path)

    state = service.evaluate_readiness(_readiness(promotable=False), actor="test")

    assert state["strategy_id"] == "dual_ma"
    assert state["stage"] == "research"
    assert state["gate_status"] == "blocked"
    assert state["missing_requirements"] == ["paper_shadow_divergence_review"]
    assert state["live_like_enabled"] is False


def test_pipeline_promotes_ready_strategy_to_paper_shadow(tmp_path) -> None:
    service = _service(tmp_path)
    service.evaluate_readiness(_readiness(promotable=True), actor="test")

    state = service.request_promotion(
        "dual_ma",
        target_stage="paper_shadow",
        readiness=_readiness(promotable=True),
        actor="test",
    )

    assert state["stage"] == "paper_shadow"
    assert state["gate_status"] == "paper_shadow_enabled"
    assert state["live_like_enabled"] is False
    events = service.list_events("dual_ma")
    assert events[-1]["event_type"] == "promoted_to_paper_shadow"


def test_pipeline_rejects_live_like_promotion_by_default(tmp_path) -> None:
    service = _service(tmp_path)
    service.evaluate_readiness(_readiness(promotable=True), actor="test")

    try:
        service.request_promotion(
            "dual_ma",
            target_stage="live_like",
            readiness=_readiness(promotable=True),
            actor="test",
        )
    except ValueError as exc:
        assert "live-like promotion is disabled by default" in str(exc)
    else:
        raise AssertionError("expected live-like promotion to be rejected")


def test_pipeline_records_pause_and_retire_as_audit_only_lifecycle_states(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    service.evaluate_readiness(_readiness(promotable=True), actor="test")
    service.request_promotion(
        "dual_ma",
        target_stage="paper_shadow",
        readiness=_readiness(promotable=True),
        actor="test",
    )

    paused = service.request_lifecycle_transition(
        "dual_ma",
        target_stage="paused",
        reason="operator paused after divergence review",
        actor="operator",
    )

    assert paused["stage"] == "paused"
    assert paused["gate_status"] == "paused"
    assert paused["live_like_enabled"] is False
    assert paused["lifecycle"]["audit_only"] is True
    assert paused["lifecycle"]["does_not_authorize_execution"] is True
    assert "controlled_bridge_pilot" in paused["lifecycle"]["disabled_stages"]
    assert paused["payload"]["reason"] == "operator paused after divergence review"
    assert paused["payload"]["does_not_submit_broker_orders"] is True

    retired = service.request_lifecycle_transition(
        "dual_ma",
        target_stage="retired",
        reason="strategy retired by operator",
        actor="operator",
    )

    assert retired["stage"] == "retired"
    assert retired["gate_status"] == "retired"
    assert retired["live_like_enabled"] is False
    assert retired["lifecycle"]["terminal"] is True
    events = service.list_events("dual_ma")
    assert [event["event_type"] for event in events][-2:] == [
        "lifecycle_paused",
        "lifecycle_retired",
    ]


def test_pipeline_rejects_controlled_bridge_pilot_lifecycle_by_default(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    service.evaluate_readiness(_readiness(promotable=True), actor="test")
    service.request_promotion(
        "dual_ma",
        target_stage="paper_shadow",
        readiness=_readiness(promotable=True),
        actor="test",
    )

    try:
        service.request_lifecycle_transition(
            "dual_ma",
            target_stage="controlled_bridge_pilot",
            reason="operator requested pilot",
            actor="operator",
        )
    except ValueError as exc:
        assert "controlled bridge pilot is disabled by default" in str(exc)
    else:
        raise AssertionError("expected controlled bridge pilot to be rejected")

    state = service.list_states()[0]
    assert state["stage"] == "paper_shadow"
    assert state["live_like_enabled"] is False
    events = service.list_events("dual_ma")
    assert events[-1]["event_type"] == "controlled_bridge_pilot_rejected"
    assert events[-1]["to_stage"] == "controlled_bridge_pilot_blocked"
