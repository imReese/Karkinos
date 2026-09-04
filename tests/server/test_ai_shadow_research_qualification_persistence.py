from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
)
from server.contracts.ai_shadow_research_qualification import (
    SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
    SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
    ShadowResearchQualificationRejected,
)
from server.contracts.content_identity import canonical_json, content_fingerprint
from server.db import AppDatabase
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.persistence.daily_strategy_artifacts import (
    DailyStrategyArtifactRepository,
)
from server.persistence.daily_strategy_backups import DailyStrategyBackupStore

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]

SOURCE_RUN_ID = "ai-shadow-research:2026-08-31:sourceinput00000"
SOURCE_SELECTION = {
    "run_id": SOURCE_RUN_ID,
    "market_date": "2026-08-31",
    "selection_id": "source-selection-1",
    "status": "no_selection",
}
SOURCE_SELECTION_FINGERPRINT = content_fingerprint(SOURCE_SELECTION)


def _backup_payload() -> dict[str, object]:
    return {
        "run_id": SOURCE_RUN_ID,
        "market_date": "2026-08-31",
        "selection": {
            **SOURCE_SELECTION,
            "selection_fingerprint": SOURCE_SELECTION_FINGERPRINT,
        },
    }


def test_qualification_candidate_backtest_rolls_back_with_overlay_failure(
    tmp_path,
) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())

    def fail_after_backtest_insert(_row):
        raise RuntimeError("injected qualification overlay failure")

    with pytest.raises(RuntimeError, match="injected qualification overlay failure"):
        store.save_qualification_candidate_with_backtest(
            **_atomic_candidate_args(run, source_candidate),
            backtest_values=_backtest_values(),
            candidate_evidence_builder=fail_after_backtest_insert,
        )

    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_candidates"
            ).fetchone()[0]
            == 0
        )


def test_qualification_candidate_backtest_and_overlay_commit_once(tmp_path) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    builder_calls = 0

    def build_evidence(row):
        nonlocal builder_calls
        builder_calls += 1
        assert int(row["id"]) > 0
        return (
            {
                "research_capital_mode": "account_bound",
                "account_qualification_status": "passed",
                "promotion_gate": {"status": "passed", "blockers": []},
            },
            "qualified",
            "paper_shadow_review",
        )

    args = _atomic_candidate_args(run, source_candidate)
    candidate = store.save_qualification_candidate_with_backtest(
        **args,
        backtest_values=_backtest_values(),
        candidate_evidence_builder=build_evidence,
    )
    replay = store.save_qualification_candidate_with_backtest(
        **args,
        backtest_values=_backtest_values(),
        candidate_evidence_builder=build_evidence,
    )
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_candidate_conflict",
    ):
        store.save_qualification_candidate_with_backtest(
            **args,
            backtest_values={**_backtest_values(), "final_equity": 900001.0},
            candidate_evidence_builder=build_evidence,
        )

    assert replay == candidate
    assert builder_calls == 1
    with sqlite3.connect(store.path) as conn:
        backtests = conn.execute("SELECT id FROM backtest_results").fetchall()
        overlays = conn.execute("""
            SELECT candidate_result_id
            FROM ai_shadow_research_qualification_candidates
            """).fetchall()
    assert backtests == [(candidate["candidate_result_id"],)]
    assert overlays == [(candidate["candidate_result_id"],)]


def test_candidate_commit_reopens_and_rehashes_current_backup(tmp_path) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    _current_backup_path(store).write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_source_backup_live_verification_failed",
    ):
        _save_qualified_candidate(store, run, source_candidate)

    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_candidates"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("drift", ["superseded_selection", "tampered_backup"])
def test_running_source_drift_cannot_finalize_completed(tmp_path, drift: str) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    candidate = _save_qualified_candidate(store, run, source_candidate)
    if drift == "superseded_selection":
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                "DELETE FROM ai_shadow_research_daily_selections WHERE run_id=?",
                (run["source_run_id"],),
            )
    else:
        _current_backup_path(store).write_text("{}\n", encoding="utf-8")

    with pytest.raises(ShadowResearchQualificationRejected):
        store.finish_qualification_run(
            run["qualification_run_id"],
            status="completed",
            selection=_selection(
                run=run,
                winner_id=candidate["qualification_candidate_id"],
            ),
            blockers=[],
            failure_code=None,
            now="2026-09-01T08:03:00+00:00",
        )

    assert store.get_qualification_run(run["qualification_run_id"])["status"] == (
        "running"
    )


def test_human_approval_rechecks_live_backup_inside_transaction(tmp_path) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    candidate = _save_qualified_candidate(store, run, source_candidate)
    store.finish_qualification_run(
        run["qualification_run_id"],
        status="completed",
        selection=_selection(
            run=run,
            winner_id=candidate["qualification_candidate_id"],
        ),
        blockers=[],
        failure_code=None,
        now="2026-09-01T08:03:00+00:00",
    )
    _current_backup_path(store).write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_source_backup_live_verification_failed",
    ):
        store.approve_qualification_candidate(
            candidate["qualification_candidate_id"],
            approved_by="human:owner",
            notes="reviewed exact evidence",
            confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
            now="2026-09-01T08:04:00+00:00",
        )

    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_approvals"
            ).fetchone()[0]
            == 0
        )


def test_atomic_qualification_promotion_rolls_back_all_three_writes(
    monkeypatch,
    tmp_path,
) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, run, candidate = _completed_qualified_candidate(tmp_path)
    values = _atomic_promotion_args(store, run, candidate)

    def crash_before_event(*_args, **_kwargs):
        raise RuntimeError("injected promotion crash")

    monkeypatch.setattr(
        "server.persistence.ai_shadow_research_qualification_promotion."
        "_insert_qualification_promotion_event",
        crash_before_event,
    )
    with pytest.raises(RuntimeError, match="injected promotion crash"):
        store.approve_qualification_candidate_for_paper_shadow(**values)

    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_approvals"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_states").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_events").fetchone()[0]
            == 0
        )


def test_atomic_qualification_promotion_rejects_stale_state_cas(tmp_path) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, run, candidate = _completed_qualified_candidate(tmp_path)
    values = _atomic_promotion_args(store, run, candidate)

    committed = store.approve_qualification_candidate_for_paper_shadow(**values)
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_promotion_state_cas_conflict",
    ):
        store.approve_qualification_candidate_for_paper_shadow(**values)

    assert committed["strategy_promotion"]["stage"] == "paper_shadow"
    assert committed["strategy_promotion"]["live_like_enabled"] is False
    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_approvals"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_states").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_events").fetchone()[0]
            == 1
        )


def test_atomic_qualification_promotion_rejects_preflight_to_begin_evidence_drift(
    tmp_path,
) -> None:
    AppDatabase(tmp_path / "app.db").init_sync()
    store, run, candidate = _completed_qualified_candidate(tmp_path)
    values = _atomic_promotion_args(store, run, candidate)
    values["current_evidence_validator"] = lambda: (
        {"status": "blocked"},
        ["reviewed_fee_schedule_revoked"],
    )

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="qualification_atomic_current_evidence_drift",
    ):
        store.approve_qualification_candidate_for_paper_shadow(**values)

    with sqlite3.connect(store.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_qualification_approvals"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_states").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM strategy_promotion_events").fetchone()[0]
            == 0
        )


def test_qualification_is_idempotent_private_and_human_approval_only(tmp_path) -> None:
    store, source_candidate = _seed_source(tmp_path)
    run, reused = store.create_or_get_qualification_run(**_run_args())
    replay, replay_reused = store.create_or_get_qualification_run(
        **{**_run_args(), "now": "2026-09-01T08:01:00+00:00"}
    )

    assert reused is False
    assert replay_reused is True
    assert replay == run
    assert run["status"] == "running"
    assert run["initial_cash_text"] == "888888.88"
    public_run = store.get_public_qualification_run(run["qualification_run_id"])
    public_body = json.dumps(public_run, ensure_ascii=False)
    assert "initial_cash_text" not in public_run
    assert "account_evidence_reference" not in public_run
    assert "888888.88" not in public_body
    assert "private-account:owner" not in public_body
    assert public_run["initial_cash_redacted"] is True
    assert public_run["private_account_values_redacted"] is True
    assert public_run["provider_call_performed"] is False

    candidate = store.save_qualification_candidate(
        qualification_run_id=run["qualification_run_id"],
        source_candidate_id=source_candidate["candidate_id"],
        source_draft_id=source_candidate["draft_id"],
        source_formula_fingerprint="sha256:" + "a" * 64,
        qualified_formula_fingerprint="sha256:" + "d" * 64,
        source_formula_semantic_fingerprint="sha256:" + "1" * 64,
        qualified_formula_semantic_fingerprint="sha256:" + "1" * 64,
        candidate_result_id=102,
        comparison={
            "research_capital_mode": "account_bound",
            "account_qualification_status": "passed",
            "promotion_gate": {"status": "passed", "blockers": []},
            "private_total_equity": "999999.99",
        },
        status="qualified",
        recommendation="paper_shadow_review",
        rank=1,
        now="2026-09-01T08:02:00+00:00",
    )
    public_candidate = store.get_public_qualification_candidate(
        candidate["qualification_candidate_id"]
    )
    assert "comparison" not in public_candidate
    assert "999999.99" not in json.dumps(public_candidate)
    assert public_candidate["provider_call_performed"] is False

    selection = _selection(
        run=run,
        winner_id=candidate["qualification_candidate_id"],
    )
    completed = store.finish_qualification_run(
        run["qualification_run_id"],
        status="completed",
        selection=selection,
        blockers=[],
        failure_code=None,
        now="2026-09-01T08:03:00+00:00",
    )
    assert completed["status"] == "completed"
    assert completed["selection"]["status"] == "winner_selected"
    assert (
        store.save_qualification_candidate(
            qualification_run_id=run["qualification_run_id"],
            source_candidate_id=source_candidate["candidate_id"],
            source_draft_id=source_candidate["draft_id"],
            source_formula_fingerprint="sha256:" + "a" * 64,
            qualified_formula_fingerprint="sha256:" + "d" * 64,
            source_formula_semantic_fingerprint="sha256:" + "1" * 64,
            qualified_formula_semantic_fingerprint="sha256:" + "1" * 64,
            candidate_result_id=102,
            comparison={
                "research_capital_mode": "account_bound",
                "account_qualification_status": "passed",
                "promotion_gate": {"status": "passed", "blockers": []},
                "private_total_equity": "999999.99",
            },
            status="qualified",
            recommendation="paper_shadow_review",
            rank=1,
            now="2026-09-01T08:02:00+00:00",
        )
        == candidate
    )

    with pytest.raises(PermissionError, match="exact human confirmation"):
        store.approve_qualification_candidate(
            candidate["qualification_candidate_id"],
            approved_by="human:owner",
            notes="reviewed exact evidence",
            confirmation="approve",
            now="2026-09-01T08:04:00+00:00",
        )
    approval = store.approve_qualification_candidate(
        candidate["qualification_candidate_id"],
        approved_by="human:owner",
        notes="reviewed exact evidence",
        confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
        now="2026-09-01T08:04:00+00:00",
    )
    approval_replay = store.approve_qualification_candidate(
        candidate["qualification_candidate_id"],
        approved_by="human:owner",
        notes="reviewed exact evidence",
        confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
        now="2026-09-01T08:05:00+00:00",
    )
    assert approval["target_stage"] == "paper_shadow"
    assert approval["reused"] is False
    assert approval_replay["reused"] is True
    assert approval["broker_order_created"] is False
    assert approval["broker_submission_enabled"] is False
    assert approval["capital_authority_granted"] is False
    assert approval["authority_effect"] == "paper_shadow_research_only"


def test_qualification_conflicts_and_terminal_mutations_fail_closed(tmp_path) -> None:
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    blocked_candidate = store.save_qualification_candidate(
        qualification_run_id=run["qualification_run_id"],
        source_candidate_id=source_candidate["candidate_id"],
        source_draft_id=source_candidate["draft_id"],
        source_formula_fingerprint="sha256:" + "b" * 64,
        qualified_formula_fingerprint="sha256:" + "e" * 64,
        source_formula_semantic_fingerprint="sha256:" + "2" * 64,
        qualified_formula_semantic_fingerprint="sha256:" + "2" * 64,
        candidate_result_id=None,
        comparison={
            "research_capital_mode": "account_bound",
            "account_qualification_status": "blocked",
            "promotion_gate": {
                "status": "blocked",
                "blockers": ["reviewed_fee_schedule_missing"],
            },
        },
        status="blocked",
        recommendation="reject",
        rank=1,
        now="2026-09-01T08:02:00+00:00",
    )

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="formula_semantics_changed",
    ):
        store.save_qualification_candidate(
            qualification_run_id=run["qualification_run_id"],
            source_candidate_id=source_candidate["candidate_id"],
            source_draft_id=source_candidate["draft_id"],
            source_formula_fingerprint="sha256:" + "b" * 64,
            qualified_formula_fingerprint="sha256:" + "c" * 64,
            source_formula_semantic_fingerprint="sha256:" + "2" * 64,
            qualified_formula_semantic_fingerprint="sha256:" + "3" * 64,
            candidate_result_id=None,
            comparison={
                "research_capital_mode": "account_bound",
                "account_qualification_status": "blocked",
            },
            status="blocked",
            recommendation="reject",
            rank=1,
            now="2026-09-01T08:02:00+00:00",
        )

    blocked_selection = {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": run["qualification_run_id"],
        "source_run_id": run["source_run_id"],
        "market_date": run["market_date"],
        "status": "no_selection",
        "winner_qualification_candidate_id": None,
        "provider_call_performed": False,
        "broker_order_created": False,
        "capital_authority_granted": False,
    }
    blocked = store.finish_qualification_run(
        run["qualification_run_id"],
        status="blocked",
        selection=blocked_selection,
        blockers=["reviewed_fee_schedule_missing"],
        failure_code=None,
        now="2026-09-01T08:03:00+00:00",
    )
    assert blocked["status"] == "blocked"
    assert blocked["blockers"] == ["reviewed_fee_schedule_missing"]

    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="terminal_result_conflict",
    ):
        store.finish_qualification_run(
            run["qualification_run_id"],
            status="blocked",
            selection=blocked_selection,
            blockers=["account_truth_changed"],
            failure_code=None,
            now="2026-09-01T08:04:00+00:00",
        )
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="not_eligible_for_approval",
    ):
        store.approve_qualification_candidate(
            blocked_candidate["qualification_candidate_id"],
            approved_by="human:owner",
            notes="cannot approve blocked evidence",
            confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
            now="2026-09-01T08:04:00+00:00",
        )
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                """
                DELETE FROM ai_shadow_research_qualification_candidates
                WHERE qualification_candidate_id=?
                """,
                (blocked_candidate["qualification_candidate_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="transition invalid"):
            conn.execute(
                """
                UPDATE ai_shadow_research_qualification_runs
                SET failure_code='mutated'
                WHERE qualification_run_id=?
                """,
                (run["qualification_run_id"],),
            )


def test_qualification_rejects_source_artifact_or_input_drift(tmp_path) -> None:
    store, _ = _seed_source(tmp_path)
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="source_artifact_binding_mismatch",
    ):
        store.create_or_get_qualification_run(
            **{**_run_args(), "source_backup_fingerprint": "changed-backup"}
        )
    with pytest.raises(
        ShadowResearchQualificationRejected,
        match="input_fingerprint_conflict",
    ):
        store.create_or_get_qualification_run(
            **{**_run_args(), "input_fingerprint": "caller-forged-input"}
        )


def _run_args() -> dict[str, object]:
    return {
        "source_run_id": SOURCE_RUN_ID,
        "market_date": "2026-08-31",
        "source_selection_id": "source-selection-1",
        "source_selection_fingerprint": SOURCE_SELECTION_FINGERPRINT,
        "source_backup_fingerprint": content_fingerprint(_backup_payload()),
        "valuation_snapshot_id": "valuation-account-1",
        "valuation_snapshot_fingerprint": "valuation-fingerprint-1",
        "ledger_cutoff_id": 42,
        "ledger_fingerprint": "ledger-fingerprint-42",
        "account_evidence_reference": "private-account:owner",
        "account_evidence_fingerprint": "account-evidence-fingerprint",
        "account_truth_source_fingerprint": "account-truth-source-fingerprint",
        "account_truth_scope_fingerprint": "account-truth-scope-fingerprint",
        "reviewed_cost_model_reference": "reviewed-cost-model:stock-v1",
        "reviewed_fee_schedule_fingerprint": "reviewed-fee-fingerprint",
        "initial_cash_text": "888888.88",
        "baseline_result_id": 101,
        "now": "2026-09-01T08:00:00+00:00",
    }


def _atomic_candidate_args(
    run: dict[str, object], source_candidate: dict[str, object]
) -> dict[str, object]:
    return {
        "qualification_run_id": run["qualification_run_id"],
        "source_candidate_id": source_candidate["candidate_id"],
        "source_draft_id": source_candidate["draft_id"],
        "source_formula_fingerprint": "sha256:" + "a" * 64,
        "qualified_formula_fingerprint": "sha256:" + "d" * 64,
        "source_formula_semantic_fingerprint": "sha256:" + "1" * 64,
        "qualified_formula_semantic_fingerprint": "sha256:" + "1" * 64,
        "rank": 1,
        "now": "2026-09-01T08:02:00+00:00",
    }


def _backtest_values() -> dict[str, object]:
    return {
        "config_json": "{}",
        "initial_cash": 888888.88,
        "final_equity": 900000.0,
        "total_return": 0.0125,
        "sharpe": 1.1,
        "max_dd": -0.03,
        "equity_curve_json": "[]",
        "annual_return": 0.0125,
        "sortino": 1.2,
        "win_rate": 0.55,
        "duration_days": 120,
        "metrics_json": "{}",
        "cost_summary_json": "{}",
    }


def _save_qualified_candidate(store: Any, run: dict, source_candidate: dict):
    return store.save_qualification_candidate_with_backtest(
        **_atomic_candidate_args(run, source_candidate),
        backtest_values=_backtest_values(),
        candidate_evidence_builder=lambda _row: (
            {
                "research_capital_mode": "account_bound",
                "account_qualification_status": "passed",
                "promotion_gate": {"status": "passed", "blockers": []},
            },
            "qualified",
            "paper_shadow_review",
        ),
    )


def _current_backup_path(store: Any) -> Path:
    with sqlite3.connect(store.path) as conn:
        relative_path = conn.execute(
            "SELECT relative_path FROM ai_shadow_research_daily_backups"
        ).fetchone()[0]
    return store.path.parent / "strategy-research-backups" / relative_path


def _completed_qualified_candidate(tmp_path):
    store, source_candidate = _seed_source(tmp_path)
    run, _ = store.create_or_get_qualification_run(**_run_args())
    candidate = _save_qualified_candidate(store, run, source_candidate)
    run = store.finish_qualification_run(
        run["qualification_run_id"],
        status="completed",
        selection=_selection(
            run=run,
            winner_id=candidate["qualification_candidate_id"],
        ),
        blockers=[],
        failure_code=None,
        now="2026-09-01T08:03:00+00:00",
    )
    return store, run, candidate


def _atomic_promotion_args(store: Any, run: dict, candidate: dict) -> dict:
    approval = store.prepare_qualification_candidate_approval(
        candidate["qualification_candidate_id"],
        approved_by="human:owner",
        notes="reviewed exact evidence",
        confirmation=SHADOW_RESEARCH_QUALIFICATION_CONFIRMATION,
        now="2026-09-01T08:04:00+00:00",
    )
    strategy_id = "ai_formula_shadow:" + str(candidate["source_candidate_id"])
    readiness = {
        "strategy_id": strategy_id,
        "candidate_id": candidate["source_candidate_id"],
        "qualification_candidate_id": candidate["qualification_candidate_id"],
        "qualification_run_id": run["qualification_run_id"],
        "human_approval_id": approval["qualification_approval_id"],
        "backtest_result_id": candidate["candidate_result_id"],
        "comparison_fingerprint": candidate["comparison_fingerprint"],
        "live_like_enabled": False,
        "broker_submission_enabled": False,
        "does_not_create_order": True,
        "does_not_authorize_execution": True,
        "does_not_change_capital_authority": True,
    }
    state_payload = {
        "schema_version": "karkinos.strategy_promotion_pipeline.v1",
        "readiness": readiness,
        "live_like_enabled": False,
        "broker_submission_enabled": False,
        "does_not_change_capital_authority": True,
    }
    return {
        "qualification_candidate_id": candidate["qualification_candidate_id"],
        "approval": approval,
        "strategy_id": strategy_id,
        "readiness": readiness,
        "state_payload": state_payload,
        "event_payload": {
            "manual_confirmation_recorded": True,
            "live_like_enabled": False,
            "broker_submission_enabled": False,
            "does_not_change_capital_authority": True,
        },
        "expected_state": None,
        "current_evidence_validator": lambda: (
            {
                "status": "pass",
                "source_candidate_id": candidate["source_candidate_id"],
                "qualification_candidate_id": candidate["qualification_candidate_id"],
                "qualification_run_id": run["qualification_run_id"],
                "qualification_approval_id": approval["qualification_approval_id"],
                "backtest_result_id": candidate["candidate_result_id"],
                "comparison_fingerprint": candidate["comparison_fingerprint"],
                "strategy_advancement_gate": readiness.get("strategy_advancement_gate"),
                "daily_strategy_artifact_binding": readiness.get(
                    "daily_strategy_artifact_binding"
                ),
                "qualification_binding": readiness.get("qualification_binding"),
            },
            [],
        ),
        "actor": "human:owner",
        "now": "2026-09-01T08:04:00+00:00",
    }


def _selection(*, run: dict[str, object], winner_id: str) -> dict[str, object]:
    return {
        "schema_version": SHADOW_RESEARCH_QUALIFICATION_SCHEMA,
        "qualification_run_id": run["qualification_run_id"],
        "source_run_id": run["source_run_id"],
        "market_date": run["market_date"],
        "status": "winner_selected",
        "winner_qualification_candidate_id": winner_id,
        "private_account_total_equity": "999999.99",
        "provider_call_performed": False,
        "broker_order_created": False,
        "capital_authority_granted": False,
    }


def _seed_source(tmp_path):
    db_path = tmp_path / "app.db"
    store = ShadowResearchStore(db_path)
    store.init()
    backups = DailyStrategyBackupStore(tmp_path / "strategy-research-backups")
    DailyStrategyArtifactRepository(
        db_path,
        backup_store=backups,
    ).init()
    receipt = backups.write(
        _backup_payload(),
        created_at="2026-08-31T08:02:00+00:00",
    )
    source_run, _ = store.claim_run(
        market_date="2026-08-31",
        input_fingerprint="sourceinput0000000000000000000000000000000000000000000000000000",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        research_context_id="normalized-notional:2026-08-31",
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now="2026-08-31T08:00:00+00:00",
    )
    source_candidate = store.save_candidate(
        run_id=source_run["run_id"],
        session_id="source-session",
        draft_id="source-draft-1",
        backtest_run_id="source-backtest-1",
        critique_id="source-critique-1",
        baseline_result_id=1,
        candidate_result_id=2,
        status="evaluated_research_only",
        recommendation="formula_research_candidate",
        comparison={
            "research_capital_mode": "normalized_notional",
            "account_qualification_status": "not_evaluated",
            "promotion_gate": {"status": "blocked", "blockers": []},
        },
        now="2026-08-31T08:01:00+00:00",
    )
    store.update_run(
        source_run["run_id"],
        status="completed",
        baseline_result_id=1,
        candidate_count=1,
        now="2026-08-31T08:02:00+00:00",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ai_shadow_research_daily_selections
            (selection_id, run_id, market_date, status, winner_candidate_id,
             expected_candidate_count, observed_candidate_count, selection_json,
             selection_fingerprint, created_at)
            VALUES (?, ?, ?, 'no_selection', NULL, 1, 1, ?, ?, ?)
            """,
            (
                "source-selection-1",
                source_run["run_id"],
                "2026-08-31",
                canonical_json(
                    {
                        **SOURCE_SELECTION,
                        "selection_fingerprint": SOURCE_SELECTION_FINGERPRINT,
                    }
                ),
                SOURCE_SELECTION_FINGERPRINT,
                "2026-08-31T08:02:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_daily_backups
            (backup_id, run_id, market_date, selection_id, relative_path,
             artifact_fingerprint, byte_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["backup_id"],
                source_run["run_id"],
                "2026-08-31",
                "source-selection-1",
                receipt["relative_path"],
                receipt["artifact_fingerprint"],
                receipt["byte_count"],
                "2026-08-31T08:02:00+00:00",
            ),
        )
    assert source_run["run_id"] == _run_args()["source_run_id"]
    return store, source_candidate
