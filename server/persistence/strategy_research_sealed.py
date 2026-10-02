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
                return self._sealed_row(row), True
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
        challenger_comparison: JsonObject | None = None,
    ) -> None:
        evidence_json = canonical_json(evidence) if evidence is not None else None
        challenger_json = (
            canonical_json(challenger_comparison)
            if challenger_comparison is not None
            else None
        )
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE ai_strategy_sealed_tests
                SET status=?, evidence_json=?, evidence_fingerprint=?,
                    challenger_comparison_json=?, failure_code=?, updated_at=?
                WHERE sealed_test_id=? AND status='running'
                """,
                (
                    status,
                    evidence_json,
                    evidence_fingerprint,
                    challenger_json,
                    failure_code,
                    updated_at,
                    sealed_test_id,
                ),
            )
        if cursor.rowcount != 1:
            raise StrategyResearchRejected("sealed_test_already_terminal")
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
        result["evidence"] = (
            json.loads(result["evidence_json"]) if result.get("evidence_json") else None
        )
        result["challenger_comparison"] = (
            json.loads(result["challenger_comparison_json"])
            if result.get("challenger_comparison_json")
            else None
        )
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
                "challenger_comparison": (
                    json.loads(row["challenger_comparison_json"])
                    if row["challenger_comparison_json"]
                    else None
                ),
            }
            for row in rows
        ]

    def reserve_research_champion(
        self, *, binding: JsonObject, created_at: str
    ) -> dict[str, Any]:
        """Freeze one selected champion before its reserved future bars exist."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        partition = binding["partition"]
        created = datetime.fromisoformat(created_at)
        request_fingerprint = content_fingerprint(binding)
        sealed_id = (
            "ai-sealed-auto-"
            + content_fingerprint({"run_id": binding["source_run_id"]})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_sealed_tests WHERE sealed_test_id=?",
                (sealed_id,),
            ).fetchone()
            if existing is not None:
                persisted = self._sealed_row(dict(existing))
                original = (persisted.get("evidence") or {}).get("reservation", {})
                replay_binding = {**binding, "frozen_at": original.get("frozen_at")}
                if existing["request_fingerprint"] != content_fingerprint(
                    replay_binding
                ):
                    raise StrategyResearchRejected(
                        "sealed_champion_reservation_conflict"
                    )
                return persisted
            if (
                created.tzinfo is None
                or created.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
                >= partition["sealed_start"]
            ):
                raise StrategyResearchRejected(
                    "sealed_champion_not_frozen_before_holdout"
                )
            for raw in conn.execute(
                "SELECT * FROM ai_strategy_sealed_tests"
            ).fetchall():
                prior = self._sealed_row(dict(raw)).get("evidence") or {}
                prior_binding = prior.get("reservation", {})
                previous = prior_binding.get("partition", prior.get("partition", {}))
                if not previous:
                    if raw["partition_fingerprint"] == binding["partition_fingerprint"]:
                        raise StrategyResearchRejected(
                            "sealed_partition_already_consumed"
                        )
                    continue
                same_assets = not prior_binding or bool(
                    set(prior_binding.get("universe", [])) & set(binding["universe"])
                )
                if (
                    same_assets
                    and previous["sealed_start"] <= partition["sealed_end"]
                    and partition["sealed_start"] <= previous["sealed_end"]
                ):
                    raise StrategyResearchRejected(
                        "sealed_partition_overlap_already_reserved"
                    )
            evidence = {"reservation": binding}
            conn.execute(
                "INSERT INTO ai_strategy_sealed_tests "
                "(sealed_test_id,idempotency_key,request_fingerprint,session_id,draft_id,"
                "backtest_run_id,research_family_id,partition_fingerprint,champion_formula_fingerprint,"
                "consumed_at,status,evidence_json,evidence_fingerprint,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?, 'reserved',?,?,?,?)",
                (
                    sealed_id,
                    sealed_id,
                    request_fingerprint,
                    binding["session_id"],
                    binding["draft_id"],
                    binding["backtest_run_id"],
                    binding["trial_family"]["research_family_id"],
                    binding["partition_fingerprint"],
                    binding["champion_formula_fingerprint"],
                    created_at,
                    canonical_json(evidence),
                    content_fingerprint(evidence),
                    created_at,
                    created_at,
                ),
            )
        return self.get_sealed_test(sealed_id)

    def research_champion_reservation(self, source_run_id: str) -> dict[str, Any]:
        sealed_id = (
            "ai-sealed-auto-" + content_fingerprint({"run_id": source_run_id})[:24]
        )
        return self.get_sealed_test(sealed_id)

    def claim_reserved_sealed_test(self, sealed_test_id: str, *, now: str) -> bool:
        """Exactly one evaluator may consume a reservation; retries read its result."""
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "UPDATE ai_strategy_sealed_tests SET status='running',updated_at=? "
                "WHERE sealed_test_id=? AND status='reserved'",
                (now, sealed_test_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _sealed_row(row: dict[str, Any]) -> dict[str, Any]:
        row["evidence"] = (
            json.loads(row["evidence_json"]) if row.get("evidence_json") else None
        )
        row["challenger_comparison"] = (
            json.loads(row["challenger_comparison_json"])
            if row.get("challenger_comparison_json")
            else None
        )
        return row
