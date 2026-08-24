"""Runtime identity and deterministic workflow definition for external analysis."""

from __future__ import annotations

from server.contracts.external_memory_analysis import (
    EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID,
    EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
    EXTERNAL_MEMORY_CLAIM_ROLE_ID,
    EXTERNAL_MEMORY_CLAIM_STAGE_ID,
    EXTERNAL_MEMORY_DEBATE_ROLE_ID,
    EXTERNAL_MEMORY_DEBATE_STAGE_ID,
    EXTERNAL_MEMORY_REPORT_ROLE_ID,
    EXTERNAL_MEMORY_REPORT_STAGE_ID,
)

from .contracts import (
    AgentRole,
    ArtifactKind,
    ModelRegistration,
    ProviderRegistration,
    StageDefinition,
    WorkflowDefinition,
    content_fingerprint,
)
from .evidence import CANONICAL_EVIDENCE_KINDS
from .provider_connectivity import ProviderConnectivitySettings
from .registry import AiRuntimeRegistry


def external_memory_workflow_definition(model_id: str) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=EXTERNAL_MEMORY_ANALYSIS_DEFINITION_ID,
        name="External review of historical memory against current evidence",
        stages=tuple(
            StageDefinition(
                stage_id=stage_id,
                role_id=role_id,
                model_id=model_id,
                output_kind=kind,
            )
            for stage_id, role_id, kind in (
                (
                    EXTERNAL_MEMORY_CLAIM_STAGE_ID,
                    EXTERNAL_MEMORY_CLAIM_ROLE_ID,
                    ArtifactKind.CLAIM,
                ),
                (
                    EXTERNAL_MEMORY_DEBATE_STAGE_ID,
                    EXTERNAL_MEMORY_DEBATE_ROLE_ID,
                    ArtifactKind.DEBATE,
                ),
                (
                    EXTERNAL_MEMORY_REPORT_STAGE_ID,
                    EXTERNAL_MEMORY_REPORT_ROLE_ID,
                    ArtifactKind.REPORT,
                ),
            )
        ),
    )


def register_external_memory_runtime(
    registry: AiRuntimeRegistry,
    *,
    settings: ProviderConnectivitySettings,
    provider_id: str,
    model_id: str,
) -> None:
    registry.register_provider(
        ProviderRegistration(
            provider_id=provider_id,
            display_name=(
                f"{settings.provider_id} external memory-informed research edge"
            ),
            adapter_kind=settings.adapter_kind,
            enabled=True,
            capabilities=(
                "human_started_memory_informed_claim_debate_report",
                "local_current_evidence_tools_required",
                "provider_side_tools_disabled",
                "no_trade_authority",
            ),
        )
    )
    registry.register_model(
        ModelRegistration(
            model_id=model_id,
            provider_id=provider_id,
            model_name=settings.model_name,
            enabled=True,
            purposes=("human_started_memory_informed_research",),
        )
    )
    for role_id, name, purpose, kind in (
        (
            EXTERNAL_MEMORY_CLAIM_ROLE_ID,
            "External current-evidence analyst",
            "Form cited hypotheses after rereading all current canonical evidence.",
            ArtifactKind.CLAIM,
        ),
        (
            EXTERNAL_MEMORY_DEBATE_ROLE_ID,
            "External evidence critic",
            "Challenge current claims and historical assumptions with exact evidence.",
            ArtifactKind.DEBATE,
        ),
        (
            EXTERNAL_MEMORY_REPORT_ROLE_ID,
            "External evidence-bound reporter",
            "Synthesize a non-authoritative report requiring human review.",
            ArtifactKind.REPORT,
        ),
    ):
        registry.register_role(
            AgentRole(
                role_id=role_id,
                display_name=name,
                purpose=purpose,
                allowed_tools=tuple(CANONICAL_EVIDENCE_KINDS),
                allowed_artifact_kinds=(kind,),
                instructions_version=EXTERNAL_MEMORY_ANALYSIS_PROMPT_VERSION,
            )
        )


def external_memory_runtime_ids(
    settings: ProviderConnectivitySettings,
) -> tuple[str, str]:
    provider_fingerprint = content_fingerprint(
        {
            "provider_id": settings.provider_id,
            "adapter_kind": settings.adapter_kind,
            "endpoint_origin": settings.endpoint_origin,
        }
    )[:16]
    model_fingerprint = content_fingerprint(
        {
            "provider_fingerprint": provider_fingerprint,
            "model_name": settings.model_name,
        }
    )[:16]
    provider_id = f"karkinos.external_memory.provider.{provider_fingerprint}.v1"
    return provider_id, f"karkinos.external_memory.model.{model_fingerprint}.v1"


def external_memory_stage_focus(stage_id: str) -> str:
    return {
        EXTERNAL_MEMORY_CLAIM_STAGE_ID: (
            "先区分当前事实与历史假设，再形成少量由当前证据直接支持的研究判断；"
            "明确哪些历史假设仍待验证，不给出交易结论。"
        ),
        EXTERNAL_MEMORY_DEBATE_STAGE_ID: (
            "逐条质疑上一阶段判断，寻找反证、口径冲突、未解释残差和合理替代解释；"
            "所有反方观点仍须引用当前证据。"
        ),
        EXTERNAL_MEMORY_REPORT_STAGE_ID: (
            "综合判断与反方观点，形成审慎的研究报告；保留未解决问题，并给出可重复、"
            "只读、不会改变财务状态的后续验证。"
        ),
    }[stage_id]


def external_memory_stage_artifact_kind(stage_id: str) -> ArtifactKind:
    return {
        EXTERNAL_MEMORY_CLAIM_STAGE_ID: ArtifactKind.CLAIM,
        EXTERNAL_MEMORY_DEBATE_STAGE_ID: ArtifactKind.DEBATE,
        EXTERNAL_MEMORY_REPORT_STAGE_ID: ArtifactKind.REPORT,
    }[stage_id]
