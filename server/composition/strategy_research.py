"""Composition of provider-neutral strategy research workflows and permissions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from server.ai_runtime.contracts import (
    AgentRole,
    ArtifactKind,
    ModelRegistration,
    ProviderRegistration,
    StageDefinition,
    WorkflowDefinition,
)
from server.ai_runtime.evidence import (
    CanonicalEvidenceRepository,
    CanonicalEvidenceToolExecutors,
)
from server.ai_runtime.formula_dsl import formula_operator_catalog
from server.ai_runtime.orchestrator import DeterministicWorkflowOrchestrator
from server.ai_runtime.permissions import (
    ToolEffect,
    ToolPermission,
    default_tool_permission_registry,
)
from server.ai_runtime.provider import ProviderAdapter
from server.ai_runtime.provider_connectivity import ProviderConnectivitySettings
from server.ai_runtime.registry import AiRuntimeRegistry
from server.ai_runtime.store import AiAuditStore
from server.ai_runtime.strategy_research_values import (
    ACCOUNT_STATE_TOOL,
    CATALOG_TOOL,
    CRITIQUE_ROLE,
    CRITIQUE_STAGE,
    HYPOTHESIS_ROLE,
    HYPOTHESIS_STAGE,
    RESEARCH_TOOL,
    SELECTION_TOOL,
    STRATEGY_RESEARCH_PROMPT_VERSION,
)
from server.contracts.strategy_research import StrategyResearchSelection


def build_strategy_research_orchestrator(
    *,
    ai_store: AiAuditStore,
    registry: AiRuntimeRegistry,
    provider: ProviderAdapter,
    evidence_repository: CanonicalEvidenceRepository,
    selection: StrategyResearchSelection,
    now: Callable[[], str],
    execution_guard: Callable[[], None] | None = None,
) -> DeterministicWorkflowOrchestrator:
    permissions = default_tool_permission_registry()
    permissions.register(
        ToolPermission(
            CATALOG_TOOL,
            ToolEffect.PURE_COMPUTE,
            False,
            "Read the reviewed in-process Formula DSL operator catalog.",
        )
    )
    permissions.register(
        ToolPermission(
            SELECTION_TOOL,
            ToolEffect.PURE_COMPUTE,
            False,
            "Read the immutable operator-selected research binding.",
        )
    )
    executors = CanonicalEvidenceToolExecutors(evidence_repository).as_mapping()
    executors.update(
        {
            CATALOG_TOOL: lambda arguments, context: formula_operator_catalog(),
            SELECTION_TOOL: lambda arguments, context: selection.to_external_dict(),
        }
    )
    return DeterministicWorkflowOrchestrator(
        store=ai_store,
        registry=registry,
        permissions=permissions,
        providers={provider.provider_id: provider},
        tool_executors=executors,
        now=now,
        max_provider_turns=2,
        execution_guard=execution_guard,
    )


def strategy_research_runtime_ids(
    settings: ProviderConnectivitySettings, mode: str
) -> tuple[str, str]:
    provider_id = f"karkinos.strategy_research.{mode}.{settings.provider_id}.v1"
    return provider_id, f"{provider_id}:{settings.model_name}"


def register_strategy_research_runtime(
    registry: AiRuntimeRegistry,
    settings: ProviderConnectivitySettings,
    provider_id: str,
    model_id: str,
    mode: Literal["hypothesis", "critique"],
) -> None:
    role_id = HYPOTHESIS_ROLE if mode == "hypothesis" else CRITIQUE_ROLE
    registry.register_provider(
        ProviderRegistration(
            provider_id=provider_id,
            display_name=f"{settings.provider_id} strategy research edge",
            adapter_kind=settings.adapter_kind,
            enabled=True,
            capabilities=(
                f"strategy_{mode}",
                "provider_side_tools_disabled",
                "raw_reasoning_not_persisted",
            ),
        )
    )
    registry.register_model(
        ModelRegistration(
            model_id=model_id,
            provider_id=provider_id,
            model_name=settings.model_name,
            enabled=True,
            purposes=(f"human_started_strategy_{mode}",),
        )
    )
    registry.register_role(
        AgentRole(
            role_id=role_id,
            display_name=(
                "Strategy hypothesis researcher"
                if mode == "hypothesis"
                else "Canonical backtest evidence critic"
            ),
            purpose=(
                "Propose or critique non-executable research hypotheses using only "
                "bound evidence and the local Formula DSL; never create authority."
            ),
            allowed_tools=(
                (
                    RESEARCH_TOOL,
                    ACCOUNT_STATE_TOOL,
                    CATALOG_TOOL,
                    SELECTION_TOOL,
                )
                if mode == "hypothesis"
                else (RESEARCH_TOOL, CATALOG_TOOL, SELECTION_TOOL)
            ),
            allowed_artifact_kinds=(ArtifactKind.REPORT,),
            instructions_version=STRATEGY_RESEARCH_PROMPT_VERSION,
        )
    )


def strategy_research_workflow_definition(
    model_id: str, mode: Literal["hypothesis", "critique"]
) -> WorkflowDefinition:
    return WorkflowDefinition(
        definition_id=f"karkinos.strategy_research.{mode}.v1",
        name=f"Human-started evidence-bound strategy {mode}",
        stages=(
            StageDefinition(
                stage_id=HYPOTHESIS_STAGE if mode == "hypothesis" else CRITIQUE_STAGE,
                role_id=HYPOTHESIS_ROLE if mode == "hypothesis" else CRITIQUE_ROLE,
                model_id=model_id,
                output_kind=ArtifactKind.REPORT,
            ),
        ),
    )
