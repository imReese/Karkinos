"""Strict short-ID citation catalog and bound-path resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from server.ai_runtime.contracts import JsonObject, canonical_json, content_fingerprint
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
)
from server.ai_runtime.strategy_research_values import CRITIQUE_CITATION_PATHS
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_MAX_CITATION_CATALOG_BYTES,
    STRATEGY_RESEARCH_MAX_CITATION_PATHS,
    StrategyResearchRejected,
)


def build_hypothesis_citation_catalog(
    sources: Mapping[str, Any],
) -> dict[str, str]:
    """Bind short model-facing IDs to exact paths in the exported JSON."""
    paths: list[str] = []

    def visit(value: Any, path: str) -> None:
        if path:
            paths.append(path)
        if isinstance(value, Mapping):
            for key in sorted(str(item) for item in value):
                if not key or any(char in key for char in ".[]"):
                    raise StrategyResearchRejected(
                        "strategy_research_citation_source_key_unrepresentable"
                    )
                visit(value[key], f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    for source_name in sorted(sources):
        source = sources[source_name]
        if source is not None:
            visit(source, source_name)
    unique_paths = sorted(
        path for path in set(paths) if citation_path_exists(path, sources)
    )
    if not unique_paths:
        raise StrategyResearchRejected("strategy_research_citation_catalog_empty")
    if len(unique_paths) > STRATEGY_RESEARCH_MAX_CITATION_PATHS:
        raise StrategyResearchRejected("strategy_research_citation_catalog_too_large")
    catalog: dict[str, str] = {}
    for path in unique_paths:
        citation_id = "cite_" + content_fingerprint({"path": path})[:16]
        existing = catalog.get(citation_id)
        if existing is not None and existing != path:
            raise StrategyResearchRejected(
                "strategy_research_citation_catalog_collision"
            )
        catalog[citation_id] = path
    if (
        len(canonical_json(catalog).encode("utf-8"))
        > STRATEGY_RESEARCH_MAX_CITATION_CATALOG_BYTES
    ):
        raise StrategyResearchRejected("strategy_research_citation_catalog_too_large")
    return catalog


def compact_hypothesis_citation_catalog(
    *,
    citation_sources: Mapping[str, Any],
) -> dict[str, str]:
    """Expose only the deterministic evidence anchors required by the model."""
    path_groups = (
        (
            "saved_backtest_evidence.performance_summary",
            "saved_backtest_evidence",
        ),
        (
            "operator_frozen_selection.dataset_snapshot_id",
            "operator_frozen_selection",
        ),
        (
            "operator_frozen_selection.cost_model_reference",
            "operator_frozen_selection",
        ),
        (
            "saved_account_evidence.summary.cash_ratio",
            "saved_account_evidence",
        ),
        (
            "iteration_context.parent_iteration.parent_artifact_fingerprint",
            "iteration_context.parent_iteration",
            "iteration_context.context_fingerprint",
            "iteration_context",
        ),
    )
    selected_paths: list[str] = []
    for alternatives in path_groups:
        selected = next(
            (
                path
                for path in alternatives
                if citation_path_exists(path, citation_sources)
            ),
            None,
        )
        if selected is not None and selected not in selected_paths:
            selected_paths.append(selected)
    if not selected_paths:
        raise StrategyResearchRejected("strategy_research_citation_catalog_empty")
    return {
        f"cite_{index:02d}": path for index, path in enumerate(selected_paths, start=1)
    }


def build_critique_citation_catalog(
    critique_input: Mapping[str, Any],
) -> dict[str, str]:
    """Expose a small exact citation set for the bound critique payload."""
    sources = {"critique_input": critique_input}
    path_groups = (
        ("critique_input.canonical_backtest.total_return",),
        ("critique_input.canonical_backtest.max_drawdown",),
        (
            "critique_input.canonical_backtest.total_cost",
            "critique_input.canonical_backtest.cost_summary",
        ),
        (
            "critique_input.canonical_backtest.oos_validation.aggregate.mean_out_of_sample_return",
            "critique_input.canonical_backtest.oos_validation",
        ),
        (
            "critique_input.hypothesis_draft.failure_conditions",
            "critique_input.hypothesis_draft.limitations",
        ),
    )
    selected_paths: list[str] = []
    for alternatives in path_groups:
        selected = next(
            (
                path
                for path in alternatives
                if path in CRITIQUE_CITATION_PATHS
                and citation_path_exists(path, sources)
            ),
            None,
        )
        if selected is not None and selected not in selected_paths:
            selected_paths.append(selected)
    if not selected_paths or not any(
        path.startswith("critique_input.canonical_backtest.") for path in selected_paths
    ):
        raise StrategyResearchRejected("strategy_critique_citation_catalog_empty")
    return {
        f"cite_{index:02d}": path for index, path in enumerate(selected_paths, start=1)
    }


def resolve_hypothesis_citations(
    payload: Mapping[str, Any],
    *,
    citation_catalog: Mapping[str, str],
    citation_sources: Mapping[str, Any],
) -> JsonObject:
    """Resolve catalog IDs to audited paths without inventing missing evidence."""
    drafts = payload.get("drafts")
    if not isinstance(drafts, list):
        raise ExternalResearchInvalidResponseError("hypothesis_draft_count_invalid")
    resolved_drafts = []
    for draft in drafts:
        if not isinstance(draft, dict):
            raise ExternalResearchInvalidResponseError("hypothesis_draft_invalid")
        citations = draft.get("citations")
        if (
            not isinstance(citations, list)
            or not citations
            or any(not isinstance(item, str) or not item for item in citations)
        ):
            raise ExternalResearchInvalidResponseError("hypothesis_citations_invalid")
        if citations != list(citation_catalog):
            raise ExternalResearchInvalidResponseError(
                "provider_citation_contract_mismatch"
            )
        resolved = []
        for citation in citations:
            path = citation_catalog.get(citation)
            if path is None or not citation_path_exists(path, citation_sources):
                raise ExternalResearchInvalidResponseError(
                    "provider_citation_not_in_bound_input"
                )
            resolved.append(path)
        resolved_drafts.append({**draft, "citations": resolved})
    return {"drafts": resolved_drafts}


def citation_path_exists(citation: str, sources: Mapping[str, Any]) -> bool:
    """Require every model citation to resolve inside the exact exported JSON."""
    parts = citation.split(".")
    if len(parts) < 2 or any(not part for part in parts):
        return False
    if parts[0] not in sources:
        return False
    value: Any = sources[parts[0]]
    for part in parts[1:]:
        suffix = ""
        if isinstance(value, Mapping):
            bracket = part.find("[")
            key = part if bracket < 0 else part[:bracket]
            if not key or key not in value:
                return False
            value = value[key]
            suffix = "" if bracket < 0 else part[bracket:]
        elif isinstance(value, list):
            suffix = f"[{part}]"
        else:
            return False

        while suffix:
            if not suffix.startswith("["):
                return False
            close = suffix.find("]")
            if close <= 1:
                return False
            index_text = suffix[1:close]
            if not index_text.isdigit() or (
                len(index_text) > 1 and index_text.startswith("0")
            ):
                return False
            index = int(index_text)
            if not isinstance(value, list) or index >= len(value):
                return False
            value = value[index]
            suffix = suffix[close + 1 :]
    return True
