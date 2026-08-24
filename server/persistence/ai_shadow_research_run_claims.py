"""Atomic run claims and exact resume validation for AI shadow research."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.strategy_research import (
    StrategyResearchRejected,
    StrategyResearchSelection,
)
from server.contracts.ai_shadow_research_automation import (
    CORRECTED_PANEL_CITATION_RESUME_ITERATION,
    CORRECTED_PANEL_CITATION_RESUME_STAGE,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    TIMEOUT_RESUME_COMPLETED_ITERATIONS,
    TIMEOUT_RESUME_ITERATION,
    ShadowResearchRejected,
    require_corrected_panel_rearm_evidence,
    shadow_research_json_object,
)


class ShadowResearchRunClaimRepositoryMixin:
    """Claim new runs or resume one exact persisted lineage atomically."""

    def claim_run(
        self,
        *,
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        now: str,
        timeout_resume_input_evidence: Mapping[str, Any] | None = None,
        corrected_panel_rearm_evidence: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT * FROM ai_shadow_research_runs WHERE market_date=?
                ORDER BY created_at LIMIT 1
                """,
                (market_date,),
            ).fetchone()
            if existing is not None:
                return self._claim_existing_run(
                    conn,
                    existing_run=dict(existing),
                    market_date=market_date,
                    input_fingerprint=input_fingerprint,
                    baseline_seed_result_id=baseline_seed_result_id,
                    valuation_snapshot_id=valuation_snapshot_id,
                    ledger_cutoff_id=ledger_cutoff_id,
                    now=now,
                    timeout_resume_input_evidence=timeout_resume_input_evidence,
                    corrected_panel_rearm_evidence=corrected_panel_rearm_evidence,
                )
            duplicate_input = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE input_fingerprint=?",
                (input_fingerprint,),
            ).fetchone()
            if duplicate_input is not None:
                return dict(duplicate_input), True
            run_id = f"ai-shadow-research:{market_date}:{input_fingerprint[:16]}"
            conn.execute(
                """
                INSERT INTO ai_shadow_research_runs
                (run_id, market_date, input_fingerprint, status,
                 baseline_seed_result_id, valuation_snapshot_id, ledger_cutoff_id,
                 created_at, updated_at)
                VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    market_date,
                    input_fingerprint,
                    baseline_seed_result_id,
                    valuation_snapshot_id,
                    ledger_cutoff_id,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id), False

    def _claim_existing_run(
        self,
        conn: sqlite3.Connection,
        *,
        existing_run: dict[str, Any],
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        now: str,
        timeout_resume_input_evidence: Mapping[str, Any] | None,
        corrected_panel_rearm_evidence: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], bool]:
        provider_free_partial_resume = (
            self._provider_free_partial_resume_evidence(conn, existing_run)
            if input_fingerprint != existing_run["input_fingerprint"]
            else None
        )
        if provider_free_partial_resume is not None:
            return self._resume_provider_free_partial_run(
                conn,
                run=existing_run,
                resume=provider_free_partial_resume,
                market_date=market_date,
                input_fingerprint=input_fingerprint,
                baseline_seed_result_id=baseline_seed_result_id,
                valuation_snapshot_id=valuation_snapshot_id,
                ledger_cutoff_id=ledger_cutoff_id,
                now=now,
            )
        citation_resume = self._unconsumed_corrected_panel_citation_resume_extension(
            conn, existing_run
        )
        if citation_resume is not None:
            return self._resume_corrected_panel_citation_run(
                conn,
                run=existing_run,
                extension=citation_resume,
                market_date=market_date,
                input_fingerprint=input_fingerprint,
                baseline_seed_result_id=baseline_seed_result_id,
                valuation_snapshot_id=valuation_snapshot_id,
                ledger_cutoff_id=ledger_cutoff_id,
                corrected_panel_rearm_evidence=corrected_panel_rearm_evidence,
                now=now,
            )
        timeout_resume = self._unconsumed_timeout_resume_call_extension(
            conn, existing_run
        )
        if timeout_resume is not None:
            return self._resume_timeout_run(
                conn,
                run=existing_run,
                extension=timeout_resume,
                input_fingerprint=input_fingerprint,
                baseline_seed_result_id=baseline_seed_result_id,
                valuation_snapshot_id=valuation_snapshot_id,
                ledger_cutoff_id=ledger_cutoff_id,
                input_evidence=timeout_resume_input_evidence,
                now=now,
            )
        return self._claim_replacement_run(
            conn,
            existing_run=existing_run,
            market_date=market_date,
            input_fingerprint=input_fingerprint,
            baseline_seed_result_id=baseline_seed_result_id,
            valuation_snapshot_id=valuation_snapshot_id,
            ledger_cutoff_id=ledger_cutoff_id,
            corrected_panel_rearm_evidence=corrected_panel_rearm_evidence,
            now=now,
        )

    def _resume_provider_free_partial_run(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        resume: Mapping[str, Any],
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        if (
            int(run["baseline_seed_result_id"]) != int(baseline_seed_result_id)
            or run["valuation_snapshot_id"] != valuation_snapshot_id
            or int(run["ledger_cutoff_id"]) != int(ledger_cutoff_id)
        ):
            raise ShadowResearchRejected("provider_free_partial_resume_input_drift")
        resume_iteration = int(resume["resume_iteration"])
        completed_iteration_count = int(resume["completed_iteration_count"])
        real_calls_before_classification = self._real_provider_call_count(
            conn, market_date
        )
        effective_call_limit = self._effective_provider_call_ceiling(
            conn,
            run_id=str(run["run_id"]),
            market_date=market_date,
            call_limit=SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
        )
        remaining_calls = (SHADOW_RESEARCH_MAX_CANDIDATES - resume_iteration + 1) * 2
        if (
            real_calls_before_classification <= 0
            or effective_call_limit - (real_calls_before_classification - 1)
            != remaining_calls
        ):
            raise ShadowResearchRejected(
                "provider_free_partial_resume_capacity_mismatch"
            )
        resume_id = (
            "ai-shadow-research-provider-free-partial-resume:"
            + content_fingerprint(
                {
                    "run_id": run["run_id"],
                    "failed_call_id": resume["failed_call_id"],
                    "failure_evidence_fingerprint": resume[
                        "failure_evidence_fingerprint"
                    ],
                    "prior_input_fingerprint": run["input_fingerprint"],
                    "resumed_input_fingerprint": input_fingerprint,
                    "completed_evidence_fingerprint": resume[
                        "completed_evidence_fingerprint"
                    ],
                }
            )[:24]
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_provider_free_partial_resumes
            (resume_id, run_id, market_date, failed_call_id,
             failed_session_id, failed_workflow_id, failed_agent_run_id,
             failure_code, failure_evidence_fingerprint,
             prior_input_fingerprint, resumed_input_fingerprint,
             completed_iteration_count, completed_evidence_fingerprint,
             resume_iteration, consumed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                run["run_id"],
                market_date,
                resume["failed_call_id"],
                resume["failed_session_id"],
                resume["failed_workflow_id"],
                resume["failed_agent_run_id"],
                resume["failure_code"],
                resume["failure_evidence_fingerprint"],
                run["input_fingerprint"],
                input_fingerprint,
                completed_iteration_count,
                resume["completed_evidence_fingerprint"],
                resume_iteration,
                now,
            ),
        )
        cursor = conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET input_fingerprint=?, status='running', failure_code=NULL,
                candidate_count=?, updated_at=?
            WHERE run_id=? AND status='failed' AND input_fingerprint=?
            """,
            (
                input_fingerprint,
                completed_iteration_count,
                now,
                run["run_id"],
                run["input_fingerprint"],
            ),
        )
        if cursor.rowcount != 1:
            raise ShadowResearchRejected(
                "provider_free_partial_resume_run_not_claimable"
            )
        resumed = conn.execute(
            "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
            (run["run_id"],),
        ).fetchone()
        if resumed is None:
            raise RuntimeError("provider-free partial resume persistence failed")
        return {
            **dict(resumed),
            "partial_resume_iteration": resume_iteration,
            "partial_resume_evidence_fingerprint": resume[
                "completed_evidence_fingerprint"
            ],
            "provider_free_partial_resume_id": resume_id,
        }, False

    def _resume_corrected_panel_citation_run(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        extension: Mapping[str, Any],
        market_date: str,
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        corrected_panel_rearm_evidence: Mapping[str, Any] | None,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        normalized = require_corrected_panel_rearm_evidence(
            corrected_panel_rearm_evidence
        )
        rearm_binding = conn.execute(
            """
            SELECT authorization.expected_rearm_evidence_fingerprint
            FROM ai_shadow_research_corrected_panel_rearm_consumptions AS consumption
            JOIN ai_shadow_research_corrected_panel_rearm_authorizations AS authorization
              ON authorization.authorization_id=consumption.authorization_id
            WHERE consumption.replacement_run_id=? AND authorization.market_date=?
            """,
            (run["run_id"], market_date),
        ).fetchone()
        if (
            rearm_binding is None
            or normalized["evidence_fingerprint"]
            != rearm_binding["expected_rearm_evidence_fingerprint"]
            or int(run["baseline_seed_result_id"]) != int(baseline_seed_result_id)
            or run["valuation_snapshot_id"] != valuation_snapshot_id
            or int(run["ledger_cutoff_id"]) != int(ledger_cutoff_id)
        ):
            raise ShadowResearchRejected("corrected_panel_citation_resume_input_drift")
        checkpoint = self._first_critique_resume_checkpoint(conn, run)
        if checkpoint["checkpoint_fingerprint"] != extension["checkpoint_fingerprint"]:
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_checkpoint_drift"
            )
        cursor = conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET status='running', failure_code=NULL, candidate_count=0, updated_at=?
            WHERE run_id=? AND status='failed'
            """,
            (now, run["run_id"]),
        )
        if cursor.rowcount != 1:
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_run_not_claimable"
            )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_corrected_panel_citation_resume_consumptions
            (extension_id, resumed_run_id, resumed_input_fingerprint,
             checkpoint_fingerprint, consumed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                extension["extension_id"],
                run["run_id"],
                input_fingerprint,
                checkpoint["checkpoint_fingerprint"],
                now,
            ),
        )
        resumed = conn.execute(
            "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run["run_id"],)
        ).fetchone()
        if resumed is None:
            raise RuntimeError("corrected panel citation resume persistence failed")
        return {
            **dict(resumed),
            "partial_resume_iteration": CORRECTED_PANEL_CITATION_RESUME_ITERATION,
            "partial_resume_stage": CORRECTED_PANEL_CITATION_RESUME_STAGE,
            "partial_resume_extension_id": extension["extension_id"],
            "partial_resume_evidence_fingerprint": checkpoint["checkpoint_fingerprint"],
        }, False

    def _resume_timeout_run(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        extension: Mapping[str, Any],
        input_fingerprint: str,
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        input_evidence: Mapping[str, Any] | None,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        if input_evidence is not None:
            self._validate_timeout_resume_input_evidence(
                conn,
                run=run,
                baseline_seed_result_id=baseline_seed_result_id,
                valuation_snapshot_id=valuation_snapshot_id,
                ledger_cutoff_id=ledger_cutoff_id,
                evidence=input_evidence,
            )
        elif input_fingerprint != run["input_fingerprint"]:
            raise ShadowResearchRejected("timeout_resume_input_fingerprint_drift")
        checkpoint = self._partial_resume_checkpoint(conn, run)
        if (
            checkpoint["completed_evidence_fingerprint"]
            != extension["completed_evidence_fingerprint"]
        ):
            raise ShadowResearchRejected("timeout_resume_completed_evidence_drift")
        conn.execute(
            """
            UPDATE ai_shadow_research_runs
            SET status='running', failure_code=NULL, candidate_count=?, updated_at=?
            WHERE run_id=? AND status='failed'
            """,
            (TIMEOUT_RESUME_COMPLETED_ITERATIONS, now, run["run_id"]),
        )
        conn.execute(
            """
            INSERT INTO ai_shadow_research_timeout_resume_call_extension_consumptions
            (extension_id, resumed_run_id, resumed_input_fingerprint,
             completed_evidence_fingerprint, consumed_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                extension["extension_id"],
                run["run_id"],
                input_fingerprint,
                checkpoint["completed_evidence_fingerprint"],
                now,
            ),
        )
        resumed = conn.execute(
            "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run["run_id"],)
        ).fetchone()
        if resumed is None:
            raise RuntimeError("timeout resume persistence failed")
        return {
            **dict(resumed),
            "partial_resume_iteration": TIMEOUT_RESUME_ITERATION,
            "partial_resume_extension_id": extension["extension_id"],
            "partial_resume_evidence_fingerprint": checkpoint[
                "completed_evidence_fingerprint"
            ],
        }, False

    def _validate_timeout_resume_input_evidence(
        self,
        conn: sqlite3.Connection,
        *,
        run: Mapping[str, Any],
        baseline_seed_result_id: int,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        evidence: Mapping[str, Any],
    ) -> None:
        selection_components = evidence.get("selection_components")
        if not isinstance(selection_components, Mapping):
            raise ShadowResearchRejected("timeout_resume_input_evidence_invalid")
        if (
            int(run.get("baseline_seed_result_id") or 0) != int(baseline_seed_result_id)
            or str(run.get("valuation_snapshot_id") or "") != str(valuation_snapshot_id)
            or int(run.get("ledger_cutoff_id") or 0) != int(ledger_cutoff_id)
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_drift")

        baseline_result_id = int(run.get("baseline_result_id") or 0)
        baseline = conn.execute(
            """
            SELECT baseline_fingerprint FROM ai_shadow_research_baselines
            WHERE backtest_result_id=?
            """,
            (baseline_result_id,),
        ).fetchone()
        if baseline is None or baseline["baseline_fingerprint"] != str(
            evidence.get("baseline_fingerprint") or ""
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_drift")
        try:
            expected_selection = StrategyResearchSelection(
                saved_backtest_result_id=baseline_result_id,
                **dict(selection_components),
            ).to_dict()
        except (TypeError, ValueError, StrategyResearchRejected) as exc:
            raise ShadowResearchRejected(
                "timeout_resume_input_evidence_invalid"
            ) from exc
        requests = conn.execute(
            """
            SELECT session.request_json
            FROM ai_shadow_research_candidates AS candidate
            JOIN ai_strategy_research_sessions AS session
              ON session.session_id=candidate.session_id
            WHERE candidate.run_id=?
            ORDER BY CAST(json_extract(candidate.comparison_json,
                         '$.iteration_lineage.iteration_number') AS INTEGER),
                     candidate.created_at, candidate.candidate_id
            """,
            (run["run_id"],),
        ).fetchall()
        expected_request_fields = {
            "requested_by": str(evidence.get("requested_by") or ""),
            "account_alias": str(evidence.get("account_alias") or ""),
            "research_question": str(evidence.get("research_question") or ""),
        }
        if len(requests) != TIMEOUT_RESUME_COMPLETED_ITERATIONS or not all(
            expected_request_fields.values()
        ):
            raise ShadowResearchRejected("timeout_resume_input_evidence_invalid")
        for row in requests:
            request = shadow_research_json_object(row["request_json"])
            if (
                any(
                    request.get(key) != value
                    for key, value in expected_request_fields.items()
                )
                or request.get("selection") != expected_selection
                or request.get("confirmation_recorded") is not True
                or request.get("api_key_recorded") is not False
            ):
                raise ShadowResearchRejected("timeout_resume_input_evidence_drift")
