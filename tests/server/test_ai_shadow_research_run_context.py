from __future__ import annotations

import sqlite3

import pytest

from server.db import AppDatabase
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    ShadowResearchRejected,
)
from server.persistence.ai_shadow_research import ShadowResearchStore
from server.projections.daily_strategy_artifacts import build_daily_strategy_selection
from server.services.strategy_promotion_pipeline import StrategyPromotionPipeline
from tests.ai_shadow_strategy_fixtures import (
    seed_ai_shadow_canonical_sources,
    seed_approved_ai_shadow_strategy,
)

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def test_store_migrates_legacy_run_context_without_inferring_mode(tmp_path) -> None:
    db_path = tmp_path / "legacy-shadow.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE ai_shadow_research_runs (
                run_id TEXT PRIMARY KEY,
                market_date TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                baseline_seed_result_id INTEGER NOT NULL,
                baseline_result_id INTEGER,
                valuation_snapshot_id TEXT NOT NULL,
                ledger_cutoff_id INTEGER NOT NULL,
                session_id TEXT,
                failure_code TEXT,
                candidate_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """)
        conn.execute("""
            INSERT INTO ai_shadow_research_runs
            VALUES ('legacy-run', '2026-08-10', 'legacy-input', 'completed',
                    1, 2, 'nominal-research:legacy-sentinel', 0, NULL, NULL, 5,
                    '2026-08-10T08:00:00+00:00',
                    '2026-08-10T08:30:00+00:00')
            """)

    store = ShadowResearchStore(db_path)
    store.init()
    store.init()
    run = store.get_run("legacy-run")

    assert run["research_capital_mode"] == "legacy_unknown"
    assert run["research_context_id"] is None
    assert run["valuation_snapshot_id"] == "nominal-research:legacy-sentinel"
    assert run["ledger_cutoff_id"] == 0

    with (
        sqlite3.connect(db_path) as conn,
        pytest.raises(sqlite3.IntegrityError, match="run context invalid"),
    ):
        conn.execute("""
            UPDATE ai_shadow_research_runs
            SET research_capital_mode='normalized_notional'
            WHERE run_id='legacy-run'
            """)


def test_new_runs_persist_explicit_normalized_and_account_contexts(tmp_path) -> None:
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()

    normalized, normalized_reused = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="normalized-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        research_context_id="nominal-research:normalized-context",
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now="2026-08-11T08:00:00+00:00",
    )
    account_bound, account_reused = store.claim_run(
        market_date="2026-08-12",
        input_fingerprint="account-input",
        baseline_seed_result_id=2,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-account",
        valuation_snapshot_id="valuation-account",
        ledger_cutoff_id=42,
        now="2026-08-12T08:00:00+00:00",
    )

    assert normalized_reused is False
    assert normalized["research_capital_mode"] == "normalized_notional"
    assert normalized["research_context_id"] == ("nominal-research:normalized-context")
    assert normalized["valuation_snapshot_id"] == ""
    assert normalized["ledger_cutoff_id"] == 0
    assert account_reused is False
    assert account_bound["research_capital_mode"] == "account_bound"
    assert account_bound["research_context_id"] == "valuation-account"
    assert account_bound["valuation_snapshot_id"] == "valuation-account"
    assert account_bound["ledger_cutoff_id"] == 42

    with pytest.raises(
        ShadowResearchRejected,
        match="normalized_research_run_context_binding_invalid",
    ):
        store.claim_run(
            market_date="2026-08-13",
            input_fingerprint="invalid-normalized-input",
            baseline_seed_result_id=3,
            research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
            research_context_id="nominal-research:invalid",
            valuation_snapshot_id="nominal-research:sentinel",
            ledger_cutoff_id=0,
            now="2026-08-13T08:00:00+00:00",
        )


def test_candidate_save_enforces_explicit_run_capital_contract(tmp_path) -> None:
    store = ShadowResearchStore(tmp_path / "app.db")
    store.init()
    normalized_run, _ = store.claim_run(
        market_date="2026-08-11",
        input_fingerprint="normalized-candidate-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
        research_context_id="nominal-research:normalized-candidate",
        valuation_snapshot_id=None,
        ledger_cutoff_id=0,
        now="2026-08-11T08:00:00+00:00",
    )
    normalized_comparison = {
        "research_capital_mode": "normalized_notional",
        "account_qualification_status": "not_evaluated",
        "promotion_gate": {"status": "blocked", "blockers": []},
    }

    candidate = store.save_candidate(
        run_id=normalized_run["run_id"],
        session_id="session-normalized",
        draft_id="draft-normalized",
        backtest_run_id="backtest-normalized",
        critique_id="critique-normalized",
        baseline_result_id=1,
        candidate_result_id=2,
        status="evaluated_research_only",
        recommendation="formula_research_candidate",
        comparison=normalized_comparison,
        now="2026-08-11T08:05:00+00:00",
    )
    assert candidate["promotion_status"] == "account_qualification_required"

    with pytest.raises(
        ShadowResearchRejected,
        match="normalized_candidate_contract_invalid",
    ):
        store.save_candidate(
            run_id=normalized_run["run_id"],
            session_id="session-normalized",
            draft_id="draft-forged-approval",
            backtest_run_id="backtest-forged-approval",
            critique_id="critique-forged-approval",
            baseline_result_id=1,
            candidate_result_id=3,
            status="awaiting_human_approval",
            recommendation="paper_shadow_review",
            comparison=normalized_comparison,
            now="2026-08-11T08:06:00+00:00",
        )

    account_run, _ = store.claim_run(
        market_date="2026-08-12",
        input_fingerprint="account-candidate-input",
        baseline_seed_result_id=1,
        research_capital_mode=SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
        research_context_id="valuation-account-candidate",
        valuation_snapshot_id="valuation-account-candidate",
        ledger_cutoff_id=42,
        now="2026-08-12T08:00:00+00:00",
    )
    with pytest.raises(
        ShadowResearchRejected,
        match="account_bound_candidate_contract_invalid",
    ):
        store.save_candidate(
            run_id=account_run["run_id"],
            session_id="session-account",
            draft_id="draft-forged-normalized",
            backtest_run_id="backtest-forged-normalized",
            critique_id="critique-forged-normalized",
            baseline_result_id=1,
            candidate_result_id=4,
            status="evaluated_research_only",
            recommendation="formula_research_candidate",
            comparison=normalized_comparison,
            now="2026-08-12T08:05:00+00:00",
        )

    legacy_run, _ = store.claim_run(
        market_date="2026-08-13",
        input_fingerprint="legacy-candidate-input",
        baseline_seed_result_id=1,
        valuation_snapshot_id="legacy-sentinel",
        ledger_cutoff_id=0,
        now="2026-08-13T08:00:00+00:00",
    )
    with pytest.raises(
        ShadowResearchRejected,
        match="legacy_candidate_research_context_unclassified",
    ):
        store.save_candidate(
            run_id=legacy_run["run_id"],
            session_id="session-legacy",
            draft_id="draft-legacy",
            backtest_run_id="backtest-legacy",
            critique_id="critique-legacy",
            baseline_result_id=1,
            candidate_result_id=5,
            status="awaiting_human_approval",
            recommendation="paper_shadow_review",
            comparison={
                "research_capital_mode": "account_bound",
                "account_qualification_status": "passed",
            },
            now="2026-08-13T08:05:00+00:00",
        )


def test_daily_selection_explicitly_excludes_normalized_candidate(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    comparison = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-forged-normalized-selection",
        critique_id="critique-forged-normalized-selection",
    )
    comparison.update(
        {
            "research_capital_mode": "normalized_notional",
            "account_qualification_status": "not_evaluated",
            "iteration_lineage": {
                "iteration_number": 1,
                "total_iterations": 1,
                "formula_fingerprint": "sha256:" + "f" * 64,
                "parent_candidate_id": None,
                "parent_draft_id": None,
                "parent_formula_fingerprint": None,
                "iteration_context_fingerprint": "sha256:" + "1" * 64,
                "sequential_feedback_bound": True,
            },
        }
    )
    selection = build_daily_strategy_selection(
        run={
            "run_id": "run-forged-normalized-selection",
            "market_date": "2026-08-12",
        },
        candidates=[
            {
                "candidate_id": "candidate-forged-normalized-selection",
                "run_id": "run-forged-normalized-selection",
                "draft_id": "draft-forged-normalized-selection",
                "critique_id": "critique-forged-normalized-selection",
                "status": "awaiting_human_approval",
                "recommendation": "paper_shadow_review",
                "comparison": comparison,
            }
        ],
        expected_candidate_count=1,
        created_at="2026-08-12T08:00:00+00:00",
    )

    assert selection["status"] == "no_selection"
    assert selection["winner_candidate_id"] is None
    assert selection["eligible_candidate_count"] == 0
    assert selection["candidate_outcomes"][0]["eligible"] is False
    assert selection["candidate_outcomes"][0]["research_capital_mode"] == (
        "normalized_notional"
    )


def test_legacy_run_cannot_receive_candidate_approval(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(db._path)
    store.init()
    comparison = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=1,
        candidate_result_id=2,
        backtest_run_id="backtest-legacy-approval",
        critique_id="critique-legacy-approval",
    )
    candidate = store.save_candidate(
        run_id="run-legacy-approval",
        session_id="session-legacy-approval",
        draft_id="draft-legacy-approval",
        backtest_run_id="backtest-legacy-approval",
        critique_id="critique-legacy-approval",
        baseline_result_id=1,
        candidate_result_id=2,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison=comparison,
        now="2026-08-12T08:00:00+00:00",
    )
    with sqlite3.connect(db._path) as conn:
        conn.execute("""
            UPDATE ai_shadow_research_runs
            SET research_capital_mode='legacy_unknown', research_context_id=NULL
            WHERE run_id='run-legacy-approval'
            """)

    with pytest.raises(
        ShadowResearchRejected,
        match="candidate_research_context_not_account_bound",
    ):
        store.approve_candidate(
            candidate["candidate_id"],
            approved_by="human:owner",
            notes="Legacy context must stay fail closed.",
            confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
            now="2026-08-12T08:05:00+00:00",
        )
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM ai_shadow_research_promotions"
            ).fetchone()[0]
            == 0
        )


def test_downstream_promotion_rejects_legacy_run_context(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    seeded = seed_approved_ai_shadow_strategy(
        db,
        fixture_id="legacy-context",
        baseline_result_id=1,
        candidate_result_id=2,
    )
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET research_capital_mode='legacy_unknown', research_context_id=NULL
            WHERE run_id=?
            """,
            (seeded["candidate"]["run_id"],),
        )

    with pytest.raises(
        ValueError,
        match="ai_shadow_research_context_not_account_bound",
    ):
        StrategyPromotionPipeline(db=db).evaluate_readiness(
            seeded["readiness"], actor="human:owner"
        )
