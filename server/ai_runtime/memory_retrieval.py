"""Explicit retrieval of human-reviewed research memory.

The retrieval boundary is deliberately narrower than an AI memory system.  A
human names the exact review records to retrieve and an already-persisted
evidence context to bind them to.  The service revalidates the source review,
the memory artifact, the current context, and every canonical evidence row on
every read.  Retrieved memory remains historical research input; it is never
promoted to account truth, a Decision input, or execution authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .analysis_reviews import (
    AnalysisReviewEffectiveStatus,
    HumanAnalysisReviewService,
)
from .contracts import (
    ArtifactKind,
    EvidenceBoundContextSnapshot,
    JsonObject,
    StoredArtifact,
    canonical_json,
    content_fingerprint,
)
from .evidence import (
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceIdentityMismatch,
)
from .store import AiAuditStore, IdempotencyConflict
from .task_analysis import HumanResearchTaskFixtureAnalysisService

REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION = (
    "retrieve_reviewed_memory_as_non_authoritative_research_input"
)
REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION = "karkinos.ai.reviewed_memory_retrieval.v1"
_MAX_REVIEW_IDS = 20


class ReviewedMemoryRetrievalRejected(ValueError):
    """Raised when a requested memory cannot pass the retrieval gates."""


@dataclass(frozen=True)
class HumanReviewedMemoryRetrievalRequest:
    idempotency_key: str
    requested_by: str
    purpose: str
    current_context_snapshot_id: str
    review_ids: tuple[str, ...]
    confirmation: str
    schema_version: str = "karkinos.ai.reviewed_memory_retrieval_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "idempotency_key",
            "requested_by",
            "purpose",
            "current_context_snapshot_id",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not self.review_ids or len(self.review_ids) > _MAX_REVIEW_IDS:
            raise ValueError(
                f"review_ids must contain between 1 and {_MAX_REVIEW_IDS} items"
            )
        if any(not item.strip() for item in self.review_ids):
            raise ValueError("review_ids must not contain empty values")
        if len(self.review_ids) != len(set(self.review_ids)):
            raise ValueError("review_ids must be unique")
        if self.confirmation != REVIEWED_MEMORY_RETRIEVAL_CONFIRMATION:
            raise ValueError(
                "explicit non-authoritative reviewed-memory retrieval "
                "confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "purpose": self.purpose,
            "current_context_snapshot_id": self.current_context_snapshot_id,
            "review_ids": list(self.review_ids),
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class EvidenceRebinding:
    tool_name: str
    kind: str
    source_reference_id: str
    source_fingerprint: str
    current_reference_id: str
    current_fingerprint: str
    current_status: str

    def to_dict(self) -> JsonObject:
        return {
            "tool_name": self.tool_name,
            "kind": self.kind,
            "source_reference_id": self.source_reference_id,
            "source_fingerprint": self.source_fingerprint,
            "current_reference_id": self.current_reference_id,
            "current_fingerprint": self.current_fingerprint,
            "current_status": self.current_status,
            "same_evidence_identity": (
                self.source_reference_id == self.current_reference_id
            ),
        }


@dataclass(frozen=True)
class ReviewedMemorySelection:
    review_id: str
    analysis_id: str
    source_context_snapshot_id: str
    memory_artifact_id: str
    memory_artifact_fingerprint: str
    memory_content: JsonObject
    rebindings: tuple[EvidenceRebinding, ...]
    fingerprint: str

    def to_dict(self) -> JsonObject:
        return {
            "review_id": self.review_id,
            "analysis_id": self.analysis_id,
            "source_context_snapshot_id": self.source_context_snapshot_id,
            "memory_artifact_id": self.memory_artifact_id,
            "memory_artifact_fingerprint": self.memory_artifact_fingerprint,
            "memory_content": dict(self.memory_content),
            "evidence_rebindings": [item.to_dict() for item in self.rebindings],
            "selection_fingerprint": self.fingerprint,
            "memory_role": "historical_reviewed_research_input",
            "memory_is_current_fact": False,
            "current_evidence_must_be_read": True,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ReviewedMemoryRetrievalTarget:
    current_context_snapshot_id: str
    current_context_fingerprint: str | None
    valuation_snapshot_id: str | None
    ledger_cutoff_id: int | None
    ledger_fingerprint: str | None
    selections: tuple[ReviewedMemorySelection, ...]
    fingerprint: str
    errors: tuple[str, ...]

    @property
    def eligible(self) -> bool:
        return not self.errors and bool(self.selections)


@dataclass(frozen=True)
class StoredReviewedMemoryRetrieval:
    retrieval_id: str
    request: HumanReviewedMemoryRetrievalRequest
    stored_idempotency_key: str
    request_fingerprint: str
    stored_current_context_snapshot_id: str
    retrieval_target_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class ReviewedMemoryRetrievalAuditReplay:
    retrieval_id: str
    valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedMemoryRetrievalReplay:
    retrieval_id: str
    valid: bool
    retrieval_eligible: bool
    request_binding_valid: bool
    target_binding_valid: bool
    event_chain_valid: bool
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.reviewed_memory_retrieval_replay.v1",
            "retrieval_id": self.retrieval_id,
            "valid": self.valid,
            "retrieval_eligible": self.retrieval_eligible,
            "request_binding_valid": self.request_binding_valid,
            "target_binding_valid": self.target_binding_valid,
            "event_chain_valid": self.event_chain_valid,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "memory_is_account_fact": False,
            "decision_handoff_enabled": False,
            "provider_invocation_count": 0,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ReviewedMemoryRetrievalResult:
    stored: StoredReviewedMemoryRetrieval
    current_target: ReviewedMemoryRetrievalTarget
    audit_replay: ReviewedMemoryRetrievalAuditReplay
    reused: bool

    @property
    def request_binding_valid(self) -> bool:
        return (
            self.stored.request_fingerprint == self.stored.request.fingerprint
            and self.stored.stored_idempotency_key
            == self.stored.request.idempotency_key
            and self.stored.stored_current_context_snapshot_id
            == self.stored.request.current_context_snapshot_id
        )

    @property
    def target_binding_valid(self) -> bool:
        return (
            self.stored.retrieval_target_fingerprint == self.current_target.fingerprint
        )

    @property
    def retrieval_eligible(self) -> bool:
        return (
            self.request_binding_valid
            and self.target_binding_valid
            and self.current_target.eligible
            and self.audit_replay.valid
        )

    @property
    def invalidation_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.request_binding_valid:
            reasons.append("retrieval_request_fingerprint_drift")
        if not self.target_binding_valid:
            reasons.append("retrieval_target_fingerprint_drift")
        reasons.extend(self.current_target.errors)
        reasons.extend(self.audit_replay.errors)
        return tuple(dict.fromkeys(reasons))

    def replay(self) -> ReviewedMemoryRetrievalReplay:
        return ReviewedMemoryRetrievalReplay(
            retrieval_id=self.stored.retrieval_id,
            valid=self.retrieval_eligible,
            retrieval_eligible=self.retrieval_eligible,
            request_binding_valid=self.request_binding_valid,
            target_binding_valid=self.target_binding_valid,
            event_chain_valid=self.audit_replay.valid,
            event_count=self.audit_replay.event_count,
            last_event_hash=self.audit_replay.last_event_hash,
            errors=self.invalidation_reasons,
        )

    def to_dict(self) -> JsonObject:
        target = self.current_target
        return {
            "schema_version": REVIEWED_MEMORY_RETRIEVAL_CONTRACT_VERSION,
            "retrieval_id": self.stored.retrieval_id,
            "requested_by": self.stored.request.requested_by,
            "purpose": self.stored.request.purpose,
            "review_ids": list(self.stored.request.review_ids),
            "current_context_snapshot_id": target.current_context_snapshot_id,
            "current_context_fingerprint": target.current_context_fingerprint,
            "valuation_snapshot_id": target.valuation_snapshot_id,
            "ledger_cutoff_id": target.ledger_cutoff_id,
            "ledger_fingerprint": target.ledger_fingerprint,
            "stored_retrieval_target_fingerprint": (
                self.stored.retrieval_target_fingerprint
            ),
            "current_retrieval_target_fingerprint": target.fingerprint,
            "request_binding_valid": self.request_binding_valid,
            "target_binding_valid": self.target_binding_valid,
            "retrieval_eligible": self.retrieval_eligible,
            "status": (
                "ready_for_evidence_bound_research_context"
                if self.retrieval_eligible
                else "invalidated"
            ),
            "invalidation_reasons": list(self.invalidation_reasons),
            "selected_memories": (
                [item.to_dict() for item in target.selections]
                if self.retrieval_eligible
                else []
            ),
            "selected_memory_count": (
                len(target.selections) if self.retrieval_eligible else 0
            ),
            "created_at": self.stored.created_at,
            "reused": self.reused,
            "explicit_human_start_required": True,
            "automatic_recall_enabled": False,
            "semantic_search_used": False,
            "provider_tool_registered": False,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "persisted_facts_only": True,
            "memory_is_account_fact": False,
            "current_evidence_must_be_read": True,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_RETRIEVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_reviewed_memory_retrievals (
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

CREATE INDEX IF NOT EXISTS idx_ai_reviewed_memory_retrievals_created
ON ai_reviewed_memory_retrievals(created_at DESC, retrieval_id DESC);

CREATE TABLE IF NOT EXISTS ai_reviewed_memory_retrieval_events (
    retrieval_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(retrieval_id, sequence),
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_reviewed_memory_retrievals(retrieval_id)
);
"""


class ReviewedMemoryRetrievalStore:
    """Append-only retrieval requests and their single-event audit chains."""

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
            conn.executescript(_RETRIEVAL_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> StoredReviewedMemoryRetrieval | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_reviewed_memory_retrievals "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return _retrieval_from_row(row) if row is not None else None

    def record(
        self,
        *,
        request: HumanReviewedMemoryRetrievalRequest,
        target: ReviewedMemoryRetrievalTarget,
        created_at: str,
    ) -> tuple[StoredReviewedMemoryRetrieval, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "retrieval_target_fingerprint": target.fingerprint,
        }
        retrieval_id = f"ai-memory-retrieval-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_reviewed_memory_retrievals "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = _retrieval_from_row(row)
                if stored.request_fingerprint != request.fingerprint:
                    raise IdempotencyConflict(
                        "reviewed-memory retrieval idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_reviewed_memory_retrievals (
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
                event_type="reviewed_memory_retrieval_started",
                payload={
                    "request_fingerprint": request.fingerprint,
                    "retrieval_target_fingerprint": target.fingerprint,
                    "current_context_snapshot_id": (
                        request.current_context_snapshot_id
                    ),
                    "review_ids": list(request.review_ids),
                    "authority_effect": "none",
                },
                created_at=created_at,
            )
            row = conn.execute(
                "SELECT * FROM ai_reviewed_memory_retrievals " "WHERE retrieval_id = ?",
                (retrieval_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("reviewed-memory retrieval persistence failed")
        return _retrieval_from_row(row), False

    def get(self, retrieval_id: str) -> StoredReviewedMemoryRetrieval:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_reviewed_memory_retrievals "
                    "WHERE retrieval_id = ?",
                    (retrieval_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"reviewed-memory retrieval not found: {retrieval_id}")
        return _retrieval_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[StoredReviewedMemoryRetrieval, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("retrieval list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_reviewed_memory_retrievals "
                    "ORDER BY created_at DESC, retrieval_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(_retrieval_from_row(row) for row in rows)

    def verify_replay(
        self,
        retrieval_id: str,
    ) -> ReviewedMemoryRetrievalAuditReplay:
        retrieval = self.get(retrieval_id)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_reviewed_memory_retrieval_events "
                "WHERE retrieval_id = ? ORDER BY sequence",
                (retrieval_id,),
            ).fetchall()
        errors: list[str] = []
        previous_hash: str | None = None
        for expected_sequence, row in enumerate(rows, start=1):
            sequence = int(row["sequence"])
            payload = json.loads(str(row["payload_json"]))
            if sequence != expected_sequence:
                errors.append("retrieval audit sequence drifted")
            if str(row["previous_hash"] or "") != str(previous_hash or ""):
                errors.append("retrieval audit previous hash drifted")
            expected_hash = _retrieval_event_hash(
                retrieval_id=retrieval_id,
                sequence=sequence,
                event_type=str(row["event_type"]),
                payload=payload,
                previous_hash=previous_hash,
                created_at=str(row["created_at"]),
            )
            if str(row["event_hash"]) != expected_hash:
                errors.append("retrieval audit event hash drifted")
            if payload.get("request_fingerprint") != retrieval.request_fingerprint:
                errors.append("retrieval audit request identity drifted")
            if (
                payload.get("retrieval_target_fingerprint")
                != retrieval.retrieval_target_fingerprint
            ):
                errors.append("retrieval audit target identity drifted")
            if payload.get("current_context_snapshot_id") != (
                retrieval.request.current_context_snapshot_id
            ):
                errors.append("retrieval audit context identity drifted")
            if payload.get("review_ids") != list(retrieval.request.review_ids):
                errors.append("retrieval audit review identities drifted")
            previous_hash = str(row["event_hash"])
        if len(rows) != 1:
            errors.append("retrieval audit must contain exactly one event")
        return ReviewedMemoryRetrievalAuditReplay(
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
        event_type: str,
        payload: JsonObject,
        created_at: str,
    ) -> None:
        previous = conn.execute(
            "SELECT sequence, event_hash "
            "FROM ai_reviewed_memory_retrieval_events "
            "WHERE retrieval_id = ? ORDER BY sequence DESC LIMIT 1",
            (retrieval_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous is not None else 1
        previous_hash = str(previous["event_hash"]) if previous is not None else None
        event_hash = _retrieval_event_hash(
            retrieval_id=retrieval_id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        conn.execute(
            """
            INSERT INTO ai_reviewed_memory_retrieval_events (
                retrieval_id, sequence, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                retrieval_id,
                sequence,
                event_type,
                canonical_json(payload),
                previous_hash,
                event_hash,
                created_at,
            ),
        )


class HumanReviewedMemoryRetrievalService:
    """Select exact reviewed memory and rebind it to current evidence."""

    def __init__(
        self,
        *,
        review_service: HumanAnalysisReviewService,
        analysis_service: HumanResearchTaskFixtureAnalysisService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        retrieval_store: ReviewedMemoryRetrievalStore,
        now: Callable[[], str],
    ) -> None:
        self._review_service = review_service
        self._analysis_service = analysis_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._retrieval_store = retrieval_store
        self._now = now

    def start(
        self,
        request: HumanReviewedMemoryRetrievalRequest,
    ) -> ReviewedMemoryRetrievalResult:
        existing = self._retrieval_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != request.fingerprint:
                raise IdempotencyConflict(
                    "reviewed-memory retrieval idempotency key was reused "
                    "with different input"
                )
            return self._result(existing, reused=True)
        target = self._target(request)
        if not target.eligible:
            raise ReviewedMemoryRetrievalRejected(
                "reviewed-memory retrieval failed closed: " + "; ".join(target.errors)
            )
        stored, reused = self._retrieval_store.record(
            request=request,
            target=target,
            created_at=self._now(),
        )
        return self._result(stored, reused=reused)

    def get(self, retrieval_id: str) -> ReviewedMemoryRetrievalResult:
        return self._result(self._retrieval_store.get(retrieval_id), reused=True)

    def list(self, *, limit: int = 50) -> tuple[ReviewedMemoryRetrievalResult, ...]:
        return tuple(
            self._result(item, reused=True)
            for item in self._retrieval_store.list(limit=limit)
        )

    def replay(self, retrieval_id: str) -> ReviewedMemoryRetrievalReplay:
        return self.get(retrieval_id).replay()

    def _result(
        self,
        stored: StoredReviewedMemoryRetrieval,
        *,
        reused: bool,
    ) -> ReviewedMemoryRetrievalResult:
        return ReviewedMemoryRetrievalResult(
            stored=stored,
            current_target=self._target(stored.request),
            audit_replay=self._retrieval_store.verify_replay(stored.retrieval_id),
            reused=reused,
        )

    def _target(
        self,
        request: HumanReviewedMemoryRetrievalRequest,
    ) -> ReviewedMemoryRetrievalTarget:
        errors: list[str] = []
        context: EvidenceBoundContextSnapshot | None = None
        current_records: tuple[CanonicalEvidenceRecord, ...] = ()
        try:
            context = self._ai_store.get_context(request.current_context_snapshot_id)
            current_records = self._validate_current_context(context)
        except (LookupError, EvidenceIdentityMismatch, ValueError) as exc:
            errors.append(f"current_context_invalid:{exc}")

        selections: list[ReviewedMemorySelection] = []
        if context is not None and current_records:
            current_by_tool: dict[str, list[CanonicalEvidenceRecord]] = defaultdict(
                list
            )
            for record in current_records:
                current_by_tool[record.tool_name].append(record)
            for review_id in request.review_ids:
                try:
                    selection = self._selection(
                        review_id=review_id,
                        current_by_tool=current_by_tool,
                    )
                except (
                    LookupError,
                    EvidenceIdentityMismatch,
                    ReviewedMemoryRetrievalRejected,
                    ValueError,
                ) as exc:
                    errors.append(f"review_not_retrievable:{review_id}:{exc}")
                else:
                    selections.append(selection)

        target_payload: JsonObject = {
            "current_context_snapshot_id": request.current_context_snapshot_id,
            "current_context_fingerprint": (
                context.fingerprint if context is not None else None
            ),
            "valuation_snapshot_id": (
                context.valuation_snapshot_id if context is not None else None
            ),
            "ledger_cutoff_id": (
                context.ledger_cutoff_id if context is not None else None
            ),
            "ledger_fingerprint": (
                context.ledger_fingerprint if context is not None else None
            ),
            "selections": [
                {
                    "review_id": item.review_id,
                    "selection_fingerprint": item.fingerprint,
                }
                for item in selections
            ],
            "errors": list(dict.fromkeys(errors)),
        }
        return ReviewedMemoryRetrievalTarget(
            current_context_snapshot_id=request.current_context_snapshot_id,
            current_context_fingerprint=(
                context.fingerprint if context is not None else None
            ),
            valuation_snapshot_id=(
                context.valuation_snapshot_id if context is not None else None
            ),
            ledger_cutoff_id=(
                context.ledger_cutoff_id if context is not None else None
            ),
            ledger_fingerprint=(
                context.ledger_fingerprint if context is not None else None
            ),
            selections=tuple(selections),
            fingerprint=content_fingerprint(target_payload),
            errors=tuple(dict.fromkeys(errors)),
        )

    def _validate_current_context(
        self,
        context: EvidenceBoundContextSnapshot,
    ) -> tuple[CanonicalEvidenceRecord, ...]:
        expected_snapshot_id = f"ai-context-{context.fingerprint[:24]}"
        if context.snapshot_id != expected_snapshot_id:
            raise EvidenceIdentityMismatch("current context fingerprint drifted")
        records: list[CanonicalEvidenceRecord] = []
        for reference in context.evidence_references:
            record = self._evidence_repository.get(reference.reference_id)
            if record is None:
                raise EvidenceIdentityMismatch(
                    f"current evidence missing:{reference.reference_id}"
                )
            if record.to_reference() != reference:
                raise EvidenceIdentityMismatch(
                    f"current evidence reference drifted:{reference.reference_id}"
                )
            if (
                record.valuation_snapshot_id != context.valuation_snapshot_id
                or record.ledger_cutoff_id != context.ledger_cutoff_id
                or record.ledger_fingerprint != context.ledger_fingerprint
            ):
                raise EvidenceIdentityMismatch(
                    f"current evidence financial identity drifted:{reference.reference_id}"
                )
            if not record.authoritative:
                raise EvidenceIdentityMismatch(
                    f"current evidence is not complete:{reference.reference_id}:"
                    f"{record.status}"
                )
            records.append(record)
        if not records:
            raise EvidenceIdentityMismatch("current context has no evidence")
        tool_names = [item.tool_name for item in records]
        if len(tool_names) != len(set(tool_names)):
            raise EvidenceIdentityMismatch(
                "current context has ambiguous duplicate canonical tools"
            )
        return tuple(records)

    def _selection(
        self,
        *,
        review_id: str,
        current_by_tool: dict[str, list[CanonicalEvidenceRecord]],
    ) -> ReviewedMemorySelection:
        review = self._review_service.get(review_id)
        if (
            review.effective_status != AnalysisReviewEffectiveStatus.REVIEWED_MEMORY
            or not review.memory_recall_eligible
        ):
            reasons = review.invalidation_reasons or (
                f"effective_status:{review.effective_status.value}",
            )
            raise ReviewedMemoryRetrievalRejected("; ".join(reasons))
        analysis = self._analysis_service.get(review.review.analysis_id)
        memory_artifact = _exact_memory_artifact(
            artifacts=analysis.artifacts,
            memory_artifact_id=review.review.memory_artifact_id,
        )
        rebindings: list[EvidenceRebinding] = []
        for source_reference_id in memory_artifact.evidence_reference_ids:
            source = self._evidence_repository.get(source_reference_id)
            if source is None:
                raise EvidenceIdentityMismatch(
                    f"source evidence missing:{source_reference_id}"
                )
            candidates = current_by_tool.get(source.tool_name, [])
            if len(candidates) != 1:
                raise EvidenceIdentityMismatch(
                    f"current evidence mapping requires exactly one "
                    f"{source.tool_name} record"
                )
            current = candidates[0]
            rebindings.append(
                EvidenceRebinding(
                    tool_name=source.tool_name,
                    kind=source.kind,
                    source_reference_id=source.reference_id,
                    source_fingerprint=source.record_fingerprint,
                    current_reference_id=current.reference_id,
                    current_fingerprint=current.record_fingerprint,
                    current_status=current.status,
                )
            )
        selection_payload: JsonObject = {
            "review_id": review.review.review_id,
            "review_target_fingerprint": review.current_target.fingerprint,
            "review_audit_last_event_hash": review.audit_replay.last_event_hash,
            "analysis_id": analysis.record.analysis_id,
            "source_context_snapshot_id": analysis.record.context_snapshot_id,
            "memory_artifact_id": memory_artifact.artifact_id,
            "memory_artifact_fingerprint": memory_artifact.fingerprint,
            "memory_content": dict(memory_artifact.content),
            "rebindings": [item.to_dict() for item in rebindings],
        }
        return ReviewedMemorySelection(
            review_id=review.review.review_id,
            analysis_id=analysis.record.analysis_id,
            source_context_snapshot_id=analysis.record.context_snapshot_id,
            memory_artifact_id=memory_artifact.artifact_id,
            memory_artifact_fingerprint=memory_artifact.fingerprint,
            memory_content=dict(memory_artifact.content),
            rebindings=tuple(rebindings),
            fingerprint=content_fingerprint(selection_payload),
        )


def _exact_memory_artifact(
    *,
    artifacts: Sequence[StoredArtifact],
    memory_artifact_id: str | None,
) -> StoredArtifact:
    matches = [
        artifact
        for artifact in artifacts
        if artifact.kind == ArtifactKind.MEMORY
        and artifact.artifact_id == memory_artifact_id
    ]
    if len(matches) != 1:
        raise EvidenceIdentityMismatch(
            "review must bind exactly one current memory artifact"
        )
    return matches[0]


def _retrieval_event_hash(
    *,
    retrieval_id: str,
    sequence: int,
    event_type: str,
    payload: JsonObject,
    previous_hash: str | None,
    created_at: str,
) -> str:
    return content_fingerprint(
        {
            "retrieval_id": retrieval_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "created_at": created_at,
        }
    )


def _retrieval_from_row(row: sqlite3.Row) -> StoredReviewedMemoryRetrieval:
    request_payload = json.loads(str(row["request_json"]))
    request = HumanReviewedMemoryRetrievalRequest(
        idempotency_key=str(request_payload["idempotency_key"]),
        requested_by=str(request_payload["requested_by"]),
        purpose=str(request_payload["purpose"]),
        current_context_snapshot_id=str(request_payload["current_context_snapshot_id"]),
        review_ids=tuple(str(item) for item in request_payload["review_ids"]),
        confirmation=str(request_payload["confirmation"]),
        schema_version=str(request_payload["schema_version"]),
    )
    return StoredReviewedMemoryRetrieval(
        retrieval_id=str(row["retrieval_id"]),
        request=request,
        stored_idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        stored_current_context_snapshot_id=str(row["current_context_snapshot_id"]),
        retrieval_target_fingerprint=str(row["retrieval_target_fingerprint"]),
        created_at=str(row["created_at"]),
    )
