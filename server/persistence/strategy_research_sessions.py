"""Session and hypothesis-draft repository operations for strategy research."""

from __future__ import annotations

import json
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_PROMPT_VERSION,
    HypothesisGenerationRequest,
)
from server.persistence.strategy_research_errors import StrategyResearchOperationalError


class StrategyResearchSessionRepositoryMixin:
    def create_or_get_session(
        self,
        request: HypothesisGenerationRequest,
        *,
        created_at: str,
    ) -> tuple[dict[str, Any], bool]:
        session_id = (
            "ai-strategy-session-"
            + content_fingerprint({"idempotency_key": request.idempotency_key})[:24]
        )
        request_json = canonical_json(
            {
                "requested_by": request.requested_by,
                "account_alias": request.account_alias,
                "research_question": request.research_question,
                "selection": request.selection.to_dict(),
                "iteration_context": request.iteration_context,
                "confirmation_recorded": True,
                "api_key_recorded": False,
            }
        )
        with self._connect(immediate=True) as conn:
            existing = conn.execute(
                "SELECT * FROM ai_strategy_research_sessions WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                row = dict(existing)
                if row["request_fingerprint"] != request.fingerprint:
                    raise IdempotencyConflict("strategy research idempotency conflict")
                return row, True
            conn.execute(
                """
                INSERT INTO ai_strategy_research_sessions
                (session_id, idempotency_key, request_fingerprint, request_json,
                 selection_fingerprint, status, prompt_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    session_id,
                    request.idempotency_key,
                    request.fingerprint,
                    request_json,
                    request.selection.fingerprint,
                    STRATEGY_RESEARCH_PROMPT_VERSION,
                    created_at,
                    created_at,
                ),
            )
        self.append_event(
            session_id,
            "strategy_research.requested",
            {"request_fingerprint": request.fingerprint},
            created_at=created_at,
        )
        return self.get_session(session_id), False

    def claim_session_run(
        self,
        session_id: str,
        *,
        binding: JsonObject,
        provider_id: str,
        model_id: str,
        claimed_at: str,
    ) -> bool:
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                """
                UPDATE ai_strategy_research_sessions
                SET status='running', context_snapshot_id=?, context_fingerprint=?,
                    evidence_reference_id=?, workflow_id=?, provider_id=?, model_id=?,
                    run_claimed_at=?, updated_at=?
                WHERE session_id=? AND status='pending' AND run_claimed_at IS NULL
                """,
                (
                    binding["context_snapshot_id"],
                    binding["context_fingerprint"],
                    binding["evidence_reference_id"],
                    binding["workflow_id"],
                    provider_id,
                    model_id,
                    claimed_at,
                    claimed_at,
                    session_id,
                ),
            )
            return cursor.rowcount == 1

    def finish_session(
        self,
        session_id: str,
        *,
        status: str,
        failure_code: str | None,
        updated_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            conn.execute(
                """
                UPDATE ai_strategy_research_sessions
                SET status=?, failure_code=?, updated_at=? WHERE session_id=?
                """,
                (status, failure_code, updated_at, session_id),
            )
        self.append_event(
            session_id,
            f"strategy_research.{status}",
            {"failure_code": failure_code},
            created_at=updated_at,
        )

    def save_drafts(
        self,
        session_id: str,
        drafts: list[JsonObject],
        *,
        created_at: str,
    ) -> None:
        with self._connect(immediate=True) as conn:
            for ordinal, draft in enumerate(drafts, start=1):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ai_strategy_hypothesis_drafts
                    (draft_id, session_id, ordinal, contract_json,
                     artifact_fingerprint, formula_fingerprint, validation_status,
                     validation_errors_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        draft["draft_id"],
                        session_id,
                        ordinal,
                        canonical_json(draft),
                        content_fingerprint(draft),
                        draft.get("formula_fingerprint"),
                        draft["validation"]["status"],
                        canonical_json(draft["validation"]["errors"]),
                        created_at,
                    ),
                )

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                "SELECT * FROM ai_strategy_research_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"strategy research session not found: {session_id}")
        return dict(row)

    def get_session_if_initialized(self, session_id: str) -> dict[str, Any] | None:
        try:
            return self.get_session(session_id)
        except (LookupError, StrategyResearchOperationalError):
            return None

    def list_drafts(self, session_id: str) -> list[dict[str, Any]]:
        try:
            with self._connect_readonly() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_strategy_hypothesis_drafts
                    WHERE session_id=? ORDER BY ordinal
                    """,
                    (session_id,),
                ).fetchall()
        except StrategyResearchOperationalError:
            return []
        return [
            {
                **dict(row),
                "contract": json.loads(row["contract_json"]),
                "validation_errors": json.loads(row["validation_errors_json"]),
            }
            for row in rows
        ]

    def get_draft(self, session_id: str, draft_id: str) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_strategy_hypothesis_drafts
                WHERE session_id=? AND draft_id=?
                """,
                (session_id, draft_id),
            ).fetchone()
        if row is None:
            raise LookupError(f"strategy hypothesis draft not found: {draft_id}")
        result = dict(row)
        result["contract"] = json.loads(result["contract_json"])
        result["validation_errors"] = json.loads(result["validation_errors_json"])
        return result
