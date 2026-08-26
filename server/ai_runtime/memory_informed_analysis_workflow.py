"""Deterministic workflow assembly for memory-informed fixture analysis."""

from __future__ import annotations

from server.contracts.memory_informed_analysis import (
    MEMORY_INFORMED_CLAIM_ROLE_ID,
    MEMORY_INFORMED_CLAIM_STAGE_ID,
    MEMORY_INFORMED_DEBATE_ROLE_ID,
    MEMORY_INFORMED_DEBATE_STAGE_ID,
    MEMORY_INFORMED_DEFINITION_ID,
    MEMORY_INFORMED_MODEL_ID,
    MEMORY_INFORMED_PROVIDER_ID,
    MEMORY_INFORMED_REPORT_ROLE_ID,
    MEMORY_INFORMED_REPORT_STAGE_ID,
    HumanMemoryInformedAnalysisRequest,
)

from .contracts import (
    AgentRole,
    ArtifactDraft,
    ArtifactKind,
    ModelRegistration,
    ProviderRegistration,
    StageDefinition,
    ToolRequest,
    WorkflowDefinition,
)
from .evidence import CANONICAL_EVIDENCE_KINDS
from .memory_informed_analysis_values import MemoryInformedInputs
from .provider import ProviderResponse
from .registry import AiRuntimeRegistry


def memory_informed_stage_ids() -> tuple[str, ...]:
    return (
        MEMORY_INFORMED_CLAIM_STAGE_ID,
        MEMORY_INFORMED_DEBATE_STAGE_ID,
        MEMORY_INFORMED_REPORT_STAGE_ID,
    )


def memory_informed_workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=MEMORY_INFORMED_DEFINITION_ID,
        name="Offline re-evaluation of reviewed memory with current evidence",
        stages=(
            StageDefinition(
                stage_id=MEMORY_INFORMED_CLAIM_STAGE_ID,
                role_id=MEMORY_INFORMED_CLAIM_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.CLAIM,
            ),
            StageDefinition(
                stage_id=MEMORY_INFORMED_DEBATE_STAGE_ID,
                role_id=MEMORY_INFORMED_DEBATE_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.DEBATE,
            ),
            StageDefinition(
                stage_id=MEMORY_INFORMED_REPORT_STAGE_ID,
                role_id=MEMORY_INFORMED_REPORT_ROLE_ID,
                model_id=MEMORY_INFORMED_MODEL_ID,
                output_kind=ArtifactKind.REPORT,
            ),
        ),
    )


def register_memory_informed_runtime(registry: AiRuntimeRegistry) -> None:
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
            MEMORY_INFORMED_CLAIM_ROLE_ID,
            "Current evidence re-reader",
            (
                "Read every current canonical evidence record before labelling "
                "historical reviewed memory as research input."
            ),
            tuple(CANONICAL_EVIDENCE_KINDS),
            ArtifactKind.CLAIM,
        ),
        (
            MEMORY_INFORMED_DEBATE_ROLE_ID,
            "Memory-evidence critic",
            "Contrast historical reviewed input with current evidence boundaries.",
            (),
            ArtifactKind.DEBATE,
        ),
        (
            MEMORY_INFORMED_REPORT_ROLE_ID,
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


def memory_informed_fixture_responses(
    *,
    request: HumanMemoryInformedAnalysisRequest,
    inputs: MemoryInformedInputs,
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
            "participant_role_ids": [
                MEMORY_INFORMED_CLAIM_ROLE_ID,
                MEMORY_INFORMED_DEBATE_ROLE_ID,
            ],
            "positions": [
                {
                    "role_id": MEMORY_INFORMED_CLAIM_ROLE_ID,
                    "position": (
                        "Only the newly read canonical records can support "
                        "claims about the current context."
                    ),
                },
                {
                    "role_id": MEMORY_INFORMED_DEBATE_ROLE_ID,
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
        MEMORY_INFORMED_CLAIM_STAGE_ID: (
            ProviderResponse(
                tool_requests=tool_requests,
                message="Read every current evidence record before using memory.",
            ),
            final(MEMORY_INFORMED_CLAIM_STAGE_ID, claim),
        ),
        MEMORY_INFORMED_DEBATE_STAGE_ID: (
            final(MEMORY_INFORMED_DEBATE_STAGE_ID, debate),
        ),
        MEMORY_INFORMED_REPORT_STAGE_ID: (
            final(MEMORY_INFORMED_REPORT_STAGE_ID, report),
        ),
    }
