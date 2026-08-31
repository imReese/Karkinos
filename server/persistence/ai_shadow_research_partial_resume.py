"""Provider-free and timeout partial-resume checkpoints."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
    SHADOW_RESEARCH_MAX_CANDIDATES,
    TIMEOUT_RESUME_COMPLETED_ITERATIONS,
    TIMEOUT_RESUME_ITERATION,
    ShadowResearchRejected,
    build_shadow_research_iteration_context,
    build_shadow_research_iteration_lineage,
    shadow_research_json_object,
)
from server.persistence.ai_shadow_research_records import (
    shadow_research_candidate_row,
)


class ShadowResearchPartialResumeRepositoryMixin:
    def load_partial_resume_checkpoint(
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
            checkpoint = self._partial_resume_checkpoint(conn, dict(run))
        if checkpoint["completed_evidence_fingerprint"] != expected_fingerprint:
            raise ShadowResearchRejected("timeout_resume_completed_evidence_drift")
        return checkpoint

    def load_provider_free_partial_resume_checkpoint(
        self,
        run_id: str,
        *,
        resume_id: str,
        expected_fingerprint: str,
    ) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            run = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            resume = conn.execute(
                """
                SELECT * FROM ai_shadow_research_provider_free_partial_resumes
                WHERE resume_id=? AND run_id=?
                """,
                (resume_id, run_id),
            ).fetchone()
            if run is None or resume is None:
                raise ShadowResearchRejected(
                    "provider_free_partial_resume_evidence_missing"
                )
            checkpoint = self._partial_resume_checkpoint(
                conn,
                {
                    **dict(run),
                    "input_fingerprint": resume["prior_input_fingerprint"],
                },
                completed_iteration_count=int(resume["completed_iteration_count"]),
                resume_iteration=int(resume["resume_iteration"]),
            )
        if (
            checkpoint["completed_evidence_fingerprint"] != expected_fingerprint
            or expected_fingerprint != resume["completed_evidence_fingerprint"]
        ):
            raise ShadowResearchRejected(
                "provider_free_partial_resume_completed_evidence_drift"
            )
        return checkpoint

    def _provider_free_partial_resume_evidence(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if run.get("status") != "failed" or run.get("failure_code") not in {
            "strategy_research_rejected",
            *LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
        }:
            return None
        existing = conn.execute(
            """
            SELECT 1 FROM ai_shadow_research_provider_free_partial_resumes
            WHERE run_id=? LIMIT 1
            """,
            (run["run_id"],),
        ).fetchone()
        if existing is not None:
            return None
        failed_calls = conn.execute(
            """
            SELECT * FROM ai_shadow_research_provider_calls
            WHERE run_id=? AND call_kind='hypothesis_iteration'
              AND status='failed' AND COALESCE(actual_tokens, 0)=0
              AND failure_code IN (
                  'strategy_research_rejected',
                  'strategy_research_citation_catalog_too_large'
              )
            ORDER BY created_at, call_id
            """,
            (run["run_id"],),
        ).fetchall()
        if len(failed_calls) != 1:
            return None
        failed_call = failed_calls[0]
        last_call = conn.execute(
            """
            SELECT call_id FROM ai_shadow_research_provider_calls
            WHERE run_id=? ORDER BY created_at DESC, call_id DESC LIMIT 1
            """,
            (run["run_id"],),
        ).fetchone()
        if last_call is None or last_call["call_id"] != failed_call["call_id"]:
            return None
        call_prefix = f"{run['run_id']}:hypothesis:iteration:"
        call_suffix = str(failed_call["call_id"])[len(call_prefix) :]
        if (
            not str(failed_call["call_id"]).startswith(call_prefix)
            or len(call_suffix) != 2
            or not call_suffix.isdigit()
        ):
            return None
        resume_iteration = int(call_suffix)
        completed_iteration_count = resume_iteration - 1
        if not 1 <= completed_iteration_count < SHADOW_RESEARCH_MAX_CANDIDATES:
            return None
        session = conn.execute(
            """
            SELECT * FROM ai_strategy_research_sessions
            WHERE idempotency_key=?
            """,
            (failed_call["call_id"],),
        ).fetchone()
        if (
            session is None
            or session["status"] != "failed"
            or session["failure_code"]
            not in {
                "strategy_research_rejected",
                *LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
            }
            or not session["workflow_id"]
        ):
            return None
        workflow = conn.execute(
            "SELECT * FROM ai_workflows WHERE workflow_id=?",
            (session["workflow_id"],),
        ).fetchone()
        agent_runs = conn.execute(
            "SELECT * FROM ai_agent_runs WHERE workflow_id=?",
            (session["workflow_id"],),
        ).fetchall()
        if (
            workflow is None
            or workflow["status"] != "failed"
            or workflow["failure_code"]
            not in {
                "strategy_research_rejected",
                *LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
            }
            or len(agent_runs) != 1
        ):
            return None
        agent_run = agent_runs[0]
        response = shadow_research_json_object(agent_run["response_json"])
        turns = response.get("turns")
        first_turn = turns[0] if isinstance(turns, list) and len(turns) == 1 else None
        tool_requests = (
            first_turn.get("tool_requests") if isinstance(first_turn, Mapping) else None
        )
        tool_names = (
            {str(item.get("tool_name") or "") for item in tool_requests}
            if isinstance(tool_requests, list)
            and all(isinstance(item, Mapping) for item in tool_requests)
            else set()
        )
        failure_code = str(response.get("error") or "")
        if (
            agent_run["status"] != "failed"
            or agent_run["error_code"]
            not in {
                "strategy_research_rejected",
                *LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES,
            }
            or failure_code not in LOCAL_PROVIDER_FREE_PARTIAL_FAILURE_CODES
            or not response
            or content_fingerprint(response) != agent_run["response_fingerprint"]
            or not isinstance(first_turn, Mapping)
            or first_turn.get("artifacts") != []
            or first_turn.get("partial") is not False
            or not isinstance(tool_requests, list)
            or len(tool_requests) != 4
            or tool_names
            != {
                "research_evidence.read",
                "account_state_projection.read",
                "formula_operator_catalog.read",
                "strategy_research_selection.read",
            }
        ):
            return None
        checkpoint = self._partial_resume_checkpoint(
            conn,
            run,
            completed_iteration_count=completed_iteration_count,
            resume_iteration=resume_iteration,
        )
        failure_evidence = {
            "schema_version": "karkinos.ai.provider_free_partial_failure.v1",
            "run_id": run["run_id"],
            "market_date": run["market_date"],
            "failed_call": {
                key: failed_call[key]
                for key in (
                    "call_id",
                    "call_kind",
                    "status",
                    "actual_tokens",
                    "failure_code",
                    "created_at",
                    "updated_at",
                )
            },
            "failed_session_id": session["session_id"],
            "session_request_fingerprint": session["request_fingerprint"],
            "failed_workflow_id": workflow["workflow_id"],
            "workflow_definition_fingerprint": workflow["definition_fingerprint"],
            "failed_agent_run_id": agent_run["run_id"],
            "agent_request_fingerprint": agent_run["request_fingerprint"],
            "agent_response_fingerprint": agent_run["response_fingerprint"],
            "failure_code": failure_code,
            "completed_iteration_count": completed_iteration_count,
            "completed_evidence_fingerprint": checkpoint[
                "completed_evidence_fingerprint"
            ],
            "resume_iteration": resume_iteration,
            "provider_transport_started": False,
            "authority_effect": "none",
        }
        return {
            **failure_evidence,
            "failed_call_id": failed_call["call_id"],
            "failed_session_id": session["session_id"],
            "failed_workflow_id": workflow["workflow_id"],
            "failed_agent_run_id": agent_run["run_id"],
            "failure_evidence_fingerprint": content_fingerprint(failure_evidence),
        }

    def _partial_resume_checkpoint(
        self,
        conn: sqlite3.Connection,
        run: Mapping[str, Any],
        *,
        completed_iteration_count: int = TIMEOUT_RESUME_COMPLETED_ITERATIONS,
        resume_iteration: int = TIMEOUT_RESUME_ITERATION,
    ) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT c.candidate_id, c.run_id, c.session_id, c.draft_id,
                   c.backtest_run_id, c.critique_id, c.baseline_result_id,
                   c.candidate_result_id, c.status, c.recommendation,
                   c.comparison_json, c.promotion_status, c.created_at,
                   c.updated_at,
                   s.idempotency_key AS session_idempotency_key,
                   s.request_fingerprint AS session_request_fingerprint,
                   s.request_json AS session_request_json,
                   s.selection_fingerprint AS session_selection_fingerprint,
                   s.status AS session_status,
                   d.contract_json AS draft_contract_json,
                   d.artifact_fingerprint AS draft_artifact_fingerprint,
                   d.formula_fingerprint AS draft_formula_fingerprint,
                   d.validation_status AS draft_validation_status,
                   b.idempotency_key AS backtest_idempotency_key,
                   b.session_id AS backtest_session_id,
                   b.draft_id AS backtest_draft_id,
                   b.status AS backtest_status,
                   b.canonical_backtest_result_id,
                   b.evidence_fingerprint AS backtest_evidence_fingerprint,
                   q.idempotency_key AS critique_idempotency_key,
                   q.session_id AS critique_session_id,
                   q.draft_id AS critique_draft_id,
                   q.backtest_run_id AS critique_backtest_run_id,
                   q.status AS critique_status,
                   q.normalized_artifact_json AS critique_artifact_json,
                   q.artifact_fingerprint AS critique_artifact_fingerprint
            FROM ai_shadow_research_candidates AS c
            LEFT JOIN ai_strategy_research_sessions AS s
              ON s.session_id=c.session_id
            LEFT JOIN ai_strategy_hypothesis_drafts AS d
              ON d.session_id=c.session_id AND d.draft_id=c.draft_id
            LEFT JOIN ai_strategy_formula_backtests AS b
              ON b.backtest_run_id=c.backtest_run_id
            LEFT JOIN ai_strategy_backtest_critiques AS q
              ON q.critique_id=c.critique_id
            WHERE c.run_id=?
            ORDER BY CAST(json_extract(c.comparison_json,
                         '$.iteration_lineage.iteration_number') AS INTEGER),
                     c.created_at, c.candidate_id
            """,
            (run["run_id"],),
        ).fetchall()
        if (
            completed_iteration_count <= 0
            or resume_iteration != completed_iteration_count + 1
            or resume_iteration > SHADOW_RESEARCH_MAX_CANDIDATES
            or len(rows) != completed_iteration_count
        ):
            raise ShadowResearchRejected(
                "timeout_resume_requires_exact_four_completed_candidates"
            )
        candidates: list[dict[str, Any]] = []
        drafts: list[dict[str, Any]] = []
        evidence_iterations: list[dict[str, Any]] = []
        previous_iteration: dict[str, Any] | None = None
        candidate_columns = (
            "candidate_id",
            "run_id",
            "session_id",
            "draft_id",
            "backtest_run_id",
            "critique_id",
            "baseline_result_id",
            "candidate_result_id",
            "status",
            "recommendation",
            "comparison_json",
            "promotion_status",
            "created_at",
            "updated_at",
        )
        for expected_iteration, row in enumerate(rows, start=1):
            candidate = shadow_research_candidate_row(
                {key: row[key] for key in candidate_columns}
            )
            draft = shadow_research_json_object(row["draft_contract_json"])
            session_request = shadow_research_json_object(row["session_request_json"])
            critique_artifact = shadow_research_json_object(
                row["critique_artifact_json"]
            )
            expected_context = build_shadow_research_iteration_context(
                iteration_number=expected_iteration,
                total_iterations=SHADOW_RESEARCH_MAX_CANDIDATES,
                previous_iteration=previous_iteration,
            )
            comparison = candidate["comparison"]
            expected_lineage = build_shadow_research_iteration_lineage(
                expected_context,
                current_formula_fingerprint=draft.get("formula_fingerprint"),
            )
            expected_hypothesis_call_prefix = (
                f"{run['run_id']}:hypothesis:iteration:{expected_iteration:02d}"
            )
            expected_backtest_idempotency_key = (
                f"{run['run_id']}:backtest:{candidate['draft_id']}"
            )
            expected_critique_call_prefix = (
                f"{run['run_id']}:critique:{candidate['draft_id']}"
            )
            hypothesis_call_id = str(row["session_idempotency_key"] or "")
            critique_call_id = str(row["critique_idempotency_key"] or "")
            completed_calls = conn.execute(
                """
                SELECT call_id, run_id, market_date, call_kind, status,
                       actual_tokens, failure_code, created_at, updated_at
                FROM ai_shadow_research_provider_calls
                WHERE call_id IN (?, ?)
                ORDER BY call_id
                """,
                (hypothesis_call_id, critique_call_id),
            ).fetchall()
            completed_call_evidence = [dict(call) for call in completed_calls]
            completed_call_by_id = {
                str(call["call_id"]): call for call in completed_call_evidence
            }
            hypothesis_call = completed_call_by_id.get(hypothesis_call_id)
            critique_call = completed_call_by_id.get(critique_call_id)
            if (
                candidate["status"]
                not in {"awaiting_human_approval", "research_blocked"}
                or candidate["promotion_status"]
                not in {"awaiting_human_approval", "blocked_by_evidence"}
                or int(candidate["baseline_result_id"] or 0)
                != int(run.get("baseline_result_id") or 0)
                or row["session_status"] != "completed"
                or not (
                    hypothesis_call_id == expected_hypothesis_call_prefix
                    or hypothesis_call_id.startswith(
                        expected_hypothesis_call_prefix + ":provider-free-resume:"
                    )
                )
                or session_request.get("iteration_context") != expected_context
                or row["draft_validation_status"] != "valid"
                or not draft
                or row["draft_artifact_fingerprint"] != content_fingerprint(draft)
                or row["draft_formula_fingerprint"] != draft.get("formula_fingerprint")
                or draft.get("iteration_context_fingerprint")
                != expected_context["context_fingerprint"]
                or row["backtest_idempotency_key"] != expected_backtest_idempotency_key
                or row["backtest_session_id"] != candidate["session_id"]
                or row["backtest_draft_id"] != candidate["draft_id"]
                or row["backtest_status"] != "completed"
                or int(row["canonical_backtest_result_id"] or 0)
                != int(candidate["candidate_result_id"] or 0)
                or not (
                    critique_call_id == expected_critique_call_prefix
                    or critique_call_id.startswith(
                        expected_critique_call_prefix
                        + ":corrected-panel-citation-resume:"
                    )
                )
                or row["critique_session_id"] != candidate["session_id"]
                or row["critique_draft_id"] != candidate["draft_id"]
                or row["critique_backtest_run_id"] != candidate["backtest_run_id"]
                or row["critique_status"] != "completed"
                or not critique_artifact
                or row["critique_artifact_fingerprint"]
                != content_fingerprint(critique_artifact)
                or comparison.get("deepseek_critique") != critique_artifact
                or comparison.get("iteration_lineage") != expected_lineage
                or len(completed_calls) != 2
                or hypothesis_call is None
                or critique_call is None
                or hypothesis_call["run_id"] != run["run_id"]
                or critique_call["run_id"] != run["run_id"]
                or hypothesis_call["market_date"] != run["market_date"]
                or critique_call["market_date"] != run["market_date"]
                or hypothesis_call["call_kind"] != "hypothesis_iteration"
                or critique_call["call_kind"] != "critique"
                or hypothesis_call["status"] != "completed"
                or critique_call["status"] != "completed"
                or hypothesis_call["failure_code"] is not None
                or critique_call["failure_code"] is not None
            ):
                raise ShadowResearchRejected(
                    "timeout_resume_completed_iteration_evidence_invalid"
                )
            candidates.append(candidate)
            drafts.append(draft)
            previous_iteration = {
                "hypotheses": {"session_id": candidate["session_id"]},
                "draft": draft,
                "candidate": candidate,
            }
            evidence_iterations.append(
                {
                    "iteration_number": expected_iteration,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_fingerprint": content_fingerprint(
                        {
                            "candidate_id": candidate["candidate_id"],
                            "session_id": candidate["session_id"],
                            "draft_id": candidate["draft_id"],
                            "backtest_run_id": candidate["backtest_run_id"],
                            "critique_id": candidate["critique_id"],
                            "candidate_result_id": candidate["candidate_result_id"],
                            "status": candidate["status"],
                            "recommendation": candidate["recommendation"],
                            "comparison": comparison,
                        }
                    ),
                    "session_request_fingerprint": row["session_request_fingerprint"],
                    "session_request_json_fingerprint": content_fingerprint(
                        session_request
                    ),
                    "session_selection_fingerprint": row[
                        "session_selection_fingerprint"
                    ],
                    "draft_artifact_fingerprint": row["draft_artifact_fingerprint"],
                    "backtest_evidence_fingerprint": row[
                        "backtest_evidence_fingerprint"
                    ],
                    "critique_artifact_fingerprint": row[
                        "critique_artifact_fingerprint"
                    ],
                    "provider_calls": completed_call_evidence,
                }
            )
        checkpoint_core = {
            "run_id": run["run_id"],
            "input_fingerprint": run["input_fingerprint"],
            "baseline_result_id": run.get("baseline_result_id"),
            "completed_iterations": evidence_iterations,
            "resume_iteration": resume_iteration,
        }
        return {
            "completed_evidence_fingerprint": content_fingerprint(checkpoint_core),
            "completed_iteration_count": len(candidates),
            "resume_iteration": resume_iteration,
            "candidates": candidates,
            "drafts": drafts,
            "previous_iteration": previous_iteration,
        }
