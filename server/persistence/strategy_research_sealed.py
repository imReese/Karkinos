"""Sealed-holdout repository operations for AI strategy research."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.jobs import JobLease, job_time
from server.contracts.strategy_research import (
    SealedTestRequest,
    StrategyResearchRejected,
)
from server.persistence.jobs import SQLiteJobStore, job_id_for, require_job_lease

_FINAL_EVALUATION_JOB_KIND = "research_final_evaluation"


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
        evaluation_lease: JobLease | None = None,
        lease_clock: Callable[[], datetime] | None = None,
    ) -> None:
        evidence_json = canonical_json(evidence) if evidence is not None else None
        challenger_json = (
            canonical_json(challenger_comparison)
            if challenger_comparison is not None
            else None
        )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM ai_strategy_sealed_tests WHERE sealed_test_id=?",
                (sealed_test_id,),
            ).fetchone()
            if row is None or row["status"] != "running":
                raise StrategyResearchRejected("sealed_test_already_terminal")
            if (
                sealed_test_id.startswith("ai-sealed-auto-")
                and evaluation_lease is None
            ):
                raise StrategyResearchRejected("sealed_evaluation_lease_required")
            if evaluation_lease is not None:
                expected_job_id = job_id_for(
                    _FINAL_EVALUATION_JOB_KIND, {"sealed_test_id": sealed_test_id}
                )
                if evaluation_lease.job_id != expected_job_id:
                    raise ValueError("job_lease_lost")
                checked = (lease_clock or (lambda: datetime.now(timezone.utc)))()
                require_job_lease(conn, evaluation_lease, now=checked)
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
            if evaluation_lease is not None:
                # The reservation and its operational lease change together. A
                # retry keeps the same consumed scientific test and budget.
                conn.execute(
                    "UPDATE job_runs SET status=?, result_ref=?, error=?, "
                    "max_attempts=MAX(max_attempts, attempt+1), "
                    "available_at=?, lease_owner=NULL, lease_expires_at=NULL, updated_at=? "
                    "WHERE job_id=?",
                    (
                        "queued"
                        if status == "reserved"
                        else ("succeeded" if status == "completed" else "failed"),
                        sealed_test_id if status == "completed" else None,
                        failure_code,
                        job_time(checked),
                        job_time(checked),
                        evaluation_lease.job_id,
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
                if "publication_grant" in binding or "simulation_policy" in binding:
                    replay_binding["error_budget"] = original.get("error_budget")
                if existing["request_fingerprint"] != content_fingerprint(
                    replay_binding
                ):
                    raise StrategyResearchRejected(
                        "sealed_champion_reservation_conflict"
                    )
                return persisted
            from datetime import time

            latest_freeze = datetime.combine(
                datetime.fromisoformat(
                    binding.get("first_evaluation_session", partition["sealed_start"])
                ).date(),
                time(9, 30)
                if binding.get("publication_grant") or binding.get("simulation_policy")
                else time.min,
                ZoneInfo("Asia/Shanghai"),
            )
            if created.tzinfo is None or created >= latest_freeze:
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
            if "publication_grant" in binding or "simulation_policy" in binding:
                from decimal import Decimal

                grant = binding.get("simulation_policy") or binding["publication_grant"]
                attempts = []
                for raw in conn.execute(
                    "SELECT evidence_json FROM ai_strategy_sealed_tests"
                ).fetchall():
                    previous = json.loads(raw["evidence_json"] or "{}").get(
                        "reservation", {}
                    )
                    if (
                        previous.get("simulation_policy")
                        or previous.get("publication_grant", {})
                    ).get("grant_id") == grant["grant_id"]:
                        attempts.append(previous)
                alpha = Decimal(str(grant["statistical_policy"]["significance_level"]))
                spent = (
                    sum(
                        (
                            Decimal(
                                str(
                                    item.get("error_budget", {}).get(
                                        "allocated_alpha", "0"
                                    )
                                )
                            )
                            for item in attempts
                        ),
                        Decimal("0"),
                    )
                    + alpha
                )
                if len(attempts) >= grant["max_final_tests"] or spent > Decimal(
                    str(grant["total_error_budget"])
                ):
                    raise StrategyResearchRejected(
                        "deployment_final_test_budget_exhausted"
                    )
                binding = {
                    **binding,
                    "error_budget": {
                        "grant_id": grant["grant_id"],
                        "generation": grant["generation"],
                        "attempt_count": len(attempts) + 1,
                        "allocated_alpha": str(alpha),
                        "error_budget_spent": str(spent),
                    },
                }
                request_fingerprint = content_fingerprint(binding)
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

    def deployment_reservations(self, grant_id: str) -> list[dict[str, Any]]:
        with self._connect_readonly() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_strategy_sealed_tests ORDER BY created_at,sealed_test_id"
            ).fetchall()
        result = []
        for raw in rows:
            row = self._sealed_row(dict(raw))
            binding = (row.get("evidence") or {}).get("reservation", {})
            if (
                binding.get("simulation_policy") or binding.get("publication_grant", {})
            ).get("grant_id") == grant_id:
                result.append(row)
        return result

    def research_champion_reservation(self, source_run_id: str) -> dict[str, Any]:
        sealed_id = (
            "ai-sealed-auto-" + content_fingerprint({"run_id": source_run_id})[:24]
        )
        return self.get_sealed_test(sealed_id)

    def claim_reserved_sealed_test(
        self,
        sealed_test_id: str,
        *,
        now: str,
        lease_owner: str | None = None,
        lease_seconds: int = 90,
    ) -> JobLease | None:
        """Lease a frozen test, including a crashed evaluator's original attempt."""
        instant = datetime.fromisoformat(now)
        at = job_time(instant)
        owner = lease_owner or uuid4().hex
        if not owner.strip() or lease_seconds <= 0:
            raise ValueError("job_lease_invalid")
        job = SQLiteJobStore(self._path).enqueue(
            _FINAL_EVALUATION_JOB_KIND, {"sealed_test_id": sealed_test_id}, now=instant
        )
        with self._connect(immediate=True) as conn:
            row = conn.execute(
                "SELECT status FROM ai_strategy_sealed_tests WHERE sealed_test_id=?",
                (sealed_test_id,),
            ).fetchone()
            if row is None or row["status"] not in {"reserved", "running"}:
                return None
            # Operational interruption must not exhaust a different scientific
            # test allowance. The attempt remains monotonic and fences old owners.
            cursor = conn.execute(
                "UPDATE job_runs SET status='running', attempt=attempt+1, "
                "max_attempts=MAX(max_attempts, attempt+1), lease_owner=?, "
                "lease_expires_at=?, heartbeat_at=?, updated_at=? "
                "WHERE job_id=? AND ((status='queued' AND available_at<=?) "
                "OR (status='running' AND lease_expires_at<=?))",
                (
                    owner,
                    job_time(instant + timedelta(seconds=lease_seconds)),
                    at,
                    at,
                    job.job_id,
                    at,
                    at,
                ),
            )
            if cursor.rowcount != 1:
                return None
            conn.execute(
                "UPDATE ai_strategy_sealed_tests SET status='running',updated_at=? "
                "WHERE sealed_test_id=?",
                (now, sealed_test_id),
            )
            attempt = conn.execute(
                "SELECT attempt FROM job_runs WHERE job_id=?", (job.job_id,)
            ).fetchone()[0]
            return JobLease(job.job_id, owner, attempt)

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
