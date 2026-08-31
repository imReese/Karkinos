"""Run and baseline repositories for AI shadow research."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from server.models import BacktestRequest


class ShadowResearchRunRepositoryMixin:
    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"shadow research run not found: {run_id}")
        return dict(row)

    def update_run(self, run_id: str, *, now: str, **updates: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "baseline_result_id",
            "session_id",
            "failure_code",
            "candidate_count",
        }
        values = {key: value for key, value in updates.items() if key in allowed}
        if not values:
            return self.get_run(run_id)
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._connect(immediate=True) as conn:
            conn.execute(
                f"UPDATE ai_shadow_research_runs SET {assignments}, updated_at=? WHERE run_id=?",
                (*values.values(), now, run_id),
            )
        return self.get_run(run_id)

    def save_baseline(
        self,
        *,
        baseline_fingerprint: str,
        request: BacktestRequest,
        result: Mapping[str, Any],
        now: str,
    ) -> int:
        """Persist a computed baseline exactly once with its canonical result row."""
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT backtest_result_id FROM ai_shadow_research_baselines WHERE baseline_fingerprint=?",
                (baseline_fingerprint,),
            ).fetchone()
            if existing is not None:
                return int(existing["backtest_result_id"])
            cursor = conn.execute(
                """
                INSERT INTO backtest_results
                (created_at, config_json, initial_cash, final_equity, total_return,
                 sharpe, sortino, max_drawdown, win_rate, duration_days,
                 equity_curve_json, metrics_json, cost_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    request.model_dump_json(),
                    result["initial_cash"],
                    result["final_equity"],
                    result["total_return"],
                    result["sharpe"],
                    result["sortino"],
                    result["max_drawdown"],
                    result["win_rate"],
                    result["duration_days"],
                    json.dumps(result["equity_curve"], ensure_ascii=False),
                    json.dumps(result["metrics_json"], ensure_ascii=False),
                    json.dumps(result["cost_summary_json"], ensure_ascii=False),
                ),
            )
            result_id = int(cursor.lastrowid or 0)
            conn.execute(
                "INSERT INTO ai_shadow_research_baselines VALUES (?, ?, ?)",
                (baseline_fingerprint, result_id, now),
            )
            return result_id

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_shadow_research_runs ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(row) for row in rows]
