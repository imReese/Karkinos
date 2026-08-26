"""Read repository and audit replay for external reviewed memory."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from server.contracts.external_reviewed_memory import (
    ExternalReviewedMemoryAuditReplay,
    StoredExternalReviewedMemoryPromotion,
    StoredExternalReviewedMemoryRevocation,
)


class ExternalReviewedMemoryRepositoryMixin:
    _path: Path
    _promotion_from_row: Callable[[sqlite3.Row], StoredExternalReviewedMemoryPromotion]
    _revocation_from_row: Callable[
        [sqlite3.Row], StoredExternalReviewedMemoryRevocation
    ]
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
    ) -> StoredExternalReviewedMemoryPromotion | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_reviewed_memory_promotions "
            "WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return self._promotion_from_row(row) if row is not None else None

    def _get_by_review_id(
        self,
        review_id: str,
    ) -> StoredExternalReviewedMemoryPromotion | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_reviewed_memory_promotions WHERE review_id = ?",
            (review_id,),
        )
        return self._promotion_from_row(row) if row is not None else None

    def _get(self, promotion_id: str) -> StoredExternalReviewedMemoryPromotion:
        row = self._one_or_none(
            "SELECT * FROM ai_external_reviewed_memory_promotions "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        if row is None:
            raise LookupError(f"external reviewed memory not found: {promotion_id}")
        return self._promotion_from_row(row)

    def _list(
        self,
        *,
        review_id: str | None = None,
        limit: int = 50,
    ) -> tuple[StoredExternalReviewedMemoryPromotion, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("memory promotion list limit must be between 1 and 200")
        params: tuple[object, ...]
        if review_id is None:
            sql = (
                "SELECT * FROM ai_external_reviewed_memory_promotions "
                "ORDER BY created_at DESC, promotion_id DESC LIMIT ?"
            )
            params = (limit,)
        else:
            sql = (
                "SELECT * FROM ai_external_reviewed_memory_promotions "
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
        return tuple(self._promotion_from_row(row) for row in rows)

    def _get_revocation(
        self,
        promotion_id: str,
    ) -> StoredExternalReviewedMemoryRevocation | None:
        row = self._one_or_none(
            "SELECT * FROM ai_external_reviewed_memory_revocations "
            "WHERE promotion_id = ?",
            (promotion_id,),
        )
        return self._revocation_from_row(row) if row is not None else None

    def _verify_replay(
        self,
        promotion_id: str,
    ) -> ExternalReviewedMemoryAuditReplay:
        promotion = self._get(promotion_id)
        revocation = self._get_revocation(promotion_id)
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_external_reviewed_memory_events "
                    "WHERE promotion_id = ? ORDER BY sequence",
                    (promotion_id,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        errors: list[str] = []
        previous_hash: str | None = None
        expected_types = ["external_reviewed_memory_promoted"]
        if revocation is not None:
            expected_types.append("external_reviewed_memory_revoked")
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            event_type = str(row["event_type"])
            if sequence != expected_sequence:
                errors.append("memory promotion audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("memory promotion audit previous hash drifted")
            expected_hash = self._event_hash(
                promotion_id=promotion_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("memory promotion audit event hash drifted")
            if expected_sequence <= len(expected_types) and event_type != (
                expected_types[expected_sequence - 1]
            ):
                errors.append("memory promotion audit event lifecycle drifted")
            if event_type == "external_reviewed_memory_promoted":
                if payload.get("review_id") != promotion.review_id:
                    errors.append("memory promotion audit review identity drifted")
                if payload.get("request_fingerprint") != (
                    promotion.request_fingerprint
                ):
                    errors.append("memory promotion audit request identity drifted")
                if payload.get("promotion_target_fingerprint") != (
                    promotion.promotion_target_fingerprint
                ):
                    errors.append("memory promotion audit target identity drifted")
                if payload.get("memory_artifact_id") != promotion.memory_artifact_id:
                    errors.append("memory promotion audit artifact identity drifted")
            elif event_type == "external_reviewed_memory_revoked":
                if revocation is None:
                    errors.append("memory revocation event has no stored revocation")
                elif (
                    payload.get("revocation_id") != revocation.revocation_id
                    or payload.get("request_fingerprint")
                    != revocation.request_fingerprint
                ):
                    errors.append("memory revocation audit identity drifted")
            if payload.get("memory_artifact_fingerprint") != (
                promotion.memory_artifact_fingerprint
            ):
                errors.append("memory promotion audit artifact fingerprint drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != len(expected_types):
            errors.append("memory promotion audit event count drifted")
        return ExternalReviewedMemoryAuditReplay(
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
