"""Deterministic offline fixture definition for research-task analysis."""

from __future__ import annotations

from .contracts import (
    AgentRole,
    ArtifactKind,
    Claim,
    Debate,
    MemoryArtifact,
    ModelRegistration,
    ProviderRegistration,
    Report,
    StageDefinition,
    ToolRequest,
    WorkflowDefinition,
)
from .evidence import CANONICAL_EVIDENCE_KINDS
from .provider import ProviderResponse
from .registry import AiRuntimeRegistry
from .tasks import ResearchTask

FIXTURE_PROVIDER_ID = "karkinos.fixture.offline.v1"
FIXTURE_MODEL_ID = "karkinos.fixture.research.v1"
FIXTURE_DEFINITION_ID = "karkinos.fixture.task_analysis.v1"
MEMORY_STAGE_INDEX = 3

_CLAIM_ROLE_ID = "fixture.evidence_analyst.v1"
_DEBATE_ROLE_ID = "fixture.evidence_critic.v1"
_REPORT_ROLE_ID = "fixture.research_reporter.v1"
_MEMORY_ROLE_ID = "fixture.memory_curator.v1"


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


fixture_definition = _fixture_definition
register_fixture_runtime = _register_fixture_runtime
fixture_responses = _fixture_responses
