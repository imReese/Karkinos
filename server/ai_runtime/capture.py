"""Human-started capture of canonical evidence into an AI research context."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol

from .contracts import (
    EvidenceBoundContextSnapshot,
    JsonObject,
    canonical_json,
    content_fingerprint,
)
from .evidence import (
    CANONICAL_EVIDENCE_KINDS,
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    EvidenceContextBuilder,
    EvidenceIdentityMismatch,
)
from .store import AiAuditStore, IdempotencyConflict

CAPTURE_CONFIRMATION = "capture_read_only_research_context"


class CaptureEvidenceType(StrEnum):
    PORTFOLIO = "portfolio"
    ACCOUNT_STATE = "account_state"
    OPERATIONS = "operations"
    RESEARCH_EVIDENCE = "research_evidence"
    ACCOUNT_TRUTH = "account_truth"
    PAPER_SHADOW = "paper_shadow"
    STRATEGY_CONTRIBUTION = "strategy_contribution"


CAPTURE_TOOL_BY_TYPE: Mapping[CaptureEvidenceType, str] = {
    CaptureEvidenceType.PORTFOLIO: "portfolio_projection.read",
    CaptureEvidenceType.ACCOUNT_STATE: "account_state_projection.read",
    CaptureEvidenceType.OPERATIONS: "operations_summary.read",
    CaptureEvidenceType.RESEARCH_EVIDENCE: "research_evidence.read",
    CaptureEvidenceType.ACCOUNT_TRUTH: "account_truth.read",
    CaptureEvidenceType.PAPER_SHADOW: "paper_shadow_evidence.read",
    CaptureEvidenceType.STRATEGY_CONTRIBUTION: "strategy_contribution.read",
}


class CaptureSelectionError(ValueError):
    """Raised when requested persisted evidence cannot be selected exactly."""


@dataclass(frozen=True)
class HumanContextCaptureRequest:
    """Explicit operator intent for a read-only research context capture."""

    idempotency_key: str
    requested_by: str
    research_question: str
    account_alias: str
    evidence_types: tuple[CaptureEvidenceType, ...]
    confirmation: str
    backtest_result_id: int | None = None
    paper_shadow_run_id: str | None = None
    strategy_id: str | None = None
    schema_version: str = "karkinos.ai.context_capture_request.v1"

    def __post_init__(self) -> None:
        for name in (
            "idempotency_key",
            "requested_by",
            "research_question",
            "account_alias",
            "schema_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.confirmation != CAPTURE_CONFIRMATION:
            raise ValueError("explicit read-only capture confirmation is required")
        if not self.evidence_types:
            raise ValueError("at least one evidence type is required")
        if len(self.evidence_types) != len(set(self.evidence_types)):
            raise ValueError("capture evidence types must be unique")
        if CaptureEvidenceType.RESEARCH_EVIDENCE in self.evidence_types:
            if self.backtest_result_id is None or self.backtest_result_id <= 0:
                raise ValueError("backtest_result_id is required for research evidence")
        if CaptureEvidenceType.PAPER_SHADOW in self.evidence_types:
            if not str(self.paper_shadow_run_id or "").strip():
                raise ValueError(
                    "paper_shadow_run_id is required for paper/shadow evidence"
                )
        if CaptureEvidenceType.STRATEGY_CONTRIBUTION in self.evidence_types:
            if not str(self.strategy_id or "").strip():
                raise ValueError(
                    "strategy_id is required for strategy contribution evidence"
                )

    @property
    def requested_tools(self) -> tuple[str, ...]:
        return tuple(CAPTURE_TOOL_BY_TYPE[item] for item in self.evidence_types)

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "research_question": self.research_question,
            "account_alias": self.account_alias,
            "evidence_types": [item.value for item in self.evidence_types],
            "confirmation": self.confirmation,
            "backtest_result_id": self.backtest_result_id,
            "paper_shadow_run_id": self.paper_shadow_run_id,
            "schema_version": self.schema_version,
        }
        if self.strategy_id is not None:
            payload["strategy_id"] = self.strategy_id
        return payload


@dataclass(frozen=True)
class CapturedProjection:
    """One already-computed canonical projection selected by a source adapter."""

    tool_name: str
    status: str
    as_of: str
    source_schema_version: str
    payload: JsonObject

    def __post_init__(self) -> None:
        if self.tool_name not in CANONICAL_EVIDENCE_KINDS:
            raise ValueError(f"unsupported capture tool: {self.tool_name}")
        if not self.as_of.strip():
            raise ValueError("captured projection as_of must not be empty")
        if not self.source_schema_version.strip():
            raise ValueError("captured projection schema must not be empty")
        canonical_json(self.payload)


@dataclass(frozen=True)
class CaptureSourceBatch:
    """Canonical payloads sharing one immutable financial identity."""

    valuation_snapshot_id: str
    ledger_cutoff_id: int
    ledger_fingerprint: str
    projections: tuple[CapturedProjection, ...]
    persisted_facts_only: bool = True

    def __post_init__(self) -> None:
        if not self.valuation_snapshot_id.strip():
            raise ValueError("valuation_snapshot_id must not be empty")
        if self.ledger_cutoff_id < 0:
            raise ValueError("ledger_cutoff_id must be non-negative")
        if not self.ledger_fingerprint.strip():
            raise ValueError("ledger_fingerprint must not be empty")
        if not self.persisted_facts_only:
            raise ValueError("capture source must use persisted facts only")
        tools = [item.tool_name for item in self.projections]
        if len(tools) != len(set(tools)):
            raise ValueError("capture source tools must be unique")


class CaptureSource(Protocol):
    async def load(
        self,
        request: HumanContextCaptureRequest,
    ) -> CaptureSourceBatch: ...


class CaptureRunStatus(StrEnum):
    RUNNING = "running"
    EVIDENCE_CAPTURED = "evidence_captured"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class ContextCaptureRun:
    capture_id: str
    idempotency_key: str
    request_fingerprint: str
    status: CaptureRunStatus
    context_snapshot_id: str | None
    evidence_reference_ids: tuple[str, ...]
    failure_code: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ContextCaptureResult:
    run: ContextCaptureRun
    context: EvidenceBoundContextSnapshot
    records: tuple[CanonicalEvidenceRecord, ...]
    reused: bool

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.context_capture_result.v1",
            "capture_id": self.run.capture_id,
            "capture_status": self.run.status.value,
            "reused": self.reused,
            "context": self.context.to_dict(),
            "evidence": [
                {
                    "evidence_reference_id": record.reference_id,
                    "kind": record.kind,
                    "tool_name": record.tool_name,
                    "status": record.status,
                    "authoritative": record.authoritative,
                    "as_of": record.as_of,
                    "source_schema_version": record.source_schema_version,
                    "record_fingerprint": record.record_fingerprint,
                }
                for record in self.records
            ],
            "persisted_facts_only": True,
            "provider_fetch_used": False,
            "model_invocation_count": 0,
            "workflow_started": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_CAPTURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_context_capture_runs (
    capture_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    context_snapshot_id TEXT,
    evidence_reference_ids_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_context_capture_runs_status
ON ai_context_capture_runs(status, updated_at DESC);
"""


class ContextCaptureAuditStore:
    """Durable lifecycle records for explicit, model-free context capture."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=2000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        with self._connection() as conn:
            conn.executescript(_CAPTURE_SCHEMA)

    def create_or_get(
        self,
        request: HumanContextCaptureRequest,
        *,
        created_at: str,
    ) -> tuple[ContextCaptureRun, bool]:
        request_json = canonical_json(request.to_dict())
        capture_identity = {
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request.fingerprint,
        }
        capture_id = f"ai-capture-{content_fingerprint(capture_identity)[:24]}"
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO ai_context_capture_runs (
                    capture_id, idempotency_key, request_json,
                    request_fingerprint, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    request.idempotency_key,
                    request_json,
                    request.fingerprint,
                    CaptureRunStatus.RUNNING.value,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
        if row is None:
            raise IdempotencyConflict("capture identity collision")
        if str(row["request_fingerprint"]) != request.fingerprint:
            raise IdempotencyConflict(
                "capture idempotency key was reused with different input"
            )
        return _capture_run_from_row(row), cursor.rowcount == 0

    def mark_running(self, capture_id: str, *, updated_at: str) -> ContextCaptureRun:
        return self._update(
            capture_id,
            status=CaptureRunStatus.RUNNING,
            context_snapshot_id=None,
            evidence_reference_ids=(),
            failure_code=None,
            updated_at=updated_at,
            preserve_completed=True,
        )

    def mark_completed(
        self,
        capture_id: str,
        *,
        context_snapshot_id: str,
        evidence_reference_ids: Sequence[str],
        updated_at: str,
    ) -> ContextCaptureRun:
        return self._update(
            capture_id,
            status=CaptureRunStatus.COMPLETED,
            context_snapshot_id=context_snapshot_id,
            evidence_reference_ids=tuple(evidence_reference_ids),
            failure_code=None,
            updated_at=updated_at,
            preserve_completed=True,
        )

    def mark_evidence_captured(
        self,
        capture_id: str,
        *,
        evidence_reference_ids: Sequence[str],
        updated_at: str,
    ) -> ContextCaptureRun:
        if not evidence_reference_ids:
            raise ValueError("captured evidence references must not be empty")
        return self._update(
            capture_id,
            status=CaptureRunStatus.EVIDENCE_CAPTURED,
            context_snapshot_id=None,
            evidence_reference_ids=tuple(evidence_reference_ids),
            failure_code=None,
            updated_at=updated_at,
            preserve_completed=True,
        )

    def mark_failed(
        self,
        capture_id: str,
        *,
        failure_code: str,
        updated_at: str,
    ) -> ContextCaptureRun:
        current = self.get(capture_id)
        return self._update(
            capture_id,
            status=CaptureRunStatus.FAILED,
            context_snapshot_id=current.context_snapshot_id,
            evidence_reference_ids=current.evidence_reference_ids,
            failure_code=failure_code,
            updated_at=updated_at,
            preserve_completed=True,
        )

    def get(self, capture_id: str) -> ContextCaptureRun:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"context capture run not found: {capture_id}")
        return _capture_run_from_row(row)

    def _update(
        self,
        capture_id: str,
        *,
        status: CaptureRunStatus,
        context_snapshot_id: str | None,
        evidence_reference_ids: Sequence[str],
        failure_code: str | None,
        updated_at: str,
        preserve_completed: bool = False,
    ) -> ContextCaptureRun:
        with self._connection() as conn:
            completed_guard = " AND status != ?" if preserve_completed else ""
            params: list[Any] = [
                status.value,
                context_snapshot_id,
                canonical_json(list(evidence_reference_ids)),
                failure_code,
                updated_at,
                capture_id,
            ]
            if preserve_completed:
                params.append(CaptureRunStatus.COMPLETED.value)
            cursor = conn.execute(
                f"""
                UPDATE ai_context_capture_runs
                SET status = ?, context_snapshot_id = ?,
                    evidence_reference_ids_json = ?, failure_code = ?,
                    updated_at = ?
                WHERE capture_id = ?{completed_guard}
                """,
                params,
            )
            row = conn.execute(
                "SELECT * FROM ai_context_capture_runs WHERE capture_id = ?",
                (capture_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"context capture run not found: {capture_id}")
        if cursor.rowcount != 1 and not (
            preserve_completed
            and str(row["status"]) == CaptureRunStatus.COMPLETED.value
        ):
            raise RuntimeError(f"context capture update failed: {capture_id}")
        return _capture_run_from_row(row)


class HumanResearchContextCaptureService:
    """Orchestrate one explicit capture without invoking any AI provider."""

    def __init__(
        self,
        *,
        source: CaptureSource,
        evidence_repository: CanonicalEvidenceRepository,
        context_store: AiAuditStore,
        capture_store: ContextCaptureAuditStore,
        now: Callable[[], str],
    ) -> None:
        self._source = source
        self._evidence_repository = evidence_repository
        self._context_store = context_store
        self._capture_store = capture_store
        self._now = now

    async def capture(
        self,
        request: HumanContextCaptureRequest,
    ) -> ContextCaptureResult:
        run, reused = self._capture_store.create_or_get(
            request,
            created_at=self._now(),
        )
        if run.status == CaptureRunStatus.COMPLETED:
            return self._restore_completed(run, reused=True)
        if reused and run.evidence_reference_ids:
            return self._resume_from_captured_evidence(request, run)
        if reused:
            run = self._capture_store.mark_running(
                run.capture_id,
                updated_at=self._now(),
            )
            if run.status == CaptureRunStatus.COMPLETED:
                return self._restore_completed(run, reused=True)
        try:
            batch = await self._source.load(request)
            self._validate_batch(request, batch)
            records = tuple(
                self._evidence_repository.persist(
                    CanonicalEvidenceRecord.capture(
                        tool_name=projection.tool_name,
                        valuation_snapshot_id=batch.valuation_snapshot_id,
                        ledger_cutoff_id=batch.ledger_cutoff_id,
                        ledger_fingerprint=batch.ledger_fingerprint,
                        status=projection.status,
                        as_of=projection.as_of,
                        source_schema_version=projection.source_schema_version,
                        payload=projection.payload,
                        captured_at=run.created_at,
                    )
                )
                for projection in batch.projections
            )
            run = self._capture_store.mark_evidence_captured(
                run.capture_id,
                evidence_reference_ids=tuple(record.reference_id for record in records),
                updated_at=self._now(),
            )
            context = EvidenceContextBuilder().build(
                account_alias=request.account_alias,
                records=records,
                created_at=run.created_at,
            )
            self._context_store.save_context(context)
            run = self._capture_store.mark_completed(
                run.capture_id,
                context_snapshot_id=context.snapshot_id,
                evidence_reference_ids=tuple(record.reference_id for record in records),
                updated_at=self._now(),
            )
            if run.context_snapshot_id != context.snapshot_id:
                return self._restore_completed(run, reused=True)
            return ContextCaptureResult(
                run=run,
                context=context,
                records=records,
                reused=reused,
            )
        except Exception as exc:
            self._capture_store.mark_failed(
                run.capture_id,
                failure_code=_capture_failure_code(exc),
                updated_at=self._now(),
            )
            raise

    def _resume_from_captured_evidence(
        self,
        request: HumanContextCaptureRequest,
        run: ContextCaptureRun,
    ) -> ContextCaptureResult:
        try:
            records = self._load_records(run)
            actual_tools = tuple(record.tool_name for record in records)
            if actual_tools != request.requested_tools:
                raise EvidenceIdentityMismatch(
                    "captured evidence does not match the requested tool order"
                )
            context = EvidenceContextBuilder().build(
                account_alias=request.account_alias,
                records=records,
                created_at=run.created_at,
            )
            self._context_store.save_context(context)
            completed = self._capture_store.mark_completed(
                run.capture_id,
                context_snapshot_id=context.snapshot_id,
                evidence_reference_ids=run.evidence_reference_ids,
                updated_at=self._now(),
            )
            if completed.context_snapshot_id != context.snapshot_id:
                return self._restore_completed(completed, reused=True)
            return ContextCaptureResult(
                run=completed,
                context=context,
                records=records,
                reused=True,
            )
        except Exception as exc:
            self._capture_store.mark_failed(
                run.capture_id,
                failure_code=_capture_failure_code(exc),
                updated_at=self._now(),
            )
            raise

    def _load_records(
        self,
        run: ContextCaptureRun,
    ) -> tuple[CanonicalEvidenceRecord, ...]:
        records: list[CanonicalEvidenceRecord] = []
        for reference_id in run.evidence_reference_ids:
            record = self._evidence_repository.get(reference_id)
            if record is None:
                raise EvidenceIdentityMismatch(
                    f"completed capture evidence is missing: {reference_id}"
                )
            records.append(record)
        return tuple(records)

    def _restore_completed(
        self,
        run: ContextCaptureRun,
        *,
        reused: bool,
    ) -> ContextCaptureResult:
        if run.context_snapshot_id is None:
            raise EvidenceIdentityMismatch(
                "completed capture is missing context snapshot id"
            )
        context = self._context_store.get_context(run.context_snapshot_id)
        records = self._load_records(run)
        expected_ids = frozenset(run.evidence_reference_ids)
        if context.evidence_reference_ids != expected_ids:
            raise EvidenceIdentityMismatch(
                "completed capture context and evidence references drifted"
            )
        rebuilt = EvidenceContextBuilder().build(
            account_alias=context.account_alias,
            records=records,
            created_at=context.created_at,
        )
        if rebuilt != context:
            raise EvidenceIdentityMismatch(
                "completed capture context payload or identity drifted"
            )
        return ContextCaptureResult(
            run=run,
            context=context,
            records=records,
            reused=reused,
        )

    @staticmethod
    def _validate_batch(
        request: HumanContextCaptureRequest,
        batch: CaptureSourceBatch,
    ) -> None:
        expected = tuple(request.requested_tools)
        actual = tuple(projection.tool_name for projection in batch.projections)
        if actual != expected:
            raise CaptureSelectionError(
                "capture source did not return the exact requested tool order"
            )


def _capture_failure_code(exc: Exception) -> str:
    if isinstance(exc, EvidenceIdentityMismatch):
        return "evidence_identity_mismatch"
    if isinstance(exc, CaptureSelectionError):
        return "capture_selection_error"
    if isinstance(exc, LookupError):
        return "persisted_evidence_not_found"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "capture_runtime_error"


def _capture_run_from_row(row: sqlite3.Row) -> ContextCaptureRun:
    return ContextCaptureRun(
        capture_id=str(row["capture_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        status=CaptureRunStatus(str(row["status"])),
        context_snapshot_id=(
            str(row["context_snapshot_id"])
            if row["context_snapshot_id"] is not None
            else None
        ),
        evidence_reference_ids=tuple(
            str(item) for item in json.loads(row["evidence_reference_ids_json"] or "[]")
        ),
        failure_code=(
            str(row["failure_code"]) if row["failure_code"] is not None else None
        ),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
