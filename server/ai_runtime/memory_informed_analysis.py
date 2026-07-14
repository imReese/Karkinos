"""Offline research workflow that re-evaluates reviewed memory with current evidence.

This boundary is intentionally deterministic. A human explicitly selects one
eligible Phase 1.8 retrieval record; the workflow then reads every current
canonical evidence record through the existing permission-checked tools before
it emits claim, debate, and report artifacts. Historical memory is copied only
as labelled research input and never becomes a current fact or authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .contracts import (
    AgentRole,
    ArtifactDraft,
    ArtifactKind,
    EvidenceBoundContextSnapshot,
    JsonObject,
    ModelRegistration,
    ProviderRegistration,
    ResearchWorkflow,
    StageDefinition,
    StoredArtifact,
    ToolCallStatus,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from .evidence import (
    CANONICAL_EVIDENCE_KINDS,
    CanonicalEvidenceRecord,
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
    EvidenceIdentityMismatch,
)
from .memory_retrieval import (
    HumanReviewedMemoryRetrievalService,
    ReviewedMemoryRetrievalResult,
)
from .orchestrator import DeterministicWorkflowOrchestrator
from .permissions import default_tool_permission_registry
from .provider import DeterministicFixtureProvider, ProviderResponse
from .registry import AiRuntimeRegistry
from .store import AiAuditStore, IdempotencyConflict

MEMORY_INFORMED_ANALYSIS_CONFIRMATION = (
    "run_offline_memory_informed_fixture_with_current_evidence_"
    "without_trade_authority"
)
MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION = (
    "karkinos.ai.memory_informed_fixture_analysis.v1"
)
MEMORY_INFORMED_PROVIDER_ID = "karkinos.fixture.memory_informed.v1"
MEMORY_INFORMED_MODEL_ID = "karkinos.fixture.memory_informed.research.v1"
MEMORY_INFORMED_DEFINITION_ID = "karkinos.memory_informed_fixture.v1"

_CLAIM_STAGE_ID = "current_evidence_claim"
_DEBATE_STAGE_ID = "memory_evidence_debate"
_REPORT_STAGE_ID = "memory_evidence_report"
_CLAIM_ROLE_ID = "karkinos.role.memory_informed_claim.v1"
_DEBATE_ROLE_ID = "karkinos.role.memory_informed_debate.v1"
_REPORT_ROLE_ID = "karkinos.role.memory_informed_report.v1"
_TERMINAL_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}


class MemoryInformedAnalysisRejected(ValueError):
    """Raised when the retrieval or current evidence cannot start analysis."""


@dataclass(frozen=True)
class HumanMemoryInformedAnalysisRequest:
    retrieval_id: str
    idempotency_key: str
    requested_by: str
    research_question: str
    confirmation: str
    schema_version: str = "karkinos.ai.memory_informed_fixture_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "retrieval_id",
            "idempotency_key",
            "requested_by",
            "research_question",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != MEMORY_INFORMED_ANALYSIS_CONFIRMATION:
            raise ValueError(
                "explicit offline memory-informed analysis confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "retrieval_id": self.retrieval_id,
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "research_question": self.research_question,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class MemoryInformedAnalysisRecord:
    analysis_id: str
    request: HumanMemoryInformedAnalysisRequest
    stored_retrieval_id: str
    stored_idempotency_key: str
    request_fingerprint: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    retrieval_target_fingerprint: str
    run_claimed_at: str | None
    run_claim_expires_at: str | None
    created_at: str


@dataclass(frozen=True)
class MemoryInformedAnalysisReplay:
    analysis_id: str
    workflow_id: str
    valid: bool
    workflow_status: WorkflowStatus
    binding_validity: str
    current_evidence_reads_complete: bool
    audit_event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.memory_informed_fixture_replay.v1",
            "analysis_id": self.analysis_id,
            "workflow_id": self.workflow_id,
            "valid": self.valid,
            "workflow_status": self.workflow_status.value,
            "binding_validity": self.binding_validity,
            "current_evidence_reads_complete": (self.current_evidence_reads_complete),
            "audit_event_count": self.audit_event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "fixture_only": True,
            "memory_input_is_current_fact": False,
            "external_model_invocation_count": 0,
            "decision_handoff_enabled": False,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class MemoryInformedAnalysisResult:
    record: MemoryInformedAnalysisRecord
    workflow: ResearchWorkflow
    retrieval: ReviewedMemoryRetrievalResult | None
    artifacts: tuple[StoredArtifact, ...]
    tool_calls: tuple[JsonObject, ...]
    audit_valid: bool
    audit_event_count: int
    audit_last_event_hash: str | None
    audit_errors: tuple[str, ...]
    binding_errors: tuple[str, ...]
    expected_current_evidence_count: int
    fixture_stage_run_count: int
    reused: bool

    @property
    def binding_validity(self) -> str:
        return "valid" if not self.binding_errors else "invalidated_by_drift"

    @property
    def current_evidence_reads_complete(self) -> bool:
        completed = [
            item
            for item in self.tool_calls
            if item.get("status") == ToolCallStatus.COMPLETED.value
        ]
        return len(completed) == self.expected_current_evidence_count and len(
            completed
        ) == len(self.tool_calls)

    @property
    def replay_valid(self) -> bool:
        return (
            self.workflow.status == WorkflowStatus.COMPLETED
            and self.binding_validity == "valid"
            and self.current_evidence_reads_complete
            and self.audit_valid
        )

    def replay(self) -> MemoryInformedAnalysisReplay:
        errors = list(self.binding_errors)
        errors.extend(self.audit_errors)
        if self.workflow.status != WorkflowStatus.COMPLETED:
            errors.append(f"workflow_not_completed:{self.workflow.status.value}")
        if not self.current_evidence_reads_complete:
            errors.append("current_evidence_reads_incomplete")
        return MemoryInformedAnalysisReplay(
            analysis_id=self.record.analysis_id,
            workflow_id=self.record.workflow_id,
            valid=self.replay_valid,
            workflow_status=self.workflow.status,
            binding_validity=self.binding_validity,
            current_evidence_reads_complete=self.current_evidence_reads_complete,
            audit_event_count=self.audit_event_count,
            last_event_hash=self.audit_last_event_hash,
            errors=tuple(dict.fromkeys(errors)),
        )

    def to_dict(self) -> JsonObject:
        retrieval_payload = self.retrieval.to_dict() if self.retrieval else None
        return {
            "schema_version": MEMORY_INFORMED_ANALYSIS_CONTRACT_VERSION,
            "analysis_id": self.record.analysis_id,
            "retrieval_id": self.record.request.retrieval_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "partial_result": self.workflow.partial_result,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "valuation_snapshot_id": (
                retrieval_payload.get("valuation_snapshot_id")
                if retrieval_payload
                else None
            ),
            "ledger_cutoff_id": (
                retrieval_payload.get("ledger_cutoff_id") if retrieval_payload else None
            ),
            "ledger_fingerprint": (
                retrieval_payload.get("ledger_fingerprint")
                if retrieval_payload
                else None
            ),
            "stored_retrieval_target_fingerprint": (
                self.record.retrieval_target_fingerprint
            ),
            "current_retrieval_target_fingerprint": (
                self.retrieval.current_target.fingerprint if self.retrieval else None
            ),
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "current_evidence_reads_complete": (self.current_evidence_reads_complete),
            "expected_current_evidence_count": (self.expected_current_evidence_count),
            "current_evidence_read_count": sum(
                item.get("status") == ToolCallStatus.COMPLETED.value
                for item in self.tool_calls
            ),
            "artifacts": [_artifact_payload(item) for item in self.artifacts],
            "tool_calls": [dict(item) for item in self.tool_calls],
            "audit_replay": {
                "valid": self.audit_valid,
                "event_count": self.audit_event_count,
                "last_event_hash": self.audit_last_event_hash,
                "errors": list(self.audit_errors),
            },
            "requested_by": self.record.request.requested_by,
            "research_question": self.record.request.research_question,
            "created_at": self.record.created_at,
            "reused": self.reused,
            "provider_id": MEMORY_INFORMED_PROVIDER_ID,
            "model_id": MEMORY_INFORMED_MODEL_ID,
            "fixture_only": True,
            "fixture_stage_run_count": self.fixture_stage_run_count,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "real_provider_registered": False,
            "provider_side_tools_enabled": False,
            "retrieval_tool_registered": False,
            "automatic_recall_enabled": False,
            "semantic_search_used": False,
            "persisted_facts_only": True,
            "memory_input_is_current_fact": False,
            "current_evidence_was_independently_read": (
                self.current_evidence_reads_complete
            ),
            "research_output_is_account_fact": False,
            "decision_handoff_enabled": False,
            "trade_plan_created": False,
            "memory_artifact_created": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_memory_informed_fixture_analyses (
    analysis_id TEXT PRIMARY KEY,
    retrieval_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    retrieval_target_fingerprint TEXT NOT NULL,
    run_claimed_at TEXT,
    run_claim_expires_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(retrieval_id)
        REFERENCES ai_reviewed_memory_retrievals(retrieval_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id),
    FOREIGN KEY(context_snapshot_id) REFERENCES ai_context_snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_memory_informed_fixture_created
ON ai_memory_informed_fixture_analyses(created_at DESC, analysis_id DESC);
"""


class MemoryInformedAnalysisStore:
    """Idempotent retrieval-to-workflow mappings with a short run lease."""

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
            conn.executescript(_ANALYSIS_SCHEMA)

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> MemoryInformedAnalysisRecord | None:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        return _record_from_row(row) if row is not None else None

    def create_or_get(
        self,
        *,
        request: HumanMemoryInformedAnalysisRequest,
        workflow_id: str,
        context: EvidenceBoundContextSnapshot,
        retrieval_target_fingerprint: str,
        created_at: str,
    ) -> tuple[MemoryInformedAnalysisRecord, bool]:
        identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "context_fingerprint": context.fingerprint,
            "retrieval_target_fingerprint": retrieval_target_fingerprint,
        }
        analysis_id = f"ai-memory-analysis-{content_fingerprint(identity)[:24]}"
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ai_memory_informed_fixture_analyses "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if row is not None:
                stored = _record_from_row(row)
                if (
                    stored.request_fingerprint != request.fingerprint
                    or stored.request.retrieval_id != request.retrieval_id
                ):
                    raise IdempotencyConflict(
                        "memory-informed analysis idempotency key was reused "
                        "with different input"
                    )
                return stored, True
            conn.execute(
                """
                INSERT INTO ai_memory_informed_fixture_analyses (
                    analysis_id, retrieval_id, idempotency_key, request_json,
                    request_fingerprint, workflow_id, context_snapshot_id,
                    context_fingerprint, retrieval_target_fingerprint,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    request.retrieval_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    workflow_id,
                    context.snapshot_id,
                    context.fingerprint,
                    retrieval_target_fingerprint,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_memory_informed_fixture_analyses "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("memory-informed analysis persistence failed")
        return _record_from_row(row), False

    def claim_run(
        self,
        analysis_id: str,
        *,
        claimed_at: str,
        expires_at: str,
    ) -> bool:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT run_claim_expires_at "
                "FROM ai_memory_informed_fixture_analyses "
                "WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"memory-informed analysis not found: {analysis_id}")
            existing_expiry = row["run_claim_expires_at"]
            if existing_expiry is not None:
                parsed_expiry = datetime.fromisoformat(str(existing_expiry))
                parsed_claimed_at = datetime.fromisoformat(claimed_at)
                if parsed_expiry.tzinfo is None or parsed_claimed_at.tzinfo is None:
                    raise ValueError("run claim timestamps must include timezone")
                if parsed_expiry > parsed_claimed_at:
                    return False
            updated = conn.execute(
                "UPDATE ai_memory_informed_fixture_analyses "
                "SET run_claimed_at = ?, run_claim_expires_at = ? "
                "WHERE analysis_id = ?",
                (claimed_at, expires_at, analysis_id),
            )
        return updated.rowcount == 1

    def get(self, analysis_id: str) -> MemoryInformedAnalysisRecord:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"memory-informed analysis not found: {analysis_id}")
        return _record_from_row(row)

    def list(self, *, limit: int = 50) -> tuple[MemoryInformedAnalysisRecord, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis list limit must be between 1 and 200")
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM ai_memory_informed_fixture_analyses "
                    "ORDER BY created_at DESC, analysis_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(_record_from_row(row) for row in rows)


@dataclass(frozen=True)
class _AnalysisInputs:
    retrieval: ReviewedMemoryRetrievalResult
    context: EvidenceBoundContextSnapshot
    records: tuple[CanonicalEvidenceRecord, ...]


class HumanMemoryInformedFixtureAnalysisService:
    """Run reviewed memory through a current-evidence-only fixture workflow."""

    def __init__(
        self,
        *,
        retrieval_service: HumanReviewedMemoryRetrievalService,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        analysis_store: MemoryInformedAnalysisStore,
        now: Callable[[], str],
        fixture_failures: Mapping[tuple[str, int], Exception] | None = None,
        partial_stage_id: str | None = None,
        run_lease_seconds: int = 30,
    ) -> None:
        if run_lease_seconds <= 0 or run_lease_seconds > 300:
            raise ValueError("run_lease_seconds must be within [1, 300]")
        if partial_stage_id not in {None, *_stage_ids()}:
            raise ValueError("partial_stage_id is not a workflow stage")
        self._retrieval_service = retrieval_service
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._analysis_store = analysis_store
        self._now = now
        self._fixture_failures = dict(fixture_failures or {})
        self._partial_stage_id = partial_stage_id
        self._run_lease_seconds = run_lease_seconds

    def start(
        self,
        request: HumanMemoryInformedAnalysisRequest,
    ) -> MemoryInformedAnalysisResult:
        existing = self._analysis_store.get_by_idempotency_key(request.idempotency_key)
        if existing is not None and existing.request_fingerprint != request.fingerprint:
            raise IdempotencyConflict(
                "memory-informed analysis idempotency key was reused with "
                "different input"
            )
        if existing is not None:
            existing_workflow = self._ai_store.get_workflow(existing.workflow_id)
            if existing_workflow.status in _TERMINAL_STATUSES:
                retrieval, records = self._current_binding(existing)
                return self._result(
                    existing,
                    workflow=existing_workflow,
                    retrieval=retrieval,
                    records=records,
                    reused=True,
                )
        inputs = self._inputs(request.retrieval_id)
        orchestrator = self._orchestrator(request=request, inputs=inputs)
        workflow = orchestrator.create_workflow(
            definition=_workflow_definition(),
            context=inputs.context,
            idempotency_key=(
                f"memory-informed:{request.idempotency_key}:{request.fingerprint}"
            ),
        )
        record, reused = self._analysis_store.create_or_get(
            request=request,
            workflow_id=workflow.workflow_id,
            context=inputs.context,
            retrieval_target_fingerprint=inputs.retrieval.current_target.fingerprint,
            created_at=self._now(),
        )
        if workflow.status not in _TERMINAL_STATUSES:
            claimed_at = self._now()
            claimed = self._analysis_store.claim_run(
                record.analysis_id,
                claimed_at=claimed_at,
                expires_at=_lease_expiry(claimed_at, self._run_lease_seconds),
            )
            if claimed:
                workflow = orchestrator.run(
                    workflow.workflow_id,
                    current_context=inputs.context,
                )
            else:
                workflow = self._ai_store.get_workflow(workflow.workflow_id)
        return self._result(
            record,
            workflow=workflow,
            retrieval=inputs.retrieval,
            records=inputs.records,
            reused=reused or existing is not None,
        )

    def get(self, analysis_id: str) -> MemoryInformedAnalysisResult:
        record = self._analysis_store.get(analysis_id)
        workflow = self._ai_store.get_workflow(record.workflow_id)
        retrieval, records = self._current_binding(record)
        return self._result(
            record,
            workflow=workflow,
            retrieval=retrieval,
            records=records,
            reused=True,
        )

    def list(self, *, limit: int = 50) -> tuple[MemoryInformedAnalysisResult, ...]:
        return tuple(
            self.get(record.analysis_id)
            for record in self._analysis_store.list(limit=limit)
        )

    def replay(self, analysis_id: str) -> MemoryInformedAnalysisReplay:
        return self.get(analysis_id).replay()

    def _inputs(self, retrieval_id: str) -> _AnalysisInputs:
        retrieval = self._retrieval_service.get(retrieval_id)
        if not retrieval.retrieval_eligible:
            raise MemoryInformedAnalysisRejected(
                "memory-informed analysis requires a currently eligible "
                "reviewed-memory retrieval: "
                + "; ".join(retrieval.invalidation_reasons)
            )
        context = self._ai_store.get_context(
            retrieval.current_target.current_context_snapshot_id
        )
        if context.fingerprint != retrieval.current_target.current_context_fingerprint:
            raise EvidenceIdentityMismatch("retrieval current context drifted")
        records = self._current_records(context)
        return _AnalysisInputs(
            retrieval=retrieval,
            context=context,
            records=records,
        )

    def _current_binding(
        self,
        record: MemoryInformedAnalysisRecord,
    ) -> tuple[
        ReviewedMemoryRetrievalResult | None,
        tuple[CanonicalEvidenceRecord, ...],
    ]:
        try:
            retrieval = self._retrieval_service.get(record.request.retrieval_id)
            context = self._ai_store.get_context(record.context_snapshot_id)
            records = self._current_records(context)
        except (LookupError, EvidenceIdentityMismatch, ValueError):
            return None, ()
        return retrieval, records

    def _current_records(
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
                    f"current evidence financial identity drifted:"
                    f"{reference.reference_id}"
                )
            if not record.authoritative:
                raise EvidenceIdentityMismatch(
                    f"current evidence is not complete:{reference.reference_id}:"
                    f"{record.status}"
                )
            records.append(record)
        if not records:
            raise EvidenceIdentityMismatch("current context has no evidence")
        return tuple(sorted(records, key=lambda item: item.reference_id))

    def _orchestrator(
        self,
        *,
        request: HumanMemoryInformedAnalysisRequest,
        inputs: _AnalysisInputs,
    ) -> DeterministicWorkflowOrchestrator:
        registry = AiRuntimeRegistry(self._ai_store)
        _register_runtime(registry)
        provider = DeterministicFixtureProvider(
            provider_id=MEMORY_INFORMED_PROVIDER_ID,
            responses=_fixture_responses(
                request=request,
                inputs=inputs,
                partial_stage_id=self._partial_stage_id,
            ),
            failures=self._fixture_failures,
        )
        return DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={MEMORY_INFORMED_PROVIDER_ID: provider},
            tool_executors=CanonicalEvidenceToolExecutors(
                self._evidence_repository
            ).as_mapping(),
            now=self._now,
            max_provider_turns=2,
        )

    def _result(
        self,
        record: MemoryInformedAnalysisRecord,
        *,
        workflow: ResearchWorkflow,
        retrieval: ReviewedMemoryRetrievalResult | None,
        records: tuple[CanonicalEvidenceRecord, ...],
        reused: bool,
    ) -> MemoryInformedAnalysisResult:
        artifacts = self._ai_store.list_artifacts(workflow.workflow_id)
        calls = self._ai_store.list_tool_calls(workflow.workflow_id)
        tool_calls = tuple(
            {
                "call_id": item.call_id,
                "run_id": item.run_id,
                "stage_id": item.stage_id,
                "role_id": item.role_id,
                "tool_name": item.tool_name,
                "status": item.status.value,
                "evidence_reference_id": item.arguments.get("evidence_reference_id"),
                "denial_reason": item.denial_reason,
            }
            for item in calls
        )
        audit = self._ai_store.verify_replay(workflow.workflow_id)
        errors = _binding_errors(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            records=records,
            artifacts=artifacts,
            tool_calls=tool_calls,
            audit_valid=audit.valid,
        )
        return MemoryInformedAnalysisResult(
            record=record,
            workflow=workflow,
            retrieval=retrieval,
            artifacts=artifacts,
            tool_calls=tool_calls,
            audit_valid=audit.valid,
            audit_event_count=audit.event_count,
            audit_last_event_hash=audit.last_event_hash,
            audit_errors=audit.errors,
            binding_errors=errors,
            expected_current_evidence_count=len(records),
            fixture_stage_run_count=len(
                self._ai_store.list_agent_runs(workflow.workflow_id)
            ),
            reused=reused,
        )


def _workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=MEMORY_INFORMED_DEFINITION_ID,
        name="Offline re-evaluation of reviewed memory with current evidence",
        stages=(
            StageDefinition(
                stage_id=_CLAIM_STAGE_ID,
                role_id=_CLAIM_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.CLAIM,
            ),
            StageDefinition(
                stage_id=_DEBATE_STAGE_ID,
                role_id=_DEBATE_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.DEBATE,
            ),
            StageDefinition(
                stage_id=_REPORT_STAGE_ID,
                role_id=_REPORT_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.REPORT,
            ),
        ),
    )


def _register_runtime(registry: AiRuntimeRegistry) -> None:
    registry.register_provider(
        ProviderRegistration(
            provider_id=MEMORY_INFORMED_PROVIDER_ID,
            display_name="Karkinos offline memory-informed fixture",
            adapter_kind="deterministic_fixture",
            enabled=True,
            capabilities=(
                "offline_memory_informed_research_fixture",
                "current_evidence_reread_required",
                "no_network",
            ),
        )
    )
    registry.register_model(
        ModelRegistration(
            model_id=MEMORY_INFORMED_MODEL_ID,
            provider_id=MEMORY_INFORMED_PROVIDER_ID,
            model_name="deterministic-memory-informed-fixture-v1",
            enabled=True,
            purposes=("test_reviewed_memory_current_evidence_workflow",),
        )
    )
    role_specs = (
        (
            _CLAIM_ROLE_ID,
            "Current evidence re-reader",
            (
                "Read every current canonical evidence record before labelling "
                "historical reviewed memory as research input."
            ),
            tuple(CANONICAL_EVIDENCE_KINDS),
            ArtifactKind.CLAIM,
        ),
        (
            _DEBATE_ROLE_ID,
            "Memory-evidence critic",
            "Contrast historical reviewed input with current evidence boundaries.",
            (),
            ArtifactKind.DEBATE,
        ),
        (
            _REPORT_ROLE_ID,
            "Memory-informed fixture reporter",
            "Report provenance and limitations without investment authority.",
            (),
            ArtifactKind.REPORT,
        ),
    )
    for role_id, display_name, purpose, tools, artifact_kind in role_specs:
        registry.register_role(
            AgentRole(
                role_id=role_id,
                display_name=display_name,
                purpose=purpose,
                allowed_tools=tools,
                allowed_artifact_kinds=(artifact_kind,),
            )
        )


def _fixture_responses(
    *,
    request: HumanMemoryInformedAnalysisRequest,
    inputs: _AnalysisInputs,
    partial_stage_id: str | None,
) -> dict[str, tuple[ProviderResponse, ...]]:
    reference_ids = tuple(item.reference_id for item in inputs.records)
    target_fingerprint = inputs.retrieval.current_target.fingerprint
    memory_inputs = [
        {
            "review_id": item.review_id,
            "analysis_id": item.analysis_id,
            "memory_artifact_id": item.memory_artifact_id,
            "memory_artifact_fingerprint": item.memory_artifact_fingerprint,
            "source_context_snapshot_id": item.source_context_snapshot_id,
            "memory_content": dict(item.memory_content),
            "role": "historical_reviewed_research_input",
            "is_current_fact": False,
        }
        for item in inputs.retrieval.current_target.selections
    ]
    evidence_inventory = [
        {
            "tool_name": item.tool_name,
            "reference_id": item.reference_id,
            "record_fingerprint": item.record_fingerprint,
            "status": item.status,
            "as_of": item.as_of,
        }
        for item in inputs.records
    ]
    common = {
        "retrieval_id": inputs.retrieval.stored.retrieval_id,
        "retrieval_target_fingerprint": target_fingerprint,
        "current_context_snapshot_id": inputs.context.snapshot_id,
        "current_context_fingerprint": inputs.context.fingerprint,
        "memory_inputs": memory_inputs,
        "memory_input_is_current_fact": False,
        "current_evidence_must_be_read": True,
        "research_output_is_account_fact": False,
        "authority_effect": "none",
    }
    claim = ArtifactDraft(
        kind=ArtifactKind.CLAIM,
        content={
            **common,
            "statement": (
                f"The fixture independently read {len(inputs.records)} current "
                f"evidence records before considering {len(memory_inputs)} "
                "reviewed historical memory inputs."
            ),
            "confidence": "fixture_only_not_an_investment_conclusion",
            "assumptions": [
                "Current immutable evidence and retrieval bindings remain valid.",
                "Historical memory is a hypothesis source, not current fact.",
            ],
            "limitations": [
                "The deterministic fixture performs no semantic investment analysis.",
                "A future model must cite current evidence for every current claim.",
            ],
        },
        evidence_reference_ids=reference_ids,
    )
    debate = ArtifactDraft(
        kind=ArtifactKind.DEBATE,
        content={
            **common,
            "topic": request.research_question,
            "participant_role_ids": [_CLAIM_ROLE_ID, _DEBATE_ROLE_ID],
            "positions": [
                {
                    "role_id": _CLAIM_ROLE_ID,
                    "position": (
                        "Only the newly read canonical records can support "
                        "claims about the current context."
                    ),
                },
                {
                    "role_id": _DEBATE_ROLE_ID,
                    "position": (
                        "Reviewed memory may identify questions but cannot carry "
                        "its old conclusions into the current context."
                    ),
                },
            ],
            "unresolved_questions": [
                "Which historical assumptions still match current evidence?",
                "Which current facts contradict or supersede the old context?",
            ],
        },
        evidence_reference_ids=reference_ids,
    )
    report = ArtifactDraft(
        kind=ArtifactKind.REPORT,
        content={
            **common,
            "title": "Fixture review of historical memory against current evidence",
            "summary": (
                "The workflow proved the current-evidence reread and provenance "
                "boundary. It did not produce an investment recommendation."
            ),
            "sections": [
                {
                    "heading": "Current canonical evidence",
                    "items": evidence_inventory,
                },
                {
                    "heading": "Historical reviewed inputs",
                    "items": memory_inputs,
                },
                {
                    "heading": "Required human next step",
                    "content": (
                        "Review any future evidence-supported comparison; do not "
                        "treat this fixture or old memory as Decision input."
                    ),
                },
            ],
            "limitations": [
                "No external model or semantic comparison ran.",
                "No result is an account, risk, capital, or execution fact.",
            ],
        },
        evidence_reference_ids=reference_ids,
    )
    tool_requests = tuple(
        ToolRequest(
            request_id=f"current-evidence-read-{index + 1}",
            tool_name=record.tool_name,
            arguments={"evidence_reference_id": record.reference_id},
        )
        for index, record in enumerate(inputs.records)
    )

    def final(stage_id: str, draft: ArtifactDraft) -> ProviderResponse:
        return ProviderResponse(
            artifacts=(draft,),
            partial=partial_stage_id == stage_id,
            message="Deterministic memory-informed fixture output.",
        )

    return {
        _CLAIM_STAGE_ID: (
            ProviderResponse(
                tool_requests=tool_requests,
                message="Read every current evidence record before using memory.",
            ),
            final(_CLAIM_STAGE_ID, claim),
        ),
        _DEBATE_STAGE_ID: (final(_DEBATE_STAGE_ID, debate),),
        _REPORT_STAGE_ID: (final(_REPORT_STAGE_ID, report),),
    }


def _binding_errors(
    *,
    record: MemoryInformedAnalysisRecord,
    workflow: ResearchWorkflow,
    retrieval: ReviewedMemoryRetrievalResult | None,
    records: tuple[CanonicalEvidenceRecord, ...],
    artifacts: tuple[StoredArtifact, ...],
    tool_calls: tuple[JsonObject, ...],
    audit_valid: bool,
) -> tuple[str, ...]:
    errors: list[str] = []
    if record.stored_retrieval_id != record.request.retrieval_id:
        errors.append("analysis_retrieval_binding_drift")
    if record.stored_idempotency_key != record.request.idempotency_key:
        errors.append("analysis_idempotency_binding_drift")
    if record.request_fingerprint != record.request.fingerprint:
        errors.append("analysis_request_fingerprint_drift")
    if workflow.definition.definition_id != MEMORY_INFORMED_DEFINITION_ID:
        errors.append("workflow_definition_drift")
    if workflow.context_snapshot_id != record.context_snapshot_id:
        errors.append("workflow_context_snapshot_drift")
    if workflow.context_fingerprint != record.context_fingerprint:
        errors.append("workflow_context_fingerprint_drift")
    if retrieval is None:
        errors.append("retrieval_or_current_evidence_invalid")
    else:
        if not retrieval.retrieval_eligible:
            errors.append("retrieval_no_longer_eligible")
        if retrieval.current_target.fingerprint != (
            record.retrieval_target_fingerprint
        ):
            errors.append("retrieval_target_fingerprint_drift")
        if retrieval.current_target.current_context_snapshot_id != (
            record.context_snapshot_id
        ):
            errors.append("retrieval_context_snapshot_drift")
        if retrieval.current_target.current_context_fingerprint != (
            record.context_fingerprint
        ):
            errors.append("retrieval_context_fingerprint_drift")
    if not audit_valid:
        errors.append("workflow_audit_invalid")

    expected_reads = {(item.tool_name, item.reference_id) for item in records}
    actual_reads = {
        (str(item.get("tool_name")), str(item.get("evidence_reference_id")))
        for item in tool_calls
        if item.get("status") == ToolCallStatus.COMPLETED.value
    }
    if actual_reads != expected_reads or len(tool_calls) != len(expected_reads):
        errors.append("current_evidence_tool_read_set_incomplete")
    if any(
        item.get("stage_id") != _CLAIM_STAGE_ID
        or item.get("status") != ToolCallStatus.COMPLETED.value
        for item in tool_calls
    ):
        errors.append("current_evidence_tool_call_invalid")

    expected_reference_ids = tuple(item.reference_id for item in records)
    for artifact in artifacts:
        actual_fingerprint = content_fingerprint(
            {
                "workflow_id": artifact.workflow_id,
                "run_id": artifact.run_id,
                "stage_id": artifact.stage_id,
                "role_id": artifact.role_id,
                "kind": artifact.kind.value,
                "content": dict(artifact.content),
                "evidence_reference_ids": list(artifact.evidence_reference_ids),
            }
        )
        if actual_fingerprint != artifact.fingerprint:
            errors.append(f"artifact_fingerprint_drift:{artifact.artifact_id}")
        if tuple(artifact.evidence_reference_ids) != expected_reference_ids:
            errors.append(f"artifact_current_evidence_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_id") != record.request.retrieval_id:
            errors.append(f"artifact_retrieval_binding_drift:{artifact.artifact_id}")
        if artifact.content.get("retrieval_target_fingerprint") != (
            record.retrieval_target_fingerprint
        ):
            errors.append(f"artifact_retrieval_target_drift:{artifact.artifact_id}")
        if artifact.content.get("memory_input_is_current_fact") is not False:
            errors.append(f"artifact_promotes_memory_to_fact:{artifact.artifact_id}")
        if artifact.content.get("authority_effect") != "none":
            errors.append(f"artifact_authority_effect_drift:{artifact.artifact_id}")
    if workflow.status == WorkflowStatus.COMPLETED:
        if tuple(item.kind for item in artifacts) != (
            ArtifactKind.CLAIM,
            ArtifactKind.DEBATE,
            ArtifactKind.REPORT,
        ):
            errors.append("analysis_artifact_lifecycle_incomplete")
    return tuple(dict.fromkeys(errors))


def _artifact_payload(artifact: StoredArtifact) -> JsonObject:
    return {
        "artifact_id": artifact.artifact_id,
        "stage_id": artifact.stage_id,
        "role_id": artifact.role_id,
        "kind": artifact.kind.value,
        "content": dict(artifact.content),
        "evidence_reference_ids": list(artifact.evidence_reference_ids),
        "fingerprint": artifact.fingerprint,
        "created_at": artifact.created_at,
        "authority_effect": "none",
    }


def _stage_ids() -> tuple[str, ...]:
    return (_CLAIM_STAGE_ID, _DEBATE_STAGE_ID, _REPORT_STAGE_ID)


def _lease_expiry(claimed_at: str, seconds: int) -> str:
    instant = datetime.fromisoformat(claimed_at)
    if instant.tzinfo is None:
        raise ValueError("run claim timestamp must include timezone")
    return (instant + timedelta(seconds=seconds)).isoformat()


def _record_from_row(row: sqlite3.Row) -> MemoryInformedAnalysisRecord:
    payload = json.loads(str(row["request_json"]))
    request = HumanMemoryInformedAnalysisRequest(
        retrieval_id=str(payload["retrieval_id"]),
        idempotency_key=str(payload["idempotency_key"]),
        requested_by=str(payload["requested_by"]),
        research_question=str(payload["research_question"]),
        confirmation=str(payload["confirmation"]),
        schema_version=str(payload["schema_version"]),
    )
    return MemoryInformedAnalysisRecord(
        analysis_id=str(row["analysis_id"]),
        request=request,
        stored_retrieval_id=str(row["retrieval_id"]),
        stored_idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        workflow_id=str(row["workflow_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        retrieval_target_fingerprint=str(row["retrieval_target_fingerprint"]),
        run_claimed_at=(
            str(row["run_claimed_at"]) if row["run_claimed_at"] is not None else None
        ),
        run_claim_expires_at=(
            str(row["run_claim_expires_at"])
            if row["run_claim_expires_at"] is not None
            else None
        ),
        created_at=str(row["created_at"]),
    )
