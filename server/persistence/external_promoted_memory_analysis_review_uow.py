"""SQLite repository and atomic UoW for promoted-memory analysis reviews."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.external_analysis_reviews import (
    ExternalAnalysisQualityRubric,
    ExternalAnalysisReviewDecision,
    ProviderPricingSnapshot,
    cost_evidence,
    event_hash,
)
from server.contracts.external_promoted_memory_analysis_review import (
    ExternalPromotedMemoryAnalysisReviewAuditReplay,
    ExternalPromotedMemoryAnalysisReviewRejected,
    ExternalPromotedMemoryAnalysisReviewTarget,
    HumanExternalPromotedMemoryAnalysisReviewRequest,
    StoredExternalPromotedMemoryAnalysisReview,
)
from server.contracts.idempotency import IdempotencyConflict

EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_analysis_reviews (
    review_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL UNIQUE,
    workflow_id TEXT NOT NULL,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    analysis_target_fingerprint TEXT NOT NULL,
    base_analysis_target_fingerprint TEXT NOT NULL,
    source_retrieval_target_fingerprint TEXT,
    report_artifact_id TEXT,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    promotion_ids_json TEXT NOT NULL,
    selected_memory_sources_json TEXT NOT NULL,
    quality_evidence_json TEXT NOT NULL,
    cost_evidence_json TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN (
        'accept_as_reviewed_research', 'request_revision', 'reject'
    )),
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_promoted_memory_analyses(analysis_id),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_promoted_analysis_reviews_created
ON ai_external_promoted_memory_analysis_reviews(created_at DESC, review_id DESC);

CREATE TABLE IF NOT EXISTS ai_external_promoted_memory_analysis_review_events (
    review_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(
        event_type = 'external_promoted_memory_analysis_review_recorded'
    ),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(review_id, sequence),
    FOREIGN KEY(review_id)
        REFERENCES ai_external_promoted_memory_analysis_reviews(review_id)
);
"""


class ExternalPromotedMemoryAnalysisReviewStore:
    """Append-only reviews and one-event audit chains."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_PROMOTED_MEMORY_ANALYSIS_REVIEW_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedMemoryAnalysisReview | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return review_from_row(row) if row is not None else None

    def record(
        self,
        *,
        target: ExternalPromotedMemoryAnalysisReviewTarget,
        request: HumanExternalPromotedMemoryAnalysisReviewRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, bool]:
        identity = {
            "analysis_id": target.analysis_id,
            "request_fingerprint": request.fingerprint,
            "analysis_target_fingerprint": target.fingerprint,
        }
        review_id = f"ai-external-promoted-review-{content_fingerprint(identity)[:24]}"
        # The canonical calculator is structurally shared by both review request
        # contracts; its legacy annotation is narrower than the fields it reads.
        stored_cost_evidence = cost_evidence(
            cast(Any, request), target.quality_evidence
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = review_from_row(existing)
                if (
                    stored.analysis_id != target.analysis_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "external promoted-memory analysis review idempotency key "
                        "was reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT review_id "
                "FROM ai_external_promoted_memory_analysis_reviews "
                "WHERE analysis_id = ?",
                (target.analysis_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedMemoryAnalysisReviewRejected(
                    "external promoted-memory analysis review is already final"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_memory_analysis_reviews (
                    review_id, analysis_id, workflow_id, retrieval_id,
                    idempotency_key, request_json, request_fingerprint,
                    analysis_target_fingerprint,
                    base_analysis_target_fingerprint,
                    source_retrieval_target_fingerprint, report_artifact_id,
                    provider_id, model_id, prompt_version, promotion_ids_json,
                    selected_memory_sources_json, quality_evidence_json,
                    cost_evidence_json, reviewed_by, decision, note, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    review_id,
                    target.analysis_id,
                    target.workflow_id,
                    target.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    target.base_analysis_target_fingerprint,
                    target.source_retrieval_target_fingerprint,
                    target.report_artifact_id,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    canonical_json(list(target.promotion_ids)),
                    canonical_json(list(target.selected_memory_sources)),
                    canonical_json(target.quality_evidence),
                    canonical_json(stored_cost_evidence),
                    request.reviewed_by,
                    request.decision.value,
                    request.note,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                review_id=review_id,
                payload={
                    "analysis_id": target.analysis_id,
                    "workflow_id": target.workflow_id,
                    "retrieval_id": target.retrieval_id,
                    "analysis_target_fingerprint": target.fingerprint,
                    "base_analysis_target_fingerprint": (
                        target.base_analysis_target_fingerprint
                    ),
                    "source_retrieval_target_fingerprint": (
                        target.source_retrieval_target_fingerprint
                    ),
                    "decision": request.decision.value,
                    "report_artifact_id": target.report_artifact_id,
                    "provider_id": target.provider_id,
                    "model_id": target.model_id,
                    "prompt_version": target.prompt_version,
                    "promotion_ids": list(target.promotion_ids),
                    "selected_memory_sources_fingerprint": content_fingerprint(
                        list(target.selected_memory_sources)
                    ),
                    "request_fingerprint": request.fingerprint,
                    "quality_evidence_fingerprint": content_fingerprint(
                        target.quality_evidence
                    ),
                    "cost_evidence_fingerprint": content_fingerprint(
                        stored_cost_evidence
                    ),
                    "memory_artifact_created": False,
                    "memory_recall_eligible": False,
                    "automatic_memory_promotion_enabled": False,
                    "provider_promotion_eligible": False,
                    "decision_handoff_enabled": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                "WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(
                "external promoted-memory analysis review persistence failed"
            )
        return review_from_row(row), False

    def get(self, review_id: str) -> StoredExternalPromotedMemoryAnalysisReview:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_promoted_memory_analysis_reviews "
                    "WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(
                f"external promoted-memory analysis review not found: {review_id}"
            )
        return review_from_row(row)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedMemoryAnalysisReview, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError(
                "external promoted-memory analysis review limit must be between "
                "1 and 200"
            )
        sql = "SELECT * FROM ai_external_promoted_memory_analysis_reviews"
        params: list[object] = []
        if analysis_id is not None:
            sql += " WHERE analysis_id = ?"
            params.append(analysis_id)
        sql += " ORDER BY created_at DESC, review_id DESC LIMIT ?"
        params.append(limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(review_from_row(row) for row in rows)

    def verify_replay(
        self,
        review_id: str,
    ) -> ExternalPromotedMemoryAnalysisReviewAuditReplay:
        review = self.get(review_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * "
                "FROM ai_external_promoted_memory_analysis_review_events "
                "WHERE review_id = ? ORDER BY sequence",
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append(
                    "external promoted-memory analysis review sequence drifted"
                )
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append(
                    "external promoted-memory analysis review previous hash drifted"
                )
            expected_hash = event_hash(
                review_id=review_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append(
                    "external promoted-memory analysis review event hash drifted"
                )
            expected = {
                "analysis_id": review.analysis_id,
                "workflow_id": review.workflow_id,
                "retrieval_id": review.retrieval_id,
                "analysis_target_fingerprint": review.analysis_target_fingerprint,
                "base_analysis_target_fingerprint": (
                    review.base_analysis_target_fingerprint
                ),
                "source_retrieval_target_fingerprint": (
                    review.source_retrieval_target_fingerprint
                ),
                "decision": review.request.decision.value,
                "report_artifact_id": review.report_artifact_id,
                "provider_id": review.provider_id,
                "model_id": review.model_id,
                "prompt_version": review.prompt_version,
                "promotion_ids": list(review.promotion_ids),
                "selected_memory_sources_fingerprint": content_fingerprint(
                    list(review.selected_memory_sources)
                ),
                "request_fingerprint": review.request_fingerprint,
                "quality_evidence_fingerprint": content_fingerprint(
                    review.quality_evidence
                ),
                "cost_evidence_fingerprint": content_fingerprint(review.cost_evidence),
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(
                        "external promoted-memory analysis review " f"{key} drifted"
                    )
            for key in (
                "memory_artifact_created",
                "memory_recall_eligible",
                "automatic_memory_promotion_enabled",
                "provider_promotion_eligible",
                "decision_handoff_enabled",
            ):
                if payload.get(key) is not False:
                    errors.append(
                        "external promoted-memory analysis review "
                        f"{key} boundary drifted"
                    )
            if payload.get("authority_effect") != "none":
                errors.append(
                    "external promoted-memory analysis review authority boundary "
                    "drifted"
                )
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append(
                "external promoted-memory analysis review must contain exactly "
                "one event"
            )
        return ExternalPromotedMemoryAnalysisReviewAuditReplay(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        review_id: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        event_type = "external_promoted_memory_analysis_review_recorded"
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_external_promoted_memory_analysis_review_events "
            "WHERE review_id = ? ORDER BY sequence DESC LIMIT 1",
            (review_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        hashed_event = event_hash(
            review_id=review_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_promoted_memory_analysis_review_events (
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
                hashed_event,
                created_at,
            ),
        )


def review_from_row(row: sqlite3.Row) -> StoredExternalPromotedMemoryAnalysisReview:
    payload = json.loads(str(row["request_json"]))
    rubric_payload = payload["quality_rubric"]
    pricing_payload = payload.get("pricing_snapshot")
    request = HumanExternalPromotedMemoryAnalysisReviewRequest(
        idempotency_key=str(payload["idempotency_key"]),
        reviewed_by=str(payload["reviewed_by"]),
        decision=ExternalAnalysisReviewDecision(str(payload["decision"])),
        note=str(payload["note"]),
        quality_rubric=ExternalAnalysisQualityRubric(
            evidence_grounding=int(rubric_payload["evidence_grounding"]),
            contradiction_handling=int(rubric_payload["contradiction_handling"]),
            uncertainty_calibration=int(rubric_payload["uncertainty_calibration"]),
            decision_usefulness=int(rubric_payload["decision_usefulness"]),
        ),
        factual_error_count=int(payload["factual_error_count"]),
        unsupported_claim_count=int(payload["unsupported_claim_count"]),
        pricing_snapshot=(
            ProviderPricingSnapshot(
                currency=str(pricing_payload["currency"]),
                prompt_price_per_million_tokens=str(
                    pricing_payload["prompt_price_per_million_tokens"]
                ),
                completion_price_per_million_tokens=str(
                    pricing_payload["completion_price_per_million_tokens"]
                ),
                source=str(pricing_payload["source"]),
                effective_at=str(pricing_payload["effective_at"]),
                schema_version=str(pricing_payload["schema_version"]),
            )
            if isinstance(pricing_payload, Mapping)
            else None
        ),
        pricing_unavailable_reason=(
            str(payload["pricing_unavailable_reason"])
            if payload.get("pricing_unavailable_reason") is not None
            else None
        ),
        confirmation=str(payload["confirmation"]),
        schema_version=str(payload["schema_version"]),
    )
    return StoredExternalPromotedMemoryAnalysisReview(
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        retrieval_id=str(row["retrieval_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        analysis_target_fingerprint=str(row["analysis_target_fingerprint"]),
        base_analysis_target_fingerprint=str(row["base_analysis_target_fingerprint"]),
        source_retrieval_target_fingerprint=(
            str(row["source_retrieval_target_fingerprint"])
            if row["source_retrieval_target_fingerprint"] is not None
            else None
        ),
        report_artifact_id=(
            str(row["report_artifact_id"])
            if row["report_artifact_id"] is not None
            else None
        ),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        promotion_ids=tuple(json.loads(str(row["promotion_ids_json"]))),
        selected_memory_sources=tuple(
            dict(item) for item in json.loads(str(row["selected_memory_sources_json"]))
        ),
        quality_evidence=dict(json.loads(str(row["quality_evidence_json"]))),
        cost_evidence=dict(json.loads(str(row["cost_evidence_json"]))),
        created_at=str(row["created_at"]),
    )
