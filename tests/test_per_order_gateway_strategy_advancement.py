from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    StrategyAdvancementGate,
)
from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    ShadowResearchStore,
)
from server.services.per_order_gateway_evidence import _resolve_decision_action
from server.services.reviewed_fee_schedule import (
    REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    ReviewedFeeScheduleReviewRepository,
)
from server.services.strategy_promotion_pipeline import (
    STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
    StrategyPromotionPipeline,
    resolve_strategy_order_generation_gate,
)
from tests.ai_shadow_strategy_fixtures import (
    seed_ai_shadow_canonical_sources,
    seed_approved_ai_shadow_strategy,
)


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


def test_generic_promotion_state_cannot_become_order_evidence(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    readiness = {
        "strategy_id": "reviewed_candidate_strategy",
        "promotion_status": "promotable_for_paper_review",
        "is_promotable": True,
        "missing_requirements": [],
        "backtest_result_id": 17,
        "strategy_advancement_gate": _passed_gate(),
    }
    pipeline = StrategyPromotionPipeline(db=db)
    state = pipeline.evaluate_readiness(readiness, actor="human:owner")
    assert state["gate_status"] == "blocked"
    assert state["missing_requirements"] == [
        "evidence_owned_candidate_approval_missing"
    ]
    db.upsert_action_task_sync(
        source_signal_id=77,
        symbol="510300.SH",
        title="reviewed generic candidate fixture",
        detail="ticket evidence must recheck the exact promotion review",
        direction="buy",
        urgency="normal",
        target_weight=0.01,
        price=4.0,
        strategy_id=readiness["strategy_id"],
        timestamp="2026-08-12T08:00:00+00:00",
        asset_class="fund",
    )
    action = db.get_action_tasks_sync(limit=1)[0]

    source, blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": readiness["strategy_id"]},
    )

    assert source["resolution_status"] == "resolved_blocked"
    assert source["strategy_promotion"]["status"] == "blocked"
    assert (
        "gateway_evidence_strategy_advancement:"
        "strategy_promotion_source_not_evidence_owned" in blockers
    )


def test_reserved_ai_shadow_order_requires_canonical_strategy_advancement_binding(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    candidate_id = "candidate-without-approval"
    strategy_id = f"ai_formula_shadow:{candidate_id}"
    db.upsert_action_task_sync(
        source_signal_id=101,
        symbol="510300.SH",
        title="reserved strategy fixture",
        detail="must fail closed without canonical advancement facts",
        direction="buy",
        urgency="normal",
        target_weight=0.01,
        price=4.0,
        strategy_id=strategy_id,
        timestamp="2026-08-12T08:00:00+00:00",
        asset_class="fund",
    )
    action = db.get_action_tasks_sync(limit=1)[0]

    source, blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )

    assert source["resolution_status"] == "resolved_blocked"
    assert source["strategy_promotion"]["status"] == "blocked"
    assert (
        "gateway_evidence_strategy_advancement:"
        "ai_shadow_candidate_approval_binding_missing"
    ) in blockers


def test_reserved_ai_shadow_order_resolves_exact_canonical_advancement_binding(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="approved",
        baseline_result_id=1,
        candidate_result_id=2,
    )
    candidate = strategy["candidate"]
    approval = strategy["approval"]
    readiness = strategy["readiness"]
    comparison = candidate["comparison"]
    strategy_id = strategy["strategy_id"]
    pipeline = StrategyPromotionPipeline(db=db)
    db.upsert_action_task_sync(
        source_signal_id=202,
        symbol="510300.SH",
        title="approved reserved strategy fixture",
        detail="must bind the exact canonical advancement facts",
        direction="buy",
        urgency="normal",
        target_weight=0.01,
        price=4.0,
        strategy_id=strategy_id,
        timestamp="2026-08-12T08:00:00+00:00",
        asset_class="fund",
    )
    action = db.get_action_tasks_sync(limit=1)[0]

    source, blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )

    assert blockers == []
    assert source["resolution_status"] == "resolved_clear"
    expected_promotion = {
        "status": "pass",
        "strategy_id": strategy_id,
        "candidate_id": candidate["candidate_id"],
        "stage": "paper_shadow",
        "gate_status": "paper_shadow_enabled",
        "backtest_result_id": 2,
        "comparison_fingerprint": content_fingerprint(comparison),
        "human_approval_id": approval["promotion_id"],
        "live_like_enabled": False,
    }
    assert {
        key: source["strategy_promotion"][key] for key in expected_promotion
    } == expected_promotion
    assert source["strategy_promotion"]["fee_schedule_binding"][
        "fee_schedule_review_id"
    ].startswith("fee_review_")
    order_generation_gate, order_generation_blockers = (
        resolve_strategy_order_generation_gate(
            db,
            strategy_id,
            as_of_date="2026-08-12",
        )
    )
    assert order_generation_blockers == []
    assert order_generation_gate["status"] == "pass"
    assert order_generation_gate["paper_shadow_evaluation_only"] is True
    assert order_generation_gate["does_not_authorize_execution"] is True
    assert order_generation_gate["does_not_change_capital_authority"] is True

    pipeline.request_lifecycle_transition(
        strategy_id,
        target_stage="paused",
        reason="human revoked the candidate after paper/shadow review",
        actor="human:owner",
        confirmation=STRATEGY_LIFECYCLE_SAFETY_CONFIRMATION,
    )
    paused_source, paused_blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )
    assert paused_source["resolution_status"] == "resolved_blocked"
    assert (
        "gateway_evidence_strategy_advancement:"
        "ai_shadow_strategy_not_in_paper_shadow" in paused_blockers
    )

    pipeline.evaluate_readiness(readiness, actor="human:owner")
    pipeline.request_promotion(
        strategy_id,
        target_stage="paper_shadow",
        readiness=readiness,
        actor="human:owner",
        confirmation=STRATEGY_PAPER_SHADOW_PROMOTION_CONFIRMATION,
        review_note="Re-reviewed after explicit pause.",
    )
    reapproved_state = next(
        item for item in pipeline.list_states() if item["strategy_id"] == strategy_id
    )
    assert reapproved_state["payload"]["human_review"]["review_note"] == (
        "Re-reviewed after explicit pause."
    )
    assert (
        reapproved_state["payload"]["human_review"][
            "strategy_advancement_gate_fingerprint"
        ]
        == comparison["promotion_gate"]["evidence_fingerprint"]
    )
    reapproved_source, reapproved_blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )
    assert reapproved_blockers == []
    assert reapproved_source["strategy_promotion"]["human_review_note_recorded"] is True

    fee_reviews = ReviewedFeeScheduleReviewRepository(db._path)
    active_review = fee_reviews.get_latest_review()
    assert active_review is not None
    fee_reviews.revoke_latest(
        expected_review_id=active_review.review_id,
        expected_review_fingerprint=active_review.review_fingerprint,
        reviewer="human_owner",
        confirmation=REVIEWED_FEE_SCHEDULE_REVOCATION_CONFIRMATION,
    )
    revoked_source, revoked_blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )
    assert revoked_source["resolution_status"] == "resolved_blocked"
    assert (
        "gateway_evidence_strategy_advancement:"
        "ai_shadow_reviewed_fee_schedule_review_revoked"
    ) in revoked_blockers

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE backtest_results SET total_return = ? WHERE id = ?",
            (0.99, 2),
        )
    drifted_source, drifted_blockers = _resolve_decision_action(
        identifier=str(action["id"]),
        db=db,
        order={"symbol": "510300.SH", "side": "buy"},
        capital_scope={"strategy_id": strategy_id},
    )

    assert drifted_source["resolution_status"] == "resolved_blocked"
    assert (
        "gateway_evidence_strategy_advancement:ai_shadow_candidate_source_drift"
        in drifted_blockers
    )


def test_reserved_ai_shadow_promotion_rebuilds_gate_from_current_sources(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    canonical_sources = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-forged-gate",
        critique_id="critique-forged-gate",
    )
    forged_gate = _passed_gate()
    comparison = {
        **canonical_sources,
        "promotion_gate": forged_gate,
    }
    candidate = store.save_candidate(
        run_id="run-forged-gate",
        session_id="session-forged-gate",
        draft_id="draft-forged-gate",
        backtest_run_id="backtest-forged-gate",
        critique_id="critique-forged-gate",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison=comparison,
        now="2026-08-12T07:00:00+00:00",
    )
    approval = store.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:owner",
        notes="Review record cannot replace current source replay.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
        now="2026-08-12T07:05:00+00:00",
    )
    readiness = {
        "schema_version": "karkinos.ai.shadow_research_promotion_readiness.v1",
        "strategy_id": f"ai_formula_shadow:{candidate['candidate_id']}",
        "promotion_status": "promotable_for_paper_review",
        "is_promotable": True,
        "missing_requirements": [],
        "backtest_result_id": 2,
        "candidate_id": candidate["candidate_id"],
        "critique_id": "critique-forged-gate",
        "comparison_fingerprint": content_fingerprint(comparison),
        "human_approval_id": approval["promotion_id"],
        "strategy_advancement_gate": forged_gate,
        "live_like_enabled": False,
        "broker_submission_enabled": False,
    }

    with pytest.raises(
        ValueError,
        match="ai_shadow_strategy_advancement_gate_current_source_mismatch",
    ):
        StrategyPromotionPipeline(db=db).evaluate_readiness(
            readiness,
            actor="human:owner",
        )

    assert db.get_strategy_promotion_state_sync(readiness["strategy_id"]) is None


def test_reserved_ai_shadow_order_rechecks_research_run_account_binding(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="account-binding",
        baseline_result_id=1,
        candidate_result_id=2,
    )

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE ai_shadow_research_runs "
            "SET research_context_id = ?, valuation_snapshot_id = ? "
            "WHERE run_id = ?",
            (
                "valuation-conflicting",
                "valuation-conflicting",
                strategy["candidate"]["run_id"],
            ),
        )

    gate, blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )

    assert gate["status"] == "blocked"
    assert "ai_shadow_research_account_capital_binding_drift" in blockers
    assert gate["does_not_create_order"] is True
    assert gate["does_not_authorize_execution"] is True
    assert gate["does_not_change_capital_authority"] is True


def test_reserved_ai_shadow_order_rechecks_daily_strategy_backup(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="daily-backup",
        baseline_result_id=1,
        candidate_result_id=2,
    )
    verified_gate, verified_blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )
    assert verified_blockers == []
    assert verified_gate["promotion"]["daily_strategy_artifact_binding"] == (
        strategy["readiness"]["daily_strategy_artifact_binding"]
    )

    backup_path = (
        Path(db._path).parent
        / "strategy-research-backups"
        / strategy["daily_artifacts"]["backup"]["relative_path"]
    )
    backup_path.unlink()
    gate, blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )

    assert gate["status"] == "blocked"
    assert "ai_shadow_daily_strategy_artifact_not_verified" in blockers
    assert gate["does_not_create_order"] is True
    assert gate["does_not_authorize_execution"] is True
    assert gate["does_not_change_capital_authority"] is True


def test_reserved_ai_shadow_order_rejects_legacy_daily_binding_gap(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="legacy-daily-binding",
        baseline_result_id=1,
        candidate_result_id=2,
    )
    row = db.get_strategy_promotion_state_sync(strategy["strategy_id"])
    assert row is not None
    payload = json.loads(row["payload_json"])
    payload["readiness"].pop("daily_strategy_artifact_binding")
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE strategy_promotion_states SET payload_json = ? "
            "WHERE strategy_id = ?",
            (json.dumps(payload, sort_keys=True), strategy["strategy_id"]),
        )

    gate, blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )

    assert gate["status"] == "blocked"
    assert "ai_shadow_readiness_daily_strategy_artifact_binding_missing" in blockers
    assert gate["broker_submission_enabled"] is False


def test_reserved_ai_shadow_order_rechecks_formula_input_binding(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="formula-binding",
        baseline_result_id=1,
        candidate_result_id=2,
    )

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE ai_strategy_formula_backtests SET dataset_snapshot_id = ? "
            "WHERE backtest_run_id = ?",
            ("sha256:" + "f" * 64, strategy["candidate"]["backtest_run_id"]),
        )

    gate, blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )

    assert gate["status"] == "blocked"
    assert "ai_shadow_canonical_backtest_binding_drift" in blockers
    assert gate["paper_shadow_evaluation_only"] is True
    assert gate["broker_submission_enabled"] is False


def test_reserved_ai_shadow_order_blocks_unreproducible_frozen_dataset(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    strategy = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="dataset-replay",
        baseline_result_id=1,
        candidate_result_id=2,
    )

    with sqlite3.connect(tmp_path / "meta.db") as conn:
        conn.execute(
            "UPDATE market_bars_v2 SET close = 99 "
            "WHERE symbol = ? AND instrument_type = 'etf' AND timestamp = ?",
            ("510300.SH", "2026-01-05T00:00:00"),
        )

    gate, blockers = resolve_strategy_order_generation_gate(
        db,
        strategy["strategy_id"],
        as_of_date="2026-08-12",
    )

    assert gate["status"] == "blocked"
    assert "ai_shadow_dataset_replay_not_reproducible" in blockers
    replay = gate["promotion"]["dataset_replay"]
    assert replay["status"] == "blocked"
    assert replay["provider_contacted"] is False
    assert replay["parquet_fallback_used"] is False
    assert gate["does_not_create_order"] is True
    assert gate["does_not_authorize_execution"] is True
    assert gate["does_not_change_capital_authority"] is True
