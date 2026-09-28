from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from analytics.normalized_research_gate import (
    build_normalized_research_advancement_gate,
)
from analytics.strategy_advancement_gate import strategy_advancement_backtest_view
from data.store import DataStore
from server.ai_runtime.contracts import content_fingerprint
from server.config import AIProviderConfig, ServerConfig
from server.db import AppDatabase
from server.dependencies import AppState
from server.services.ai_shadow_research_automation import (
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    AiShadowResearchAutomationService,
    ShadowResearchStore,
)
from server.services.ai_shadow_research_daily_artifacts import (
    DailyStrategyArtifactStore,
)
from server.services.strategy_promotion_pipeline import (
    resolve_strategy_order_generation_gate,
)
from server.services.trading_controls import TradingControlState
from tests.ai_shadow_strategy_fixtures import (
    _backtest_source_fingerprint,
    seed_ai_shadow_canonical_sources,
)


def _state(db: AppDatabase) -> AppState:
    state = AppState()
    state.config = ServerConfig(
        ai=AIProviderConfig(
            enabled=True,
            provider="deepseek",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
        )
    )
    state.db = db
    state.trading_controls = TradingControlState(db=db)
    return state


def test_normalized_research_candidate_promotes_to_paper_shadow_without_broker_reconciliation(
    tmp_path: Path,
) -> None:
    """Verify decoupling: normalized research candidate promotes to paper shadow

    without demanding real-money account qualification or broker statement matching.
    """
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    store = ShadowResearchStore(db._path)
    store.init()

    baseline_result_id = 1
    candidate_result_id = 2
    backtest_run_id = "backtest-norm-1"
    critique_id = "critique-norm-1"
    run_id = "run-norm-1"
    session_id = "session-norm-1"
    draft_id = "draft-norm-1"
    formula_fingerprint = "sha256:" + "f" * 64

    # Seed canonical backtest results, critiques, and sources
    comparison = seed_ai_shadow_canonical_sources(
        db,
        baseline_result_id=baseline_result_id,
        candidate_result_id=candidate_result_id,
        backtest_run_id=backtest_run_id,
        critique_id=critique_id,
    )

    # Switch research run context to normalized_notional mode
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET research_capital_mode = 'normalized_notional',
                research_context_id = 'normalized_notional_research',
                valuation_snapshot_id = '',
                ledger_cutoff_id = 0
            WHERE run_id = ?
            """,
            (run_id,),
        )
        for res_id in (baseline_result_id, candidate_result_id):
            row = conn.execute(
                "SELECT metrics_json FROM backtest_results WHERE id=?", (res_id,)
            ).fetchone()
            if row and row[0]:
                metrics = json.loads(row[0])
                fee_ev = dict(metrics.get("fee_component_evidence") or {})
                fee_ev.pop("evidence_fingerprint", None)
                fee_ev["account_specific"] = False
                fee_ev["fee_schedule_source"] = "canonical_default_estimate"
                fee_ev["fee_schedule_fingerprint"] = ""
                fee_ev["broker_statement_reconciled"] = False
                encoded = json.dumps(
                    fee_ev,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                fee_ev["evidence_fingerprint"] = hashlib.sha256(encoded).hexdigest()
                metrics["fee_component_evidence"] = fee_ev
                conn.execute(
                    "UPDATE backtest_results SET metrics_json=? WHERE id=?",
                    (json.dumps(metrics), res_id),
                )

        conn.row_factory = sqlite3.Row
        baseline_row = dict(
            conn.execute(
                "SELECT * FROM backtest_results WHERE id=?",
                (baseline_result_id,),
            ).fetchone()
        )
        candidate_row = dict(
            conn.execute(
                "SELECT * FROM backtest_results WHERE id=?",
                (candidate_result_id,),
            ).fetchone()
        )
        critique_row = dict(
            conn.execute(
                "SELECT * FROM ai_strategy_backtest_critiques WHERE critique_id=?",
                (critique_id,),
            ).fetchone()
        )

    baseline_view = strategy_advancement_backtest_view(baseline_row)
    candidate_view = strategy_advancement_backtest_view(candidate_row)

    critique_evidence = {
        "status": critique_row["status"],
        "critique_id": critique_id,
        "artifact_fingerprint": critique_row["artifact_fingerprint"],
    }

    research_gate = build_normalized_research_advancement_gate(
        baseline=baseline_view,
        candidate=candidate_view,
        critique_evidence=critique_evidence,
    )
    assert research_gate.passed is True

    candidate_comparison = {
        **comparison,
        "research_capital_mode": "normalized_notional",
        "account_qualification_status": "not_evaluated",
        "baseline_source_fingerprint": _backtest_source_fingerprint(baseline_row),
        "candidate_source_fingerprint": _backtest_source_fingerprint(candidate_row),
        "research_gate": research_gate.to_json_dict(),
        "promotion_gate": research_gate.to_json_dict(),
        "iteration_lineage": {
            "iteration_number": 1,
            "total_iterations": 1,
            "formula_fingerprint": formula_fingerprint,
            "parent_candidate_id": None,
            "parent_draft_id": None,
            "parent_formula_fingerprint": None,
            "iteration_context_fingerprint": "sha256:" + "c" * 64,
            "sequential_feedback_bound": True,
        },
        "automatic_strategy_replacement_enabled": False,
    }

    candidate = store.save_candidate(
        run_id=run_id,
        session_id=session_id,
        draft_id=draft_id,
        backtest_run_id=backtest_run_id,
        critique_id=critique_id,
        baseline_result_id=baseline_result_id,
        candidate_result_id=candidate_result_id,
        status="awaiting_human_approval",
        recommendation="paper_shadow_review",
        comparison=candidate_comparison,
        now="2026-08-12T07:00:00+00:00",
    )

    daily_artifacts = DailyStrategyArtifactStore(
        tmp_path / "app.db",
        tmp_path / "strategy-research-backups",
    )
    daily_artifacts.record_daily_artifacts(
        run={
            "run_id": run_id,
            "market_date": "2026-08-12",
            "input_fingerprint": content_fingerprint({"run_id": run_id}),
        },
        candidates=[candidate],
        drafts=[
            {
                "draft_id": draft_id,
                "formula_ast": {"schema_version": "fixture"},
                "formula_fingerprint": formula_fingerprint,
                "economic_hypothesis": "Robust momentum breakout.",
                "risk_impact": "Loss limited to stop-loss threshold.",
                "failure_conditions": ["Drawdown exceeds 10%."],
                "limitations": ["Tested on 2025-2026 window."],
                "anti_lookahead_assumptions": ["Signals on bar close."],
                "validation": {"status": "valid", "errors": []},
            }
        ],
        expected_candidate_count=1,
        run_status="completed",
        created_at="2026-08-12T07:05:00+00:00",
    )

    service = AiShadowResearchAutomationService(
        state=_state(db),
        store=store,
        data_store=DataStore(tmp_path / "market"),
        daily_artifact_store=daily_artifacts,
    )

    # Status before approval shows active_paper_shadow_strategy_id as None
    status_before = service.status()
    assert status_before["active_paper_shadow_strategy_id"] is None

    # Detail listing & retrieval methods work
    candidates_list = service.list_candidates_detail()
    assert len(candidates_list) >= 1
    assert candidates_list[0]["candidate_id"] == candidate["candidate_id"]

    detail = service.get_candidate_detail(candidate["candidate_id"])
    assert detail["candidate_id"] == candidate["candidate_id"]
    assert detail["comparison"]["research_capital_mode"] == "normalized_notional"

    # Human approves candidate into paper_shadow without requiring broker reconciliation!
    promoted = service.approve_candidate(
        candidate["candidate_id"],
        approved_by="human:quant_lead",
        notes="Validated trend logic, trade count >10, and positive OOS excess.",
        confirmation=SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    )

    assert promoted["paper_shadow_stage_recorded"] is True
    assert promoted["strategy_promotion"]["stage"] == "paper_shadow"
    assert promoted["strategy_promotion"]["live_like_enabled"] is False
    assert promoted["strategy_id"] == f"ai_formula_shadow:{candidate['candidate_id']}"

    # Status now exposes the active paper_shadow strategy!
    status_after = service.status()
    assert status_after["active_paper_shadow_strategy_id"] == promoted["strategy_id"]

    # Order generation gate passes for paper shadow evaluation
    order_gate, blockers = resolve_strategy_order_generation_gate(
        db, promoted["strategy_id"]
    )
    assert not blockers
    assert order_gate["status"] == "pass"
    assert order_gate["paper_shadow_evaluation_only"] is True
    assert order_gate["broker_submission_enabled"] is False
