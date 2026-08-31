"""Corrected-panel citation resume persistence and checkpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE,
    CORRECTED_PANEL_CITATION_FAILURE_CODE,
    CORRECTED_PANEL_CITATION_RESUME_ITERATION,
    CORRECTED_PANEL_CITATION_RESUME_STAGE,
    SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
    ShadowResearchRejected,
    build_shadow_research_iteration_context,
    build_shadow_research_iteration_lineage,
    require_corrected_panel_rearm_evidence,
    shadow_research_json_object,
)
from server.persistence.ai_shadow_research_records import (
    shadow_research_candidate_row,
)


class ShadowResearchCitationResumeRepositoryMixin:
    def authorize_corrected_panel_citation_resume_extension(
        self,
        failed_run_id: str,
        *,
        rearm_evidence: Mapping[str, Any],
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        """Authorize one call to resume the exact failed first critique."""
        if confirmation != SHADOW_RESEARCH_CORRECTED_PANEL_CITATION_RESUME_CONFIRMATION:
            raise PermissionError(
                "corrected panel citation resume requires exact owner confirmation"
            )
        approved_by = approved_by.strip()
        notes = notes.strip()
        if not approved_by or not notes:
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_approver_and_notes_required"
            )
        normalized_rearm_evidence = require_corrected_panel_rearm_evidence(
            rearm_evidence
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                """
                SELECT *
                FROM ai_shadow_research_corrected_panel_citation_resume_extensions
                WHERE failed_run_id=?
                """,
                (failed_run_id,),
            ).fetchone()
            if existing is not None:
                if existing["approved_by"] != approved_by or existing["notes"] != notes:
                    raise ShadowResearchRejected(
                        "corrected_panel_citation_resume_authorization_conflict"
                    )
                return self._corrected_panel_citation_resume_extension_row(
                    conn, existing
                )

            failed_run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (failed_run_id,),
            ).fetchone()
            if failed_run is None:
                raise LookupError(f"shadow research run not found: {failed_run_id}")
            failed_run_mapping = dict(failed_run)
            if (
                failed_run["status"] != "failed"
                or failed_run["failure_code"] != "sequential_iteration_not_complete"
                or int(failed_run["candidate_count"] or 0) != 0
                or failed_run["market_date"] != normalized_rearm_evidence["market_date"]
            ):
                raise ShadowResearchRejected(
                    "corrected_panel_citation_resume_requires_exact_failed_run"
                )
            rearm = conn.execute(
                """
                SELECT authorization.provider_call_ceiling,
                       authorization.expected_rearm_evidence_fingerprint
                FROM ai_shadow_research_corrected_panel_rearm_consumptions
                     AS consumption
                JOIN ai_shadow_research_corrected_panel_rearm_authorizations
                     AS authorization
                  ON authorization.authorization_id=consumption.authorization_id
                WHERE consumption.replacement_run_id=?
                  AND authorization.market_date=?
                """,
                (failed_run_id, failed_run["market_date"]),
            ).fetchone()
            if (
                rearm is None
                or rearm["expected_rearm_evidence_fingerprint"]
                != normalized_rearm_evidence["evidence_fingerprint"]
            ):
                raise ShadowResearchRejected(
                    "corrected_panel_citation_resume_rearm_evidence_drift"
                )
            checkpoint = self._first_critique_resume_checkpoint(
                conn, failed_run_mapping
            )
            market_date = str(failed_run["market_date"])
            provider_calls = self._real_provider_call_count(conn, market_date)
            prior_ceiling = self._effective_provider_call_ceiling(
                conn,
                run_id=failed_run_id,
                market_date=market_date,
                call_limit=SHADOW_RESEARCH_MAX_PROVIDER_CALLS,
            )
            provider_call_ceiling = prior_ceiling + 1
            failed_call_id = str(checkpoint["failed_call_id"])
            if (
                provider_calls != 16
                or prior_ceiling != 24
                or int(rearm["provider_call_ceiling"]) != 24
                or provider_call_ceiling != 25
                or provider_call_ceiling - provider_calls != 9
            ):
                raise ShadowResearchRejected(
                    "corrected_panel_citation_resume_must_add_exactly_one_call"
                )
            extension_id = (
                "ai-shadow-research-corrected-panel-citation-resume:"
                + content_fingerprint(
                    {
                        "failed_run_id": failed_run_id,
                        "failed_call_id": failed_call_id,
                        "checkpoint_fingerprint": checkpoint["checkpoint_fingerprint"],
                        "provider_calls_at_authorization": provider_calls,
                        "prior_provider_call_ceiling": prior_ceiling,
                        "provider_call_ceiling": provider_call_ceiling,
                        "approved_by": approved_by,
                        "notes": notes,
                    }
                )[:24]
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_corrected_panel_citation_resume_extensions
                (extension_id, failed_run_id, market_date,
                 failed_input_fingerprint, failed_call_id,
                 failed_call_failure_code, checkpoint_fingerprint,
                 provider_calls_at_authorization, prior_provider_call_ceiling,
                 authorized_additional_calls, provider_call_ceiling,
                 resume_iteration, resume_stage, approved_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, 'critique_citation_outside_binding', ?,
                        ?, ?, 1, ?, 1, 'critique', ?, ?, ?)
                """,
                (
                    extension_id,
                    failed_run_id,
                    market_date,
                    failed_run["input_fingerprint"],
                    failed_call_id,
                    checkpoint["checkpoint_fingerprint"],
                    provider_calls,
                    prior_ceiling,
                    provider_call_ceiling,
                    approved_by,
                    notes,
                    now,
                ),
            )
            saved = conn.execute(
                """
                SELECT *
                FROM ai_shadow_research_corrected_panel_citation_resume_extensions
                WHERE extension_id=?
                """,
                (extension_id,),
            ).fetchone()
            if saved is None:
                raise RuntimeError(
                    "corrected panel citation resume authorization persistence failed"
                )
            return self._corrected_panel_citation_resume_extension_row(conn, saved)

    def _unconsumed_corrected_panel_citation_resume_extension(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> sqlite3.Row | None:
        if (
            run.get("status") != "failed"
            or run.get("failure_code") != "sequential_iteration_not_complete"
            or int(run.get("candidate_count") or 0) != 0
        ):
            return None
        return conn.execute(
            """
            SELECT extension.*
            FROM ai_shadow_research_corrected_panel_citation_resume_extensions
                 AS extension
            LEFT JOIN ai_shadow_research_corrected_panel_citation_resume_consumptions
                 AS consumption
              ON consumption.extension_id=extension.extension_id
            WHERE extension.failed_run_id=?
              AND extension.failed_input_fingerprint=?
              AND extension.failed_call_failure_code=?
              AND extension.resume_iteration=?
              AND extension.resume_stage=?
              AND consumption.extension_id IS NULL
            """,
            (
                run["run_id"],
                run["input_fingerprint"],
                CORRECTED_PANEL_CITATION_FAILURE_CODE,
                CORRECTED_PANEL_CITATION_RESUME_ITERATION,
                CORRECTED_PANEL_CITATION_RESUME_STAGE,
            ),
        ).fetchone()

    def load_first_critique_resume_checkpoint(
        self,
        run_id: str,
        *,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise LookupError(f"shadow research run not found: {run_id}")
            checkpoint = self._first_critique_resume_checkpoint(conn, dict(run))
        if checkpoint["checkpoint_fingerprint"] != expected_fingerprint:
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_checkpoint_drift"
            )
        return checkpoint

    def _first_critique_resume_checkpoint(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> dict[str, Any]:
        candidate_rows = conn.execute(
            "SELECT * FROM ai_shadow_research_candidates WHERE run_id=?",
            (run["run_id"],),
        ).fetchall()
        if len(candidate_rows) != 1:
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_candidate_lineage_invalid"
            )
        candidate = shadow_research_candidate_row(candidate_rows[0])
        session = conn.execute(
            "SELECT * FROM ai_strategy_research_sessions WHERE session_id=?",
            (candidate["session_id"],),
        ).fetchone()
        draft_row = conn.execute(
            "SELECT * FROM ai_strategy_hypothesis_drafts WHERE draft_id=?",
            (candidate["draft_id"],),
        ).fetchone()
        backtest = conn.execute(
            "SELECT * FROM ai_strategy_formula_backtests WHERE backtest_run_id=?",
            (candidate["backtest_run_id"],),
        ).fetchone()
        critique_rows = conn.execute(
            """
            SELECT * FROM ai_strategy_backtest_critiques
            WHERE session_id=? AND draft_id=? AND backtest_run_id=?
            ORDER BY created_at, critique_id
            """,
            (
                candidate["session_id"],
                candidate["draft_id"],
                candidate["backtest_run_id"],
            ),
        ).fetchall()
        provider_calls = conn.execute(
            """
            SELECT call_id, run_id, market_date, call_kind, status,
                   actual_tokens, failure_code
            FROM ai_shadow_research_provider_calls
            WHERE run_id=? ORDER BY created_at, call_id
            """,
            (run["run_id"],),
        ).fetchall()
        resume_consumption = conn.execute(
            """
            SELECT consumption.checkpoint_fingerprint
            FROM ai_shadow_research_corrected_panel_citation_resume_consumptions
                 AS consumption
            JOIN ai_shadow_research_corrected_panel_citation_resume_extensions
                 AS extension
              ON extension.extension_id=consumption.extension_id
            WHERE consumption.resumed_run_id=?
              AND extension.failed_input_fingerprint=?
            """,
            (run["run_id"], run["input_fingerprint"]),
        ).fetchone()
        if (
            session is None
            or draft_row is None
            or backtest is None
            or len(critique_rows) != 1
            or len(provider_calls) != 2
        ):
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_checkpoint_incomplete"
            )
        critique = critique_rows[0]
        draft = shadow_research_json_object(draft_row["contract_json"])
        session_request = shadow_research_json_object(session["request_json"])
        comparison = candidate.get("comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        expected_context = build_shadow_research_iteration_context(
            iteration_number=CORRECTED_PANEL_CITATION_RESUME_ITERATION,
            total_iterations=SHADOW_RESEARCH_MAX_CANDIDATES,
            previous_iteration=None,
        )
        expected_hypothesis_call_id = (
            f"{run['run_id']}:hypothesis:iteration:"
            f"{CORRECTED_PANEL_CITATION_RESUME_ITERATION:02d}"
        )
        expected_backtest_idempotency_key = (
            f"{run['run_id']}:backtest:{candidate['draft_id']}"
        )
        expected_critique_call_id = f"{run['run_id']}:critique:{candidate['draft_id']}"
        call_by_id = {str(row["call_id"]): row for row in provider_calls}
        hypothesis_call = call_by_id.get(expected_hypothesis_call_id)
        failed_critique_call = call_by_id.get(expected_critique_call_id)
        expected_lineage = build_shadow_research_iteration_lineage(
            expected_context,
            current_formula_fingerprint=draft.get("formula_fingerprint"),
        )
        failed_state = (
            run.get("status") == "failed"
            and run.get("failure_code") == "sequential_iteration_not_complete"
            and resume_consumption is None
        )
        resumed_state = (
            run.get("status") == "running"
            and run.get("failure_code") is None
            and resume_consumption is not None
        )
        if (
            not (failed_state or resumed_state)
            or int(run.get("candidate_count") or 0) != 0
            or candidate["status"] != "failed_closed"
            or candidate["recommendation"] != "reject"
            or candidate["promotion_status"] != "blocked_by_evidence"
            or candidate.get("critique_id") is not None
            or int(candidate.get("baseline_result_id") or 0)
            != int(run.get("baseline_result_id") or 0)
            or int(candidate.get("candidate_result_id") or 0) <= 0
            or comparison.get("failure_code")
            != CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE
            or comparison.get("iteration_lineage") != expected_lineage
            or comparison.get("promotion_gate", {}).get("status") != "blocked"
            or comparison.get("promotion_gate", {}).get("blockers")
            != [CORRECTED_PANEL_CITATION_CANDIDATE_FAILURE_CODE]
            or session["status"] != "completed"
            or session["failure_code"] is not None
            or session["idempotency_key"] != expected_hypothesis_call_id
            or session_request.get("iteration_context") != expected_context
            or draft_row["session_id"] != candidate["session_id"]
            or draft_row["validation_status"] != "valid"
            or not draft
            or draft_row["artifact_fingerprint"] != content_fingerprint(draft)
            or draft_row["formula_fingerprint"] != draft.get("formula_fingerprint")
            or draft.get("iteration_context_fingerprint")
            != expected_context["context_fingerprint"]
            or backtest["idempotency_key"] != expected_backtest_idempotency_key
            or backtest["session_id"] != candidate["session_id"]
            or backtest["draft_id"] != candidate["draft_id"]
            or backtest["status"] != "completed"
            or backtest["failure_code"] is not None
            or int(backtest["canonical_backtest_result_id"] or 0)
            != int(candidate["candidate_result_id"])
            or critique["idempotency_key"] != expected_critique_call_id
            or critique["session_id"] != candidate["session_id"]
            or critique["draft_id"] != candidate["draft_id"]
            or critique["backtest_run_id"] != candidate["backtest_run_id"]
            or critique["status"] != "failed"
            or critique["failure_code"] != CORRECTED_PANEL_CITATION_FAILURE_CODE
            or critique["normalized_artifact_json"] is not None
            or critique["artifact_fingerprint"] is not None
            or hypothesis_call is None
            or failed_critique_call is None
            or hypothesis_call["call_kind"] != "hypothesis_iteration"
            or hypothesis_call["status"] != "completed"
            or hypothesis_call["failure_code"] is not None
            or failed_critique_call["call_kind"] != "critique"
            or failed_critique_call["status"] != "failed"
            or failed_critique_call["failure_code"]
            != CORRECTED_PANEL_CITATION_FAILURE_CODE
            or any(row["run_id"] != run["run_id"] for row in provider_calls)
            or any(row["market_date"] != run["market_date"] for row in provider_calls)
        ):
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_checkpoint_invalid"
            )
        checkpoint_core = {
            "schema_version": "karkinos.ai.first_critique_resume_checkpoint.v1",
            "run_id": run["run_id"],
            "input_fingerprint": run["input_fingerprint"],
            "baseline_result_id": run.get("baseline_result_id"),
            "valuation_snapshot_id": run.get("valuation_snapshot_id"),
            "ledger_cutoff_id": run.get("ledger_cutoff_id"),
            "session_id": candidate["session_id"],
            "session_request_fingerprint": session["request_fingerprint"],
            "draft_id": candidate["draft_id"],
            "draft_artifact_fingerprint": draft_row["artifact_fingerprint"],
            "draft_formula_fingerprint": draft_row["formula_fingerprint"],
            "backtest_run_id": candidate["backtest_run_id"],
            "backtest_result_id": candidate["candidate_result_id"],
            "backtest_evidence_fingerprint": backtest["evidence_fingerprint"],
            "failed_critique_id": critique["critique_id"],
            "failed_call_id": expected_critique_call_id,
            "failure_code": CORRECTED_PANEL_CITATION_FAILURE_CODE,
            "provider_calls": [dict(row) for row in provider_calls],
            "iteration_context": expected_context,
        }
        checkpoint_fingerprint = content_fingerprint(checkpoint_core)
        if (
            resume_consumption is not None
            and resume_consumption["checkpoint_fingerprint"] != checkpoint_fingerprint
        ):
            raise ShadowResearchRejected(
                "corrected_panel_citation_resume_checkpoint_drift"
            )
        return {
            "checkpoint_fingerprint": checkpoint_fingerprint,
            "resume_iteration": CORRECTED_PANEL_CITATION_RESUME_ITERATION,
            "resume_stage": CORRECTED_PANEL_CITATION_RESUME_STAGE,
            "hypotheses": {
                "session_id": candidate["session_id"],
                "status": "completed",
            },
            "draft": draft,
            "completed_backtest": {
                "backtest_run_id": candidate["backtest_run_id"],
                "candidate_result_id": int(candidate["candidate_result_id"]),
            },
            "iteration_context": expected_context,
            "failed_call_id": expected_critique_call_id,
        }

    def _corrected_panel_citation_resume_extension_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        consumption = conn.execute(
            """
            SELECT resumed_run_id, resumed_input_fingerprint,
                   checkpoint_fingerprint, consumed_at
            FROM ai_shadow_research_corrected_panel_citation_resume_consumptions
            WHERE extension_id=?
            """,
            (row["extension_id"],),
        ).fetchone()
        return {
            **dict(row),
            "consumed": consumption is not None,
            "resumed_run_id": (
                consumption["resumed_run_id"] if consumption is not None else None
            ),
            "resumed_input_fingerprint": (
                consumption["resumed_input_fingerprint"]
                if consumption is not None
                else None
            ),
            "consumed_checkpoint_fingerprint": (
                consumption["checkpoint_fingerprint"]
                if consumption is not None
                else None
            ),
            "consumed_at": (
                consumption["consumed_at"] if consumption is not None else None
            ),
            "automatic_strategy_replacement_enabled": False,
            "production_strategy_mutation_enabled": False,
            "broker_submission_enabled": False,
            "capital_authority_changed": False,
            "authority_effect": "research_only",
        }
