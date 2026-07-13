"""Provider-neutral contracts for evidence-bound AI research workflows.

These contracts describe research artifacts only.  None of them carries OMS,
ledger, risk-decision, capital-authorization, or broker authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

JsonObject = dict[str, Any]


def canonical_json(value: Any) -> str:
    """Return stable JSON used by ids, audit events, and replay checks."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_fingerprint(value: Any) -> str:
    """Return a SHA-256 content fingerprint for a JSON-compatible value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class AgentRunStatus(StrEnum):
    RUNNING = "running"
    FAILED = "failed"
    PARTIAL = "partial"
    COMPLETED = "completed"


class ToolCallStatus(StrEnum):
    REQUESTED = "requested"
    DENIED = "denied"
    FAILED = "failed"
    COMPLETED = "completed"


class ArtifactKind(StrEnum):
    CLAIM = "claim"
    DEBATE = "debate"
    REPORT = "report"
    TRADE_PLAN_DRAFT = "trade_plan_draft"
    REVIEW = "review"
    MEMORY = "memory"


@dataclass(frozen=True)
class ProviderRegistration:
    provider_id: str
    display_name: str
    adapter_kind: str
    enabled: bool = False
    capabilities: tuple[str, ...] = ()
    config_schema_version: str = "karkinos.ai.provider.v1"

    def __post_init__(self) -> None:
        _require_text(self.provider_id, "provider_id")
        _require_text(self.display_name, "display_name")
        _require_text(self.adapter_kind, "adapter_kind")

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class ModelRegistration:
    model_id: str
    provider_id: str
    model_name: str
    enabled: bool = False
    purposes: tuple[str, ...] = ()
    context_window: int | None = None
    config_schema_version: str = "karkinos.ai.model.v1"

    def __post_init__(self) -> None:
        _require_text(self.model_id, "model_id")
        _require_text(self.provider_id, "provider_id")
        _require_text(self.model_name, "model_name")
        if self.context_window is not None and self.context_window <= 0:
            raise ValueError("context_window must be positive when present")

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class AgentRole:
    role_id: str
    display_name: str
    purpose: str
    allowed_tools: tuple[str, ...] = ()
    allowed_artifact_kinds: tuple[ArtifactKind, ...] = ()
    instructions_version: str = "karkinos.ai.role.v1"

    def __post_init__(self) -> None:
        _require_text(self.role_id, "role_id")
        _require_text(self.display_name, "display_name")
        _require_text(self.purpose, "purpose")

    def to_dict(self) -> JsonObject:
        payload = asdict(self)
        payload["allowed_artifact_kinds"] = [
            item.value for item in self.allowed_artifact_kinds
        ]
        return payload


@dataclass(frozen=True)
class EvidenceReference:
    reference_id: str
    kind: str
    fingerprint: str
    as_of: str
    status: str
    schema_version: str

    def __post_init__(self) -> None:
        for name in (
            "reference_id",
            "kind",
            "fingerprint",
            "as_of",
            "status",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceBoundContextSnapshot:
    snapshot_id: str
    account_alias: str
    valuation_snapshot_id: str
    ledger_cutoff_id: int
    ledger_fingerprint: str
    evidence_references: tuple[EvidenceReference, ...]
    created_at: str
    persisted_facts_only: bool = True
    schema_version: str = "karkinos.ai.evidence_context.v1"

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "account_alias",
            "valuation_snapshot_id",
            "ledger_fingerprint",
            "created_at",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.ledger_cutoff_id < 0:
            raise ValueError("ledger_cutoff_id must be non-negative")
        if not self.persisted_facts_only:
            raise ValueError("AI financial context must use persisted facts only")
        reference_ids = [item.reference_id for item in self.evidence_references]
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("evidence reference ids must be unique")

    @classmethod
    def create(
        cls,
        *,
        account_alias: str,
        valuation_snapshot_id: str,
        ledger_cutoff_id: int,
        ledger_fingerprint: str,
        evidence_references: Sequence[EvidenceReference],
        created_at: str,
    ) -> EvidenceBoundContextSnapshot:
        identity = {
            "account_alias": account_alias,
            "valuation_snapshot_id": valuation_snapshot_id,
            "ledger_cutoff_id": ledger_cutoff_id,
            "ledger_fingerprint": ledger_fingerprint,
            "evidence_references": [item.to_dict() for item in evidence_references],
            "created_at": created_at,
            "persisted_facts_only": True,
            "schema_version": "karkinos.ai.evidence_context.v1",
        }
        return cls(
            snapshot_id=f"ai-context-{content_fingerprint(identity)[:24]}",
            account_alias=account_alias,
            valuation_snapshot_id=valuation_snapshot_id,
            ledger_cutoff_id=ledger_cutoff_id,
            ledger_fingerprint=ledger_fingerprint,
            evidence_references=tuple(evidence_references),
            created_at=created_at,
        )

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict(include_snapshot_id=False))

    @property
    def evidence_reference_ids(self) -> frozenset[str]:
        return frozenset(item.reference_id for item in self.evidence_references)

    def to_dict(self, *, include_snapshot_id: bool = True) -> JsonObject:
        payload: JsonObject = {
            "account_alias": self.account_alias,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "ledger_cutoff_id": self.ledger_cutoff_id,
            "ledger_fingerprint": self.ledger_fingerprint,
            "evidence_references": [
                item.to_dict() for item in self.evidence_references
            ],
            "created_at": self.created_at,
            "persisted_facts_only": self.persisted_facts_only,
            "schema_version": self.schema_version,
        }
        if include_snapshot_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    role_id: str
    model_id: str
    output_kind: ArtifactKind
    required: bool = True

    def __post_init__(self) -> None:
        _require_text(self.stage_id, "stage_id")
        _require_text(self.role_id, "role_id")
        _require_text(self.model_id, "model_id")

    def to_dict(self) -> JsonObject:
        payload = asdict(self)
        payload["output_kind"] = self.output_kind.value
        return payload


@dataclass(frozen=True)
class WorkflowDefinition:
    definition_id: str
    name: str
    stages: tuple[StageDefinition, ...]
    schema_version: str = "karkinos.ai.workflow_definition.v1"

    def __post_init__(self) -> None:
        _require_text(self.definition_id, "definition_id")
        _require_text(self.name, "name")
        if not self.stages:
            raise ValueError("workflow definition requires at least one stage")
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("workflow stage ids must be unique")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "definition_id": self.definition_id,
            "name": self.name,
            "stages": [stage.to_dict() for stage in self.stages],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowDefinition:
        return cls(
            definition_id=str(payload["definition_id"]),
            name=str(payload["name"]),
            stages=tuple(
                StageDefinition(
                    stage_id=str(stage["stage_id"]),
                    role_id=str(stage["role_id"]),
                    model_id=str(stage["model_id"]),
                    output_kind=ArtifactKind(str(stage["output_kind"])),
                    required=bool(stage.get("required", True)),
                )
                for stage in payload["stages"]
            ),
            schema_version=str(
                payload.get("schema_version") or "karkinos.ai.workflow_definition.v1"
            ),
        )


@dataclass(frozen=True)
class ResearchWorkflow:
    workflow_id: str
    idempotency_key: str
    definition: WorkflowDefinition
    context_snapshot_id: str
    context_fingerprint: str
    status: WorkflowStatus
    current_stage_index: int
    partial_result: bool
    failure_code: str | None
    created_at: str
    updated_at: str

    @property
    def complete(self) -> bool:
        return self.status == WorkflowStatus.COMPLETED


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    workflow_id: str
    stage_id: str
    role_id: str
    model_id: str
    provider_id: str
    status: AgentRunStatus
    request_fingerprint: str
    response_fingerprint: str | None
    error_code: str | None
    started_at: str
    finished_at: str | None


@dataclass(frozen=True)
class ToolRequest:
    request_id: str
    tool_name: str
    arguments: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.request_id, "request_id")
        _require_text(self.tool_name, "tool_name")

    def to_dict(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
        }


@dataclass(frozen=True)
class ToolExecutionResult:
    request_id: str
    tool_name: str
    output: JsonObject

    def to_dict(self) -> JsonObject:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "output": dict(self.output),
        }


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    run_id: str
    workflow_id: str
    stage_id: str
    role_id: str
    tool_name: str
    status: ToolCallStatus
    arguments: JsonObject
    result: JsonObject | None
    denial_reason: str | None
    created_at: str
    completed_at: str | None


@dataclass(frozen=True)
class ArtifactDraft:
    kind: ArtifactKind
    content: JsonObject
    evidence_reference_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.evidence_reference_ids:
            raise ValueError("AI artifacts must cite at least one evidence reference")
        if len(self.evidence_reference_ids) != len(set(self.evidence_reference_ids)):
            raise ValueError("artifact evidence references must be unique")

    def to_dict(self) -> JsonObject:
        return {
            "kind": self.kind.value,
            "content": dict(self.content),
            "evidence_reference_ids": list(self.evidence_reference_ids),
        }


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    workflow_id: str
    run_id: str
    stage_id: str
    role_id: str
    kind: ArtifactKind
    content: JsonObject
    evidence_reference_ids: tuple[str, ...]
    fingerprint: str
    created_at: str


@dataclass(frozen=True)
class Claim:
    statement: str
    confidence: str
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.CLAIM,
            content={
                "statement": self.statement,
                "confidence": self.confidence,
                "assumptions": list(self.assumptions),
                "limitations": list(self.limitations),
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )


@dataclass(frozen=True)
class Debate:
    topic: str
    participant_role_ids: tuple[str, ...]
    positions: tuple[JsonObject, ...]
    unresolved_questions: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.DEBATE,
            content={
                "topic": self.topic,
                "participant_role_ids": list(self.participant_role_ids),
                "positions": [dict(item) for item in self.positions],
                "unresolved_questions": list(self.unresolved_questions),
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )


@dataclass(frozen=True)
class Report:
    title: str
    summary: str
    sections: tuple[JsonObject, ...]
    limitations: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.REPORT,
            content={
                "title": self.title,
                "summary": self.summary,
                "sections": [dict(item) for item in self.sections],
                "limitations": list(self.limitations),
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )


@dataclass(frozen=True)
class TradePlanDraft:
    thesis: str
    candidate_actions: tuple[JsonObject, ...]
    assumptions: tuple[str, ...]
    risk_notes: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]
    requires_human_review: bool = True
    executable: bool = False
    authority_effect: str = "none"

    def __post_init__(self) -> None:
        if not self.requires_human_review or self.executable:
            raise ValueError("AI trade-plan drafts must be non-executable and reviewed")
        if self.authority_effect != "none":
            raise ValueError("AI trade-plan drafts cannot change execution authority")

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.TRADE_PLAN_DRAFT,
            content={
                "thesis": self.thesis,
                "candidate_actions": [dict(item) for item in self.candidate_actions],
                "assumptions": list(self.assumptions),
                "risk_notes": list(self.risk_notes),
                "requires_human_review": self.requires_human_review,
                "executable": self.executable,
                "authority_effect": self.authority_effect,
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )


@dataclass(frozen=True)
class Review:
    decision: str
    reviewer_type: str
    notes: str
    reviewed_artifact_ids: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]
    does_not_enable_execution: bool = True

    def __post_init__(self) -> None:
        if not self.does_not_enable_execution:
            raise ValueError("AI review artifacts cannot enable execution")

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.REVIEW,
            content={
                "decision": self.decision,
                "reviewer_type": self.reviewer_type,
                "notes": self.notes,
                "reviewed_artifact_ids": list(self.reviewed_artifact_ids),
                "does_not_enable_execution": self.does_not_enable_execution,
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )


@dataclass(frozen=True)
class MemoryArtifact:
    scope: str
    content: JsonObject
    source_artifact_ids: tuple[str, ...]
    validity_status: str
    evidence_reference_ids: tuple[str, ...]
    authority_effect: str = "none"

    def __post_init__(self) -> None:
        if self.authority_effect != "none":
            raise ValueError("memory artifacts cannot change execution authority")

    def to_draft(self) -> ArtifactDraft:
        return ArtifactDraft(
            kind=ArtifactKind.MEMORY,
            content={
                "scope": self.scope,
                "content": dict(self.content),
                "source_artifact_ids": list(self.source_artifact_ids),
                "validity_status": self.validity_status,
                "authority_effect": self.authority_effect,
            },
            evidence_reference_ids=self.evidence_reference_ids,
        )
