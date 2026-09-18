"""Shared value projection and failure helpers for AI strategy research."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from server.ai_runtime.contracts import (
    ArtifactKind,
    JsonObject,
    ResearchEvaluationBundle,
    ResearchSelection,
    ResearchSelectionDecision,
    ResearchSelectionSource,
    StoredArtifact,
    canonical_json,
    content_fingerprint,
)
from server.ai_runtime.external_research_errors import (
    ExternalResearchInvalidResponseError,
)
from server.ai_runtime.formula_dsl import FormulaValidationError
from server.ai_runtime.provider_call_window import ProviderCallDeferred
from server.ai_runtime.store import AiAuditStore
from server.contracts.strategy_research import (
    STRATEGY_RESEARCH_API_CONTRACT,
    StrategyResearchRejected,
    StrategyResearchSelection,
)


def build_research_evaluation_bundle(
    *,
    backtest_result_id: int,
    persisted_row: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> ResearchEvaluationBundle:
    """Project persisted deterministic backtest evidence without re-scoring it."""

    metrics_payload = dict(metrics)
    dataset = strategy_research_json_object(metrics_payload.get("dataset_snapshot"))
    research = strategy_research_json_object(
        metrics_payload.get("research_evidence_bundle")
    )
    oos = strategy_research_json_object(metrics_payload.get("oos_validation"))
    after_cost = strategy_research_json_object(metrics_payload.get("evidence_bundle"))
    cost_summary = strategy_research_json_object(persisted_row.get("cost_summary_json"))
    parameter_robustness = strategy_research_json_object(
        metrics_payload.get("parameter_robustness")
        or metrics_payload.get("sweep_robustness")
    )
    market_regime = strategy_research_json_object(
        metrics_payload.get("market_regime_robustness")
    )
    capacity_review = strategy_research_json_object(
        metrics_payload.get("capacity_review")
    )
    drawdown_evidence = strategy_research_json_object(
        metrics_payload.get("drawdown_evidence")
    )
    signal_execution = strategy_research_json_object(
        metrics_payload.get("signal_execution_evidence")
    )
    lot_feasibility = strategy_research_json_object(
        metrics_payload.get("lot_feasibility_evidence")
    )

    dataset_snapshot_id = (
        str(dataset.get("snapshot_id")) if dataset.get("snapshot_id") else None
    )
    research_gate_status = str(research.get("gate_status") or "not_evaluated")
    required_evidence = (
        ("dataset_snapshot", dataset_snapshot_id is not None),
        ("after_cost_evidence", bool(after_cost)),
        ("cost_summary", bool(cost_summary)),
        ("oos_validation", bool(oos)),
        ("research_evidence_bundle", bool(research)),
    )
    missing_evidence = tuple(
        name for name, available in required_evidence if not available
    )

    source_payload: JsonObject = {
        "backtest_result_id": backtest_result_id,
        "initial_cash": persisted_row.get("initial_cash"),
        "final_equity": persisted_row.get("final_equity"),
        "total_return": persisted_row.get("total_return"),
        "sharpe": persisted_row.get("sharpe"),
        "max_drawdown": persisted_row.get("max_drawdown"),
        "duration_days": persisted_row.get("duration_days"),
        "dataset_snapshot": dataset,
        "research_evidence_bundle": research,
        "oos_validation": oos,
        "after_cost_evidence": after_cost,
        "cost_summary": cost_summary,
        "parameter_robustness": parameter_robustness,
        "market_regime_robustness": market_regime,
        "capacity_review": capacity_review,
        "drawdown_evidence": drawdown_evidence,
        "signal_execution_evidence": signal_execution,
        "lot_feasibility_evidence": lot_feasibility,
    }
    source_fingerprint = "sha256:" + content_fingerprint(source_payload)
    evaluation_identity = {
        "backtest_result_id": backtest_result_id,
        "source_fingerprint": source_fingerprint,
        "schema_version": "karkinos.ai.research_evaluation_bundle.v1",
    }
    evaluation_id = (
        "research-evaluation-" + content_fingerprint(evaluation_identity)[:24]
    )
    # Round-trip once so nested mappings are detached from mutable DB payloads.
    detached = json.loads(canonical_json(source_payload))

    return ResearchEvaluationBundle(
        evaluation_id=evaluation_id,
        backtest_result_id=backtest_result_id,
        source_fingerprint=source_fingerprint,
        dataset_snapshot_id=dataset_snapshot_id,
        research_gate_status=research_gate_status,
        research_evidence_bundle=dict(detached["research_evidence_bundle"]),
        oos_validation=dict(detached["oos_validation"]),
        after_cost_evidence=dict(detached["after_cost_evidence"]),
        cost_summary=dict(detached["cost_summary"]),
        parameter_robustness=dict(detached["parameter_robustness"]),
        market_regime_robustness=dict(detached["market_regime_robustness"]),
        capacity_review=dict(detached["capacity_review"]),
        drawdown_evidence=dict(detached["drawdown_evidence"]),
        signal_execution_evidence=dict(detached["signal_execution_evidence"]),
        lot_feasibility_evidence=dict(detached["lot_feasibility_evidence"]),
        missing_evidence=missing_evidence,
    )


def build_human_research_selection(
    *,
    review: Mapping[str, Any],
    session: Mapping[str, Any],
    critique: Mapping[str, Any],
    evaluation: ResearchEvaluationBundle,
) -> ResearchSelection:
    disposition = str(review.get("disposition") or "")
    decision_by_disposition = {
        "accepted_for_more_research": (
            ResearchSelectionDecision.SELECTED_FOR_FURTHER_RESEARCH
        ),
        "needs_revision": ResearchSelectionDecision.NEEDS_REVISION,
        "rejected": ResearchSelectionDecision.REJECTED,
    }
    try:
        decision = decision_by_disposition[disposition]
    except KeyError as exc:
        raise StrategyResearchRejected("review_disposition_invalid") from exc

    projected_task_id = session.get("research_task_id")
    if projected_task_id is not None:
        task_id = str(projected_task_id)
    elif session.get("request_json") is not None:
        request = strategy_research_request_json(session)
        task_id = (
            str(request["research_task_id"])
            if request.get("research_task_id") is not None
            else None
        )
    else:
        task_id = None
    review_id = str(review.get("review_id") or "")
    session_id = str(review.get("session_id") or session.get("session_id") or "")
    candidate_id = str(critique.get("draft_id") or "")
    critique_id = str(review.get("critique_id") or critique.get("critique_id") or "")
    reviewer = str(review.get("reviewer") or "")
    created_at = str(review.get("created_at") or "")
    notes = str(review.get("notes") or "")
    identity = {
        "review_id": review_id,
        "session_id": session_id,
        "candidate_id": candidate_id,
        "critique_id": critique_id,
        "evaluation_id": evaluation.evaluation_id,
        "decision": decision.value,
        "schema_version": "karkinos.ai.research_selection.v1",
    }
    selection_id = "research-selection-" + content_fingerprint(identity)[:24]
    return ResearchSelection(
        selection_id=selection_id,
        session_id=session_id,
        task_id=task_id,
        task_binding_status="bound" if task_id is not None else "legacy_unbound",
        candidate_id=candidate_id,
        critique_id=critique_id,
        evaluation_id=evaluation.evaluation_id,
        evaluation_fingerprint=evaluation.fingerprint,
        evaluation_gate_status=evaluation.research_gate_status,
        decision=decision,
        source=ResearchSelectionSource.HUMAN,
        reviewer=reviewer,
        notes=notes,
        created_at=created_at,
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
        sealed_end_date=(
            str(selection["sealed_end_date"])
            if selection.get("sealed_end_date") is not None
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
    if isinstance(exc, ProviderCallDeferred):
        return str(exc)
    if isinstance(exc, FormulaValidationError):
        return f"formula_validation:{exc.code}"
    name = exc.__class__.__name__.replace("Error", "").strip("_")
    normalized = "".join(
        f"_{char.lower()}" if char.isupper() else char for char in name
    ).lstrip("_")
    return normalized or "strategy_research_failure"


def strategy_research_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
