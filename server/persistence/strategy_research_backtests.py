"""Formula-backtest repository operations for AI strategy research."""

from __future__ import annotations

from typing import Any

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import FormulaBacktestRequest


class StrategyResearchBacktestRepositoryMixin:
    def create_or_get_backtest(
        self,
        request: FormulaBacktestRequest,
        *,
        formula_fingerprint: str,
        dataset_snapshot_id: str,
        cost_model_reference: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        request_fingerprint = content_fingerprint(
            {
                "requested_by": request.requested_by,
                "session_id": request.session_id,
                "draft_id": request.draft_id,
                "confirmation": request.confirmation,
                "formula_fingerprint": formula_fingerprint,
                "dataset_snapshot_id": dataset_snapshot_id,
                "cost_model_reference": cost_model_reference,
            }
        )
        run_id = (
            "ai-formula-backtest-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_formula_backtests WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict("formula backtest idempotency conflict")
                return row, True
            conn.execute(
                """
                INSERT INTO ai_strategy_formula_backtests
                (backtest_run_id, idempotency_key, request_fingerprint, session_id,
                 draft_id, formula_fingerprint, dataset_snapshot_id,
                 cost_model_reference, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id,
                    request.idempotency_key,
                    request_fingerprint,
                    request.session_id,
                    request.draft_id,
                    formula_fingerprint,
                    dataset_snapshot_id,
                    cost_model_reference,
                    created_at,
                    created_at,
                ),
            )
        return self.get_backtest(run_id), False

    def finish_backtest(
        self,
        run_id: str,
        *,
        status: str,
        result_id: int | None,
        evidence_fingerprint: str | None,
        failure_code: str | None,
        updated_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_strategy_formula_backtests
                SET status=?, canonical_backtest_result_id=?, evidence_fingerprint=?,
                    failure_code=?, updated_at=? WHERE backtest_run_id=?
                """,
                (
                    status,
                    result_id,
                    evidence_fingerprint,
                    failure_code,
                    updated_at,
                    run_id,
                ),
            )
        self.append_event(
            run_id,
            f"formula_backtest.{status}",
            {
                "canonical_backtest_result_id": result_id,
                "failure_code": failure_code,
            },
            created_at=updated_at,
        )

    def get_backtest(self, run_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_strategy_formula_backtests WHERE backtest_run_id=?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"formula backtest not found: {run_id}")
        return dict(row)
