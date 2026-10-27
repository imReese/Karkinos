from __future__ import annotations

import pytest

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.db import AppDatabase
from server.services.research.strategy_promotion_pipeline import (
    STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    STRATEGY_REINSTATE_CONFIRMATION,
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


def test_human_paper_shadow_promotion_preserves_other_active_strategy(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline._require_ai_shadow_readiness_binding",
        lambda db, readiness: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    strat_1_id = "ai_formula_shadow:candidate_1"
    strat_2_id = "ai_formula_shadow:candidate_2"
    readiness_strat_1 = {**_readiness(promotable=True), "strategy_id": strat_1_id}
    readiness_strat_2 = {**_readiness(promotable=True), "strategy_id": strat_2_id}

    # Promote strategy 1
    state_1 = service.request_promotion(
        strat_1_id,
        target_stage="paper_shadow",
        readiness=readiness_strat_1,
        actor="operator",
        review_note="gen 1 promotion",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    )
    assert state_1["stage"] == "paper_shadow"
    assert state_1["gate_status"] == "paper_shadow_enabled"

    # Promote strategy 2
    state_2 = service.request_promotion(
        strat_2_id,
        target_stage="paper_shadow",
        readiness=readiness_strat_2,
        actor="operator",
        review_note="gen 2 promotion",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    )
    assert state_2["stage"] == "paper_shadow"
    assert state_2["gate_status"] == "paper_shadow_enabled"

    # A human approval names no incumbent and grants no blanket replacement scope.
    states_by_id = {s["strategy_id"]: s for s in service.list_states()}
    assert states_by_id[strat_1_id]["stage"] == "paper_shadow"
    assert states_by_id[strat_1_id]["gate_status"] == "paper_shadow_enabled"
    assert states_by_id[strat_2_id]["stage"] == "paper_shadow"
    assert states_by_id[strat_2_id]["gate_status"] == "paper_shadow_enabled"

    events_1 = service.list_events(strat_1_id)
    assert not any(e["event_type"] == "lifecycle_retired" for e in events_1)


def test_lifecycle_transition_preserves_historical_readiness_and_review(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
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

    service.request_promotion(
        strat_id,
        target_stage="paper_shadow",
        readiness=readiness,
        actor="operator",
        review_note="promoted initial champion",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    )

    retired = service.request_lifecycle_transition(
        strat_id,
        target_stage="retired",
        reason="superseded by experimental challenger",
        actor="operator",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    )

    assert retired["stage"] == "retired"
    assert retired["payload"]["reason"] == "superseded by experimental challenger"
    assert retired["payload"]["readiness"] == readiness
    assert retired["payload"]["historical_human_review"]["reviewer"] == "operator"


def test_reinstate_promoted_strategy_recovers_incumbent_to_paper_shadow(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline._require_ai_shadow_readiness_binding",
        lambda db, readiness: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    strat_id = "ai_formula_shadow:candidate_champion"
    readiness = {**_readiness(promotable=True), "strategy_id": strat_id}

    service.request_promotion(
        strat_id,
        target_stage="paper_shadow",
        readiness=readiness,
        actor="operator",
        review_note="initial champion promotion",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    )

    service.request_lifecycle_transition(
        strat_id,
        target_stage="retired",
        reason="temporarily retired for challenger experiment",
        actor="operator",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    )

    # Reinstatement requires exact safety confirmation
    with pytest.raises(
        ValueError, match="reinstatement requires exact human confirmation"
    ):
        service.reinstate_promoted_strategy(
            strat_id,
            actor="operator",
            reason="challenger withdrawn, restore verified champion",
            confirmation="wrong_confirmation",
        )

    # Reinstatement restores paper_shadow using preserved historical readiness
    reinstated = service.reinstate_promoted_strategy(
        strat_id,
        actor="operator",
        reason="challenger withdrawn, restore verified champion",
        confirmation=STRATEGY_REINSTATE_CONFIRMATION,
    )

    assert reinstated["stage"] == "paper_shadow"
    assert reinstated["gate_status"] == "paper_shadow_enabled"
    assert reinstated["live_like_enabled"] is False
    assert reinstated["payload"]["reinstatement"]["reinstated_reason"] == (
        "challenger withdrawn, restore verified champion"
    )

    events = service.list_events(strat_id)
    assert events[-1]["event_type"] == "reinstated_to_paper_shadow"
    assert events[-1]["to_stage"] == "paper_shadow"
    assert events[-1]["from_stage"] == "retired"


def test_reinstate_promoted_strategy_enforces_safety_and_historical_checks(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(
        "server.services.research.strategy_promotion_pipeline._require_ai_shadow_readiness_binding",
        lambda db, readiness: None,
    )
    monkeypatch.setattr(
        "server.services.research.research_final_evaluation.require_new_publication_final_evaluation",
        lambda db, result_id, expected_candidate_id: None,
    )
    strat_id = "ai_formula_shadow:candidate_champion_safety"
    readiness = {**_readiness(promotable=True), "strategy_id": strat_id}

    # 1. Non-existent strategy cannot be reinstated
    with pytest.raises(ValueError, match="no historical promotion record found"):
        service.reinstate_promoted_strategy(
            strat_id,
            actor="operator",
            reason="restore champion",
            confirmation=STRATEGY_REINSTATE_CONFIRMATION,
            readiness=readiness,
        )

    # Promote to paper_shadow first
    service.request_promotion(
        strat_id,
        target_stage="paper_shadow",
        readiness=readiness,
        actor="operator",
        review_note="initial champion promotion",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    )

    # 2. Already in paper_shadow cannot be reinstated
    with pytest.raises(ValueError, match="already in paper_shadow"):
        service.reinstate_promoted_strategy(
            strat_id,
            actor="operator",
            reason="restore champion",
            confirmation=STRATEGY_REINSTATE_CONFIRMATION,
        )

    # Retire the strategy
    service.request_lifecycle_transition(
        strat_id,
        target_stage="retired",
        reason="challenger trial",
        actor="operator",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    )

    # 3. Automated actor cannot create human reinstatement
    with pytest.raises(
        ValueError, match="automated_decision_cannot_create_human_approval"
    ):
        service.reinstate_promoted_strategy(
            strat_id,
            actor="automation:scheduler",
            reason="auto restore",
            confirmation=STRATEGY_REINSTATE_CONFIRMATION,
        )

    # 4. Strategy ID mismatch with readiness
    mismatched_readiness = {**readiness, "strategy_id": "ai_formula_shadow:other"}
    with pytest.raises(
        ValueError, match="readiness strategy_id does not match promotion target"
    ):
        service.reinstate_promoted_strategy(
            strat_id,
            actor="operator",
            reason="restore champion",
            confirmation=STRATEGY_REINSTATE_CONFIRMATION,
            readiness=mismatched_readiness,
        )

    # 5. Successful reinstatement after checks pass
    reinstated = service.reinstate_promoted_strategy(
        strat_id,
        actor="operator",
        reason="restore champion",
        confirmation=STRATEGY_REINSTATE_CONFIRMATION,
        readiness=readiness,
    )
    assert reinstated["stage"] == "paper_shadow"
    events = service.list_events(strat_id)
    assert events[-1]["from_stage"] == "retired"
    assert events[-1]["to_stage"] == "paper_shadow"
