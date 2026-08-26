"""Shared value projection and failure helpers for AI strategy research."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from server.ai_runtime.contracts import ArtifactKind, JsonObject, StoredArtifact
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
)
from server.ai_runtime.formula_dsl import FormulaValidationError
from server.ai_runtime.store import AiAuditStore
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_API_CONTRACT,
    StrategyResearchRejected,
    StrategyResearchSelection,
)


def report_artifact(ai_store: AiAuditStore, workflow_id: str) -> StoredArtifact:
    artifacts = [
        item
        for item in ai_store.list_artifacts(workflow_id)
        if item.kind == ArtifactKind.REPORT
    ]
    if len(artifacts) != 1:
        raise StrategyResearchRejected("strategy_research_report_artifact_missing")
    return artifacts[0]


def selection_from_session(session: Mapping[str, Any]) -> StrategyResearchSelection:
    selection = strategy_research_request_json(session).get("selection")
    if not isinstance(selection, dict):
        raise StrategyResearchRejected("stored_selection_missing")
    return StrategyResearchSelection(
        saved_backtest_result_id=int(selection["saved_backtest_result_id"]),
        universe=tuple(str(item) for item in selection["universe"]),
        asset_classes=tuple(str(item) for item in selection["asset_classes"]),
        dataset_snapshot_id=str(selection["dataset_snapshot_id"]),
        start_date=str(selection["start_date"]),
        end_date=str(selection["end_date"]),
        frequency=str(selection["frequency"]),
        initial_cash=float(selection["initial_cash"]),
        cost_model_reference=str(selection["cost_model_reference"]),
        account_truth_freshness_as_of=(
            str(selection["account_truth_freshness_as_of"])
            if selection.get("account_truth_freshness_as_of") is not None
            else None
        ),
        valuation_snapshot_id=(
            str(selection["valuation_snapshot_id"])
            if selection.get("valuation_snapshot_id") is not None
            else None
        ),
        ledger_cutoff_id=(
            int(selection["ledger_cutoff_id"])
            if selection.get("ledger_cutoff_id") is not None
            else None
        ),
    )


def strategy_research_request_json(session: Mapping[str, Any]) -> JsonObject:
    value = session.get("request_json")
    if not isinstance(value, str):
        raise StrategyResearchRejected("stored_request_missing")
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise StrategyResearchRejected("stored_request_invalid")
    return decoded


def strategy_research_json_object(value: Any) -> JsonObject:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def critique_response(row: dict[str, Any], *, reused: bool) -> JsonObject:
    return {
        "schema_version": STRATEGY_RESEARCH_API_CONTRACT,
        "critique_id": row["critique_id"],
        "session_id": row["session_id"],
        "draft_id": row["draft_id"],
        "backtest_run_id": row["backtest_run_id"],
        "status": row["status"],
        "failure_code": row.get("failure_code"),
        "provider_id": row.get("provider_id"),
        "model_id": row.get("model_id"),
        "prompt_version": row.get("prompt_version"),
        "artifact": row.get("artifact"),
        "reused": reused,
        "non_authoritative": True,
        "non_executable": True,
        "requires_human_review": True,
        "trade_plan_created": False,
        "authority_effect": "none",
    }


def safe_provider_usage(value: Any) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    allowed = {"prompt_tokens", "completion_tokens", "total_tokens"}
    return {
        key: int(item)
        for key, item in value.items()
        if key in allowed and isinstance(item, int) and item >= 0
    }


def decode_model_json(content: str) -> JsonObject:
    """Accept an exact JSON object, tolerating only a single JSON code fence."""
    candidate = content.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    elif candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
    try:
        decoded = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ExternalResearchInvalidResponseError("provider_content_not_json") from exc
    if not isinstance(decoded, dict):
        raise ExternalResearchInvalidResponseError("provider_content_not_json_object")
    return decoded


def strategy_research_failure_code(exc: Exception) -> str:
    if isinstance(exc, FormulaValidationError):
        return f"formula_validation:{exc.code}"
    name = exc.__class__.__name__.replace("Error", "").strip("_")
    normalized = "".join(
        f"_{char.lower()}" if char.isupper() else char for char in name
    ).lstrip("_")
    return normalized or "strategy_research_failure"


def strategy_research_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
