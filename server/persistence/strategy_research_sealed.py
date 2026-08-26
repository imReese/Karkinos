"""Sealed-holdout repository operations for AI strategy research."""

from __future__ import annotations

import json
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import (
    SealedTestRequest,
    StrategyResearchRejected,
)


class StrategyResearchSealedRepositoryMixin:
    def create_or_get_sealed_test(
        self,
        request: SealedTestRequest,
        *,
        partition_fingerprint: str,
        champion_formula_fingerprint: str,
        research_family_id: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        request_fingerprint = content_fingerprint(
            {
                "requested_by": request.requested_by,
                "session_id": request.session_id,
                "draft_id": request.draft_id,
                "backtest_run_id": request.backtest_run_id,
                "confirmation": request.confirmation,
                "benchmark_return": (
                    str(request.benchmark_return)
                    if request.benchmark_return is not None
                    else None
                ),
                "partition_fingerprint": partition_fingerprint,
                "champion_formula_fingerprint": champion_formula_fingerprint,
                "research_family_id": research_family_id,
            }
        )
        sealed_test_id = (
            "ai-sealed-test-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_sealed_tests WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict("sealed test idempotency conflict")
                return row, True
            prior = conn.execute(
                "SELECT sealed_test_id FROM ai_strategy_sealed_tests "
                "WHERE partition_fingerprint=? LIMIT 1",
                (partition_fingerprint,),
            ).fetchone()
            if prior is not None:
                raise StrategyResearchRejected("sealed_partition_already_consumed")
            conn.execute(
                """
                INSERT INTO ai_strategy_sealed_tests
                (sealed_test_id, idempotency_key, request_fingerprint, session_id,
                 draft_id, backtest_run_id, research_family_id,
                 partition_fingerprint, champion_formula_fingerprint, consumed_at,
                 status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    sealed_test_id,
                    request.idempotency_key,
                    request_fingerprint,
                    request.session_id,
                    request.draft_id,
                    request.backtest_run_id,
                    research_family_id,
                    partition_fingerprint,
                    champion_formula_fingerprint,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
        self.append_event(
            sealed_test_id,
            "sealed_test.requested",
            {"partition_fingerprint": partition_fingerprint},
            created_at=created_at,
        )
        return self.get_sealed_test(sealed_test_id), False

    def finish_sealed_test(
        self,
        sealed_test_id: str,
        *,
        status: str,
        evidence: JsonObject | None,
        evidence_fingerprint: str | None,
        failure_code: str | None,
        updated_at: str,
    ) -> None:
        evidence_json = canonical_json(evidence) if evidence is not None else None
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_strategy_sealed_tests
                SET status=?, evidence_json=?, evidence_fingerprint=?,
                    failure_code=?, updated_at=? WHERE sealed_test_id=?
                """,
                (
                    status,
                    evidence_json,
                    evidence_fingerprint,
                    failure_code,
                    updated_at,
                    sealed_test_id,
                ),
            )
        self.append_event(
            sealed_test_id,
            f"sealed_test.{status}",
            {
                "evidence_fingerprint": evidence_fingerprint,
                "failure_code": failure_code,
            },
            created_at=updated_at,
        )

    def get_sealed_test(self, sealed_test_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_strategy_sealed_tests WHERE sealed_test_id=?",
                (sealed_test_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"sealed test not found: {sealed_test_id}")
        result = dict(row)
        if result.get("evidence_json"):
            result["evidence"] = json.loads(result["evidence_json"])
        else:
            result["evidence"] = None
        return result

    def list_sealed_tests(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_strategy_sealed_tests
                WHERE session_id=? ORDER BY created_at
                """,
                (session_id,),
            ).fetchall()
        return [
            {
                **dict(row),
                "evidence": (
                    json.loads(row["evidence_json"]) if row["evidence_json"] else None
                ),
            }
            for row in rows
        ]
