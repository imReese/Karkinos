"""SQLite repository and atomic UoW for promoted-memory retrieval."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.contracts.external_promoted_analysis_memory_retrieval import (
    ExternalPromotedAnalysisMemoryRetrievalAuditReplay,
    ExternalPromotedAnalysisMemoryRetrievalTarget,
    HumanExternalPromotedAnalysisMemoryRetrievalRequest,
    StoredExternalPromotedAnalysisMemoryRetrieval,
)
from server.contracts.idempotency import IdempotencyConflict

EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_retrievals (
    retrieval_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    current_context_snapshot_id TEXT NOT NULL,
    retrieval_target_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(current_context_snapshot_id)
        REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS
idx_ai_external_promoted_analysis_memory_retrievals_created
ON ai_external_promoted_analysis_memory_retrievals(
    created_at DESC,
    retrieval_id DESC
);

CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_retrieval_events (
    retrieval_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(
        event_type = 'external_promoted_analysis_memory_retrieval_started'
    ),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(retrieval_id, sequence),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_promoted_analysis_memory_retrievals(retrieval_id)
);
"""


class ExternalPromotedAnalysisMemoryRetrievalStore:
    """Append-only exact promoted-analysis memory retrievals."""

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
            conn.executescript(EXTERNAL_PROMOTED_ANALYSIS_MEMORY_RETRIEVAL_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedAnalysisMemoryRetrieval | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM "
                    "ai_external_promoted_analysis_memory_retrievals "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return retrieval_from_row(row) if row is not None else None

    def record(
        self,
        *,
        request: HumanExternalPromotedAnalysisMemoryRetrievalRequest,
        target: ExternalPromotedAnalysisMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRetrieval, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "retrieval_target_fingerprint": target.fingerprint,
        }
        retrieval_id = (
            "ai-external-promoted-analysis-memory-retrieval-"
            f"{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_retrievals "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = retrieval_from_row(row)
                if stored.request_fingerprint != request.fingerprint:
                    raise IdempotencyConflict(
                        "promoted-analysis memory retrieval idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_external_promoted_analysis_memory_retrievals (
                    retrieval_id, idempotency_key, request_json,
                    request_fingerprint, current_context_snapshot_id,
                    retrieval_target_fingerprint, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.current_context_snapshot_id,
                    target.fingerprint,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                retrieval_id=retrieval_id,
                payload={
                    "request_fingerprint": request.fingerprint,
                    "retrieval_target_fingerprint": target.fingerprint,
                    "current_context_snapshot_id": (
                        request.current_context_snapshot_id
                    ),
                    "promotion_ids": list(request.promotion_ids),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_retrievals "
                "WHERE retrieval_id = ?",
                (retrieval_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("promoted-analysis memory retrieval persistence failed")
        return retrieval_from_row(row), False

    def get(
        self,
        retrieval_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryRetrieval:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM "
                    "ai_external_promoted_analysis_memory_retrievals "
                    "WHERE retrieval_id = ?",
                    (retrieval_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(
                "promoted-analysis memory retrieval not found: " f"{retrieval_id}"
            )
        return retrieval_from_row(row)

    def list(
        self,
        *,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRetrieval, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("retrieval list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM "
                    "ai_external_promoted_analysis_memory_retrievals "
                    "ORDER BY created_at DESC, retrieval_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(retrieval_from_row(row) for row in rows)

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ExternalPromotedAnalysisMemoryRetrievalAuditReplay:
        retrieval = self.get(retrieval_id)
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM "
                    "ai_external_promoted_analysis_memory_retrieval_events "
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
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append(
                    "promoted-analysis memory retrieval audit sequence drifted"
                )
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append(
                    "promoted-analysis memory retrieval previous hash drifted"
                )
            if str(row["event_type"]) != (
                "external_promoted_analysis_memory_retrieval_started"
            ):
                errors.append("promoted-analysis memory retrieval event type drifted")
            expected_hash = event_hash(
                retrieval_id=retrieval_id,
                sequence=sequence,
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("promoted-analysis memory retrieval event hash drifted")
            if payload.get("request_fingerprint") != retrieval.request_fingerprint:
                errors.append(
                    "promoted-analysis memory retrieval request identity drifted"
                )
            if payload.get("retrieval_target_fingerprint") != (
                retrieval.retrieval_target_fingerprint
            ):
                errors.append(
                    "promoted-analysis memory retrieval target identity drifted"
                )
            if payload.get("current_context_snapshot_id") != (
                retrieval.request.current_context_snapshot_id
            ):
                errors.append(
                    "promoted-analysis memory retrieval context identity drifted"
                )
            if payload.get("promotion_ids") != list(retrieval.request.promotion_ids):
                errors.append(
                    "promoted-analysis memory retrieval promotion ids drifted"
                )
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append(
                "promoted-analysis memory retrieval must contain exactly one event"
            )
        return ExternalPromotedAnalysisMemoryRetrievalAuditReplay(
            retrieval_id=retrieval_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        retrieval_id: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        sequence = 1
        previous_hash = None
        hashed_event = event_hash(
            retrieval_id=retrieval_id,
            sequence=sequence,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_promoted_analysis_memory_retrieval_events (
                retrieval_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retrieval_id,
                sequence,
                "external_promoted_analysis_memory_retrieval_started",
                canonical_json(payload),
                previous_hash,
                hashed_event,
                created_at,
            ),
        )


def event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "retrieval_id": retrieval_id,
            "sequence": sequence,
            "event_type": ("external_promoted_analysis_memory_retrieval_started"),
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )


def retrieval_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedAnalysisMemoryRetrieval:
    request_payload = json.loads(str(row["request_json"]))
    request = HumanExternalPromotedAnalysisMemoryRetrievalRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        requested_by=str(request_payload["requested_by"]),
        purpose=str(request_payload["purpose"]),
        current_context_snapshot_id=str(request_payload["current_context_snapshot_id"]),
        promotion_ids=tuple(str(item) for item in request_payload["promotion_ids"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalPromotedAnalysisMemoryRetrieval(
        retrieval_id=str(row["retrieval_id"]),
        request=request,
        stored_idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        stored_current_context_snapshot_id=str(row["current_context_snapshot_id"]),
        retrieval_target_fingerprint=str(row["retrieval_target_fingerprint"]),
        created_at=str(row["created_at"]),
    )
