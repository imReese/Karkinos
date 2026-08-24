"""Critique and human-review repository operations for strategy research."""

from __future__ import annotations

import json
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import (
    REVIEW_CONFIRMATION,
    STRATEGY_RESEARCH_PROMPT_VERSION,
    CritiqueRequest,
    StrategyResearchRejected,
)
from server.persistence.strategy_research_errors import StrategyResearchOperationalError


class StrategyResearchCritiqueRepositoryMixin:
    def create_or_get_critique(
        self,
        request: CritiqueRequest,
        *,
        provider_id: str,
        model_id: str,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        request_fingerprint = content_fingerprint(
            {
                "requested_by": request.requested_by,
                "session_id": request.session_id,
                "draft_id": request.draft_id,
                "backtest_run_id": request.backtest_run_id,
                "confirmation": request.confirmation,
            }
        )
        critique_id = (
            "ai-strategy-critique-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_backtest_critiques WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request_fingerprint:
                    raise IdempotencyConflict("strategy critique idempotency conflict")
                return row, True
            conn.execute(
                """
                INSERT INTO ai_strategy_backtest_critiques
                (critique_id, idempotency_key, request_fingerprint, session_id,
                 draft_id, backtest_run_id, status, provider_id, model_id,
                 prompt_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    critique_id,
                    request.idempotency_key,
                    request_fingerprint,
                    request.session_id,
                    request.draft_id,
                    request.backtest_run_id,
                    provider_id,
                    model_id,
                    STRATEGY_RESEARCH_PROMPT_VERSION,
                    created_at,
                    created_at,
                ),
            )
        return self.get_critique(critique_id), False

    def claim_critique(
        self,
        critique_id: str,
        *,
        workflow_id: str,
        claimed_at: str,
    ) -> bool:
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE ai_strategy_backtest_critiques
                SET status='running', workflow_id=?, run_claimed_at=?, updated_at=?
                WHERE critique_id=? AND status='pending' AND run_claimed_at IS NULL
                """,
                (workflow_id, claimed_at, claimed_at, critique_id),
            )
            return cursor.rowcount == 1

    def finish_critique(
        self,
        critique_id: str,
        *,
        status: str,
        artifact: JsonObject | None,
        failure_code: str | None,
        updated_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_strategy_backtest_critiques
                SET status=?, normalized_artifact_json=?, artifact_fingerprint=?,
                    failure_code=?, updated_at=? WHERE critique_id=?
                """,
                (
                    status,
                    canonical_json(artifact) if artifact is not None else None,
                    content_fingerprint(artifact) if artifact is not None else None,
                    failure_code,
                    updated_at,
                    critique_id,
                ),
            )
        self.append_event(
            critique_id,
            f"strategy_critique.{status}",
            {
                "artifact_fingerprint": (
                    content_fingerprint(artifact) if artifact is not None else None
                ),
                "failure_code": failure_code,
            },
            created_at=updated_at,
        )

    def get_critique(self, critique_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_strategy_backtest_critiques WHERE critique_id=?",
                (critique_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"strategy critique not found: {critique_id}")
        result = dict(row)
        raw = result.get("normalized_artifact_json")
        result["artifact"] = json.loads(raw) if raw else None
        return result

    def save_review(
        self,
        *,
        idempotency_key: str,
        session_id: str,
        critique_id: str,
        critique_artifact_fingerprint: str,
        reviewer: str,
        disposition: str,
        notes: str,
        confirmation: str,
        created_at: str,
    ) -> dict[str, Any]:
        if confirmation != REVIEW_CONFIRMATION:
            raise PermissionError("human review requires exact confirmation")
        if disposition not in {
            "accepted_for_more_research",
            "rejected",
            "needs_revision",
        }:
            raise StrategyResearchRejected("review_disposition_invalid")
        input_fingerprint = content_fingerprint(
            {
                "session_id": session_id,
                "critique_id": critique_id,
                "critique_artifact_fingerprint": critique_artifact_fingerprint,
                "reviewer": reviewer,
                "disposition": disposition,
                "notes": notes,
                "confirmation": confirmation,
            }
        )
        review_id = (
            "ai-strategy-review-"
            + content_fingerprint({"idempotency_key": idempotency_key})[:24]
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_research_reviews WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["input_fingerprint"] != input_fingerprint:
                    raise IdempotencyConflict("strategy review idempotency conflict")
                return row
            conn.execute(
                """
                INSERT INTO ai_strategy_research_reviews
                (review_id, idempotency_key, session_id, critique_id,
                 critique_artifact_fingerprint, reviewer, disposition, notes,
                 input_fingerprint, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    idempotency_key,
                    session_id,
                    critique_id,
                    critique_artifact_fingerprint,
                    reviewer,
                    disposition,
                    notes,
                    input_fingerprint,
                    created_at,
                ),
            )
        self.append_event(
            session_id,
            "strategy_research.review_recorded",
            {
                "review_id": review_id,
                "critique_id": critique_id,
                "critique_artifact_fingerprint": critique_artifact_fingerprint,
                "input_fingerprint": input_fingerprint,
            },
            created_at=created_at,
        )
        return {
            "review_id": review_id,
            "session_id": session_id,
            "critique_id": critique_id,
            "critique_artifact_fingerprint": critique_artifact_fingerprint,
            "reviewer": reviewer,
            "disposition": disposition,
            "notes": notes,
            "input_fingerprint": input_fingerprint,
            "created_at": created_at,
        }

    def list_reviews(self, session_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_strategy_research_reviews
                    WHERE session_id=? ORDER BY created_at, review_id
                    """,
                    (session_id,),
                ).fetchall()
        except StrategyResearchOperationalError:
            return []
        return [dict(row) for row in rows]
