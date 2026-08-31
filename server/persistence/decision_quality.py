"""Transactional decision-quality capture repository and audit replay."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from server.contracts.content_identity import canonical_json, content_fingerprint
from server.contracts.decision_quality import (
    DECISION_QUALITY_CAPTURE_VERSION,
    DecisionQualityCaptureRequest,
    DecisionQualityReplay,
    DecisionQualityReport,
    DecisionQualityTarget,
    StoredDecisionQualityCapture,
)
from server.contracts.idempotency import IdempotencyConflict
from server.persistence.event_log import insert_event_sync


class DecisionQualityStore:
    """Append-only quality captures plus a tamper-evident event chain."""

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
    ) -> StoredDecisionQualityCapture | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return _capture_from_row(row) if row is not None else None

    def get(self, snapshot_id: str) -> StoredDecisionQualityCapture:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"decision quality snapshot not found: {snapshot_id}")
        return _capture_from_row(row)

    def list(self, *, limit: int = 500) -> list[StoredDecisionQualityCapture]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM decision_quality_snapshots
                ORDER BY captured_at DESC, snapshot_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_capture_from_row(row) for row in rows]

    def record(
        self,
        *,
        target: DecisionQualityTarget,
        request: DecisionQualityCaptureRequest,
        captured_at: str,
    ) -> tuple[StoredDecisionQualityCapture, bool]:
        snapshot_id = (
            "decision-quality-"
            + content_fingerprint(
                {
                    "decision_date": target.decision_date,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                }
            )[:24]
        )
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                stored = _capture_from_row(existing)
                if (
                    stored.request_fingerprint != request.fingerprint
                    or stored.target_fingerprint != target.fingerprint
                ):
                    raise IdempotencyConflict(
                        "decision quality idempotency key was reused with different input"
                    )
                conn.commit()
                return stored, True

            target_document = target.to_dict()
            conn.execute(
                """
                INSERT INTO decision_quality_snapshots (
                    snapshot_id, decision_date, idempotency_key, request_json,
                    request_fingerprint, target_json, target_fingerprint,
                    qualified, captured_by, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    target.decision_date,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    canonical_json(target_document),
                    target.fingerprint,
                    int(target.qualified),
                    request.captured_by,
                    captured_at,
                ),
            )
            self._append_event(
                conn,
                snapshot_id=snapshot_id,
                event_type="decision_quality_captured",
                payload={
                    "decision_date": target.decision_date,
                    "request_fingerprint": request.fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "target_document_fingerprint": content_fingerprint(target_document),
                    "qualified": target.qualified,
                    "authority_effect": "none",
                },
                created_at=captured_at,
            )
            insert_event_sync(
                conn,
                event_type="decision.quality.captured",
                timestamp=captured_at,
                entity_type="decision_day",
                entity_id=target.decision_date,
                source="decision_quality_snapshots",
                source_ref=snapshot_id,
                payload={
                    "schema_version": DECISION_QUALITY_CAPTURE_VERSION,
                    "snapshot_id": snapshot_id,
                    "decision_date": target.decision_date,
                    "qualified": target.qualified,
                    "diagnostic_score_percent": target.diagnostic_score_percent,
                    "decision_fingerprint": target.decision_fingerprint,
                    "target_fingerprint": target.fingerprint,
                    "valuation_snapshot_id": target.valuation_snapshot_id,
                    "ledger_cutoff_id": target.ledger_cutoff_id,
                    "persisted_facts_only": True,
                    "provider_contacted": False,
                    "does_not_mutate_financial_state": True,
                    "authorizes_execution": False,
                    "authority_effect": "none",
                },
            )
            row = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("decision quality capture persistence failed")
        return _capture_from_row(row), False

    def verify_replay(self, snapshot_id: str) -> DecisionQualityReplay:
        with self._connection() as conn:
            capture = conn.execute(
                "SELECT * FROM decision_quality_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if capture is None:
                raise LookupError(f"decision quality snapshot not found: {snapshot_id}")
            rows = conn.execute(
                """
                SELECT * FROM decision_quality_snapshot_events
                WHERE snapshot_id = ? ORDER BY sequence ASC
                """,
                (snapshot_id,),
            ).fetchall()
        errors: list[str] = []
        stored = _capture_from_row(capture)
        if content_fingerprint(stored.request) != stored.request_fingerprint:
            errors.append("request_fingerprint_mismatch")
        if stored.target.get("target_fingerprint") != stored.target_fingerprint:
            errors.append("target_fingerprint_mismatch")
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            payload = _json_object(row["payload_json"])
            if int(row["sequence"]) != expected_sequence:
                errors.append("event_sequence_gap")
            if row["previous_hash"] != previous_hash:
                errors.append("event_previous_hash_mismatch")
            expected_hash = _event_hash(
                snapshot_id=snapshot_id,
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if row["event_hash"] != expected_hash:
                errors.append("event_hash_mismatch")
            if payload.get("request_fingerprint") != stored.request_fingerprint:
                errors.append("event_request_fingerprint_mismatch")
            if payload.get("target_fingerprint") != stored.target_fingerprint:
                errors.append("event_target_fingerprint_mismatch")
            if payload.get("target_document_fingerprint") != content_fingerprint(
                stored.target
            ):
                errors.append("target_document_fingerprint_mismatch")
            previous_hash = str(row["event_hash"])
        if not rows:
            errors.append("capture_event_missing")
        return DecisionQualityReplay(
            snapshot_id=snapshot_id,
            valid=not errors,
            event_count=len(rows),
            last_event_hash=previous_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection,
        *,
        snapshot_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = conn.execute(
            """
            SELECT sequence, event_hash FROM decision_quality_snapshot_events
            WHERE snapshot_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _event_hash(
            snapshot_id=snapshot_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO decision_quality_snapshot_events (
                snapshot_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )


def _capture_from_row(row: sqlite3.Row) -> StoredDecisionQualityCapture:
    return StoredDecisionQualityCapture(
        snapshot_id=str(row["snapshot_id"]),
        decision_date=str(row["decision_date"]),
        idempotency_key=str(row["idempotency_key"]),
        request=_json_object(row["request_json"]),
        request_fingerprint=str(row["request_fingerprint"]),
        target=_json_object(row["target_json"]),
        target_fingerprint=str(row["target_fingerprint"]),
        qualified=bool(row["qualified"]),
        captured_at=str(row["captured_at"]),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    parsed = json.loads(str(value or "{}"))
    if not isinstance(parsed, dict):
        raise ValueError("stored decision quality JSON must be an object")
    return parsed


def _event_hash(
    *,
    snapshot_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "snapshot_id": snapshot_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )
