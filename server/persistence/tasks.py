"""SQLite repository and unit-of-work for human research tasks."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.evidence import EvidenceIdentityMismatch
from server.ai_runtime.store import IdempotencyConflict
from server.ai_runtime.task_schema import TASK_SCHEMA


class ResearchTaskPersistenceMixin:
    """Own task/review transactions while the façade owns domain contracts."""

    _path: Path

    @staticmethod
    def _task_from_row(row: Any) -> Any:
        raise NotImplementedError

    @staticmethod
    def _review_from_row(row: Any) -> Any:
        raise NotImplementedError

    @staticmethod
    def _event_hash(**kwargs: Any) -> str:
        raise NotImplementedError

    @staticmethod
    def _task_rejected(message: str) -> Exception:
        return ValueError(message)

    @staticmethod
    def _task_status(value: str) -> Any:
        return value

    @staticmethod
    def _task_replay(**kwargs: Any) -> Any:
        raise NotImplementedError

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
            conn.executescript(TASK_SCHEMA)

    def create_or_get(
        self,
        request: Any,
        *,
        context_snapshot_id: str,
        context_fingerprint: str,
        account_alias: str,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
        evidence: Sequence[Any],
        blockers: Sequence[str],
        created_at: str,
    ) -> tuple[Any, bool]:
        identity = {
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request.fingerprint,
            "context_fingerprint": context_fingerprint,
        }
        task_id = f"ai-research-task-{content_fingerprint(identity)[:24]}"
        status = "blocked_by_evidence" if blockers else "awaiting_human_review"
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_research_tasks WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_fingerprint"]) != request.fingerprint:
                    raise IdempotencyConflict(
                        "research task idempotency key was reused with different input"
                    )
                return self._task_from_row(existing), True
            conn.execute(
                """
                INSERT INTO ai_research_tasks (
                    task_id, idempotency_key, request_json, request_fingerprint,
                    capture_id, context_snapshot_id, context_fingerprint,
                    account_alias, valuation_snapshot_id, ledger_cutoff_id,
                    ledger_fingerprint, created_by, title, research_question,
                    evidence_json, blockers_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.capture_id,
                    context_snapshot_id,
                    context_fingerprint,
                    account_alias,
                    valuation_snapshot_id,
                    ledger_cutoff_id,
                    ledger_fingerprint,
                    request.created_by,
                    request.title,
                    request.research_question,
                    canonical_json([item.to_dict() for item in evidence]),
                    canonical_json(list(blockers)),
                    status,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("research task persistence failed")
            task = self._task_from_row(row)
            self._append_event(
                conn,
                task_id=task_id,
                event_type="task_created",
                payload={
                    "request_fingerprint": request.fingerprint,
                    "context_fingerprint": context_fingerprint,
                    "status": status,
                },
                created_at=created_at,
            )
        return task, False

    def get(self, task_id: str) -> Any:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_research_tasks WHERE task_id = ?", (task_id,)
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"research task not found: {task_id}")
        return self._task_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[Any, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("task list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_research_tasks "
                    "ORDER BY updated_at DESC, task_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(self._task_from_row(row) for row in rows)

    def record_review(
        self,
        task_id: str,
        request: Any,
        *,
        created_at: str,
    ) -> tuple[Any, Any, bool]:
        next_status = request.decision.value
        with self._connection() as conn:
            task_row = conn.execute(
                "SELECT * FROM ai_research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                raise LookupError(f"research task not found: {task_id}")
            existing = conn.execute(
                "SELECT * FROM ai_research_task_reviews WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_fingerprint"]) != request.fingerprint
                    or str(existing["task_id"]) != task_id
                ):
                    raise IdempotencyConflict(
                        "research review idempotency key was reused with different input"
                    )
                return (
                    self._task_from_row(task_row),
                    self._review_from_row(existing),
                    True,
                )

            current = self._task_from_row(task_row)
            if current.status.value in {
                "context_accepted",
                "context_revision_requested",
                "closed_without_analysis",
            }:
                raise self._task_rejected("research task review is already final")
            if (
                next_status == "context_accepted"
                and not current.all_evidence_authoritative
            ):
                raise self._task_rejected(
                    "non-authoritative evidence cannot be accepted for analysis"
                )
            review_identity = {
                "task_id": task_id,
                "idempotency_key": request.idempotency_key,
                "request_fingerprint": request.fingerprint,
            }
            review_id = (
                f"ai-research-review-{content_fingerprint(review_identity)[:24]}"
            )
            conn.execute(
                """
                INSERT INTO ai_research_task_reviews (
                    review_id, task_id, idempotency_key, request_json,
                    request_fingerprint, reviewed_by, decision, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    task_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.reviewed_by,
                    next_status,
                    request.note,
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE ai_research_tasks SET status = ?, updated_at = ? "
                "WHERE task_id = ?",
                (next_status, created_at, task_id),
            )
            self._append_event(
                conn,
                task_id=task_id,
                event_type="human_review_recorded",
                payload={
                    "review_id": review_id,
                    "request_fingerprint": request.fingerprint,
                    "decision": next_status,
                    "status": next_status,
                },
                created_at=created_at,
            )
            updated_row = conn.execute(
                "SELECT * FROM ai_research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            review_row = conn.execute(
                "SELECT * FROM ai_research_task_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if updated_row is None or review_row is None:
            raise RuntimeError("research task review persistence failed")
        return (
            self._task_from_row(updated_row),
            self._review_from_row(review_row),
            False,
        )

    def replay(self, task_id: str) -> Any:
        task = self.get(task_id)
        with self._connection() as conn:
            events = conn.execute(
                "SELECT * FROM ai_research_task_events WHERE task_id = ? "
                "ORDER BY sequence",
                (task_id,),
            ).fetchall()
        if not events:
            raise EvidenceIdentityMismatch("research task audit chain is missing")
        previous_hash: str | None = None
        replayed_status: str | None = None
        for expected_sequence, row in enumerate(events, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise EvidenceIdentityMismatch("research task audit sequence drifted")
            payload = json.loads(str(row["payload_json"]))
            expected_hash = self._event_hash(
                task_id=task_id,
                sequence=expected_sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                raise EvidenceIdentityMismatch(
                    "research task audit previous hash drifted"
                )
            if str(row["event_hash"]) != expected_hash:
                raise EvidenceIdentityMismatch("research task audit event hash drifted")
            replayed_status = str(payload["status"])
            previous_hash = expected_hash
        if replayed_status != task.status.value:
            raise EvidenceIdentityMismatch(
                "research task status and audit replay drifted"
            )
        return self._task_replay(
            task_id=task_id,
            valid=True,
            event_count=len(events),
            final_event_hash=previous_hash,
            replayed_status=self._task_status(str(replayed_status)),
        )

    def _append_event(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: str,
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash FROM ai_research_task_events "
            "WHERE task_id = ? ORDER BY sequence DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = self._event_hash(
            task_id=task_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_research_task_events (
                task_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
