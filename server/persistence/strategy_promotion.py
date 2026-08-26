"""SQLite repository for strategy promotion state and append-only events."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from server.persistence.connection import SQLiteRepository

logger = logging.getLogger(__name__)


class StrategyPromotionRepository(SQLiteRepository):
    """Own strategy promotion state and append-only events."""

    def upsert_strategy_promotion_state_sync(
        self,
        *,
        strategy_id: str,
        stage: str,
        gate_status: str,
        live_like_enabled: bool,
        missing_requirements: list[str] | None = None,
        backtest_result_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion state."""
        now = self._now().isoformat()
        missing_json = json.dumps(
            missing_requirements or [],
            ensure_ascii=False,
            sort_keys=True,
        )
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            existing = conn.execute(
                """
                SELECT created_at
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                LIMIT 1
                """,
                (strategy_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else now
            conn.execute(
                """
                INSERT INTO strategy_promotion_states (
                    strategy_id, stage, gate_status, live_like_enabled,
                    missing_requirements_json, backtest_result_id, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    stage = excluded.stage,
                    gate_status = excluded.gate_status,
                    live_like_enabled = excluded.live_like_enabled,
                    missing_requirements_json = excluded.missing_requirements_json,
                    backtest_result_id = excluded.backtest_result_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    strategy_id,
                    stage,
                    gate_status,
                    1 if live_like_enabled else 0,
                    missing_json,
                    backtest_result_id,
                    payload_json,
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def get_strategy_promotion_state_sync(
        self,
        strategy_id: str,
    ) -> dict[str, Any] | None:
        """Read one strategy promotion state."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                WHERE strategy_id = ?
                """,
                (strategy_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_ai_shadow_strategy_promotion_binding_sync(
        self,
        candidate_id: str,
    ) -> dict[str, Any] | None:
        """Read the candidate and human approval that back one reserved strategy."""

        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        candidate.candidate_id,
                        candidate.run_id,
                        candidate.session_id,
                        candidate.draft_id,
                        candidate.critique_id,
                        candidate.backtest_run_id,
                        candidate.baseline_result_id,
                        candidate.candidate_result_id,
                        candidate.status AS candidate_status,
                        candidate.recommendation,
                        candidate.comparison_json,
                        candidate.promotion_status,
                        promotion.promotion_id,
                        promotion.target_stage,
                        promotion.approved_by,
                        promotion.candidate_fingerprint,
                        promotion.created_at AS approved_at,
                        research_run.status AS research_run_status,
                        research_run.baseline_result_id AS research_run_baseline_result_id,
                        research_run.valuation_snapshot_id AS research_run_valuation_snapshot_id,
                        research_run.ledger_cutoff_id AS research_run_ledger_cutoff_id,
                        research_run.session_id AS research_run_session_id,
                        formula_backtest.status AS formula_backtest_status,
                        formula_backtest.canonical_backtest_result_id,
                        formula_backtest.evidence_fingerprint AS backtest_evidence_fingerprint,
                        formula_backtest.session_id AS formula_backtest_session_id,
                        formula_backtest.draft_id AS formula_backtest_draft_id,
                        formula_backtest.formula_fingerprint AS formula_backtest_formula_fingerprint,
                        formula_backtest.dataset_snapshot_id AS formula_backtest_dataset_snapshot_id,
                        formula_backtest.cost_model_reference AS formula_backtest_cost_model_reference,
                        critique.status AS critique_status,
                        critique.session_id AS critique_session_id,
                        critique.draft_id AS critique_draft_id,
                        critique.backtest_run_id AS critique_backtest_run_id,
                        critique.normalized_artifact_json AS critique_artifact_json,
                        critique.artifact_fingerprint AS critique_artifact_fingerprint,
                        baseline.initial_cash AS baseline_initial_cash,
                        baseline.final_equity AS baseline_final_equity,
                        baseline.total_return AS baseline_total_return,
                        baseline.sharpe AS baseline_sharpe,
                        baseline.max_drawdown AS baseline_max_drawdown,
                        baseline.equity_curve_json AS baseline_equity_curve_json,
                        baseline.metrics_json AS baseline_metrics_json,
                        baseline.cost_summary_json AS baseline_cost_summary_json,
                        candidate_result.initial_cash AS candidate_initial_cash,
                        candidate_result.final_equity AS candidate_final_equity,
                        candidate_result.total_return AS candidate_total_return,
                        candidate_result.sharpe AS candidate_sharpe,
                        candidate_result.max_drawdown AS candidate_max_drawdown,
                        candidate_result.equity_curve_json AS candidate_equity_curve_json,
                        candidate_result.metrics_json AS candidate_metrics_json,
                        candidate_result.cost_summary_json AS candidate_cost_summary_json
                    FROM ai_shadow_research_candidates AS candidate
                    LEFT JOIN ai_shadow_research_promotions AS promotion
                      ON promotion.candidate_id = candidate.candidate_id
                    LEFT JOIN ai_shadow_research_runs AS research_run
                      ON research_run.run_id = candidate.run_id
                    LEFT JOIN ai_strategy_formula_backtests AS formula_backtest
                      ON formula_backtest.backtest_run_id = candidate.backtest_run_id
                    LEFT JOIN ai_strategy_backtest_critiques AS critique
                      ON critique.critique_id = candidate.critique_id
                    LEFT JOIN backtest_results AS baseline
                      ON baseline.id = candidate.baseline_result_id
                    LEFT JOIN backtest_results AS candidate_result
                      ON candidate_result.id = candidate.candidate_result_id
                    WHERE candidate.candidate_id = ?
                    LIMIT 1
                    """,
                    (str(candidate_id),),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return dict(row) if row else None

    def list_strategy_promotion_states_sync(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List strategy promotion states."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_states
                ORDER BY updated_at DESC, strategy_id ASC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
            return [dict(row) for row in rows]

    def record_strategy_promotion_event_sync(
        self,
        *,
        strategy_id: str,
        event_type: str,
        from_stage: str | None = None,
        to_stage: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist one strategy promotion audit event."""
        now = self._now().isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO strategy_promotion_events (
                    strategy_id, event_type, from_stage, to_stage, actor,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    event_type,
                    from_stage,
                    to_stage,
                    actor,
                    payload_json,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM strategy_promotion_events WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
            conn.commit()
            return dict(row)

    def list_strategy_promotion_events_sync(
        self,
        strategy_id: str,
    ) -> list[dict[str, Any]]:
        """List strategy promotion audit events for one strategy."""
        with sqlite3.connect(self._path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM strategy_promotion_events
                WHERE strategy_id = ?
                ORDER BY id ASC
                """,
                (strategy_id,),
            ).fetchall()
            return [dict(row) for row in rows]
