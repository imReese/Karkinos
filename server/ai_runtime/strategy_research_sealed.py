"""Sealed-holdout evaluation workflow for AI strategy research."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from analytics.sealed_holdout import (
    build_consumption_receipt,
    build_sealed_holdout_evaluation,
    build_sealed_partition,
)
from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.strategy_research_backtest import (
    RestrictedFormulaBacktestAdapter,
)
from server.ai_runtime.strategy_research_support import (
    selection_from_session,
    strategy_research_failure_code,
)
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_API_CONTRACT,
    SealedTestRequest,
    StrategyResearchRejected,
)


class StrategyResearchSealedMixin:
    async def sealed_test(self, request: SealedTestRequest) -> JsonObject:
        session = self._research_store.get_session(request.session_id)
        self._validate_session_integrity(session)
        draft_row = self._research_store.get_draft(request.session_id, request.draft_id)
        if draft_row["validation_status"] != "valid":
            raise StrategyResearchRejected("hypothesis_draft_not_validated")
        backtest = self._research_store.get_backtest(request.backtest_run_id)
        if (
            backtest["status"] != "completed"
            or not backtest["canonical_backtest_result_id"]
        ):
            raise StrategyResearchRejected("canonical_backtest_not_complete")
        if backtest["draft_id"] != request.draft_id:
            raise StrategyResearchRejected("sealed_draft_backtest_mismatch")

        selection = selection_from_session(session)
        if not selection.has_sealed_holdout:
            raise StrategyResearchRejected("sealed_holdout_not_frozen")
        sealed_end_date = selection.sealed_end_date
        if sealed_end_date is None:
            raise StrategyResearchRejected("sealed_holdout_not_frozen")
        partition = build_sealed_partition(
            research_start=selection.start_date,
            research_end=selection.end_date,
            sealed_end=sealed_end_date,
        )

        draft = draft_row["contract"]
        champion_formula_fingerprint = "sha256:" + content_fingerprint(
            draft["formula_ast"]
        )
        research_family_id = session["session_id"]
        sealed_test, reused = self._research_store.create_or_get_sealed_test(
            request,
            partition_fingerprint=partition.partition_fingerprint,
            champion_formula_fingerprint=champion_formula_fingerprint,
            research_family_id=research_family_id,
            created_at=self._now(),
        )
        if reused and sealed_test["status"] == "completed":
            return self._sealed_test_response(sealed_test, reused=True)
        if reused and sealed_test["status"] == "failed":
            raise StrategyResearchRejected(
                sealed_test.get("failure_code") or "sealed_test_failed"
            )

        try:
            reviewed_fee_schedule_resolution = await asyncio.to_thread(
                self._resolve_reviewed_fee_schedule, selection
            )
            result = await asyncio.to_thread(
                RestrictedFormulaBacktestAdapter(
                    data_store=self._data_store
                ).run_sealed,
                selection=selection,
                draft=draft,
                sealed_end_date=sealed_end_date,
                reviewed_fee_schedule_resolution=reviewed_fee_schedule_resolution,
            )
            benchmark_return = (
                Decimal(str(request.benchmark_return))
                if request.benchmark_return is not None
                else None
            )
            evidence = build_sealed_holdout_evaluation(
                strategy_id="ai_formula_research",
                benchmark_role="formula_champion",
                research_family_id=research_family_id,
                formula_fingerprint=champion_formula_fingerprint,
                partition=partition,
                result=result,
                benchmark_return=benchmark_return,
            )
            receipt = build_consumption_receipt(
                research_family_id=research_family_id,
                partition=partition,
                champion_formula_fingerprint=champion_formula_fingerprint,
                consumed_at=self._now(),
                evaluator_code_revision="strategy_research_sealed.v1",
            )
            evidence_payload = evidence.to_json_dict()
            self._research_store.finish_sealed_test(
                sealed_test["sealed_test_id"],
                status="completed",
                evidence=evidence_payload,
                evidence_fingerprint=evidence_payload["evidence_fingerprint"],
                failure_code=None,
                updated_at=self._now(),
            )
            self._research_store.append_event(
                sealed_test["sealed_test_id"],
                "sealed_test.consumption_recorded",
                {"receipt_fingerprint": receipt.receipt_fingerprint},
                created_at=self._now(),
            )
        except Exception as exc:
            self._research_store.finish_sealed_test(
                sealed_test["sealed_test_id"],
                status="failed",
                evidence=None,
                evidence_fingerprint=None,
                failure_code=strategy_research_failure_code(exc),
                updated_at=self._now(),
            )
            raise
        return self._sealed_test_response(
            self._research_store.get_sealed_test(sealed_test["sealed_test_id"]),
            reused=False,
        )

    def _sealed_test_response(self, row: dict, *, reused: bool) -> JsonObject:
        return {
            "schema_version": STRATEGY_RESEARCH_API_CONTRACT,
            "sealed_test_id": row["sealed_test_id"],
            "session_id": row["session_id"],
            "draft_id": row["draft_id"],
            "backtest_run_id": row["backtest_run_id"],
            "research_family_id": row["research_family_id"],
            "partition_fingerprint": row["partition_fingerprint"],
            "champion_formula_fingerprint": row["champion_formula_fingerprint"],
            "status": row["status"],
            "failure_code": row.get("failure_code"),
            "evidence": row.get("evidence"),
            "reused": reused,
            "non_authoritative": True,
            "non_executable": True,
            "requires_human_review": True,
            "authority_effect": "none",
        }
