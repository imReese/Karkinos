"""Candidate and human-only promotion repositories."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from analytics.strategy_advancement_gate import (
    is_valid_passed_strategy_advancement_gate,
)
from server.ai_runtime.contracts import canonical_json, content_fingerprint
from server.contracts.ai_shadow_research_automation import (
    SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND,
    SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL,
    SHADOW_RESEARCH_API_SCHEMA,
    SHADOW_RESEARCH_PROMOTION_CONFIRMATION,
    ShadowResearchRejected,
)
from server.persistence.ai_shadow_research_records import (
    SHADOW_RESEARCH_CAPITAL_MODE_LEGACY_UNKNOWN,
    normalize_shadow_research_run_context,
    shadow_research_candidate_row,
)


class ShadowResearchCandidateRepositoryMixin:
    def save_candidate(
        self,
        *,
        run_id: str,
        session_id: str,
        draft_id: str,
        backtest_run_id: str | None,
        critique_id: str | None,
        baseline_result_id: int,
        candidate_result_id: int | None,
        status: str,
        recommendation: str,
        comparison: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate_id = (
            "ai-shadow-candidate-"
            + content_fingerprint({"run_id": run_id, "draft_id": draft_id})[:24]
        )
        with self._connect(immediate=True) as conn:
            run_row = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run_row is None:
                raise ShadowResearchRejected("candidate_research_run_context_missing")
            run_context = normalize_shadow_research_run_context(
                research_capital_mode=str(run_row["research_capital_mode"] or ""),
                research_context_id=run_row["research_context_id"],
                valuation_snapshot_id=run_row["valuation_snapshot_id"],
                ledger_cutoff_id=run_row["ledger_cutoff_id"],
            )
            _require_candidate_contract_matches_run_context(
                run_context=run_context,
                status=status,
                recommendation=recommendation,
                comparison=comparison,
            )
            promotion_status = (
                "awaiting_human_approval"
                if status == "awaiting_human_approval"
                else (
                    "account_qualification_required"
                    if status == "evaluated_research_only"
                    else "blocked_by_evidence"
                )
            )
            conn.execute(
                """
                INSERT INTO ai_shadow_research_candidates
                (candidate_id, run_id, session_id, draft_id, backtest_run_id,
                 critique_id, baseline_result_id, candidate_result_id, status,
                 recommendation, comparison_json, promotion_status, created_at,
                 updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, draft_id) DO UPDATE SET
                    backtest_run_id=excluded.backtest_run_id,
                    critique_id=excluded.critique_id,
                    candidate_result_id=excluded.candidate_result_id,
                    status=excluded.status,
                    recommendation=excluded.recommendation,
                    comparison_json=excluded.comparison_json,
                    promotion_status=CASE
                        WHEN ai_shadow_research_candidates.promotion_status IN
                             ('paper_shadow_approval_recorded', 'paper_shadow_approved')
                        THEN ai_shadow_research_candidates.promotion_status
                        ELSE excluded.promotion_status
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    candidate_id,
                    run_id,
                    session_id,
                    draft_id,
                    backtest_run_id,
                    critique_id,
                    baseline_result_id,
                    candidate_result_id,
                    status,
                    recommendation,
                    canonical_json(dict(comparison)),
                    promotion_status,
                    now,
                    now,
                ),
            )
        return self.get_candidate(candidate_id)

    def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_shadow_research_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"shadow research candidate not found: {candidate_id}")
        return shadow_research_candidate_row(row)

    def approve_candidate(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        notes: str,
        confirmation: str,
        now: str,
    ) -> dict[str, Any]:
        if confirmation != SHADOW_RESEARCH_PROMOTION_CONFIRMATION:
            raise PermissionError(
                "paper/shadow approval requires exact human confirmation"
            )
        if not approved_by.strip() or not notes.strip():
            raise ShadowResearchRejected("approver_and_notes_required")
        candidate = self.get_candidate(candidate_id)
        comparison = candidate["comparison"]
        if (
            comparison.get("research_capital_mode") == "normalized_notional"
            or comparison.get("account_qualification_status") == "not_evaluated"
        ):
            raise ShadowResearchRejected("candidate_account_qualification_required")
        promotion_gate = comparison.get("promotion_gate")
        if (
            candidate["status"] != "awaiting_human_approval"
            or candidate["recommendation"] != "paper_shadow_review"
            or not is_valid_passed_strategy_advancement_gate(promotion_gate)
        ):
            raise ShadowResearchRejected("candidate_not_eligible_for_paper_shadow")
        candidate_fingerprint = content_fingerprint(
            {
                "candidate_id": candidate_id,
                "comparison": comparison,
                "candidate_result_id": candidate.get("candidate_result_id"),
                "critique_id": candidate.get("critique_id"),
            }
        )
        promotion_id = (
            "ai-shadow-promotion-"
            + content_fingerprint(
                {
                    "candidate_id": candidate_id,
                    "candidate_fingerprint": candidate_fingerprint,
                }
            )[:24]
        )
        with self._connect(immediate=True) as conn:
            run_row = conn.execute(
                "SELECT * FROM ai_shadow_research_runs WHERE run_id=?",
                (candidate["run_id"],),
            ).fetchone()
            if run_row is None:
                raise ShadowResearchRejected(
                    "candidate_research_context_not_account_bound"
                )
            run_context = normalize_shadow_research_run_context(
                research_capital_mode=str(run_row["research_capital_mode"] or ""),
                research_context_id=run_row["research_context_id"],
                valuation_snapshot_id=run_row["valuation_snapshot_id"],
                ledger_cutoff_id=run_row["ledger_cutoff_id"],
            )
            if (
                run_context["research_capital_mode"]
                != SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND
            ):
                raise ShadowResearchRejected(
                    "candidate_research_context_not_account_bound"
                )
            existing = conn.execute(
                "SELECT * FROM ai_shadow_research_promotions WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO ai_shadow_research_promotions
                    VALUES (?, ?, 'paper_shadow', ?, ?, ?, ?)
                    """,
                    (
                        promotion_id,
                        candidate_id,
                        approved_by.strip(),
                        notes.strip(),
                        candidate_fingerprint,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE ai_shadow_research_candidates
                    SET promotion_status='paper_shadow_approval_recorded', updated_at=?
                    WHERE candidate_id=?
                    """,
                    (now, candidate_id),
                )
            else:
                promotion_id = str(existing["promotion_id"])
                approved_by = str(existing["approved_by"])
                notes = str(existing["notes"])
                now = str(existing["created_at"])
        return {
            "schema_version": SHADOW_RESEARCH_API_SCHEMA,
            "promotion_id": promotion_id,
            "candidate_id": candidate_id,
            "target_stage": "paper_shadow",
            "approved_by": approved_by.strip(),
            "notes": notes.strip(),
            "created_at": now,
            "production_strategy_replaced": False,
            "strategy_registry_mutated": False,
            "broker_order_created": False,
            "manual_confirmation_recorded": True,
            "authority_effect": "paper_shadow_research_only",
        }

    def finalize_candidate_paper_shadow_stage(
        self,
        candidate_id: str,
        *,
        strategy_promotion: Mapping[str, Any],
        now: str,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate["promotion_status"] not in {
            "paper_shadow_approval_recorded",
            "paper_shadow_approved",
        }:
            raise ShadowResearchRejected("paper_shadow_approval_not_recorded")
        if (
            strategy_promotion.get("stage") != "paper_shadow"
            or bool(strategy_promotion.get("live_like_enabled"))
            or int(strategy_promotion.get("backtest_result_id") or 0)
            != int(candidate.get("candidate_result_id") or 0)
        ):
            raise ShadowResearchRejected("canonical_paper_shadow_stage_invalid")
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_shadow_research_candidates
                SET promotion_status='paper_shadow_approved', updated_at=?
                WHERE candidate_id=?
                """,
                (now, candidate_id),
            )
        return self.get_candidate(candidate_id)

    def list_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_shadow_research_candidates
                    ORDER BY created_at DESC, candidate_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [shadow_research_candidate_row(row) for row in rows]


def _require_candidate_contract_matches_run_context(
    *,
    run_context: Mapping[str, Any],
    status: str,
    recommendation: str,
    comparison: Mapping[str, Any],
) -> None:
    run_mode = run_context["research_capital_mode"]
    comparison_mode = str(comparison.get("research_capital_mode") or "")
    account_qualification = str(comparison.get("account_qualification_status") or "")
    candidate_contract = (status, recommendation)

    if run_mode == SHADOW_RESEARCH_CAPITAL_MODE_LEGACY_UNKNOWN:
        raise ShadowResearchRejected("legacy_candidate_research_context_unclassified")
    if run_mode == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL:
        if (
            comparison_mode != SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
            or account_qualification != "not_evaluated"
            or candidate_contract
            not in {
                ("evaluated_research_only", "formula_research_candidate"),
                ("failed_closed", "reject"),
            }
        ):
            raise ShadowResearchRejected("normalized_candidate_contract_invalid")
        return
    if run_mode == SHADOW_RESEARCH_CAPITAL_MODE_ACCOUNT_BOUND and (
        comparison_mode == SHADOW_RESEARCH_CAPITAL_MODE_NORMALIZED_NOTIONAL
        or account_qualification == "not_evaluated"
        or status == "evaluated_research_only"
        or recommendation == "formula_research_candidate"
    ):
        raise ShadowResearchRejected("account_bound_candidate_contract_invalid")
