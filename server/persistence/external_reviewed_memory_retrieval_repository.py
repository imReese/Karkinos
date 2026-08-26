"""Read repository and audit replay for external reviewed-memory retrieval."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from server.ai_runtime.contracts import JsonObject
from server.contracts.external_reviewed_memory_retrieval import (
    ExternalReviewedMemoryRetrievalAuditReplay,
    StoredExternalReviewedMemoryRetrieval,
)


class ExternalReviewedMemoryRetrievalRepositoryMixin:
    _path: Path
    _retrieval_from_row: Callable[[sqlite3.Row], StoredExternalReviewedMemoryRetrieval]
    _event_hash: Callable[..., str]

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

    def _get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalReviewedMemoryRetrieval | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_reviewed_memory_retrievals "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return self._retrieval_from_row(row) if row is not None else None

    def _get(self, retrieval_id: str) -> StoredExternalReviewedMemoryRetrieval:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_external_reviewed_memory_retrievals "
                    "WHERE retrieval_id = ?",
                    (retrieval_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(
                f"external reviewed-memory retrieval not found: {retrieval_id}"
            )
        return self._retrieval_from_row(row)

    def _list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredExternalReviewedMemoryRetrieval, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("retrieval list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_reviewed_memory_retrievals "
                    "ORDER BY created_at DESC, retrieval_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(self._retrieval_from_row(row) for row in rows)

    def _verify_replay(
        self,
        retrieval_id: str,
    ) -> ExternalReviewedMemoryRetrievalAuditReplay:
        retrieval = self._get(retrieval_id)
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_reviewed_memory_retrieval_events "
                    "WHERE retrieval_id = ? ORDER BY sequence",
                    (retrieval_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload: JsonObject = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("external memory retrieval audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("external memory retrieval previous hash drifted")
            if str(row["event_type"]) != ("external_reviewed_memory_retrieval_started"):
                errors.append("external memory retrieval event type drifted")
            expected_hash = self._event_hash(
                retrieval_id=retrieval_id,
                sequence=sequence,
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("external memory retrieval event hash drifted")
            if payload.get("request_fingerprint") != retrieval.request_fingerprint:
                errors.append("external memory retrieval request identity drifted")
            if payload.get("retrieval_target_fingerprint") != (
                retrieval.retrieval_target_fingerprint
            ):
                errors.append("external memory retrieval target identity drifted")
            if payload.get("current_context_snapshot_id") != (
                retrieval.request.current_context_snapshot_id
            ):
                errors.append("external memory retrieval context identity drifted")
            if payload.get("promotion_ids") != list(retrieval.request.promotion_ids):
                errors.append("external memory retrieval promotion ids drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append("external memory retrieval must contain exactly one event")
        return ExternalReviewedMemoryRetrievalAuditReplay(
            retrieval_id=retrieval_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )
