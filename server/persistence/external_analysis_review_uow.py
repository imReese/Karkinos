"""Atomic write unit for external-analysis human reviews."""

from __future__ import annotations

import sqlite3
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.external_analysis_review_values import (
    external_analysis_review_cost_evidence,
    external_analysis_review_event_hash,
)
from server.contracts.idempotency import IdempotencyConflict


class ExternalAnalysisReviewUnitOfWorkMixin:
    """Own the review and audit-event transaction boundary."""

    _rejected_type: Any
    _connection: Any
    _review_from_row: Any

    def _record(
        self,
        *,
        target: Any,
        request: Any,
        created_at: str,
    ) -> tuple[object, bool]:
        identity = {
            "analysis_id": target.analysis_id,
            "request_fingerprint": request.fingerprint,
            "analysis_target_fingerprint": target.fingerprint,
        }
        review_id = f"ai-external-review-{content_fingerprint(identity)[:24]}"
        cost_evidence = external_analysis_review_cost_evidence(
            request,
            target.quality_evidence,
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_analysis_reviews WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = self._review_from_row(existing)
                if (
                    stored.analysis_id != target.analysis_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "external analysis review idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT review_id FROM ai_external_analysis_reviews "
                "WHERE analysis_id = ?",
                (target.analysis_id,),
            ).fetchone()
            if final is not None:
                raise self._rejected_type("external analysis review is already final")
            conn.execute(
                """
                INSERT INTO ai_external_analysis_reviews (
                    review_id, analysis_id, workflow_id, idempotency_key,
                    request_json, request_fingerprint,
                    analysis_target_fingerprint, report_artifact_id,
                    provider_id, model_id, prompt_version,
                    quality_evidence_json, cost_evidence_json, reviewed_by,
                    decision, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    target.analysis_id,
                    target.workflow_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    target.report_artifact_id,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    canonical_json(target.quality_evidence),
                    canonical_json(cost_evidence),
                    request.reviewed_by,
                    request.decision.value,
                    request.note,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                review_id=review_id,
                event_type="external_analysis_review_recorded",
                payload={
                    "analysis_id": target.analysis_id,
                    "analysis_target_fingerprint": target.fingerprint,
                    "decision": request.decision.value,
                    "report_artifact_id": target.report_artifact_id,
                    "provider_id": target.provider_id,
                    "model_id": target.model_id,
                    "prompt_version": target.prompt_version,
                    "request_fingerprint": request.fingerprint,
                    "quality_evidence_fingerprint": content_fingerprint(
                        target.quality_evidence
                    ),
                    "cost_evidence_fingerprint": content_fingerprint(cost_evidence),
                    "memory_recall_eligible": False,
                    "provider_promotion_eligible": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_analysis_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external analysis review persistence failed")
        return self._review_from_row(row), False

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        review_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash FROM ai_external_analysis_review_events "
            "WHERE review_id = ? ORDER BY sequence DESC LIMIT 1",
            (review_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = external_analysis_review_event_hash(
            review_id=review_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_analysis_review_events (
                review_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
