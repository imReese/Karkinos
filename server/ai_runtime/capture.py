"""Human-started capture of canonical evidence into an AI research context."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol

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
from .persistence.context_capture import ContextCaptureSqliteRepository
from .store import AiAuditStore, IdempotencyConflict

CAPTURE_CONFIRMATION = "capture_read_only_research_context"


def _require_write_open(write_guard: Callable[[], Any] | None) -> None:
    if callable(write_guard):
        write_guard()


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


class ContextCaptureAuditStore:
    """Durable lifecycle records for explicit, model-free context capture."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._repository = ContextCaptureSqliteRepository(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def init(self) -> None:
        self._repository.init()

    def capture_guarded(self, **kwargs: Any) -> tuple[Any, ...]:
        """Delegate one atomic capture to the canonical persistence adapter."""

        return self._repository.capture_guarded(**kwargs)

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
        row, reused = self._repository.create_or_get(
            capture_id=capture_id,
            idempotency_key=request.idempotency_key,
            request_json=request_json,
            request_fingerprint=request.fingerprint,
            status=CaptureRunStatus.RUNNING.value,
            created_at=created_at,
        )
        if row is None:
            raise IdempotencyConflict("capture identity collision")
        if str(row["request_fingerprint"]) != request.fingerprint:
            raise IdempotencyConflict(
                "capture idempotency key was reused with different input"
            )
        return _capture_run_from_mapping(row), reused

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
        row = self._repository.get(capture_id)
        if row is None:
            raise LookupError(f"context capture run not found: {capture_id}")
        return _capture_run_from_mapping(row)

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
        row, updated = self._repository.update(
            capture_id=capture_id,
            status=status.value,
            context_snapshot_id=context_snapshot_id,
            evidence_reference_ids_json=canonical_json(list(evidence_reference_ids)),
            failure_code=failure_code,
            updated_at=updated_at,
            preserve_status=(
                CaptureRunStatus.COMPLETED.value if preserve_completed else None
            ),
        )
        if row is None:
            raise LookupError(f"context capture run not found: {capture_id}")
        if not updated and not (
            preserve_completed
            and str(row["status"]) == CaptureRunStatus.COMPLETED.value
        ):
            raise RuntimeError(f"context capture update failed: {capture_id}")
        return _capture_run_from_mapping(row)


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
        *,
        write_guard: Callable[[], Any] | None = None,
    ) -> ContextCaptureResult:
        if callable(write_guard):
            batch = await self._source.load(request)
            self._validate_batch(request, batch)
            return self._capture_guarded_atomically(
                request,
                batch=batch,
                write_guard=write_guard,
            )
        _require_write_open(write_guard)
        run, reused = self._capture_store.create_or_get(
            request,
            created_at=self._now(),
        )
        if run.status == CaptureRunStatus.COMPLETED:
            return self._restore_completed(run, reused=True)
        if reused and run.evidence_reference_ids:
            return self._resume_from_captured_evidence(request, run)
        if reused:
            _require_write_open(write_guard)
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
                self._persist_guarded_evidence(
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
                    ),
                    write_guard=write_guard,
                )
                for projection in batch.projections
            )
            _require_write_open(write_guard)
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
            _require_write_open(write_guard)
            self._context_store.save_context(context)
            _require_write_open(write_guard)
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
            _require_write_open(write_guard)
            self._capture_store.mark_failed(
                run.capture_id,
                failure_code=_capture_failure_code(exc),
                updated_at=self._now(),
            )
            raise

    def _capture_guarded_atomically(
        self,
        request: HumanContextCaptureRequest,
        *,
        batch: CaptureSourceBatch,
        write_guard: Callable[[], Any],
    ) -> ContextCaptureResult:
        """Commit a guarded capture only if the deadline remains open."""

        paths = {
            self._capture_store.path.resolve(),
            self._evidence_repository.path.resolve(),
            self._context_store.path.resolve(),
        }
        if len(paths) != 1:
            raise RuntimeError("guarded capture stores must share one database")
        capture_identity = {
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": request.fingerprint,
        }
        capture_id = f"ai-capture-{content_fingerprint(capture_identity)[:24]}"

        def build_records(created_at: str) -> tuple[CanonicalEvidenceRecord, ...]:
            return tuple(
                CanonicalEvidenceRecord.capture(
                    tool_name=projection.tool_name,
                    valuation_snapshot_id=batch.valuation_snapshot_id,
                    ledger_cutoff_id=batch.ledger_cutoff_id,
                    ledger_fingerprint=batch.ledger_fingerprint,
                    status=projection.status,
                    as_of=projection.as_of,
                    source_schema_version=projection.source_schema_version,
                    payload=projection.payload,
                    captured_at=created_at,
                )
                for projection in batch.projections
            )

        def build_context(
            records: Sequence[CanonicalEvidenceRecord], created_at: str
        ) -> EvidenceBoundContextSnapshot:
            return EvidenceContextBuilder().build(
                account_alias=request.account_alias,
                records=records,
                created_at=created_at,
            )

        row, records, context, reused, completed_existing = (
            self._capture_store.capture_guarded(
                capture_id=capture_id,
                idempotency_key=request.idempotency_key,
                request_json=canonical_json(request.to_dict()),
                request_fingerprint=request.fingerprint,
                running_status=CaptureRunStatus.RUNNING.value,
                completed_status=CaptureRunStatus.COMPLETED.value,
                created_at=self._now,
                updated_at=self._now,
                write_guard=write_guard,
                build_records=build_records,
                record_values=lambda record: {
                    **record.to_dict(),
                    "payload_json": canonical_json(record.payload),
                },
                build_context=build_context,
                context_values=lambda value, captured_records: {
                    "snapshot_id": value.snapshot_id,
                    "context_fingerprint": value.fingerprint,
                    "valuation_snapshot_id": value.valuation_snapshot_id,
                    "ledger_cutoff_id": value.ledger_cutoff_id,
                    "ledger_fingerprint": value.ledger_fingerprint,
                    "payload_json": canonical_json(value.to_dict()),
                    "created_at": value.created_at,
                    "evidence_reference_ids_json": canonical_json(
                        [record.reference_id for record in captured_records]
                    ),
                },
                identity_conflict=IdempotencyConflict,
                evidence_conflict=EvidenceIdentityMismatch,
            )
        )
        run = _capture_run_from_mapping(row)
        if completed_existing:
            return self._restore_completed(run, reused=True)
        if context is None:
            raise RuntimeError("guarded capture returned no context")
        return ContextCaptureResult(
            run=run,
            context=context,
            records=tuple(records),
            reused=reused,
        )

    def _persist_guarded_evidence(
        self,
        record: CanonicalEvidenceRecord,
        *,
        write_guard: Callable[[], Any] | None,
    ) -> CanonicalEvidenceRecord:
        _require_write_open(write_guard)
        return self._evidence_repository.persist(record)

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


def _capture_run_from_mapping(row: Mapping[str, Any]) -> ContextCaptureRun:
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
