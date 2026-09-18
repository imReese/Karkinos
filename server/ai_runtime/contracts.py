"""Provider-neutral contracts for evidence-bound AI research workflows.

These contracts describe research artifacts only.  None of them carries OMS,
ledger, risk-decision, capital-authorization, or broker authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from server.contracts.content_identity import canonical_json, content_fingerprint

JsonObject = dict[str, Any]


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
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIAL = "partial"
    COMPLETED = "completed"


class ToolCallStatus(StrEnum):
    REQUESTED = "requested"
    DENIED = "denied"
    FAILED = "failed"
    COMPLETED = "completed"


class AIResearchCapability(StrEnum):
    """Bounded AI capabilities. Capital execution is deliberately absent."""

    OBSERVE = "observe"
    EXPLAIN = "explain"
    INVESTIGATE = "investigate"
    PROPOSE = "propose"
    ORCHESTRATE_RESEARCH = "orchestrate_research"

    @property
    def level(self) -> int:
        return {
            AIResearchCapability.OBSERVE: 0,
            AIResearchCapability.EXPLAIN: 1,
            AIResearchCapability.INVESTIGATE: 2,
            AIResearchCapability.PROPOSE: 3,
            AIResearchCapability.ORCHESTRATE_RESEARCH: 4,
        }[self]

    def allows(self, required: AIResearchCapability) -> bool:
        return self.level >= required.level


class ResearchClaimSupportStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    MIXED = "mixed"
    UNRESOLVED = "unresolved"


class ResearchSelectionDecision(StrEnum):
    SELECTED_FOR_FURTHER_RESEARCH = "selected_for_further_research"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class ResearchSelectionSource(StrEnum):
    HUMAN = "human"
    DETERMINISTIC_RULE = "deterministic_rule"


class ResearchRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class ArtifactKind(StrEnum):
    CLAIM = "claim"
    DEBATE = "debate"
    REPORT = "report"
    TRADE_PLAN_DRAFT = "trade_plan_draft"
    REVIEW = "review"
    MEMORY = "memory"


@dataclass(frozen=True)
class ResearchBudget:
    max_candidates: int
    max_iterations: int
    max_backtests: int
    max_parameter_variants: int
    max_provider_calls: int
    max_external_searches: int
    schema_version: str = "karkinos.ai.research_budget.v1"

    def __post_init__(self) -> None:
        positive = {
            "max_candidates": self.max_candidates,
            "max_iterations": self.max_iterations,
            "max_backtests": self.max_backtests,
        }
        non_negative = {
            "max_parameter_variants": self.max_parameter_variants,
            "max_provider_calls": self.max_provider_calls,
            "max_external_searches": self.max_external_searches,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name, value in non_negative.items():
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        _require_text(self.schema_version, "schema_version")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True)
class ResearchHypothesis:
    hypothesis_id: str
    task_id: str
    thesis: str
    mechanism: str
    baseline_reference: str
    expected_regime: str
    falsification_conditions: tuple[str, ...]
    required_evidence: tuple[str, ...]
    source_trace_id: str | None = None
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.research_hypothesis.v1"

    def __post_init__(self) -> None:
        for name in (
            "hypothesis_id",
            "task_id",
            "thesis",
            "mechanism",
            "baseline_reference",
            "expected_regime",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if not self.falsification_conditions:
            raise ValueError(
                "formal research hypotheses require falsification conditions"
            )
        if any(not item.strip() for item in self.falsification_conditions):
            raise ValueError("falsification conditions must not be empty")
        if len(self.falsification_conditions) != len(
            set(self.falsification_conditions)
        ):
            raise ValueError("falsification conditions must be unique")
        if not self.required_evidence:
            raise ValueError("formal research hypotheses require evidence requirements")
        if any(not item.strip() for item in self.required_evidence):
            raise ValueError("required evidence entries must not be empty")
        if len(self.required_evidence) != len(set(self.required_evidence)):
            raise ValueError("required evidence entries must be unique")
        if self.authority_effect != "none":
            raise ValueError("research hypotheses cannot change execution authority")
        if self.source_trace_id is not None:
            _require_text(self.source_trace_id, "source_trace_id")

    def to_dict(self) -> JsonObject:
        return {
            "hypothesis_id": self.hypothesis_id,
            "task_id": self.task_id,
            "thesis": self.thesis,
            "mechanism": self.mechanism,
            "baseline_reference": self.baseline_reference,
            "expected_regime": self.expected_regime,
            "falsification_conditions": list(self.falsification_conditions),
            "required_evidence": list(self.required_evidence),
            "source_trace_id": self.source_trace_id,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchClaim:
    claim_id: str
    task_id: str
    run_id: str
    statement: str
    claim_type: str
    evidence_reference_ids: tuple[str, ...]
    support_status: ResearchClaimSupportStatus
    as_of: str
    source_trace_id: str | None = None
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.research_claim.v1"

    def __post_init__(self) -> None:
        for name in (
            "claim_id",
            "task_id",
            "run_id",
            "statement",
            "claim_type",
            "as_of",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if not self.evidence_reference_ids:
            raise ValueError("research claims must cite evidence")
        if len(self.evidence_reference_ids) != len(set(self.evidence_reference_ids)):
            raise ValueError("research claim evidence references must be unique")
        if any(not item.strip() for item in self.evidence_reference_ids):
            raise ValueError("research claim evidence references must not be empty")
        if self.authority_effect != "none":
            raise ValueError("research claims cannot change execution authority")
        if self.source_trace_id is not None:
            _require_text(self.source_trace_id, "source_trace_id")

    def to_dict(self) -> JsonObject:
        return {
            "claim_id": self.claim_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "statement": self.statement,
            "claim_type": self.claim_type,
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "support_status": self.support_status.value,
            "as_of": self.as_of,
            "source_trace_id": self.source_trace_id,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AITrace:
    trace_id: str
    task_id: str
    run_id: str
    capability: AIResearchCapability
    provider_id: str
    model_id: str
    prompt_version: str
    input_artifact_ids: tuple[str, ...]
    evidence_reference_ids: tuple[str, ...]
    tool_names: tuple[str, ...]
    started_at: str
    finished_at: str | None = None
    token_usage: int | None = None
    raw_output_fingerprint: str | None = None
    parsed_output_fingerprint: str | None = None
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.trace.v1"

    def __post_init__(self) -> None:
        for name in (
            "trace_id",
            "task_id",
            "run_id",
            "provider_id",
            "model_id",
            "prompt_version",
            "started_at",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        for name, values in (
            ("input_artifact_ids", self.input_artifact_ids),
            ("evidence_reference_ids", self.evidence_reference_ids),
            ("tool_names", self.tool_names),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            if any(not value.strip() for value in values):
                raise ValueError(f"{name} must not contain empty values")
        if self.finished_at is not None:
            _require_text(self.finished_at, "finished_at")
        if self.token_usage is not None and self.token_usage < 0:
            raise ValueError("token_usage must be non-negative")
        for name in ("raw_output_fingerprint", "parsed_output_fingerprint"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if self.authority_effect != "none":
            raise ValueError("AI traces cannot change execution authority")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "capability": self.capability.value,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "input_artifact_ids": list(self.input_artifact_ids),
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "tool_names": list(self.tool_names),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "token_usage": self.token_usage,
            "raw_output_fingerprint": self.raw_output_fingerprint,
            "parsed_output_fingerprint": self.parsed_output_fingerprint,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchRun:
    run_id: str
    task_id: str | None
    task_binding_status: str
    research_question: str
    status: ResearchRunStatus
    selection_fingerprint: str
    context_snapshot_id: str | None
    context_fingerprint: str | None
    workflow_id: str | None
    workflow_status: str | None
    research_budget: ResearchBudget | None
    provider_id: str | None
    model_id: str | None
    prompt_version: str
    created_at: str
    updated_at: str
    requires_deterministic_evaluation: bool = True
    requires_human_selection: bool = True
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.research_run.v1"

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "task_binding_status",
            "research_question",
            "selection_fingerprint",
            "prompt_version",
            "created_at",
            "updated_at",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.task_binding_status not in {"bound", "legacy_unbound"}:
            raise ValueError("task_binding_status invalid")
        if (self.task_id is None) != (self.task_binding_status == "legacy_unbound"):
            raise ValueError("task binding status does not match task id")
        if self.task_id is not None:
            _require_text(self.task_id, "task_id")
        if (self.context_snapshot_id is None) != (self.context_fingerprint is None):
            raise ValueError("research run context binding must be complete")
        if self.context_snapshot_id is not None:
            _require_text(self.context_snapshot_id, "context_snapshot_id")
            _require_text(self.context_fingerprint, "context_fingerprint")
        if self.workflow_status is not None and self.workflow_id is None:
            raise ValueError("workflow status requires workflow identity")
        if self.workflow_id is not None:
            _require_text(self.workflow_id, "workflow_id")
        if self.workflow_status is not None:
            _require_text(self.workflow_status, "workflow_status")
        if (self.provider_id is None) != (self.model_id is None):
            raise ValueError("provider and model identity must be bound together")
        if self.provider_id is not None:
            _require_text(self.provider_id, "provider_id")
            _require_text(self.model_id, "model_id")
        if not self.requires_deterministic_evaluation:
            raise ValueError("research runs require deterministic evaluation")
        if not self.requires_human_selection:
            raise ValueError("research runs require human research selection")
        if self.authority_effect != "none":
            raise ValueError("research runs cannot change execution authority")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_binding_status": self.task_binding_status,
            "research_question": self.research_question,
            "status": self.status.value,
            "selection_fingerprint": self.selection_fingerprint,
            "context_snapshot_id": self.context_snapshot_id,
            "context_fingerprint": self.context_fingerprint,
            "workflow_id": self.workflow_id,
            "workflow_status": self.workflow_status,
            "research_budget": (
                self.research_budget.to_dict()
                if self.research_budget is not None
                else None
            ),
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "requires_deterministic_evaluation": self.requires_deterministic_evaluation,
            "requires_human_selection": self.requires_human_selection,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchEvaluationBundle:
    evaluation_id: str
    backtest_result_id: int
    source_fingerprint: str
    dataset_snapshot_id: str | None
    research_gate_status: str
    research_evidence_bundle: JsonObject
    oos_validation: JsonObject
    after_cost_evidence: JsonObject
    cost_summary: JsonObject
    parameter_robustness: JsonObject
    market_regime_robustness: JsonObject
    capacity_review: JsonObject
    drawdown_evidence: JsonObject
    signal_execution_evidence: JsonObject
    lot_feasibility_evidence: JsonObject
    missing_evidence: tuple[str, ...]
    persisted_source_only: bool = True
    deterministic: bool = True
    ai_generated: bool = False
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.research_evaluation_bundle.v1"

    def __post_init__(self) -> None:
        for name in (
            "evaluation_id",
            "source_fingerprint",
            "research_gate_status",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.backtest_result_id <= 0:
            raise ValueError("backtest_result_id must be positive")
        if self.dataset_snapshot_id is not None:
            _require_text(self.dataset_snapshot_id, "dataset_snapshot_id")
        if len(self.missing_evidence) != len(set(self.missing_evidence)):
            raise ValueError("missing_evidence must be unique")
        if any(not item.strip() for item in self.missing_evidence):
            raise ValueError("missing_evidence must not contain empty values")
        if not self.persisted_source_only:
            raise ValueError("research evaluation must use persisted sources only")
        if not self.deterministic:
            raise ValueError("research evaluation must remain deterministic")
        if self.ai_generated:
            raise ValueError("AI cannot generate canonical evaluation bundles")
        if self.authority_effect != "none":
            raise ValueError("research evaluation cannot change execution authority")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "evaluation_id": self.evaluation_id,
            "backtest_result_id": self.backtest_result_id,
            "source_fingerprint": self.source_fingerprint,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "research_gate_status": self.research_gate_status,
            "research_evidence_bundle": dict(self.research_evidence_bundle),
            "oos_validation": dict(self.oos_validation),
            "after_cost_evidence": dict(self.after_cost_evidence),
            "cost_summary": dict(self.cost_summary),
            "parameter_robustness": dict(self.parameter_robustness),
            "market_regime_robustness": dict(self.market_regime_robustness),
            "capacity_review": dict(self.capacity_review),
            "drawdown_evidence": dict(self.drawdown_evidence),
            "signal_execution_evidence": dict(self.signal_execution_evidence),
            "lot_feasibility_evidence": dict(self.lot_feasibility_evidence),
            "missing_evidence": list(self.missing_evidence),
            "persisted_source_only": self.persisted_source_only,
            "deterministic": self.deterministic,
            "ai_generated": self.ai_generated,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ResearchSelection:
    selection_id: str
    session_id: str
    task_id: str | None
    task_binding_status: str
    candidate_id: str
    critique_id: str
    evaluation_id: str
    evaluation_fingerprint: str
    evaluation_gate_status: str
    decision: ResearchSelectionDecision
    source: ResearchSelectionSource
    reviewer: str | None
    notes: str
    created_at: str
    requires_human_promotion: bool = True
    ai_generated: bool = False
    authority_effect: str = "none"
    schema_version: str = "karkinos.ai.research_selection.v1"

    def __post_init__(self) -> None:
        for name in (
            "selection_id",
            "session_id",
            "task_binding_status",
            "candidate_id",
            "critique_id",
            "evaluation_id",
            "evaluation_fingerprint",
            "evaluation_gate_status",
            "notes",
            "created_at",
            "schema_version",
        ):
            _require_text(str(getattr(self, name)), name)
        if self.task_id is not None:
            _require_text(self.task_id, "task_id")
        if self.task_binding_status not in {"bound", "legacy_unbound"}:
            raise ValueError("task_binding_status invalid")
        if (self.task_id is None) != (self.task_binding_status == "legacy_unbound"):
            raise ValueError("task binding status does not match task id")
        if self.source == ResearchSelectionSource.HUMAN:
            if self.reviewer is None:
                raise ValueError("human research selection requires reviewer")
            _require_text(self.reviewer, "reviewer")
        elif self.reviewer is not None:
            raise ValueError("deterministic research selection cannot claim reviewer")
        if not self.requires_human_promotion:
            raise ValueError("research selection cannot bypass human promotion")
        if self.ai_generated:
            raise ValueError("AI cannot create canonical research selection")
        if self.authority_effect != "none":
            raise ValueError("research selection cannot change execution authority")

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> JsonObject:
        return {
            "selection_id": self.selection_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "task_binding_status": self.task_binding_status,
            "candidate_id": self.candidate_id,
            "critique_id": self.critique_id,
            "evaluation_id": self.evaluation_id,
            "evaluation_fingerprint": self.evaluation_fingerprint,
            "evaluation_gate_status": self.evaluation_gate_status,
            "decision": self.decision.value,
            "source": self.source.value,
            "reviewer": self.reviewer,
            "notes": self.notes,
            "created_at": self.created_at,
            "requires_human_promotion": self.requires_human_promotion,
            "ai_generated": self.ai_generated,
            "authority_effect": self.authority_effect,
            "schema_version": self.schema_version,
        }


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
    capability: AIResearchCapability
    allowed_tools: tuple[str, ...] = ()
    allowed_artifact_kinds: tuple[ArtifactKind, ...] = ()
    instructions_version: str = "karkinos.ai.role.v1"

    def __post_init__(self) -> None:
        _require_text(self.role_id, "role_id")
        _require_text(self.display_name, "display_name")
        _require_text(self.purpose, "purpose")

    def to_dict(self) -> JsonObject:
        payload = asdict(self)
        payload["capability"] = self.capability.value
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
    research_budget: ResearchBudget | None = None
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
        payload: JsonObject = {
            "definition_id": self.definition_id,
            "name": self.name,
            "stages": [stage.to_dict() for stage in self.stages],
            "schema_version": self.schema_version,
        }
        if self.research_budget is not None:
            payload["research_budget"] = self.research_budget.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowDefinition:
        budget_payload = payload.get("research_budget")
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
            research_budget=(
                ResearchBudget(
                    max_candidates=int(budget_payload["max_candidates"]),
                    max_iterations=int(budget_payload["max_iterations"]),
                    max_backtests=int(budget_payload["max_backtests"]),
                    max_parameter_variants=int(
                        budget_payload["max_parameter_variants"]
                    ),
                    max_provider_calls=int(budget_payload["max_provider_calls"]),
                    max_external_searches=int(budget_payload["max_external_searches"]),
                    schema_version=str(
                        budget_payload.get("schema_version")
                        or "karkinos.ai.research_budget.v1"
                    ),
                )
                if isinstance(budget_payload, Mapping)
                else None
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
