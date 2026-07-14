"""Explicit deterministic-fixture analysis for accepted human research tasks.

This boundary exercises the provider-neutral workflow runtime with immutable
local fixtures only.  It performs no network I/O, calls no external model, and
has no OMS, ledger, risk, capital, kill-switch, or broker authority.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .contracts import (
    AgentRole,
    ArtifactKind,
    Claim,
    Debate,
    EvidenceBoundContextSnapshot,
    JsonObject,
    MemoryArtifact,
    ModelRegistration,
    ProviderRegistration,
    Report,
    ResearchWorkflow,
    StageDefinition,
    StoredArtifact,
    ToolRequest,
    WorkflowDefinition,
    WorkflowStatus,
    canonical_json,
    content_fingerprint,
)
from .evidence import (
    CANONICAL_EVIDENCE_KINDS,
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
    EvidenceIdentityMismatch,
)
from .orchestrator import DeterministicWorkflowOrchestrator
from .permissions import default_tool_permission_registry
from .provider import DeterministicFixtureProvider, ProviderResponse
from .registry import AiRuntimeRegistry
from .store import AiAuditStore, AuditReplayResult, IdempotencyConflict
from .tasks import (
    HumanResearchTaskService,
    ResearchTask,
    ResearchTaskRejected,
    ResearchTaskStatus,
    ResearchTaskStore,
)

FIXTURE_ANALYSIS_CONFIRMATION = (
    "run_deterministic_fixture_analysis_without_external_model"
)
FIXTURE_PROVIDER_ID = "karkinos.fixture.offline.v1"
FIXTURE_MODEL_ID = "karkinos.fixture.research.v1"
FIXTURE_DEFINITION_ID = "karkinos.fixture.task_analysis.v1"
FIXTURE_CONTRACT_VERSION = "karkinos.ai.task_fixture_analysis.v1"

_CLAIM_ROLE_ID = "fixture.evidence_analyst.v1"
_DEBATE_ROLE_ID = "fixture.evidence_critic.v1"
_REPORT_ROLE_ID = "fixture.research_reporter.v1"
_MEMORY_ROLE_ID = "fixture.memory_curator.v1"
_MEMORY_STAGE_INDEX = 3


class ResearchTaskAnalysisRejected(ValueError):
    """Raised when an analysis command cannot cross the human/evidence gates."""


@dataclass(frozen=True)
class HumanFixtureAnalysisRequest:
    task_id: str
    idempotency_key: str
    requested_by: str
    confirmation: str
    schema_version: str = "karkinos.ai.human_fixture_analysis_request.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "task_id",
            "idempotency_key",
            "requested_by",
            "schema_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.confirmation != FIXTURE_ANALYSIS_CONFIRMATION:
            raise ValueError(
                "explicit deterministic fixture analysis confirmation is required"
            )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "task_id": self.task_id,
            "idempotency_key": self.idempotency_key,
            "requested_by": self.requested_by,
            "confirmation": self.confirmation,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchTaskAnalysisRecord:
    analysis_id: str
    task_id: str
    idempotency_key: str
    request_fingerprint: str
    requested_by: str
    workflow_id: str
    context_snapshot_id: str
    context_fingerprint: str
    fixture_contract_version: str
    created_at: str


@dataclass(frozen=True)
class ResearchTaskAnalysisReplay:
    analysis_id: str
    task_id: str
    workflow_id: str
    valid: bool
    binding_validity: str
    event_count: int
    last_event_hash: str | None
    errors: tuple[str, ...]

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": "karkinos.ai.task_fixture_analysis_replay.v1",
            "analysis_id": self.analysis_id,
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "valid": self.valid,
            "binding_validity": self.binding_validity,
            "event_count": self.event_count,
            "last_event_hash": self.last_event_hash,
            "errors": list(self.errors),
            "fixture_only": True,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "authority_effect": "none",
        }


@dataclass(frozen=True)
class ResearchTaskAnalysisResult:
    record: ResearchTaskAnalysisRecord
    workflow: ResearchWorkflow
    artifacts: tuple[StoredArtifact, ...]
    tool_calls: tuple[JsonObject, ...]
    audit_replay: AuditReplayResult
    binding_validity: str
    binding_errors: tuple[str, ...]
    fixture_stage_run_count: int
    reused: bool

    @property
    def memory_validity(self) -> str:
        if self.binding_validity != "valid":
            return "invalidated_by_evidence_drift"
        if not any(item.kind == ArtifactKind.MEMORY for item in self.artifacts):
            return "not_created"
        return "human_review_required_exact_context_only"

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": FIXTURE_CONTRACT_VERSION,
            "analysis_id": self.record.analysis_id,
            "task_id": self.record.task_id,
            "workflow_id": self.record.workflow_id,
            "workflow_status": self.workflow.status.value,
            "workflow_failure_code": self.workflow.failure_code,
            "partial_result": self.workflow.partial_result,
            "context_snapshot_id": self.record.context_snapshot_id,
            "context_fingerprint": self.record.context_fingerprint,
            "binding_validity": self.binding_validity,
            "binding_errors": list(self.binding_errors),
            "memory_validity": self.memory_validity,
            "artifacts": [_artifact_payload(item) for item in self.artifacts],
            "tool_calls": [dict(item) for item in self.tool_calls],
            "audit_replay": {
                "valid": self.audit_replay.valid,
                "event_count": self.audit_replay.event_count,
                "last_event_hash": self.audit_replay.last_event_hash,
                "errors": list(self.audit_replay.errors),
            },
            "requested_by": self.record.requested_by,
            "created_at": self.record.created_at,
            "reused": self.reused,
            "provider_id": FIXTURE_PROVIDER_ID,
            "model_id": FIXTURE_MODEL_ID,
            "fixture_only": True,
            "fixture_stage_run_count": self.fixture_stage_run_count,
            "network_io_used": False,
            "external_model_invocation_count": 0,
            "real_provider_registered": False,
            "background_execution_used": False,
            "persisted_facts_only": True,
            "research_output_is_account_fact": False,
            "authority_effect": "none",
            "does_not_mutate_financial_state": True,
        }


_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_research_task_analyses (
    analysis_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    workflow_id TEXT NOT NULL UNIQUE,
    context_snapshot_id TEXT NOT NULL,
    context_fingerprint TEXT NOT NULL,
    fixture_contract_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES ai_research_tasks(task_id),
    FOREIGN KEY(workflow_id) REFERENCES ai_workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_research_task_analyses_task
ON ai_research_task_analyses(task_id, created_at DESC);
"""


class ResearchTaskAnalysisStore:
    """Task-to-workflow mappings for explicitly started local fixture runs."""

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

    def create_or_get(
        self,
        request: HumanFixtureAnalysisRequest,
        *,
        workflow_id: str,
        context_snapshot_id: str,
        context_fingerprint: str,
        created_at: str,
    ) -> tuple[ResearchTaskAnalysisRecord, bool]:
        analysis_identity = {
            "request_fingerprint": request.fingerprint,
            "workflow_id": workflow_id,
            "context_fingerprint": context_fingerprint,
        }
        analysis_id = f"ai-task-analysis-{content_fingerprint(analysis_identity)[:24]}"
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM ai_research_task_analyses WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["request_fingerprint"]) != request.fingerprint
                    or str(existing["workflow_id"]) != workflow_id
                ):
                    raise IdempotencyConflict(
                        "fixture analysis idempotency key was reused with different input"
                    )
                return _analysis_from_row(existing), True
            conn.execute(
                """
                INSERT INTO ai_research_task_analyses (
                    analysis_id, task_id, idempotency_key, request_json,
                    request_fingerprint, requested_by, workflow_id,
                    context_snapshot_id, context_fingerprint,
                    fixture_contract_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    request.task_id,
                    request.idempotency_key,
                    canonical_json(request.to_dict()),
                    request.fingerprint,
                    request.requested_by,
                    workflow_id,
                    context_snapshot_id,
                    context_fingerprint,
                    FIXTURE_CONTRACT_VERSION,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM ai_research_task_analyses WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("fixture analysis mapping persistence failed")
        return _analysis_from_row(row), False

    def get(self, analysis_id: str) -> ResearchTaskAnalysisRecord:
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ai_research_task_analyses WHERE analysis_id = ?",
                    (analysis_id,),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            row = None
        if row is None:
            raise LookupError(f"fixture analysis not found: {analysis_id}")
        return _analysis_from_row(row)

    def list(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ResearchTaskAnalysisRecord, ...]:
        if limit <= 0 or limit > 200:
            raise ValueError("analysis list limit must be between 1 and 200")
        sql = "SELECT * FROM ai_research_task_analyses"
        params: list[object] = []
        if task_id is not None:
            sql += " WHERE task_id = ?"
            params.append(task_id)
        sql += " ORDER BY created_at DESC, analysis_id DESC LIMIT ?"
        params.append(limit)
        try:
            with self._connection() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
        return tuple(_analysis_from_row(row) for row in rows)


class HumanResearchTaskFixtureAnalysisService:
    """Run the existing workflow runtime only through explicit local fixtures."""

    def __init__(
        self,
        *,
        ai_store: AiAuditStore,
        evidence_repository: CanonicalEvidenceRepository,
        task_store: ResearchTaskStore,
        task_service: HumanResearchTaskService,
        analysis_store: ResearchTaskAnalysisStore,
        now: Callable[[], str],
    ) -> None:
        self._ai_store = ai_store
        self._evidence_repository = evidence_repository
        self._task_store = task_store
        self._task_service = task_service
        self._analysis_store = analysis_store
        self._now = now

    def start(
        self,
        request: HumanFixtureAnalysisRequest,
    ) -> ResearchTaskAnalysisResult:
        task = self._require_accepted_task(request.task_id)
        self._task_service.replay(task.task_id)
        context = self._load_exact_context(task)
        definition = _fixture_definition()
        initial_orchestrator = self._orchestrator(
            task=task,
            memory_source_artifact_ids=(),
        )
        workflow = initial_orchestrator.create_workflow(
            definition=definition,
            context=context,
            idempotency_key=f"task-fixture-analysis:{request.idempotency_key}",
        )
        record, reused = self._analysis_store.create_or_get(
            request,
            workflow_id=workflow.workflow_id,
            context_snapshot_id=context.snapshot_id,
            context_fingerprint=context.fingerprint,
            created_at=self._now(),
        )

        if workflow.status not in _TERMINAL_ANALYSIS_STATUSES:
            stages_before_memory = max(
                0,
                _MEMORY_STAGE_INDEX - workflow.current_stage_index,
            )
            if stages_before_memory:
                workflow = initial_orchestrator.run(
                    workflow.workflow_id,
                    current_context=context,
                    max_stages=stages_before_memory,
                )
            if workflow.status not in _TERMINAL_ANALYSIS_STATUSES:
                source_ids = tuple(
                    item.artifact_id
                    for item in self._ai_store.list_artifacts(workflow.workflow_id)
                )
                memory_orchestrator = self._orchestrator(
                    task=task,
                    memory_source_artifact_ids=source_ids,
                )
                workflow = memory_orchestrator.run(
                    workflow.workflow_id,
                    current_context=context,
                )
        return self._result(record, workflow=workflow, reused=reused)

    def get(self, analysis_id: str) -> ResearchTaskAnalysisResult:
        record = self._analysis_store.get(analysis_id)
        workflow = self._ai_store.get_workflow(record.workflow_id)
        return self._result(record, workflow=workflow, reused=True)

    def list(
        self,
        *,
        task_id: str | None = None,
        limit: int = 50,
    ) -> tuple[ResearchTaskAnalysisResult, ...]:
        return tuple(
            self.get(record.analysis_id)
            for record in self._analysis_store.list(task_id=task_id, limit=limit)
        )

    def replay(self, analysis_id: str) -> ResearchTaskAnalysisReplay:
        record = self._analysis_store.get(analysis_id)
        binding_validity, binding_errors = self._binding_validity(record.task_id)
        audit = self._ai_store.verify_replay(record.workflow_id)
        errors = (*audit.errors, *binding_errors)
        return ResearchTaskAnalysisReplay(
            analysis_id=record.analysis_id,
            task_id=record.task_id,
            workflow_id=record.workflow_id,
            valid=audit.valid and binding_validity == "valid",
            binding_validity=binding_validity,
            event_count=audit.event_count,
            last_event_hash=audit.last_event_hash,
            errors=errors,
        )

    def _require_accepted_task(self, task_id: str) -> ResearchTask:
        task = self._task_store.get(task_id)
        if task.status != ResearchTaskStatus.CONTEXT_ACCEPTED:
            raise ResearchTaskAnalysisRejected(
                "fixture analysis requires an explicitly accepted task context"
            )
        if not task.all_evidence_authoritative:
            raise ResearchTaskAnalysisRejected(
                "fixture analysis requires complete authoritative evidence"
            )
        return task

    def _load_exact_context(
        self,
        task: ResearchTask,
    ) -> EvidenceBoundContextSnapshot:
        context = self._ai_store.get_context(task.context_snapshot_id)
        if context.fingerprint != task.context_fingerprint:
            raise EvidenceIdentityMismatch("fixture analysis task context drifted")
        if context.valuation_snapshot_id != task.valuation_snapshot_id:
            raise EvidenceIdentityMismatch(
                "fixture analysis valuation snapshot drifted"
            )
        if context.ledger_cutoff_id != task.ledger_cutoff_id:
            raise EvidenceIdentityMismatch("fixture analysis ledger cutoff drifted")
        if context.ledger_fingerprint != task.ledger_fingerprint:
            raise EvidenceIdentityMismatch(
                "fixture analysis ledger fingerprint drifted"
            )
        return context

    def _orchestrator(
        self,
        *,
        task: ResearchTask,
        memory_source_artifact_ids: tuple[str, ...],
    ) -> DeterministicWorkflowOrchestrator:
        registry = AiRuntimeRegistry(self._ai_store)
        _register_fixture_runtime(registry)
        provider = DeterministicFixtureProvider(
            provider_id=FIXTURE_PROVIDER_ID,
            responses=_fixture_responses(
                task,
                memory_source_artifact_ids=memory_source_artifact_ids,
            ),
        )
        return DeterministicWorkflowOrchestrator(
            store=self._ai_store,
            registry=registry,
            permissions=default_tool_permission_registry(),
            providers={FIXTURE_PROVIDER_ID: provider},
            tool_executors=CanonicalEvidenceToolExecutors(
                self._evidence_repository
            ).as_mapping(),
            now=self._now,
        )

    def _binding_validity(self, task_id: str) -> tuple[str, tuple[str, ...]]:
        try:
            task = self._require_accepted_task(task_id)
            self._task_service.replay(task_id)
            self._load_exact_context(task)
        except (EvidenceIdentityMismatch, ResearchTaskRejected) as exc:
            return "evidence_drift", (str(exc),)
        return "valid", ()

    def _result(
        self,
        record: ResearchTaskAnalysisRecord,
        *,
        workflow: ResearchWorkflow,
        reused: bool,
    ) -> ResearchTaskAnalysisResult:
        binding_validity, binding_errors = self._binding_validity(record.task_id)
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
            for item in self._ai_store.list_tool_calls(workflow.workflow_id)
        )
        return ResearchTaskAnalysisResult(
            record=record,
            workflow=workflow,
            artifacts=self._ai_store.list_artifacts(workflow.workflow_id),
            tool_calls=tool_calls,
            audit_replay=self._ai_store.verify_replay(workflow.workflow_id),
            binding_validity=binding_validity,
            binding_errors=binding_errors,
            fixture_stage_run_count=len(
                self._ai_store.list_agent_runs(workflow.workflow_id)
            ),
            reused=reused,
        )


_TERMINAL_ANALYSIS_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.PARTIAL,
    WorkflowStatus.FAILED,
    WorkflowStatus.BLOCKED,
}


def _fixture_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=FIXTURE_DEFINITION_ID,
        name="Explicit offline fixture analysis for an accepted research task",
        stages=(
            StageDefinition(
                stage_id="claim",
                role_id=_CLAIM_ROLE_ID,
                model_id=FIXTURE_MODEL_ID,
                output_kind=ArtifactKind.CLAIM,
            ),
            StageDefinition(
                stage_id="debate",
                role_id=_DEBATE_ROLE_ID,
                model_id=FIXTURE_MODEL_ID,
                output_kind=ArtifactKind.DEBATE,
            ),
            StageDefinition(
                stage_id="report",
                role_id=_REPORT_ROLE_ID,
                model_id=FIXTURE_MODEL_ID,
                output_kind=ArtifactKind.REPORT,
            ),
            StageDefinition(
                stage_id="memory",
                role_id=_MEMORY_ROLE_ID,
                model_id=FIXTURE_MODEL_ID,
                output_kind=ArtifactKind.MEMORY,
            ),
        ),
    )


def _register_fixture_runtime(registry: AiRuntimeRegistry) -> None:
    registry.register_provider(
        ProviderRegistration(
            provider_id=FIXTURE_PROVIDER_ID,
            display_name="Karkinos deterministic offline fixture",
            adapter_kind="deterministic_fixture",
            enabled=True,
            capabilities=("offline_research_fixture", "no_network"),
        )
    )
    registry.register_model(
        ModelRegistration(
            model_id=FIXTURE_MODEL_ID,
            provider_id=FIXTURE_PROVIDER_ID,
            model_name="deterministic-research-fixture-v1",
            enabled=True,
            purposes=("test_research_workflow",),
        )
    )
    role_specs = (
        (
            _CLAIM_ROLE_ID,
            "Fixture evidence analyst",
            "Read exact persisted evidence and state only its bounded scope.",
            tuple(CANONICAL_EVIDENCE_KINDS),
            (ArtifactKind.CLAIM,),
        ),
        (
            _DEBATE_ROLE_ID,
            "Fixture evidence critic",
            "Record deterministic competing interpretations and limitations.",
            (),
            (ArtifactKind.DEBATE,),
        ),
        (
            _REPORT_ROLE_ID,
            "Fixture research reporter",
            "Summarize fixture artifacts without investment or execution claims.",
            (),
            (ArtifactKind.REPORT,),
        ),
        (
            _MEMORY_ROLE_ID,
            "Fixture memory curator",
            "Create context-bound memory that remains subject to human review.",
            (),
            (ArtifactKind.MEMORY,),
        ),
    )
    for role_id, display_name, purpose, allowed_tools, artifact_kinds in role_specs:
        registry.register_role(
            AgentRole(
                role_id=role_id,
                display_name=display_name,
                purpose=purpose,
                allowed_tools=allowed_tools,
                allowed_artifact_kinds=artifact_kinds,
            )
        )


def _fixture_responses(
    task: ResearchTask,
    *,
    memory_source_artifact_ids: tuple[str, ...],
) -> dict[str, tuple[ProviderResponse, ...]]:
    evidence_reference_ids = tuple(item.reference_id for item in task.evidence)
    evidence_inventory = [
        {
            "tool_name": item.tool_name,
            "status": item.status,
            "authoritative": item.authoritative,
            "as_of": item.as_of,
            "evidence_reference_id": item.reference_id,
        }
        for item in task.evidence
    ]
    tool_requests = tuple(
        ToolRequest(
            request_id=f"fixture-read-{index + 1}",
            tool_name=item.tool_name,
            arguments={"evidence_reference_id": item.reference_id},
        )
        for index, item in enumerate(task.evidence)
    )
    claim = Claim(
        statement=(
            f"The accepted task binds {len(task.evidence)} complete persisted "
            "evidence records to one exact valuation and ledger identity."
        ),
        confidence="fixture_only_not_an_investment_conclusion",
        assumptions=(
            "The immutable evidence rows and context fingerprint remain unchanged.",
            "This local fixture does not infer facts beyond the cited records.",
        ),
        limitations=(
            "The output is deterministic workflow evidence, not model intelligence.",
            "A frozen snapshot does not establish future performance or trade intent.",
        ),
        evidence_reference_ids=evidence_reference_ids,
    ).to_draft()
    debate = Debate(
        topic=task.research_question,
        participant_role_ids=(_CLAIM_ROLE_ID, _DEBATE_ROLE_ID),
        positions=(
            {
                "role_id": _CLAIM_ROLE_ID,
                "position": (
                    "The exact persisted evidence is suitable for a bounded human "
                    "research review."
                ),
            },
            {
                "role_id": _DEBATE_ROLE_ID,
                "position": (
                    "The same evidence cannot justify execution, future returns, "
                    "or facts outside its snapshot and ledger cutoff."
                ),
            },
        ),
        unresolved_questions=(
            "What additional evidence would change the human conclusion?",
            "Has the valuation or ledger identity changed since capture?",
        ),
        evidence_reference_ids=evidence_reference_ids,
    ).to_draft()
    report = Report(
        title=f"Fixture review: {task.title}",
        summary=(
            "A deterministic local fixture exercised the evidence-bound research "
            "workflow. No external model ran and no investment action was inferred."
        ),
        sections=(
            {
                "heading": "Research question",
                "content": task.research_question,
            },
            {
                "heading": "Evidence inventory",
                "items": evidence_inventory,
            },
            {
                "heading": "Human next step",
                "content": (
                    "Review the cited evidence and limitations; do not treat this "
                    "fixture report as account truth, risk approval, or trade intent."
                ),
            },
        ),
        limitations=(
            "Fixture output is static and deterministic.",
            "No external provider, live market refresh, or broker connection was used.",
            "Any evidence drift invalidates this report and its memory artifact.",
        ),
        evidence_reference_ids=evidence_reference_ids,
    ).to_draft()
    memory = MemoryArtifact(
        scope=f"research-task/{task.task_id}",
        content={
            "task_title": task.title,
            "research_question": task.research_question,
            "context_snapshot_id": task.context_snapshot_id,
            "context_fingerprint": task.context_fingerprint,
            "lesson": (
                "Reuse only after a human confirms the exact context still matches."
            ),
            "human_review_required": True,
            "valid_only_for_exact_context": True,
        },
        source_artifact_ids=memory_source_artifact_ids,
        validity_status="human_review_required_and_invalid_on_evidence_drift",
        evidence_reference_ids=evidence_reference_ids,
    ).to_draft()
    return {
        "claim": (
            ProviderResponse(
                tool_requests=tool_requests,
                message="Read every exact evidence reference before fixture output.",
            ),
            ProviderResponse(
                artifacts=(claim,),
                message="Deterministic evidence-bound claim fixture.",
            ),
        ),
        "debate": (
            ProviderResponse(
                artifacts=(debate,),
                message="Deterministic bounded debate fixture.",
            ),
        ),
        "report": (
            ProviderResponse(
                artifacts=(report,),
                message="Deterministic non-authoritative report fixture.",
            ),
        ),
        "memory": (
            ProviderResponse(
                artifacts=(memory,),
                message="Context-bound memory draft requiring human review.",
            ),
        ),
    }


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


def _analysis_from_row(row: sqlite3.Row) -> ResearchTaskAnalysisRecord:
    return ResearchTaskAnalysisRecord(
        analysis_id=str(row["analysis_id"]),
        task_id=str(row["task_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_fingerprint=str(row["request_fingerprint"]),
        requested_by=str(row["requested_by"]),
        workflow_id=str(row["workflow_id"]),
        context_snapshot_id=str(row["context_snapshot_id"]),
        context_fingerprint=str(row["context_fingerprint"]),
        fixture_contract_version=str(row["fixture_contract_version"]),
        created_at=str(row["created_at"]),
    )
