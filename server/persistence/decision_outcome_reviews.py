"""Transactional decision-outcome review repository and audit replay."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.decision_outcome_review import (
    DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
    DecisionOutcomeReviewReplay,
    DecisionOutcomeReviewRequest,
    DecisionOutcomeReviewTarget,
    StoredDecisionOutcomeReview,
)
from server.contracts.idempotency import IdempotencyConflict
from server.persistence.event_log import insert_event_sync


class DecisionOutcomeReviewStore:
    """Transactional review records plus a tamper-evident event chain."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            yield conn
        finally:
            conn.close()

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> StoredDecisionOutcomeReview | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _review_from_row(row) if row is not None else None

    def get(self, review_id: str) -> StoredDecisionOutcomeReview:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"decision outcome review not found: {review_id}")
        return _review_from_row(row)

    def list_latest_by_signal(
        self,
        *,
        limit: int = 100,
    ) -> list[StoredDecisionOutcomeReview]:
        """Return the latest stored review per signal without creating schema."""

        with self._connection() as conn:
            try:
                rows = conn.execute(
                    """
                    WITH ranked AS (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY signal_id
                            ORDER BY created_at DESC, review_id DESC
                        ) AS signal_rank
                        FROM decision_outcome_reviews
                    )
                    SELECT * FROM ranked
                    WHERE signal_rank = 1
                    ORDER BY created_at DESC, review_id DESC
                    LIMIT ?
                    """,
                    (max(1, min(int(limit), 500)),),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    return []
                raise
        return [_review_from_row(row) for row in rows]

    def record(
        self,
        *,
        signal_id: int,
        target: DecisionOutcomeReviewTarget,
        request: DecisionOutcomeReviewRequest,
        created_at: str,
    ) -> tuple[StoredDecisionOutcomeReview, bool]:
        review_id = (
            "decision-review-"
            + content_fingerprint(
                {
                    "signal_id": signal_id,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                }
            )[:24]
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _review_from_row(existing)
                if (
                    stored.signal_id != signal_id
                    or stored.request_fingerprint != request.fingerprint
                    or stored.target_fingerprint != target.fingerprint
                ):
                    raise IdempotencyConflict(
                        "decision review idempotency key was reused with different input"
                    )
                conn.commit()
                return stored, True

            conn.execute(
                """
                INSERT INTO decision_outcome_reviews (
                    review_id, signal_id, idempotency_key, request_json,
                    request_fingerprint, target_json, target_fingerprint,
                    reviewed_by, user_decision, outcome, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    signal_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    canonical_json(target.to_dict()),
                    target.fingerprint,
                    request.reviewed_by,
                    request.user_decision,
                    request.outcome,
                    request.note,
                    created_at,
                ),
            )
            self._append_review_event(
                conn,
                review_id=review_id,
                event_type="decision_outcome_review_recorded",
                payload={
                    "signal_id": signal_id,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "outcome": request.outcome,
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            contribution = target.strategy_contribution_report
            insert_event_sync(
                conn,
                event_type="decision.outcome_review.recorded",
                timestamp=created_at,
                entity_type="signal",
                entity_id=str(signal_id),
                source="decision_outcome_reviews",
                source_ref=review_id,
                payload={
                    "schema_version": DECISION_OUTCOME_REVIEW_CONTRACT_VERSION,
                    "review_id": review_id,
                    "signal_id": signal_id,
                    "reviewed_at": created_at,
                    "user_decision": request.user_decision,
                    "outcome": request.outcome,
                    "review_notes": request.note,
                    "reviewer": request.reviewed_by,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "signal_fingerprint": target.signal_fingerprint,
                    "financial_evidence_status": target.financial_evidence_status,
                    "valuation_snapshot_id": contribution.get("valuation_snapshot_id"),
                    "ledger_cutoff_id": contribution.get("ledger_cutoff_id", 0),
                    "contribution_fingerprint": contribution.get(
                        "contribution_fingerprint"
                    ),
                    "persisted_facts_only": True,
                    "provider_contacted": False,
                    "does_not_mutate_financial_state": True,
                    "authorizes_execution": False,
                    "authority_effect": "none",
                },
            )
            row = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("decision outcome review persistence failed")
        return _review_from_row(row), False

    def verify_replay(self, review_id: str) -> DecisionOutcomeReviewReplay:
        with self._connection() as conn:
            review = conn.execute(
                "SELECT * FROM decision_outcome_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
            if review is None:
                raise LookupError(f"decision outcome review not found: {review_id}")
            rows = conn.execute(
                """
                SELECT * FROM decision_outcome_review_events
                WHERE review_id = ? ORDER BY sequence ASC
                """,
                (review_id,),
            ).fetchall()
        errors = list(_stored_review_integrity_errors(review))
        previous_hash: str | None = None
        first_payload: dict[str, Any] | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            try:
                payload = _json_object(row["payload_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
                errors.append("review_event_payload_json_invalid")
            if first_payload is None:
                first_payload = payload
            if int(row["sequence"]) != expected_sequence:
                errors.append("event_sequence_gap")
            if row["previous_hash"] != previous_hash:
                errors.append("event_previous_hash_mismatch")
            expected_hash = _event_hash(
                review_id=review_id,
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if row["event_hash"] != expected_hash:
                errors.append("event_hash_mismatch")
            previous_hash = str(row["event_hash"])
        if not rows:
            errors.append("review_event_missing")
        else:
            first = rows[0]
            if str(first["event_type"]) != "decision_outcome_review_recorded":
                errors.append("review_event_type_mismatch")
            if str(first["created_at"]) != str(review["created_at"]):
                errors.append("review_event_timestamp_mismatch")
            expected_event_payload = {
                "signal_id": int(review["signal_id"]),
                "request_fingerprint": str(review["request_fingerprint"]),
                "target_fingerprint": str(review["target_fingerprint"]),
                "outcome": str(review["outcome"]),
                "authority_effect": "none",
            }
            if first_payload != expected_event_payload:
                errors.append("review_event_record_binding_mismatch")
        return DecisionOutcomeReviewReplay(
            review_id=review_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_review_event(
        conn: sqlite3.Connection,
        *,
        review_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = conn.execute(
            """
            SELECT sequence, event_hash FROM decision_outcome_review_events
            WHERE review_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (review_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _event_hash(
            review_id=review_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO decision_outcome_review_events (
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


def _review_from_row(row: sqlite3.Row) -> StoredDecisionOutcomeReview:
    return StoredDecisionOutcomeReview(
        review_id=str(row["review_id"]),
        signal_id=int(row["signal_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request=_safe_json_object(row["request_json"]),
        request_fingerprint=str(row["request_fingerprint"]),
        target=_safe_json_object(row["target_json"]),
        target_fingerprint=str(row["target_fingerprint"]),
        created_at=str(row["created_at"]),
    )


def _stored_review_integrity_errors(row: sqlite3.Row) -> tuple[str, ...]:
    errors: list[str] = []
    try:
        request = _json_object(row["request_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        request = {}
        errors.append("stored_review_request_json_invalid")
    try:
        target = _json_object(row["target_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        target = {}
        errors.append("stored_review_target_json_invalid")

    request_fingerprint = str(row["request_fingerprint"])
    target_fingerprint = str(row["target_fingerprint"])
    if request and content_fingerprint(request) != request_fingerprint:
        errors.append("stored_review_request_fingerprint_mismatch")
    target_identity = {
        key: target.get(key)
        for key in (
            "schema_version",
            "signal_id",
            "signal",
            "signal_fingerprint",
            "action_task",
            "risk_decision",
            "execution_evidence",
            "strategy_contribution_report",
            "financial_evidence_status",
            "allowed_outcomes",
            "blockers",
            "limitations",
        )
    }
    if target and content_fingerprint(target_identity) != target_fingerprint:
        errors.append("stored_review_target_fingerprint_mismatch")
    if str(target.get("target_fingerprint") or "") != target_fingerprint:
        errors.append("stored_review_embedded_target_fingerprint_mismatch")
    if str(request.get("expected_target_fingerprint") or "") != target_fingerprint:
        errors.append("stored_review_request_target_binding_mismatch")
    if str(request.get("idempotency_key") or "") != str(row["idempotency_key"]):
        errors.append("stored_review_idempotency_binding_mismatch")
    if str(request.get("reviewed_by") or "") != str(row["reviewed_by"]):
        errors.append("stored_review_reviewer_binding_mismatch")
    if str(request.get("user_decision") or "") != str(row["user_decision"]):
        errors.append("stored_review_user_decision_binding_mismatch")
    if str(request.get("outcome") or "") != str(row["outcome"]):
        errors.append("stored_review_outcome_binding_mismatch")
    if str(request.get("note") or "") != str(row["note"]):
        errors.append("stored_review_note_binding_mismatch")
    try:
        target_signal_id = int(target.get("signal_id") or 0)
    except (TypeError, ValueError):
        target_signal_id = 0
    if target_signal_id != int(row["signal_id"]):
        errors.append("stored_review_signal_binding_mismatch")
    expected_review_id = (
        "decision-review-"
        + content_fingerprint(
            {
                "signal_id": int(row["signal_id"]),
                "request_fingerprint": request_fingerprint,
                "target_fingerprint": target_fingerprint,
            }
        )[:24]
    )
    if str(row["review_id"]) != expected_review_id:
        errors.append("stored_review_id_fingerprint_mismatch")
    return tuple(dict.fromkeys(errors))


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("stored review JSON must be an object")
    return parsed


def _safe_json_object(value: Any) -> dict[str, Any]:
    try:
        return _json_object(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _event_hash(
    *,
    review_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "review_id": review_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
