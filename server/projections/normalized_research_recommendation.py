"""Deterministic best-available recommendation for normalized formula research."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from server.contracts.content_identity import content_fingerprint
from server.contracts.normalized_strategy_research import (
    NORMALIZED_RESEARCH_NOTIONAL,
)
from server.projections.normalized_research_operation_preview import (
    bind_research_winner_operation_preview,
    is_valid_research_operation_recommendation,
    project_normalized_research_operation_preview,
    unavailable_research_operation_recommendation,
)

NORMALIZED_RESEARCH_RECOMMENDATION_SCHEMA = (
    "karkinos.ai.normalized_daily_research_recommendation.v1"
)
_RECOMMENDATION_FIELDS = {
    "schema_version",
    "run_id",
    "market_date",
    "status",
    "research_winner_candidate_id",
    "expected_candidate_count",
    "evaluated_candidate_count",
    "blockers",
    "ranking_method",
    "ranked_candidates",
    "research_operation_preview",
    "account_qualification_status",
    "account_qualified",
    "promotion_eligible",
    "paper_shadow_eligible",
    "decision_eligible",
    "execution_eligible",
    "human_review_required",
    "automatic_strategy_replacement_enabled",
    "broker_submission_enabled",
    "authority_effect",
    "evidence_fingerprint",
}
_RANKED_CANDIDATE_FIELDS = {
    "candidate_id",
    "draft_id",
    "formula_fingerprint",
    "dataset_snapshot_id",
    "iteration_number",
    "total_iterations",
    "parent_candidate_id",
    "parent_draft_id",
    "parent_formula_fingerprint",
    "total_return",
    "mean_oos_return",
    "worst_oos_return",
    "sharpe",
    "max_drawdown",
    "total_cost_bps",
    "comparison_fingerprint",
    "rank",
}
_RANKING_METHOD_FIELDS = {
    "type",
    "priority",
    "deepseek_selects_winner",
    "best_available_is_not_a_quality_gate",
}


def build_normalized_research_recommendation(
    *,
    run_id: str,
    market_date: str,
    candidates: Sequence[Mapping[str, Any]],
    expected_candidate_count: int,
) -> dict[str, Any]:
    """Rank complete normalized candidates without granting promotion authority."""

    blockers: list[str] = []
    ranked_inputs: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    if len(candidates) != expected_candidate_count:
        blockers.append("configured_normalized_candidate_set_incomplete")
    for candidate in candidates:
        outcome = _research_outcome(candidate, run_id=run_id)
        if outcome is None:
            blockers.append("normalized_candidate_research_evidence_incomplete")
            continue
        ranked_inputs.append((outcome.pop("ranking_key"), outcome))
    candidate_ids = [outcome["candidate_id"] for _, outcome in ranked_inputs]
    if len(candidate_ids) != len(set(candidate_ids)):
        blockers.append("normalized_candidate_identity_conflict")
    lineage = {outcome.get("iteration_number"): outcome for _, outcome in ranked_inputs}
    expected_iterations = set(range(1, expected_candidate_count + 1))
    if set(lineage) != expected_iterations or any(
        outcome.get("total_iterations") != expected_candidate_count
        for _, outcome in ranked_inputs
    ):
        blockers.append("normalized_candidate_iteration_lineage_invalid")
    else:
        for iteration_number in range(1, expected_candidate_count + 1):
            outcome = lineage[iteration_number]
            previous = lineage.get(iteration_number - 1)
            if (
                outcome.get("parent_candidate_id")
                != (previous["candidate_id"] if previous else None)
                or outcome.get("parent_draft_id")
                != (previous["draft_id"] if previous else None)
                or outcome.get("parent_formula_fingerprint")
                != (previous["formula_fingerprint"] if previous else None)
            ):
                blockers.append("normalized_candidate_iteration_lineage_invalid")
                break
    if len(ranked_inputs) != expected_candidate_count:
        blockers.append("normalized_candidate_research_evidence_incomplete")
    if not blockers:
        ranked_inputs.sort(key=lambda item: item[0])
    winner_operation_preview = (
        ranked_inputs[0][1].get("_operation_preview")
        if ranked_inputs and not blockers
        else None
    )
    ranked = (
        [
            {
                **{
                    key: value
                    for key, value in outcome.items()
                    if not key.startswith("_")
                },
                "rank": rank,
            }
            for rank, (_, outcome) in enumerate(ranked_inputs, start=1)
        ]
        if not blockers
        else []
    )
    research_winner_candidate_id = str(ranked[0]["candidate_id"]) if ranked else None
    operation_recommendation = (
        bind_research_winner_operation_preview(
            preview=winner_operation_preview,
            candidate_id=research_winner_candidate_id,
            run_id=run_id,
            market_date=market_date,
        )
        if research_winner_candidate_id
        else unavailable_research_operation_recommendation(
            reason="verified_normalized_research_winner_unavailable",
            run_id=run_id,
            market_date=market_date,
        )
    )
    core = {
        "schema_version": NORMALIZED_RESEARCH_RECOMMENDATION_SCHEMA,
        "run_id": run_id,
        "market_date": market_date,
        "status": (
            "best_available_for_further_research"
            if research_winner_candidate_id
            else "no_recommendation"
        ),
        "research_winner_candidate_id": research_winner_candidate_id,
        "expected_candidate_count": expected_candidate_count,
        "evaluated_candidate_count": len(ranked_inputs),
        "blockers": sorted(set(blockers)),
        "ranking_method": {
            "type": "normalized_evidence_lexicographic",
            "priority": [
                "total_return_desc",
                "mean_oos_return_desc",
                "worst_oos_return_desc",
                "sharpe_desc",
                "max_drawdown_asc",
                "total_cost_bps_asc",
                "candidate_id_asc",
            ],
            "deepseek_selects_winner": False,
            "best_available_is_not_a_quality_gate": True,
        },
        "ranked_candidates": ranked,
        "research_operation_preview": operation_recommendation,
        "account_qualification_status": "not_evaluated",
        "account_qualified": False,
        "promotion_eligible": False,
        "paper_shadow_eligible": False,
        "decision_eligible": False,
        "execution_eligible": False,
        "human_review_required": True,
        "automatic_strategy_replacement_enabled": False,
        "broker_submission_enabled": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def is_valid_normalized_research_recommendation(value: Any) -> bool:
    """Validate the non-authorizing nested artifact before public projection."""

    if not isinstance(value, Mapping):
        return False
    if set(value) != _RECOMMENDATION_FIELDS:
        return False
    payload = dict(value)
    evidence_fingerprint = payload.pop("evidence_fingerprint", None)
    winner = payload.get("research_winner_candidate_id")
    status = payload.get("status")
    operation_preview = payload.get("research_operation_preview")
    ranked_candidates = payload.get("ranked_candidates")
    ranking_method = payload.get("ranking_method")
    blockers = payload.get("blockers")
    if (
        not isinstance(ranked_candidates, list)
        or any(
            not isinstance(item, Mapping) or set(item) != _RANKED_CANDIDATE_FIELDS
            for item in ranked_candidates
        )
        or not isinstance(ranking_method, Mapping)
        or set(ranking_method) != _RANKING_METHOD_FIELDS
        or not isinstance(blockers, list)
        or any(not isinstance(item, str) or not item for item in blockers)
    ):
        return False
    winner_rows = (
        [
            item
            for item in ranked_candidates
            if isinstance(item, Mapping) and item.get("candidate_id") == winner
        ]
        if isinstance(ranked_candidates, list) and winner
        else []
    )
    winner_row = winner_rows[0] if len(winner_rows) == 1 else None
    operation_source_bound = (
        isinstance(operation_preview, Mapping)
        and operation_preview.get("source_preview_fingerprint") is not None
    )
    return (
        payload.get("schema_version") == NORMALIZED_RESEARCH_RECOMMENDATION_SCHEMA
        and status in {"best_available_for_further_research", "no_recommendation"}
        and (status == "best_available_for_further_research") == bool(winner)
        and (status == "best_available_for_further_research") == bool(ranked_candidates)
        and ranking_method.get("type") == "normalized_evidence_lexicographic"
        and ranking_method.get("deepseek_selects_winner") is False
        and ranking_method.get("best_available_is_not_a_quality_gate") is True
        and payload.get("account_qualification_status") == "not_evaluated"
        and payload.get("account_qualified") is False
        and payload.get("promotion_eligible") is False
        and payload.get("paper_shadow_eligible") is False
        and payload.get("decision_eligible") is False
        and payload.get("execution_eligible") is False
        and payload.get("automatic_strategy_replacement_enabled") is False
        and payload.get("broker_submission_enabled") is False
        and payload.get("authority_effect") == "none"
        and is_valid_research_operation_recommendation(operation_preview)
        and operation_preview.get("research_winner_candidate_id") == winner
        and operation_preview.get("run_id") == payload.get("run_id")
        and operation_preview.get("market_date") == payload.get("market_date")
        and (
            not winner
            or (
                winner_row is not None
                and (
                    not operation_source_bound
                    or (
                        operation_preview.get("formula_fingerprint")
                        == winner_row.get("formula_fingerprint")
                        and operation_preview.get("dataset_snapshot_id")
                        == winner_row.get("dataset_snapshot_id")
                    )
                )
            )
        )
        and isinstance(evidence_fingerprint, str)
        and evidence_fingerprint == content_fingerprint(payload)
    )


def _research_outcome(
    candidate: Mapping[str, Any], *, run_id: str
) -> dict[str, Any] | None:
    comparison = _mapping(candidate.get("comparison"))
    metrics = _mapping(comparison.get("candidate"))
    lineage = _mapping(comparison.get("iteration_lineage"))
    candidate_id = str(candidate.get("candidate_id") or "")
    if (
        not candidate_id
        or str(candidate.get("run_id") or "") != run_id
        or candidate.get("status") != "evaluated_research_only"
        or candidate.get("recommendation") != "formula_research_candidate"
        or comparison.get("research_capital_mode") != "normalized_notional"
        or comparison.get("account_qualification_status") != "not_evaluated"
        or not _valid_fingerprint(comparison.get("baseline_source_fingerprint"))
        or not _valid_fingerprint(comparison.get("candidate_source_fingerprint"))
        or not str(candidate.get("critique_id") or "")
        or lineage.get("sequential_feedback_bound") is not True
        or not str(lineage.get("formula_fingerprint") or "").startswith("sha256:")
    ):
        return None
    operation_preview = project_normalized_research_operation_preview(
        comparison.get("normalized_research_operation_preview")
    )
    formula_fingerprint = lineage.get("formula_fingerprint")
    dataset_snapshot_id = metrics.get("dataset_snapshot_id")
    if operation_preview is not None and (
        not _valid_fingerprint(dataset_snapshot_id)
        or operation_preview.get("formula_fingerprint") != formula_fingerprint
        or operation_preview.get("dataset_snapshot_id") != dataset_snapshot_id
    ):
        operation_preview = None
    total_return = _number(metrics.get("total_return"))
    mean_oos_return = _number(metrics.get("mean_oos_return"))
    worst_oos_return = _number(metrics.get("worst_oos_return"))
    sharpe = _number(metrics.get("sharpe"))
    max_drawdown = _number(metrics.get("max_drawdown"))
    total_cost = _number(metrics.get("total_cost"))
    initial_cash = _number(metrics.get("initial_cash"))
    if (
        None
        in {
            total_return,
            mean_oos_return,
            worst_oos_return,
            sharpe,
            max_drawdown,
            total_cost,
            initial_cash,
        }
        or initial_cash is None
        or initial_cash != NORMALIZED_RESEARCH_NOTIONAL
        or total_cost is None
        or total_cost < 0
    ):
        return None
    total_cost_bps = total_cost / initial_cash * 10_000
    return {
        "candidate_id": candidate_id,
        "draft_id": str(candidate.get("draft_id") or ""),
        "formula_fingerprint": formula_fingerprint,
        "dataset_snapshot_id": dataset_snapshot_id,
        "iteration_number": lineage.get("iteration_number"),
        "total_iterations": lineage.get("total_iterations"),
        "parent_candidate_id": lineage.get("parent_candidate_id"),
        "parent_draft_id": lineage.get("parent_draft_id"),
        "parent_formula_fingerprint": lineage.get("parent_formula_fingerprint"),
        "total_return": total_return,
        "mean_oos_return": mean_oos_return,
        "worst_oos_return": worst_oos_return,
        "sharpe": sharpe,
        "max_drawdown": abs(max_drawdown),
        "total_cost_bps": total_cost_bps,
        "comparison_fingerprint": content_fingerprint(comparison),
        "_operation_preview": operation_preview,
        "ranking_key": (
            -total_return,
            -mean_oos_return,
            -worst_oos_return,
            -sharpe,
            abs(max_drawdown),
            total_cost_bps,
            candidate_id,
        ),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _valid_fingerprint(value: Any) -> bool:
    text = str(value or "").removeprefix("sha256:")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text.lower())
