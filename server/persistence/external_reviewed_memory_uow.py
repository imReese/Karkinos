"""Atomic promotion and revocation units for external reviewed memory."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.contracts.external_reviewed_memory import (
    ExternalReviewedMemoryPromotionRejected,
    ExternalReviewedMemoryPromotionRequest,
    ExternalReviewedMemoryRevocationRequest,
    ExternalReviewedMemoryTarget,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
)
from server.contracts.idempotency import IdempotencyConflict


class ExternalReviewedMemoryUnitOfWorkMixin:
    _connection: Any
    _promotion_from_row: Callable[[sqlite3.Row], StoredExternalReviewedMemoryPromotion]
    _revocation_from_row: Callable[
        [sqlite3.Row], StoredExternalReviewedMemoryRevocation
    ]
    _event_hash: Callable[..., str]

    def _record_promotion(
        self,
        *,
        request: ExternalReviewedMemoryPromotionRequest,
        target: ExternalReviewedMemoryTarget,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryPromotion, bool]:
        if not target.eligible or target.memory_content is None:
            raise ExternalReviewedMemoryPromotionRejected(
                "external reviewed memory target is not eligible"
            )
        if (
            target.report_artifact_id is None
            or target.report_artifact_fingerprint is None
            or target.memory_artifact_fingerprint is None
        ):
            raise ExternalReviewedMemoryPromotionRejected(
                "external reviewed memory target is incomplete"
            )
        identity = {
            "review_id": target.review_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": target.fingerprint,
        }
        promotion_id = (
            f"ai-external-memory-promotion-{content_fingerprint(identity)[:24]}"
        )
        memory_artifact_id = (
            f"ai-external-memory-{target.memory_artifact_fingerprint[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_promotions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = self._promotion_from_row(row)
                if (
                    stored.review_id != target.review_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "external reviewed-memory promotion idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT promotion_id FROM ai_external_reviewed_memory_promotions "
                "WHERE review_id = ?",
                (target.review_id,),
            ).fetchone()
            if final is not None:
                raise ExternalReviewedMemoryPromotionRejected(
                    "external analysis review already has a final memory promotion"
                )
            conn.execute(
                """
                INSERT INTO ai_external_reviewed_memory_promotions (
                    promotion_id, review_id, analysis_id, workflow_id,
                    idempotency_key, request_json, request_fingerprint,
                    promotion_target_fingerprint, memory_artifact_id,
                    memory_content_json, memory_artifact_fingerprint,
                    evidence_reference_ids_json, source_context_snapshot_id,
                    source_context_fingerprint, source_retrieval_id,
                    source_retrieval_target_fingerprint, report_artifact_id,
                    report_artifact_fingerprint, provider_id, model_id,
                    prompt_version, promoted_by, rationale, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?)
                """,
                (
                    promotion_id,
                    target.review_id,
                    target.analysis_id,
                    target.workflow_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    memory_artifact_id,
                    canonical_json(target.memory_content),
                    target.memory_artifact_fingerprint,
                    canonical_json(list(target.evidence_reference_ids)),
                    target.source_context_snapshot_id,
                    target.source_context_fingerprint,
                    target.source_retrieval_id,
                    target.source_retrieval_target_fingerprint,
                    target.report_artifact_id,
                    target.report_artifact_fingerprint,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    request.promoted_by,
                    request.rationale,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                promotion_id=promotion_id,
                event_type="external_reviewed_memory_promoted",
                payload={
                    "review_id": target.review_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": target.fingerprint,
                    "memory_artifact_id": memory_artifact_id,
                    "memory_artifact_fingerprint": (target.memory_artifact_fingerprint),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_promotions "
                "WHERE promotion_id = ?",
                (promotion_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external reviewed-memory promotion persistence failed")
        return self._promotion_from_row(row), False

    def _record_revocation(
        self,
        *,
        promotion: StoredExternalReviewedMemoryPromotion,
        request: ExternalReviewedMemoryRevocationRequest,
        created_at: str,
    ) -> tuple[StoredExternalReviewedMemoryRevocation, bool]:
        identity = {
            "promotion_id": promotion.promotion_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": promotion.promotion_target_fingerprint,
            "memory_artifact_fingerprint": promotion.memory_artifact_fingerprint,
        }
        revocation_id = (
            f"ai-external-memory-revocation-{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_revocations "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = self._revocation_from_row(row)
                if (
                    stored.promotion_id != promotion.promotion_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "external reviewed-memory revocation idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT revocation_id FROM ai_external_reviewed_memory_revocations "
                "WHERE promotion_id = ?",
                (promotion.promotion_id,),
            ).fetchone()
            if final is not None:
                raise ExternalReviewedMemoryPromotionRejected(
                    "external reviewed memory is already revoked"
                )
            conn.execute(
                """
                INSERT INTO ai_external_reviewed_memory_revocations (
                    revocation_id, promotion_id, idempotency_key, request_json,
                    request_fingerprint, promotion_target_fingerprint,
                    memory_artifact_fingerprint, revoked_by, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revocation_id,
                    promotion.promotion_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    promotion.promotion_target_fingerprint,
                    promotion.memory_artifact_fingerprint,
                    request.revoked_by,
                    request.reason,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                promotion_id=promotion.promotion_id,
                event_type="external_reviewed_memory_revoked",
                payload={
                    "revocation_id": revocation_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": (
                        promotion.promotion_target_fingerprint
                    ),
                    "memory_artifact_fingerprint": (
                        promotion.memory_artifact_fingerprint
                    ),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_reviewed_memory_revocations "
                "WHERE revocation_id = ?",
                (revocation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("external reviewed-memory revocation persistence failed")
        return self._revocation_from_row(row), False

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        promotion_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash FROM ai_external_reviewed_memory_events "
            "WHERE promotion_id = ? ORDER BY sequence DESC LIMIT 1",
            (promotion_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = self._event_hash(
            promotion_id=promotion_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_reviewed_memory_events (
                promotion_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                promotion_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
