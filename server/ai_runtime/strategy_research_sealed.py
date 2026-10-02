"""Sealed-holdout evaluation workflow for AI strategy research."""

from __future__ import annotations

from analytics.sealed_holdout import (
    build_sealed_partition,
)
from server.ai_runtime.contracts import JsonObject, content_fingerprint
from server.ai_runtime.strategy_research_support import (
    selection_from_session,
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
        # Historical completed tests remain readable; new evaluations must freeze
        # the champion before future bars exist through the automation reservation.
        sealed_id = (
            "ai-sealed-test-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        try:
            historical = self._research_store.get_sealed_test(sealed_id)
        except LookupError:
            historical = None
        if historical is not None and historical["status"] == "completed":
            row, _ = self._research_store.create_or_get_sealed_test(
                request,
                partition_fingerprint=partition.partition_fingerprint,
                champion_formula_fingerprint=champion_formula_fingerprint,
                research_family_id=research_family_id,
                created_at=self._now(),
            )
            return self._sealed_test_response(row, reused=True)
        raise StrategyResearchRejected(
            "sealed_test_requires_frozen_automation_champion"
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
            "challenger_comparison": row.get("challenger_comparison"),
            "reused": reused,
            "non_authoritative": True,
            "non_executable": True,
            "requires_human_review": True,
            "authority_effect": "none",
        }
