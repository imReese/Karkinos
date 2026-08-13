from __future__ import annotations

import pytest

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.db import AppDatabase
from server.services.strategy_promotion_pipeline import (
    STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    StrategyPromotionPipeline,
    resolve_strategy_order_generation_gate,
    resolve_strategy_promotion_binding,
)


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


def test_missing_strategy_promotion_evidence_fails_closed_before_simulation(
    tmp_path,
) -> None:
    service = _service(tmp_path)

    promotion, promotion_blockers = resolve_strategy_promotion_binding(
        service._db,
        "dual_ma",
    )
    gate, blockers = resolve_strategy_order_generation_gate(
        service._db,
        "dual_ma",
        as_of_date="2026-08-13",
    )

    assert promotion["status"] == "blocked"
    assert promotion["broker_submission_enabled"] is False
    assert promotion_blockers == ["strategy_promotion_evidence_missing"]
    assert gate["status"] == "blocked"
    assert gate["paper_shadow_evaluation_only"] is True
    assert gate["does_not_create_order"] is True
    assert gate["does_not_authorize_execution"] is True
    assert gate["does_not_change_capital_authority"] is True
    assert blockers == [
        "strategy_promotion_evidence_missing",
        "strategy_promotion_not_passing",
        "strategy_not_promoted_to_paper_shadow",
        "strategy_paper_shadow_gate_not_enabled",
    ]


def test_pipeline_persists_blocked_research_state(tmp_path) -> None:
    service = _service(tmp_path)

    state = service.evaluate_readiness(_readiness(promotable=False), actor="test")

    assert state["strategy_id"] == "dual_ma"
    assert state["stage"] == "research"
    assert state["gate_status"] == "blocked"
    assert state["missing_requirements"] == [
        "paper_shadow_divergence_review",
        "strategy_advancement_gate_not_passed",
        "evidence_owned_candidate_approval_missing",
    ]
    assert state["live_like_enabled"] is False


def test_pipeline_blocks_generic_strategy_without_evidence_owned_candidate(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    readiness = service.evaluate_readiness(_readiness(promotable=True), actor="test")

    assert readiness["stage"] == "research"
    assert readiness["gate_status"] == "blocked"
    assert readiness["missing_requirements"] == [
        "evidence_owned_candidate_approval_missing"
    ]
    with pytest.raises(ValueError, match="evidence_owned_candidate_approval_missing"):
        service.request_promotion(
            "dual_ma",
            target_stage="paper_shadow",
            readiness=_readiness(promotable=True),
            actor="test",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            review_note="Reviewed deterministic gate.",
        )

    events = service.list_events("dual_ma")
    assert [event["event_type"] for event in events] == ["readiness_evaluated"]


def test_pipeline_rejects_claimed_readiness_without_gate_or_human_review(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    forged = _readiness(promotable=True)
    forged.pop("strategy_advancement_gate")

    readiness = service.evaluate_readiness(forged, actor="caller")

    assert readiness["gate_status"] == "blocked"
    assert readiness["missing_requirements"] == [
        "strategy_advancement_gate_not_passed",
        "evidence_owned_candidate_approval_missing",
    ]
    with pytest.raises(ValueError, match="reviewer is required"):
        service.request_promotion(
            "dual_ma",
            target_stage="paper_shadow",
            readiness=_readiness(promotable=True),
            actor="",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            review_note="Reviewed deterministic gate.",
        )
    with pytest.raises(ValueError, match="exact human confirmation"):
        service.request_promotion(
            "dual_ma",
            target_stage="paper_shadow",
            readiness=_readiness(promotable=True),
            actor="human:owner",
            confirmation="approve",
            review_note="Reviewed deterministic gate.",
        )
    with pytest.raises(ValueError, match="review note is required"):
        service.request_promotion(
            "dual_ma",
            target_stage="paper_shadow",
            readiness=_readiness(promotable=True),
            actor="human:owner",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            review_note="",
        )
    with pytest.raises(ValueError, match="strategy_advancement_gate_not_passed"):
        service.request_promotion(
            "dual_ma",
            target_stage="paper_shadow",
            readiness=forged,
            actor="human:owner",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            review_note="Reviewed deterministic gate.",
        )


def test_pipeline_rejects_reserved_ai_shadow_strategy_without_candidate_binding(
    tmp_path,
) -> None:
    service = _service(tmp_path)
    readiness = {
        **_readiness(promotable=True),
        "strategy_id": "ai_formula_shadow:forged-candidate",
        "schema_version": "karkinos.ai.shadow_research_promotion_readiness.v1",
        "candidate_id": "forged-candidate",
        "critique_id": "critique-forged",
        "comparison_fingerprint": "a" * 64,
        "human_approval_id": "promotion-forged",
        "live_like_enabled": False,
        "broker_submission_enabled": False,
    }

    with pytest.raises(
        ValueError,
        match="ai_shadow_candidate_approval_binding_missing",
    ):
        service.evaluate_readiness(readiness, actor="untrusted-caller")


def test_pipeline_rejects_live_like_promotion_by_default(tmp_path) -> None:
    service = _service(tmp_path)
    service.evaluate_readiness(_readiness(promotable=True), actor="test")

    try:
        service.request_promotion(
            "dual_ma",
            target_stage="live_like",
            readiness=_readiness(promotable=True),
            actor="test",
            confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
            review_note="Reviewed deterministic gate.",
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

    paused = service.request_lifecycle_transition(
        "dual_ma",
        target_stage="paused",
        reason="operator paused after divergence review",
        actor="operator",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    )

    assert paused["stage"] == "paused"
    assert paused["gate_status"] == "paused"
    assert paused["live_like_enabled"] is False
    assert paused["lifecycle"]["audit_only"] is True
    assert paused["lifecycle"]["does_not_authorize_execution"] is True
    assert "controlled_bridge_pilot" in paused["lifecycle"]["disabled_stages"]
    assert paused["payload"]["reason"] == "operator paused after divergence review"
    assert paused["payload"]["reviewer"] == "operator"
    assert paused["payload"]["manual_confirmation_recorded"] is True
    assert paused["payload"]["does_not_submit_broker_orders"] is True

    retired = service.request_lifecycle_transition(
        "dual_ma",
        target_stage="retired",
        reason="strategy retired by operator",
        actor="operator",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
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

    try:
        service.request_lifecycle_transition(
            "dual_ma",
            target_stage="controlled_bridge_pilot",
            reason="operator requested pilot",
            actor="operator",
            confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
        )
    except ValueError as exc:
        assert "controlled bridge pilot is disabled by default" in str(exc)
    else:
        raise AssertionError("expected controlled bridge pilot to be rejected")

    state = service.list_states()[0]
    assert state["stage"] == "research"
    assert state["gate_status"] == "blocked"
    assert state["live_like_enabled"] is False
    events = service.list_events("dual_ma")
    assert events[-1]["event_type"] == "controlled_bridge_pilot_rejected"
    assert events[-1]["to_stage"] == "controlled_bridge_pilot_blocked"
