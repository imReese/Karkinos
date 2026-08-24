"""Formula-backtest command workflow for AI strategy research."""

from __future__ import annotations

import asyncio
import json

from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_support import (
    selection_from_session,
    strategy_research_failure_code,
)
from server.contracts.strategy_research import (
    FormulaBacktestRequest,
    StrategyResearchRejected,
)


class StrategyResearchBacktestWorkflowMixin:
    async def run_formula_backtest(self, request: FormulaBacktestRequest) -> JsonObject:
        session = self._research_store.get_session(request.session_id)
        if session["status"] != "completed":
            raise StrategyResearchRejected("hypothesis_session_not_complete")
        self._validate_session_integrity(session)
        draft_row = self._research_store.get_draft(request.session_id, request.draft_id)
        if draft_row["validation_status"] != "valid":
            raise StrategyResearchRejected("hypothesis_draft_not_validated")
        draft = draft_row["contract"]
        selection = selection_from_session(session)
        expected_dataset_snapshot = await self._validate_saved_selection(selection)
        reviewed_fee_schedule_resolution = await asyncio.to_thread(
            self._resolve_reviewed_fee_schedule,
            selection,
        )
        account_capital_evidence = self._account_capital_evidence_for_session(
            session=session,
            selection=selection,
            reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
        )
        backtest, reused = self._research_store.create_or_get_backtest(
            request,
            formula_fingerprint=str(draft["formula_fingerprint"]),
            dataset_snapshot_id=selection.dataset_snapshot_id,
            cost_model_reference=selection.cost_model_reference,
            created_at=self._now(),
        )
        if reused:
            return await self._backtest_response(backtest, reused=True)
        try:
            bt_result, bt_request = await asyncio.to_thread(
                RestrictedFormulaBacktestAdapter(data_store=self._data_store).run,
                selection=selection,
                draft=draft,
                expected_dataset_snapshot=expected_dataset_snapshot,
                reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
                account_capital_evidence=account_capital_evidence,
            )
            result_id = await self._db.save_backtest_result(
                config_json=bt_request.model_dump_json(),
                initial_cash=bt_result["initial_cash"],
                final_equity=bt_result["final_equity"],
                total_return=bt_result["total_return"],
                sharpe=bt_result["sharpe"],
                max_dd=bt_result["max_drawdown"],
                equity_curve_json=json.dumps(bt_result["equity_curve"]),
                annual_return=bt_result["annual_return"],
                sortino=bt_result["sortino"],
                win_rate=bt_result["win_rate"],
                duration_days=bt_result["duration_days"],
                metrics_json=json.dumps(bt_result["metrics_json"], ensure_ascii=False),
                cost_summary_json=json.dumps(
                    bt_result["cost_summary_json"], ensure_ascii=False
                ),
            )
            evidence_fingerprint = content_fingerprint(
                bt_result["metrics_json"]["research_evidence_bundle"]
            )
            self._research_store.finish_backtest(
                backtest["backtest_run_id"],
                status="completed",
                result_id=result_id,
                evidence_fingerprint=evidence_fingerprint,
                failure_code=None,
                updated_at=self._now(),
            )
        except Exception as exc:
            self._research_store.finish_backtest(
                backtest["backtest_run_id"],
                status="failed",
                result_id=None,
                evidence_fingerprint=None,
                failure_code=strategy_research_failure_code(exc),
                updated_at=self._now(),
            )
            raise
        return await self._backtest_response(
            self._research_store.get_backtest(backtest["backtest_run_id"]),
            reused=False,
        )
