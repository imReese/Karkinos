from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from server.ai_runtime.contracts import content_fingerprint
from server.db import AppDatabase
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_selection,
)
from tests.ai_shadow_strategy_fixtures import seed_ai_shadow_canonical_sources


def _draft(ordinal: int) -> dict:
    return {
        "draft_id": f"draft-{ordinal}",
        "economic_hypothesis": f"Hypothesis {ordinal}",
        "risk_impact": "Research-only risk statement.",
        "failure_conditions": ["OOS evidence drifts"],
        "limitations": ["Historical evidence only"],
        "anti_lookahead_assumptions": ["Signals use closed daily bars"],
        "formula_ast": {
            "schema_version": "karkinos.formula_ast.v1",
            "entry": {"op": "const", "value": True},
            "exit": {"op": "const", "value": False},
            "position_size": {"op": "const", "value": 0.1},
        },
        "formula_fingerprint": f"sha256:{ordinal:064x}",
        "parameter_values": {},
        "parameter_ranges": {},
        "selected_universe": ["510300"],
        "dataset_snapshot_id": "sha256:frozen-market",
        "test_window": {"start_date": "2025-01-01", "end_date": "2026-08-11"},
        "frequency": "1d",
        "cost_model_reference": "reviewed-account-costs",
        "validation": {"status": "valid", "errors": []},
    }


def _passed_candidates(tmp_path: Path) -> tuple[AppDatabase, list[dict]]:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    comparison = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-daily-selection",
        critique_id="critique-daily-selection",
    )
    candidates = []
    for ordinal in range(1, 6):
        candidate_comparison = deepcopy(comparison)
        candidate_comparison["iteration_lineage"] = {
            "iteration_number": ordinal,
            "total_iterations": 5,
            "formula_fingerprint": f"sha256:{ordinal:064x}",
            "parent_candidate_id": (
                None if ordinal == 1 else f"candidate-{ordinal - 1}"
            ),
            "parent_draft_id": None if ordinal == 1 else f"draft-{ordinal - 1}",
            "parent_formula_fingerprint": (
                None if ordinal == 1 else f"sha256:{ordinal - 1:064x}"
            ),
            "iteration_context_fingerprint": f"sha256:{ordinal + 100:064x}",
            "sequential_feedback_bound": True,
        }
        gate = candidate_comparison["promotion_gate"]
        for check in gate["checks"]:
            if check["name"] == "after_tax_excess_return":
                check["evidence"]["after_tax_excess_return"] = ordinal / 100
        gate.pop("evidence_fingerprint")
        gate["evidence_fingerprint"] = content_fingerprint(gate)
        candidates.append(
            {
                "candidate_id": f"candidate-{ordinal}",
                "run_id": "run-daily-selection",
                "session_id": "session-daily-selection",
                "draft_id": f"draft-{ordinal}",
                "status": "awaiting_human_approval",
                "recommendation": "paper_shadow_review",
                "comparison": candidate_comparison,
            }
        )
    return db, candidates


@pytest.mark.unit
@pytest.mark.trading_safety
def test_five_complete_sequential_rounds_get_one_deterministic_winner_and_backup(
    tmp_path,
) -> None:
    _, candidates = _passed_candidates(tmp_path)
    artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db", tmp_path / "strategy-research-backups"
    )

    result = artifacts.record_daily_artifacts(
        run={
            "run_id": "run-daily-selection",
            "market_date": "2026-08-11",
            "input_fingerprint": "sha256:daily-input",
        },
        candidates=candidates,
        drafts=[_draft(ordinal) for ordinal in range(1, 6)],
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-11T08:30:00+00:00",
    )

    assert result["selection"]["status"] == "winner_selected"
    assert result["selection"]["winner_candidate_id"] == "candidate-5"
    assert result["selection"]["eligible_candidate_count"] == 5
    assert result["selection"]["ranking_method"]["weighted_average_used"] is False
    assert result["selection"]["ranking_method"]["deepseek_selects_winner"] is False
    assert (
        result["selection"]["ranking_method"]["sequential_iteration_lineage_required"]
        is True
    )
    assert result["selection"]["incumbent_strategy_state_changed"] is False
    assert result["selection"]["implies_daily_trading_no_action"] is False
    assert result["backup"]["verification_status"] == "verified"
    assert result["backup"]["contains_private_account_identifiers"] is False
    assert result["backup"]["contains_broker_export_rows"] is False
    assert (
        artifacts.require_verified_winner(
            candidate_id="candidate-5", run_id="run-daily-selection"
        )["backup"]["verification_status"]
        == "verified"
    )
    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="candidate_is_not_verified_daily_winner",
    ):
        artifacts.require_verified_winner(
            candidate_id="candidate-2", run_id="run-daily-selection"
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_incomplete_or_nonpassing_daily_set_is_no_selection(tmp_path) -> None:
    _, passed = _passed_candidates(tmp_path)
    incomplete = build_daily_strategy_selection(
        run={"run_id": "run-incomplete", "market_date": "2026-08-11"},
        candidates=passed[:4],
        expected_candidate_count=5,
        created_at="2026-08-11T08:30:00+00:00",
    )
    blocked = [
        {
            **candidate,
            "status": "research_blocked",
            "recommendation": "keep_researching",
        }
        for candidate in passed
    ]
    no_pass = build_daily_strategy_selection(
        run={"run_id": "run-no-pass", "market_date": "2026-08-11"},
        candidates=blocked,
        expected_candidate_count=5,
        created_at="2026-08-11T08:30:00+00:00",
    )

    assert incomplete["status"] == "no_selection"
    assert incomplete["winner_candidate_id"] is None
    assert "configured_candidate_set_incomplete" in incomplete["blockers"]
    assert no_pass["status"] == "no_selection"
    assert no_pass["winner_candidate_id"] is None
    assert "no_candidate_passed_advancement_gate" in no_pass["blockers"]
    assert no_pass["incumbent_strategy_policy"] == (
        "leave_current_human_approved_strategy_unchanged"
    )
    assert no_pass["incumbent_strategy_state_changed"] is False
    assert no_pass["daily_trading_decision_status"] == "not_evaluated"
    assert no_pass["implies_daily_trading_no_action"] is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_mismatched_sequential_parent_artifact_is_no_selection(tmp_path) -> None:
    _, candidates = _passed_candidates(tmp_path)
    candidates[1]["comparison"]["iteration_lineage"][
        "parent_draft_id"
    ] = "unrelated-draft"

    result = build_daily_strategy_selection(
        run={"run_id": "run-daily-selection", "market_date": "2026-08-11"},
        candidates=candidates,
        expected_candidate_count=5,
        created_at="2026-08-11T08:30:00+00:00",
    )

    assert result["status"] == "no_selection"
    assert result["winner_candidate_id"] is None
    assert "candidate_iteration_lineage_invalid" in result["blockers"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_tampered_daily_backup_blocks_winner_approval(tmp_path) -> None:
    _, candidates = _passed_candidates(tmp_path)
    backup_root = tmp_path / "strategy-research-backups"
    artifacts = DailyStrategyArtifactStore(tmp_path / "app.db", backup_root)
    result = artifacts.record_daily_artifacts(
        run={
            "run_id": "run-daily-selection",
            "market_date": "2026-08-11",
            "input_fingerprint": "sha256:daily-input",
        },
        candidates=candidates,
        drafts=[_draft(ordinal) for ordinal in range(1, 6)],
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-11T08:30:00+00:00",
    )
    backup_path = backup_root / result["backup"]["relative_path"]
    backup_path.write_text("{}\n", encoding="utf-8")

    assert artifacts.list_backups()[0]["verification_status"] == (
        "fingerprint_mismatch"
    )
    with pytest.raises(
        DailyStrategyArtifactRejected, match="daily_strategy_backup_not_verified"
    ):
        artifacts.require_verified_winner(
            candidate_id="candidate-5", run_id="run-daily-selection"
        )
