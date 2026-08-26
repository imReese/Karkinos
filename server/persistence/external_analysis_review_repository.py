"""Read-side persistence for external-analysis human reviews."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from server.ai_runtime.contracts import content_fingerprint
from server.ai_runtime.external_analysis_review_values import (
    external_analysis_review_event_hash,
)


class ExternalAnalysisReviewRepositoryMixin:
    """SQLite connection and read ownership for external-analysis reviews."""

    _path: Path
    _audit_replay_type: Any
    _review_from_row: Any

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

    def _get_by_idempotency_key(self, idempotency_key: str) -> Any | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_analysis_reviews "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return self._review_from_row(row) if row is not None else None

    def _get(self, review_id: str) -> Any:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_analysis_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"external analysis review not found: {review_id}")
        return self._review_from_row(row)

    def _list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[Any, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("external analysis review limit must be between 1 and 200")
        sql = "SELECT * FROM ai_external_analysis_reviews"
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
        return tuple(self._review_from_row(row) for row in rows)

    def _verify_replay(self, review_id: str) -> Any:
        review = self._get(review_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_external_analysis_review_events "
                "WHERE review_id = ? ORDER BY sequence",
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("external analysis review sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("external analysis review previous hash drifted")
            expected_hash = external_analysis_review_event_hash(
                review_id=review_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("external analysis review event hash drifted")
            expected = {
                "analysis_id": review.analysis_id,
                "analysis_target_fingerprint": review.analysis_target_fingerprint,
                "decision": review.request.decision.value,
                "report_artifact_id": review.report_artifact_id,
                "provider_id": review.provider_id,
                "model_id": review.model_id,
                "prompt_version": review.prompt_version,
                "request_fingerprint": review.request_fingerprint,
                "quality_evidence_fingerprint": content_fingerprint(
                    review.quality_evidence
                ),
                "cost_evidence_fingerprint": content_fingerprint(review.cost_evidence),
            }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(f"external analysis review {key} drifted")
            if payload.get("memory_recall_eligible") is not False:
                errors.append("external analysis review memory boundary drifted")
            if payload.get("provider_promotion_eligible") is not False:
                errors.append("external analysis review provider boundary drifted")
            if payload.get("authority_effect") != "none":
                errors.append("external analysis review authority boundary drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append("external analysis review must contain exactly one event")
        return self._audit_replay_type(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )
