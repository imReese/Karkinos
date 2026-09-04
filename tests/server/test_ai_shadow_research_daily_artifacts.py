from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.db import AppDatabase
from server.services.ai_shadow_research_automation import ShadowResearchStore
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactRejected,
    DailyStrategyArtifactStore,
    build_daily_strategy_selection,
)
from server.services.promoted_strategy_universe_scan import (
    PromotedStrategyUniverseScanService,
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


def _normalized_candidates(
    *,
    run_id: str = "run-normalized-research",
    candidate_prefix: str = "normalized-candidate",
    draft_prefix: str = "draft",
) -> list[dict]:
    candidates = []
    for ordinal in range(1, 6):
        candidates.append(
            {
                "candidate_id": f"{candidate_prefix}-{ordinal}",
                "run_id": run_id,
                "session_id": f"session-{run_id}",
                "draft_id": f"{draft_prefix}-{ordinal}",
                "critique_id": f"critique-{ordinal}",
                "status": "evaluated_research_only",
                "recommendation": "formula_research_candidate",
                "comparison": {
                    "research_capital_mode": "normalized_notional",
                    "account_qualification_status": "not_evaluated",
                    "baseline_source_fingerprint": "sha256:" + "a" * 64,
                    "candidate_source_fingerprint": (f"sha256:{ordinal + 20:064x}"),
                    "candidate": {
                        "dataset_snapshot_id": "sha256:" + "d" * 64,
                        "initial_cash": 1_000_000,
                        "total_return": ordinal / 100,
                        "mean_oos_return": ordinal / 200,
                        "worst_oos_return": ordinal / 400,
                        "sharpe": 1 + ordinal / 10,
                        "max_drawdown": 0.1,
                        "total_cost": 1_000,
                    },
                    "iteration_lineage": {
                        "iteration_number": ordinal,
                        "total_iterations": 5,
                        "formula_fingerprint": f"sha256:{ordinal:064x}",
                        "parent_candidate_id": (
                            None
                            if ordinal == 1
                            else f"{candidate_prefix}-{ordinal - 1}"
                        ),
                        "parent_draft_id": (
                            None if ordinal == 1 else f"{draft_prefix}-{ordinal - 1}"
                        ),
                        "parent_formula_fingerprint": (
                            None if ordinal == 1 else f"sha256:{ordinal - 1:064x}"
                        ),
                        "iteration_context_fingerprint": (
                            f"sha256:{ordinal + 100:064x}"
                        ),
                        "sequential_feedback_bound": True,
                    },
                    "promotion_gate": {
                        "status": "blocked",
                        "blockers": ["account_qualification_not_evaluated"],
                    },
                },
            }
        )
    return candidates


def _normalized_drafts(
    *,
    market_date: str = "2026-08-31",
    draft_prefix: str = "draft",
) -> list[dict]:
    drafts = []
    for ordinal in range(1, 6):
        draft = _draft(ordinal)
        draft["draft_id"] = f"{draft_prefix}-{ordinal}"
        draft["dataset_snapshot_id"] = "sha256:" + "d" * 64
        draft["test_window"] = {
            "start_date": "2025-01-01",
            "end_date": market_date,
        }
        draft["cost_model_reference"] = (
            "karkinos.backtest.multi_asset_commission.default.v1"
        )
        drafts.append(draft)
    return drafts


def _record_normalized_artifacts(tmp_path: Path) -> DailyStrategyArtifactStore:
    artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db", tmp_path / "strategy-research-backups"
    )
    _record_normalized_batch(
        artifacts,
        run_id="run-normalized-research",
        market_date="2026-08-31",
        candidate_prefix="normalized-candidate",
        draft_prefix="draft",
    )
    return artifacts


def _record_normalized_batch(
    artifacts: DailyStrategyArtifactStore,
    *,
    run_id: str,
    market_date: str,
    candidate_prefix: str,
    draft_prefix: str,
) -> dict:
    return artifacts.record_daily_artifacts(
        run={
            "run_id": run_id,
            "market_date": market_date,
            "input_fingerprint": "sha256:" + "e" * 64,
        },
        candidates=_normalized_candidates(
            run_id=run_id,
            candidate_prefix=candidate_prefix,
            draft_prefix=draft_prefix,
        ),
        drafts=_normalized_drafts(
            market_date=market_date,
            draft_prefix=draft_prefix,
        ),
        expected_candidate_count=5,
        run_status="completed",
        created_at=f"{market_date}T10:16:00+00:00",
    )


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
    verified = artifacts.require_verified_winner(
        candidate_id="candidate-5", run_id="run-daily-selection"
    )
    assert verified["backup"]["verification_status"] == "verified"
    assert verified["operating_constraints"]["candidate_id"] == "candidate-5"
    assert verified["operating_constraints"]["failure_conditions"] == [
        "OOS evidence drifts"
    ]
    assert verified["operating_constraints"]["automatic_enforcement_enabled"] is False
    assert verified["operating_constraints"]["human_review_required"] is True
    assert verified["operating_constraints"]["authorizes_execution"] is False
    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="candidate_is_not_verified_daily_winner",
    ):
        artifacts.require_verified_winner(
            candidate_id="candidate-2", run_id="run-daily-selection"
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_latest_verified_normalized_batch_loads_every_formula_without_authority(
    tmp_path,
) -> None:
    artifacts = _record_normalized_artifacts(tmp_path)

    batch = artifacts.load_latest_verified_research_candidate_strategies()
    candidate = artifacts.require_verified_research_candidate(
        candidate_id="normalized-candidate-2",
        run_id="run-normalized-research",
    )

    assert batch["run_id"] == "run-normalized-research"
    assert batch["expected_candidate_count"] == 5
    assert batch["research_winner_candidate_id"] == "normalized-candidate-5"
    assert batch["source_research_selection"] == {
        "schema_version": "karkinos.ai.normalized_source_selection_binding.v1",
        "universe": ["510300"],
        "asset_classes": ["stock"],
        "asset_class_policy": "daily_candidate_stock_only",
        "dataset_snapshot_id": "sha256:" + "d" * 64,
        "start_date": "2025-01-01",
        "end_date": "2026-08-31",
        "frequency": "1d",
        "initial_cash": 1_000_000.0,
        "notional_policy_id": "karkinos.ai.normalized_research_notional.cny_1m.v1",
        "cost_model_reference": ("karkinos.backtest.multi_asset_commission.default.v1"),
        "account_fact_binding": "not_applicable_strategy_only_research",
        "saved_backtest_result_id": None,
        "saved_backtest_result_id_status": ("not_present_in_privacy_minimized_backup"),
        "contains_private_account_identifiers": False,
        "authority_effect": "research_only",
    }
    assert [item["iteration_number"] for item in batch["candidate_strategies"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert candidate["candidate_id"] == "normalized-candidate-2"
    assert candidate["strategy"]["formula_ast"]["entry"]["op"] == "const"
    assert candidate["formula_fingerprint"] == "sha256:" + f"{2:064x}"
    assert len(candidate["source_comparison_fingerprint"]) == 64
    assert candidate["account_qualification_status"] == "not_evaluated"
    assert candidate["provider_contact_performed"] is False
    assert candidate["read_only"] is True
    assert candidate["authorizes_strategy_promotion"] is False
    assert candidate["authorizes_order_creation"] is False
    assert candidate["authorizes_execution"] is False
    assert candidate["changes_capital_authority"] is False
    assert candidate["authority_effect"] == "none"
    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="candidate_is_not_verified_daily_winner",
    ):
        artifacts.require_verified_winner(
            candidate_id="normalized-candidate-5",
            run_id="run-normalized-research",
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_verified_research_pairs_are_live_checked_and_oldest_first(tmp_path) -> None:
    artifacts = _record_normalized_artifacts(tmp_path)
    _record_normalized_batch(
        artifacts,
        run_id="run-newer-normalized-research",
        market_date="2026-09-01",
        candidate_prefix="newer-normalized-candidate",
        draft_prefix="newer-draft",
    )

    assert [
        item["run_id"] for item in artifacts.list_verified_research_artifact_pairs()
    ] == ["run-normalized-research", "run-newer-normalized-research"]

    oldest_backup = next(
        item
        for item in artifacts.list_backups(limit=-1)
        if item["run_id"] == "run-normalized-research"
    )
    backup_path = (
        tmp_path / "strategy-research-backups" / oldest_backup["relative_path"]
    )
    backup_path.write_text("{}", encoding="utf-8")

    assert [
        item["run_id"] for item in artifacts.list_verified_research_artifact_pairs()
    ] == ["run-newer-normalized-research"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_promoted_scan_reopens_exact_older_batch_after_new_research_batch(
    tmp_path,
) -> None:
    artifacts = _record_normalized_artifacts(tmp_path)
    old_candidate = artifacts.require_verified_research_candidate(
        candidate_id="normalized-candidate-5",
        run_id="run-normalized-research",
    )
    _record_normalized_batch(
        artifacts,
        run_id="run-newer-normalized-research",
        market_date="2026-09-01",
        candidate_prefix="newer-normalized-candidate",
        draft_prefix="newer-draft",
    )
    strategy_id = "ai_formula_shadow:normalized-candidate-5"
    db = SimpleNamespace(
        path=tmp_path / "app.db",
        list_strategy_promotion_states_sync=lambda: [
            {"strategy_id": strategy_id, "stage": "paper_shadow"}
        ],
    )
    service = object.__new__(PromotedStrategyUniverseScanService)
    service._db = db
    service._strategy_loader = service._load_strategy
    service._strategy_gate_resolver = lambda current_db, current_id, **kwargs: (
        {
            "status": "pass",
            "promotion": {
                "daily_strategy_artifact_binding": {
                    "winner_candidate_id": old_candidate["candidate_id"],
                    "run_id": old_candidate["run_id"],
                    "qualification_overlay_required": True,
                    "operating_constraints": {
                        "strategy_artifact_fingerprint": old_candidate[
                            "strategy_artifact_fingerprint"
                        ]
                    },
                },
                "qualification_binding": {"evidence_fingerprint": "sha256:" + "f" * 64},
            },
        },
        [],
    )

    latest = artifacts.load_latest_verified_research_candidate_strategies()
    promoted, blockers = service._resolve_promoted_strategies("2026-09-02")

    assert latest["run_id"] == "run-newer-normalized-research"
    assert blockers == []
    assert len(promoted) == 1
    assert promoted[0]["strategy_id"] == strategy_id
    assert promoted[0]["strategy"] == old_candidate["strategy"]
    assert (
        promoted[0]["strategy_artifact_fingerprint"]
        == old_candidate["strategy_artifact_fingerprint"]
    )

    old_backup = next(
        item
        for item in artifacts.list_backups()
        if item["run_id"] == "run-normalized-research"
    )
    (tmp_path / "strategy-research-backups" / old_backup["relative_path"]).write_text(
        "{}\n",
        encoding="utf-8",
    )
    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="daily_research_backup_not_verified",
    ):
        artifacts.require_verified_research_candidate(
            candidate_id="normalized-candidate-5",
            run_id="run-normalized-research",
        )
    drifted_promoted, drift_blockers = service._resolve_promoted_strategies(
        "2026-09-02"
    )
    assert drifted_promoted == []
    assert len(drift_blockers) == 1
    assert drift_blockers[0].startswith(f"promoted_strategy_snapshot:{strategy_id}:")


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    ("tamper", "error"),
    [
        ("duplicate_candidate", "daily_research_candidate_identity_conflict"),
        ("comparison", "daily_research_candidate_comparison_mismatch"),
        ("strategy", "daily_research_candidate_strategy_mismatch"),
    ],
)
def test_normalized_batch_fails_closed_on_cross_artifact_mismatch(
    tmp_path,
    monkeypatch,
    tamper: str,
    error: str,
) -> None:
    artifacts = _record_normalized_artifacts(tmp_path)
    payload = deepcopy(artifacts.load_latest_verified_research_artifacts()["payload"])
    if tamper == "duplicate_candidate":
        payload["candidates"][-1] = deepcopy(payload["candidates"][0])
    elif tamper == "comparison":
        payload["candidates"][0]["comparison_fingerprint"] = "sha256:" + "9" * 64
    else:
        payload["candidates"][0]["strategy"]["formula_fingerprint"] = (
            "sha256:" + "9" * 64
        )
    monkeypatch.setattr(
        artifacts,
        "_load_verified_payload",
        lambda record, **kwargs: payload,
    )

    with pytest.raises(DailyStrategyArtifactRejected, match=error):
        artifacts.load_latest_verified_research_candidate_strategies()


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


@pytest.mark.unit
@pytest.mark.trading_safety
def test_incomplete_operating_constraints_block_winner_approval(tmp_path) -> None:
    _, candidates = _passed_candidates(tmp_path)
    artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db", tmp_path / "strategy-research-backups"
    )
    drafts = [_draft(ordinal) for ordinal in range(1, 6)]
    drafts[-1]["failure_conditions"] = []
    artifacts.record_daily_artifacts(
        run={
            "run_id": "run-daily-selection",
            "market_date": "2026-08-11",
            "input_fingerprint": "sha256:daily-input",
        },
        candidates=candidates,
        drafts=drafts,
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-11T08:30:00+00:00",
    )

    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="daily_strategy_operating_constraints_incomplete",
    ):
        artifacts.require_verified_winner(
            candidate_id="candidate-5", run_id="run-daily-selection"
        )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_authorized_corrected_panel_result_atomically_supersedes_old_no_selection(
    tmp_path,
) -> None:
    _, candidates = _passed_candidates(tmp_path)
    db_path = tmp_path / "app.db"
    ShadowResearchStore(db_path).init()
    artifacts = DailyStrategyArtifactStore(
        db_path, tmp_path / "strategy-research-backups"
    )
    blocked = []
    for candidate in deepcopy(candidates):
        blocked.append(
            {
                **candidate,
                "run_id": "old-single-stock-run",
                "status": "research_blocked",
                "recommendation": "keep_researching",
            }
        )
    old_result = artifacts.record_daily_artifacts(
        run={
            "run_id": "old-single-stock-run",
            "market_date": "2026-08-21",
            "input_fingerprint": "sha256:old-single-stock",
        },
        candidates=blocked,
        drafts=[_draft(ordinal) for ordinal in range(1, 6)],
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-22T00:00:00+00:00",
    )
    assert old_result["selection"]["status"] == "no_selection"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_shadow_research_corrected_panel_rearm_authorizations
            (authorization_id, completed_run_id, market_date,
             completed_input_fingerprint, completed_selection_fingerprint,
             expected_rearm_evidence_json, expected_rearm_evidence_fingerprint,
             provider_calls_at_authorization, prior_provider_call_ceiling,
             authorized_additional_calls, provider_call_ceiling,
             approved_by, notes, created_at)
            VALUES ('corrected-auth', 'old-single-stock-run', '2026-08-21',
                    'sha256:old-single-stock', ?, '{}', 'sha256:rearm',
                    14, 14, 10, 24, 'human:owner', 'Exact 40-stock rearm.',
                    '2026-08-23T00:00:00+00:00')
            """,
            (old_result["selection"]["selection_fingerprint"],),
        )
        conn.execute("""
            INSERT INTO ai_shadow_research_corrected_panel_rearm_consumptions
            (authorization_id, replacement_run_id, replacement_input_fingerprint,
             consumed_rearm_evidence_fingerprint, consumed_at)
            VALUES ('corrected-auth', 'new-forty-stock-run',
                    'sha256:new-forty-stock', 'sha256:rearm',
                    '2026-08-23T00:01:00+00:00')
            """)

    corrected_candidates = [
        {**candidate, "run_id": "new-forty-stock-run"}
        for candidate in deepcopy(candidates)
    ]
    corrected = artifacts.record_daily_artifacts(
        run={
            "run_id": "new-forty-stock-run",
            "market_date": "2026-08-21",
            "input_fingerprint": "sha256:new-forty-stock",
        },
        candidates=corrected_candidates,
        drafts=[_draft(ordinal) for ordinal in range(1, 6)],
        expected_candidate_count=5,
        run_status="completed",
        created_at="2026-08-23T00:30:00+00:00",
    )

    assert corrected["selection"]["status"] == "winner_selected"
    assert artifacts.list_selections()[0]["run_id"] == "new-forty-stock-run"
    assert artifacts.list_backups()[0]["run_id"] == "new-forty-stock-run"
    superseded_selections = artifacts.list_superseded_selections()
    superseded_backups = artifacts.list_superseded_backups()
    assert superseded_selections[0]["run_id"] == "old-single-stock-run"
    assert superseded_selections[0]["integrity_status"] == "verified"
    assert superseded_selections[0]["superseded_by_run_id"] == ("new-forty-stock-run")
    assert superseded_backups[0]["run_id"] == "old-single-stock-run"
    assert superseded_backups[0]["verification_status"] == "verified"
    with pytest.raises(
        DailyStrategyArtifactRejected,
        match="daily_research_selection_or_backup_missing",
    ):
        artifacts.load_verified_research_artifacts(run_id="old-single-stock-run")
