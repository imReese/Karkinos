"""Human-owned AI research task and review audit boundary.

Tasks in this module bind an already completed, model-free context capture to a
human research question.  They do not start an AI workflow, invoke a provider,
or carry any financial or execution authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator

from .capture import CaptureRunStatus, ContextCaptureAuditStore
from .contracts import JsonObject, canonical_json, content_fingerprint
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceContextBuilder,
    EvidenceIdentityMismatch,
)
from .store import AiAuditStore, IdempotencyConflict

TASK_CONFIRMATION = "record_human_research_task_without_model_execution"
REVIEW_CONFIRMATION = "record_human_research_review_without_model_execution"


class ResearchTaskStatus(StrEnum):
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    BLOCKED_BY_EVIDENCE = "blocked_by_evidence"
    CONTEXT_ACCEPTED = "context_accepted"
    CONTEXT_REVISION_REQUESTED = "context_revision_requested"
    CLOSED_WITHOUT_ANALYSIS = "closed_without_analysis"


class ResearchTaskReviewDecision(StrEnum):
    CONTEXT_ACCEPTED = "context_accepted"
    CONTEXT_REVISION_REQUESTED = "context_revision_requested"
    CLOSED_WITHOUT_ANALYSIS = "closed_without_analysis"


class ResearchTaskRejected(ValueError):
    """Raised when a human-task transition fails closed."""


@dataclass(frozen=True)
class HumanResearchTaskRequest:
    idempotency_key: str
    capture_id: str
    created_by: str
    title: str
    research_question: str
    confirmation: str
    schema_version: str = "karkinos.ai.human_research_task_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "capture_id",
            "created_by",
            "title",
            "research_question",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != TASK_CONFIRMATION:
            raise ValueError(
                "explicit model-free research task confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "capture_id": self.capture_id,
            "created_by": self.created_by,
            "title": self.title,
            "research_question": self.research_question,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class HumanResearchTaskReviewRequest:
    idempotency_key: str
    reviewed_by: str
    decision: ResearchTaskReviewDecision
    note: str
    confirmation: str
    schema_version: str = "karkinos.ai.human_research_task_review_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "reviewed_by",
            "note",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != REVIEW_CONFIRMATION:
            raise ValueError(
                "explicit model-free research review confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "reviewed_by": self.reviewed_by,
            "decision": self.decision.value,
            "note": self.note,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchTaskEvidence:
    reference_id: str
    tool_name: str
    status: str
    authoritative: bool
    as_of: str
    record_fingerprint: str

    @classmethod
    def from_record(cls, record: CanonicalEvidenceRecord) -> ResearchTaskEvidence:
        return cls(
            reference_id=record.reference_id,
            tool_name=record.tool_name,
            status=record.status,
            authoritative=record.authoritative,
            as_of=record.as_of,
            record_fingerprint=record.record_fingerprint,
        )

    def to_dict(self) -> JsonObject:
        return {
            "evidence_reference_id": self.reference_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "authoritative": self.authoritative,
            "as_of": self.as_of,
            "record_fingerprint": self.record_fingerprint,
        }


@dataclass(frozen=True)
class ResearchTask:
    task_id: str
    idempotency_key: str
    request_fingerprint: str
    capture_id: str
    context_snapshot_id: str
    context_fingerprint: str
    account_alias: str
    valuation_snapshot_id: str
    ledger_cutoff_id: int
    ledger_fingerprint: str
    created_by: str
    title: str
    research_question: str
    evidence: tuple[ResearchTaskEvidence, ...]
    blockers: tuple[str, ...]
    status: ResearchTaskStatus
    created_at: str
    updated_at: str

    @property
    def all_evidence_authoritative(self) -> bool:
        return bool(self.evidence) and all(item.authoritative for item in self.evidence)

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.human_research_task.v1",
            "task_id": self.task_id,
            "capture_id": self.capture_id,
            "context_snapshot_id": self.context_snapshot_id,
            "context_fingerprint": self.context_fingerprint,
            "account_alias": self.account_alias,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "ledger_fingerprint": self.ledger_fingerprint,
            "created_by": self.created_by,
            "title": self.title,
            "research_question": self.research_question,
            "evidence": [item.to_dict() for item in self.evidence],
            "all_evidence_authoritative": self.all_evidence_authoritative,
            "blockers": list(self.blockers),
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "persisted_facts_only": True,
            "provider_fetch_used": False,
            "model_execution_enabled": False,
            "model_invocation_count": 0,
            "workflow_started": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


@dataclass(frozen=True)
class ResearchTaskReview:
    review_id: str
    task_id: str
    idempotency_key: str
    request_fingerprint: str
    reviewed_by: str
    decision: ResearchTaskReviewDecision
    note: str
    created_at: str

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.human_research_task_review.v1",
            "review_id": self.review_id,
            "task_id": self.task_id,
            "reviewed_by": self.reviewed_by,
            "decision": self.decision.value,
            "note": self.note,
            "created_at": self.created_at,
            "model_execution_enabled": False,
            "workflow_started": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ResearchTaskResult:
    task: ResearchTask
    reused: bool

    def to_dict(self) -> JsonObject:
        return {**self.task.to_dict(), "reused": self.reused}


@dataclass(frozen=True)
class ResearchTaskReviewResult:
    task: ResearchTask
    review: ResearchTaskReview
    reused: bool

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.human_research_task_review_result.v1",
            "task": self.task.to_dict(),
            "review": self.review.to_dict(),
            "reused": self.reused,
            "model_execution_enabled": False,
            "workflow_started": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ResearchTaskReplay:
    task_id: str
    valid: bool
    event_count: int
    final_event_hash: str | None
    replayed_status: ResearchTaskStatus

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.human_research_task_replay.v1",
            "task_id": self.task_id,
            "valid": self.valid,
            "event_count": self.event_count,
            "final_event_hash": self.final_event_hash,
            "replayed_status": self.replayed_status.value,
            "model_execution_enabled": False,
            "workflow_started": False,
            "authority_effect": "none",
        }


_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_research_tasks (
    task_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    account_alias TEXT NOT NULL,
    valuation_snapshot_id TEXT NOT NULL,
    ledger_cutoff_id INTEGER NOT NULL CHECK(ledger_cutoff_id >= 0),
    ledger_fingerprint TEXT NOT NULL,
    created_by TEXT NOT NULL,
    title TEXT NOT NULL,
    research_question TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    blockers_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_research_tasks_status
ON ai_research_tasks(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_research_task_reviews (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    reviewed_by TEXT NOT NULL,
    decision TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_research_task_reviews_task
ON ai_research_task_reviews(task_id, created_at, review_id);

CREATE TABLE IF NOT EXISTS ai_research_task_events (
    task_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, sequence),
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id)
);
"""


class ResearchTaskStore:
    """Durable tasks, reviews, and a deterministic per-task event chain."""

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
            conn.executescript(_TASK_SCHEMA)

    def create_or_get(
        self,
        request: HumanResearchTaskRequest,
        *,
        context_snapshot_id: str,
        context_fingerprint: str,
        account_alias: str,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
        evidence: Sequence[ResearchTaskEvidence],
        blockers: Sequence[str],
        created_at: str,
    ) -> tuple[ResearchTask, bool]:
        identity = {
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request.fingerprint,
            "context_fingerprint": context_fingerprint,
        }
        task_id = f"ai-research-task-{content_fingerprint(identity)[:24]}"
        status = (
            ResearchTaskStatus.BLOCKED_BY_EVIDENCE
            if blockers
            else ResearchTaskStatus.AWAITING_HUMAN_REVIEW
        )
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
                return _task_from_row(existing), True
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
                    status.value,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_research_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("research task persistence failed")
            task = _task_from_row(row)
            self._append_event(
                conn,
                task_id=task_id,
                event_type="task_created",
                payload={
                    "request_fingerprint": request.fingerprint,
                    "context_fingerprint": context_fingerprint,
                    "status": status.value,
                },
                created_at=created_at,
            )
        return task, False

    def get(self, task_id: str) -> ResearchTask:
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
        return _task_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[ResearchTask, ...]:
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
        return tuple(_task_from_row(row) for row in rows)

    def record_review(
        self,
        task_id: str,
        request: HumanResearchTaskReviewRequest,
        *,
        created_at: str,
    ) -> tuple[ResearchTask, ResearchTaskReview, bool]:
        next_status = ResearchTaskStatus(request.decision.value)
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
                return _task_from_row(task_row), _review_from_row(existing), True

            current = _task_from_row(task_row)
            if current.status in {
                ResearchTaskStatus.CONTEXT_ACCEPTED,
                ResearchTaskStatus.CONTEXT_REVISION_REQUESTED,
                ResearchTaskStatus.CLOSED_WITHOUT_ANALYSIS,
            }:
                raise ResearchTaskRejected("research task review is already final")
            if (
                request.decision == ResearchTaskReviewDecision.CONTEXT_ACCEPTED
                and not current.all_evidence_authoritative
            ):
                raise ResearchTaskRejected(
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
                    request.decision.value,
                    request.note,
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE ai_research_tasks SET status = ?, updated_at = ? "
                "WHERE task_id = ?",
                (next_status.value, created_at, task_id),
            )
            self._append_event(
                conn,
                task_id=task_id,
                event_type="human_review_recorded",
                payload={
                    "review_id": review_id,
                    "request_fingerprint": request.fingerprint,
                    "decision": request.decision.value,
                    "status": next_status.value,
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
        return _task_from_row(updated_row), _review_from_row(review_row), False

    def replay(self, task_id: str) -> ResearchTaskReplay:
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
        replayed_status: ResearchTaskStatus | None = None
        for expected_sequence, row in enumerate(events, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise EvidenceIdentityMismatch("research task audit sequence drifted")
            payload = json.loads(str(row["payload_json"]))
            expected_hash = _event_hash(
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
            replayed_status = ResearchTaskStatus(str(payload["status"]))
            previous_hash = expected_hash
        if replayed_status != task.status:
            raise EvidenceIdentityMismatch(
                "research task status and audit replay drifted"
            )
        return ResearchTaskReplay(
            task_id=task_id,
            valid=True,
            event_count=len(events),
            final_event_hash=previous_hash,
            replayed_status=replayed_status,
        )

    @staticmethod
    def _append_event(
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
        event_hash = _event_hash(
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


class HumanResearchTaskService:
    """Create and review tasks only after replaying their frozen capture."""

    def __init__(
        self,
        *,
        evidence_repository: CanonicalEvidenceRepository,
        context_store: AiAuditStore,
        capture_store: ContextCaptureAuditStore,
        task_store: ResearchTaskStore,
        now: Callable[[], str],
    ) -> None:
        self._evidence_repository = evidence_repository
        self._context_store = context_store
        self._capture_store = capture_store
        self._task_store = task_store
        self._now = now

    def create(self, request: HumanResearchTaskRequest) -> ResearchTaskResult:
        context, records = self._restore_capture(request.capture_id)
        evidence = tuple(ResearchTaskEvidence.from_record(item) for item in records)
        blockers = tuple(
            f"evidence_not_authoritative:{item.tool_name}:{item.status}"
            for item in evidence
            if not item.authoritative
        )
        task, reused = self._task_store.create_or_get(
            request,
            context_snapshot_id=context.snapshot_id,
            context_fingerprint=context.fingerprint,
            account_alias=context.account_alias,
            valuation_snapshot_id=context.valuation_snapshot_id,
            ledger_cutoff_id=context.ledger_cutoff_id,
            ledger_fingerprint=context.ledger_fingerprint,
            evidence=evidence,
            blockers=blockers,
            created_at=self._now(),
        )
        return ResearchTaskResult(task=task, reused=reused)

    def review(
        self,
        task_id: str,
        request: HumanResearchTaskReviewRequest,
    ) -> ResearchTaskReviewResult:
        task = self._task_store.get(task_id)
        context, records = self._restore_capture(task.capture_id)
        if context.snapshot_id != task.context_snapshot_id:
            raise EvidenceIdentityMismatch("research task context snapshot drifted")
        if context.fingerprint != task.context_fingerprint:
            raise EvidenceIdentityMismatch("research task context fingerprint drifted")
        current_evidence = tuple(
            ResearchTaskEvidence.from_record(item) for item in records
        )
        if current_evidence != task.evidence:
            raise EvidenceIdentityMismatch("research task evidence binding drifted")
        updated, review, reused = self._task_store.record_review(
            task_id,
            request,
            created_at=self._now(),
        )
        return ResearchTaskReviewResult(
            task=updated,
            review=review,
            reused=reused,
        )

    def get(self, task_id: str) -> ResearchTask:
        return self._task_store.get(task_id)

    def list(self, *, limit: int = 50) -> tuple[ResearchTask, ...]:
        return self._task_store.list(limit=limit)

    def replay(self, task_id: str) -> ResearchTaskReplay:
        task = self._task_store.get(task_id)
        self._restore_capture(task.capture_id)
        return self._task_store.replay(task_id)

    def _restore_capture(self, capture_id: str):
        capture = self._capture_store.get(capture_id)
        if capture.status != CaptureRunStatus.COMPLETED:
            raise ResearchTaskRejected(
                "research task requires a completed context capture"
            )
        if capture.context_snapshot_id is None:
            raise EvidenceIdentityMismatch(
                "completed context capture is missing its context snapshot"
            )
        context = self._context_store.get_context(capture.context_snapshot_id)
        records: list[CanonicalEvidenceRecord] = []
        for reference_id in capture.evidence_reference_ids:
            record = self._evidence_repository.get(reference_id)
            if record is None:
                raise EvidenceIdentityMismatch(
                    f"completed context capture evidence is missing: {reference_id}"
                )
            records.append(record)
        if context.evidence_reference_ids != frozenset(capture.evidence_reference_ids):
            raise EvidenceIdentityMismatch(
                "completed context capture evidence references drifted"
            )
        rebuilt = EvidenceContextBuilder().build(
            account_alias=context.account_alias,
            records=records,
            created_at=context.created_at,
        )
        if rebuilt != context:
            raise EvidenceIdentityMismatch(
                "completed context capture payload or identity drifted"
            )
        return context, tuple(records)


def _event_hash(
    *,
    task_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "task_id": task_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )


def _task_from_row(row: sqlite3.Row) -> ResearchTask:
    evidence_payload = json.loads(str(row["evidence_json"]))
    return ResearchTask(
        task_id=str(row["task_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        capture_id=str(row["capture_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        account_alias=str(row["account_alias"]),
        valuation_snapshot_id=str(row["valuation_snapshot_id"]),
        ledger_cutoff_id=int(row["ledger_cutoff_id"]),
        ledger_fingerprint=str(row["ledger_fingerprint"]),
        created_by=str(row["created_by"]),
        title=str(row["title"]),
        research_question=str(row["research_question"]),
        evidence=tuple(
            ResearchTaskEvidence(
                reference_id=str(item["evidence_reference_id"]),
                tool_name=str(item["tool_name"]),
                status=str(item["status"]),
                authoritative=bool(item["authoritative"]),
                as_of=str(item["as_of"]),
                record_fingerprint=str(item["record_fingerprint"]),
            )
            for item in evidence_payload
        ),
        blockers=tuple(str(item) for item in json.loads(str(row["blockers_json"]))),
        status=ResearchTaskStatus(str(row["status"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _review_from_row(row: sqlite3.Row) -> ResearchTaskReview:
    return ResearchTaskReview(
        review_id=str(row["review_id"]),
        task_id=str(row["task_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        reviewed_by=str(row["reviewed_by"]),
        decision=ResearchTaskReviewDecision(str(row["decision"])),
        note=str(row["note"]),
        created_at=str(row["created_at"]),
    )
