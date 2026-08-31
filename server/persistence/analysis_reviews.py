"""SQLite repository and unit-of-work for fixture analysis reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from server.ai_runtime.analysis_review_schema import ANALYSIS_REVIEW_SCHEMA
from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.store import IdempotencyConflict


class AnalysisReviewPersistenceMixin:
    """Own append-only review persistence while the façade owns contracts."""

    _path: Path

    @staticmethod
    def _review_from_row(row: Any) -> Any:
        raise NotImplementedError

    @staticmethod
    def _review_event_hash(**kwargs: Any) -> str:
        raise NotImplementedError

    @staticmethod
    def _review_rejected(message: str) -> Exception:
        return ValueError(message)

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
            conn.executescript(ANALYSIS_REVIEW_SCHEMA)

    def get_by_idempotency_key(self, idempotency_key: str) -> Any | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_research_task_analysis_reviews "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return self._review_from_row(row) if row is not None else None

    def record(
        self,
        *,
        analysis_id: str,
        task_id: str,
        workflow_id: str,
        target: Any,
        request: Any,
        created_at: str,
    ) -> tuple[Any, bool]:
        identity = {
            "analysis_id": analysis_id,
            "request_fingerprint": request.fingerprint,
            "analysis_target_fingerprint": target.fingerprint,
        }
        review_id = f"ai-analysis-review-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ai_research_task_analysis_reviews "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = self._review_from_row(existing)
                if (
                    stored.analysis_id != analysis_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "analysis review idempotency key was reused with "
                        "different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT review_id FROM ai_research_task_analysis_reviews "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if final is not None:
                raise self._review_rejected("fixture analysis review is already final")
            conn.execute(
                """
                INSERT INTO ai_research_task_analysis_reviews (
                    review_id, analysis_id, task_id, workflow_id,
                    idempotency_key, request_json, request_fingerprint,
                    analysis_target_fingerprint, memory_artifact_id,
                    reviewed_by, decision, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    analysis_id,
                    task_id,
                    workflow_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    target.fingerprint,
                    target.memory_artifact_id,
                    request.reviewed_by,
                    request.decision.value,
                    request.note,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                review_id=review_id,
                event_type="analysis_review_recorded",
                payload={
                    "analysis_id": analysis_id,
                    "analysis_target_fingerprint": target.fingerprint,
                    "decision": request.decision.value,
                    "memory_artifact_id": target.memory_artifact_id,
                    "request_fingerprint": request.fingerprint,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_research_task_analysis_reviews "
                "WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("fixture analysis review persistence failed")
        return self._review_from_row(row), False

    def get(self, review_id: str) -> Any:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_research_task_analysis_reviews "
                    "WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"fixture analysis review not found: {review_id}")
        return self._review_from_row(row)

    def list(
        self,
        *,
        analysis_id: str | None = None,
        limit: int = 50,
    ) -> tuple[Any, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis review list limit must be between 1 and 200")
        sql = "SELECT * FROM ai_research_task_analysis_reviews"
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

    def verify_replay(self, review_id: str) -> Any:
        review = self.get(review_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_research_task_analysis_review_events "
                "WHERE review_id = ? ORDER BY sequence",
                (review_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("analysis review audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("analysis review audit previous hash drifted")
            expected_hash = self._review_event_hash(
                review_id=review_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("analysis review audit event hash drifted")
            if payload.get("analysis_id") != review.analysis_id:
                errors.append("analysis review audit analysis identity drifted")
            if (
                payload.get("analysis_target_fingerprint")
                != review.analysis_target_fingerprint
            ):
                errors.append("analysis review audit target identity drifted")
            if payload.get("decision") != review.decision.value:
                errors.append("analysis review audit decision drifted")
            if payload.get("memory_artifact_id") != review.memory_artifact_id:
                errors.append("analysis review audit memory identity drifted")
            if payload.get("request_fingerprint") != review.request_fingerprint:
                errors.append("analysis review audit request identity drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append("analysis review audit must contain exactly one event")
        return self._audit_replay(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _audit_replay(**kwargs: Any) -> Any:
        raise NotImplementedError

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        review_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_research_task_analysis_review_events "
            "WHERE review_id = ? ORDER BY sequence DESC LIMIT 1",
            (review_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = self._review_event_hash(
            review_id=review_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_research_task_analysis_review_events (
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
