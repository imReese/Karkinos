"""SQLite repository and atomic UoWs for promoted external-analysis memory."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.contracts.external_promoted_analysis_memory import (
    ExternalPromotedAnalysisMemoryAuditReplay,
    ExternalPromotedAnalysisMemoryPromotionRequest,
    ExternalPromotedAnalysisMemoryRejected,
    ExternalPromotedAnalysisMemoryRevocationRequest,
    ExternalPromotedAnalysisMemoryTarget,
    StoredExternalPromotedAnalysisMemoryPromotion,
    StoredExternalPromotedAnalysisMemoryRevocation,
)
from server.contracts.idempotency import IdempotencyConflict

EXTERNAL_PROMOTED_ANALYSIS_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_promotions (
    promotion_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL UNIQUE,
    analysis_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_id TEXT NOT NULL UNIQUE,
    memory_content_json TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    evidence_reference_ids_json TEXT NOT NULL,
    source_context_snapshot_id TEXT NOT NULL,
    source_context_fingerprint TEXT NOT NULL,
    source_retrieval_target_fingerprint TEXT,
    source_promotion_ids_json TEXT NOT NULL,
    selected_memory_sources_json TEXT NOT NULL,
    report_artifact_id TEXT NOT NULL,
    report_artifact_fingerprint TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    review_target_fingerprint TEXT NOT NULL,
    review_event_hash TEXT,
    quality_evidence_fingerprint TEXT NOT NULL,
    cost_evidence_fingerprint TEXT NOT NULL,
    promoted_by TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(review_id)
        REFERENCES ai_external_promoted_memory_analysis_reviews(review_id),
    FOREIGN KEY(analysis_id)
        REFERENCES ai_external_promoted_memory_analyses(analysis_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_external_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(source_context_snapshot_id)
        REFERENCES ai_context_snapshots(snapshot_id),
    FOREIGN KEY(report_artifact_id) REFERENCES ai_artifacts(artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_external_promoted_analysis_memory_created
ON ai_external_promoted_analysis_memory_promotions(
    created_at DESC, promotion_id DESC
);

CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_revocations (
    revocation_id TEXT PRIMARY KEY,
    promotion_id TEXT NOT NULL UNIQUE,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    promotion_target_fingerprint TEXT NOT NULL,
    memory_artifact_fingerprint TEXT NOT NULL,
    revoked_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_promoted_analysis_memory_promotions(promotion_id)
);

CREATE TABLE IF NOT EXISTS ai_external_promoted_analysis_memory_events (
    promotion_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'external_promoted_analysis_memory_promoted',
        'external_promoted_analysis_memory_revoked'
    )),
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(promotion_id, sequence),
    FOREIGN KEY(promotion_id)
        REFERENCES ai_external_promoted_analysis_memory_promotions(promotion_id)
);
"""


class ExternalPromotedAnalysisMemoryStore:
    """Append-only promotion, revocation, and event storage."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(EXTERNAL_PROMOTED_ANALYSIS_MEMORY_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return promotion_from_row(row) if row is not None else None

    def record_promotion(
        self,
        *,
        request: ExternalPromotedAnalysisMemoryPromotionRequest,
        target: ExternalPromotedAnalysisMemoryTarget,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, bool]:
        if not target.eligible or target.memory_content is None:
            raise ExternalPromotedAnalysisMemoryRejected(
                "promoted-analysis memory target is not eligible"
            )
        if (
            target.report_artifact_id is None
            or target.report_artifact_fingerprint is None
            or target.memory_artifact_fingerprint is None
        ):
            raise ExternalPromotedAnalysisMemoryRejected(
                "promoted-analysis memory target is incomplete"
            )
        identity = {
            "review_id": target.review_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": target.fingerprint,
        }
        promotion_id = (
            "ai-external-promoted-analysis-memory-promotion-"
            f"{content_fingerprint(identity)[:24]}"
        )
        memory_artifact_id = (
            "ai-external-promoted-analysis-memory-"
            f"{target.memory_artifact_fingerprint[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = promotion_from_row(row)
                if (
                    stored.review_id != target.review_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "promoted-analysis memory promotion idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT promotion_id "
                "FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE review_id = ?",
                (target.review_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedAnalysisMemoryRejected(
                    "promoted-memory analysis review already has a final memory "
                    "promotion"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_analysis_memory_promotions (
                    promotion_id, review_id, analysis_id, workflow_id,
                    retrieval_id, idempotency_key, request_json,
                    request_fingerprint, promotion_target_fingerprint,
                    memory_artifact_id, memory_content_json,
                    memory_artifact_fingerprint, evidence_reference_ids_json,
                    source_context_snapshot_id, source_context_fingerprint,
                    source_retrieval_target_fingerprint,
                    source_promotion_ids_json, selected_memory_sources_json,
                    report_artifact_id, report_artifact_fingerprint,
                    provider_id, model_id, prompt_version,
                    review_target_fingerprint, review_event_hash,
                    quality_evidence_fingerprint, cost_evidence_fingerprint,
                    promoted_by, rationale, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    promotion_id,
                    target.review_id,
                    target.analysis_id,
                    target.workflow_id,
                    target.retrieval_id,
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
                    target.source_retrieval_target_fingerprint,
                    canonical_json(list(target.source_promotion_ids)),
                    canonical_json(list(target.selected_memory_sources)),
                    target.report_artifact_id,
                    target.report_artifact_fingerprint,
                    target.provider_id,
                    target.model_id,
                    target.prompt_version,
                    target.review_target_fingerprint,
                    target.review_event_hash,
                    target.quality_evidence_fingerprint,
                    target.cost_evidence_fingerprint,
                    request.promoted_by,
                    request.rationale,
                    created_at,
                ),
            )
            self._append_event(
                conn,
                promotion_id=promotion_id,
                event_type="external_promoted_analysis_memory_promoted",
                payload={
                    "review_id": target.review_id,
                    "analysis_id": target.analysis_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": target.fingerprint,
                    "memory_artifact_id": memory_artifact_id,
                    "memory_artifact_fingerprint": target.memory_artifact_fingerprint,
                    "review_target_fingerprint": target.review_target_fingerprint,
                    "review_event_hash": target.review_event_hash,
                    "source_promotion_ids": list(target.source_promotion_ids),
                    "automatic_recall_enabled": False,
                    "retrieval_contract_available": False,
                    "legacy_phase_1_12_contract_modified": False,
                    "provider_invocation_count": 0,
                    "decision_handoff_enabled": False,
                    "trade_plan_created": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE promotion_id = ?",
                (promotion_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("promoted-analysis memory promotion persistence failed")
        return promotion_from_row(row), False

    def record_revocation(
        self,
        *,
        promotion: StoredExternalPromotedAnalysisMemoryPromotion,
        request: ExternalPromotedAnalysisMemoryRevocationRequest,
        created_at: str,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryRevocation, bool]:
        identity = {
            "promotion_id": promotion.promotion_id,
            "request_fingerprint": request.fingerprint,
            "promotion_target_fingerprint": promotion.promotion_target_fingerprint,
            "memory_artifact_fingerprint": promotion.memory_artifact_fingerprint,
        }
        revocation_id = (
            "ai-external-promoted-analysis-memory-revocation-"
            f"{content_fingerprint(identity)[:24]}"
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = revocation_from_row(row)
                if (
                    stored.promotion_id != promotion.promotion_id
                    or stored.request_fingerprint != request.fingerprint
                ):
                    raise IdempotencyConflict(
                        "promoted-analysis memory revocation idempotency key was "
                        "reused with different input"
                    )
                return stored, True
            final = conn.execute(
                "SELECT revocation_id "
                "FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE promotion_id = ?",
                (promotion.promotion_id,),
            ).fetchone()
            if final is not None:
                raise ExternalPromotedAnalysisMemoryRejected(
                    "promoted-analysis memory is already revoked"
                )
            conn.execute(
                """
                INSERT INTO ai_external_promoted_analysis_memory_revocations (
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
                event_type="external_promoted_analysis_memory_revoked",
                payload={
                    "revocation_id": revocation_id,
                    "request_fingerprint": request.fingerprint,
                    "promotion_target_fingerprint": (
                        promotion.promotion_target_fingerprint
                    ),
                    "memory_artifact_fingerprint": (
                        promotion.memory_artifact_fingerprint
                    ),
                    "automatic_recall_enabled": False,
                    "retrieval_contract_available": False,
                    "legacy_phase_1_12_contract_modified": False,
                    "provider_invocation_count": 0,
                    "decision_handoff_enabled": False,
                    "trade_plan_created": False,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
                "WHERE revocation_id = ?",
                (revocation_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("promoted-analysis memory revocation persistence failed")
        return revocation_from_row(row), False

    def get(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryPromotion:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        if row is None:
            raise LookupError(f"promoted-analysis memory not found: {promotion_id}")
        return promotion_from_row(row)

    def list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalPromotedAnalysisMemoryPromotion, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("memory promotion limit must be between 1 and 200")
        params: tuple[object, ...]
        if review_id is None:
            sql = (
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "ORDER BY created_at DESC, promotion_id DESC LIMIT ?"
            )
            params = (limit,)
        else:
            sql = (
                "SELECT * FROM ai_external_promoted_analysis_memory_promotions "
                "WHERE review_id = ? "
                "ORDER BY created_at DESC, promotion_id DESC LIMIT ?"
            )
            params = (review_id, limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(promotion_from_row(row) for row in rows)

    def get_revocation(
        self,
        promotion_id: str,
    ) -> StoredExternalPromotedAnalysisMemoryRevocation | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_promoted_analysis_memory_revocations "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        return revocation_from_row(row) if row is not None else None

    def verify_replay(
        self,
        promotion_id: str,
    ) -> ExternalPromotedAnalysisMemoryAuditReplay:
        promotion = self.get(promotion_id)
        revocation = self.get_revocation(promotion_id)
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_promoted_analysis_memory_events "
                    "WHERE promotion_id = ? ORDER BY sequence",
                    (promotion_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        errors: list[str] = []
        previous_hash: str | None = None
        expected_types = ["external_promoted_analysis_memory_promoted"]
        if revocation is not None:
            expected_types.append("external_promoted_analysis_memory_revoked")
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            event_type = str(row["event_type"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("promoted-analysis memory audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("promoted-analysis memory audit previous hash drifted")
            expected_hash = event_hash(
                promotion_id=promotion_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("promoted-analysis memory audit event hash drifted")
            if expected_sequence <= len(expected_types) and event_type != (
                expected_types[expected_sequence - 1]
            ):
                errors.append("promoted-analysis memory audit lifecycle drifted")
            if event_type == "external_promoted_analysis_memory_promoted":
                expected = {
                    "review_id": promotion.review_id,
                    "analysis_id": promotion.analysis_id,
                    "request_fingerprint": promotion.request_fingerprint,
                    "promotion_target_fingerprint": (
                        promotion.promotion_target_fingerprint
                    ),
                    "memory_artifact_id": promotion.memory_artifact_id,
                    "memory_artifact_fingerprint": (
                        promotion.memory_artifact_fingerprint
                    ),
                    "review_target_fingerprint": promotion.review_target_fingerprint,
                    "review_event_hash": promotion.review_event_hash,
                    "source_promotion_ids": list(promotion.source_promotion_ids),
                }
            else:
                expected = {}
                if revocation is None:
                    errors.append(
                        "promoted-analysis memory revocation event has no row"
                    )
                else:
                    expected = {
                        "revocation_id": revocation.revocation_id,
                        "request_fingerprint": revocation.request_fingerprint,
                        "promotion_target_fingerprint": (
                            revocation.promotion_target_fingerprint
                        ),
                        "memory_artifact_fingerprint": (
                            revocation.memory_artifact_fingerprint
                        ),
                    }
            for key, value in expected.items():
                if payload.get(key) != value:
                    errors.append(f"promoted-analysis memory audit {key} drifted")
            for key in (
                "automatic_recall_enabled",
                "retrieval_contract_available",
                "legacy_phase_1_12_contract_modified",
                "decision_handoff_enabled",
                "trade_plan_created",
            ):
                if payload.get(key) is not False:
                    errors.append(f"promoted-analysis memory {key} boundary drifted")
            if payload.get("provider_invocation_count") != 0:
                errors.append(
                    "promoted-analysis memory provider invocation boundary drifted"
                )
            if payload.get("authority_effect") != "none":
                errors.append("promoted-analysis memory authority boundary drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != len(expected_types):
            errors.append("promoted-analysis memory audit event count drifted")
        return ExternalPromotedAnalysisMemoryAuditReplay(
            promotion_id=promotion_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    def _one_or_none(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> sqlite3.Row | None:
        try:
            with self._connection() as conn:
                return conn.execute(sql, params).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            return None

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        promotion_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_external_promoted_analysis_memory_events "
            "WHERE promotion_id = ? ORDER BY sequence DESC LIMIT 1",
            (promotion_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        hashed_event = event_hash(
            promotion_id=promotion_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_external_promoted_analysis_memory_events (
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
                hashed_event,
                created_at,
            ),
        )


def event_hash(
    *,
    promotion_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "promotion_id": promotion_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )


def promotion_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedAnalysisMemoryPromotion:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalPromotedAnalysisMemoryPromotionRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        promoted_by=str(request_payload["promoted_by"]),
        rationale=str(request_payload["rationale"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalPromotedAnalysisMemoryPromotion(
        promotion_id=str(row["promotion_id"]),
        review_id=str(row["review_id"]),
        analysis_id=str(row["analysis_id"]),
        workflow_id=str(row["workflow_id"]),
        retrieval_id=str(row["retrieval_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_id=str(row["memory_artifact_id"]),
        memory_content=dict(json.loads(str(row["memory_content_json"]))),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        evidence_reference_ids=tuple(
            str(item) for item in json.loads(str(row["evidence_reference_ids_json"]))
        ),
        source_context_snapshot_id=str(row["source_context_snapshot_id"]),
        source_context_fingerprint=str(row["source_context_fingerprint"]),
        source_retrieval_target_fingerprint=(
            str(row["source_retrieval_target_fingerprint"])
            if row["source_retrieval_target_fingerprint"] is not None
            else None
        ),
        source_promotion_ids=tuple(
            str(item) for item in json.loads(str(row["source_promotion_ids_json"]))
        ),
        selected_memory_sources=tuple(
            dict(item) for item in json.loads(str(row["selected_memory_sources_json"]))
        ),
        report_artifact_id=str(row["report_artifact_id"]),
        report_artifact_fingerprint=str(row["report_artifact_fingerprint"]),
        provider_id=str(row["provider_id"]),
        model_id=str(row["model_id"]),
        prompt_version=str(row["prompt_version"]),
        review_target_fingerprint=str(row["review_target_fingerprint"]),
        review_event_hash=(
            str(row["review_event_hash"])
            if row["review_event_hash"] is not None
            else None
        ),
        quality_evidence_fingerprint=str(row["quality_evidence_fingerprint"]),
        cost_evidence_fingerprint=str(row["cost_evidence_fingerprint"]),
        created_at=str(row["created_at"]),
    )


def revocation_from_row(
    row: sqlite3.Row,
) -> StoredExternalPromotedAnalysisMemoryRevocation:
    request_payload = json.loads(str(row["request_json"]))
    request = ExternalPromotedAnalysisMemoryRevocationRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        revoked_by=str(request_payload["revoked_by"]),
        reason=str(request_payload["reason"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredExternalPromotedAnalysisMemoryRevocation(
        revocation_id=str(row["revocation_id"]),
        promotion_id=str(row["promotion_id"]),
        request=request,
        request_fingerprint=str(row["request_fingerprint"]),
        promotion_target_fingerprint=str(row["promotion_target_fingerprint"]),
        memory_artifact_fingerprint=str(row["memory_artifact_fingerprint"]),
        created_at=str(row["created_at"]),
    )
