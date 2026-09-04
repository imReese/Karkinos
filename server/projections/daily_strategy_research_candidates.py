"""Verified normalized-candidate projections for account qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from server.contracts.content_identity import content_fingerprint
from server.contracts.daily_strategy_artifacts import (
    DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA,
    DAILY_STRATEGY_BACKUP_SCHEMA,
    DAILY_STRATEGY_SELECTION_SCHEMA,
    DailyStrategyArtifactRejected,
)
from server.contracts.normalized_strategy_research import (
    CANONICAL_COST_MODEL_REFERENCE,
    NORMALIZED_RESEARCH_NOTIONAL,
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
)
from server.projections.normalized_research_recommendation import (
    is_valid_normalized_research_recommendation,
)

VERIFIED_RESEARCH_CANDIDATE_STRATEGY_SCHEMA = (
    "karkinos.ai.verified_research_candidate_strategy.v1"
)
VERIFIED_RESEARCH_CANDIDATE_STRATEGY_BATCH_SCHEMA = (
    "karkinos.ai.verified_research_candidate_strategy_batch.v1"
)


def build_verified_research_candidate_strategy_batch(
    *,
    payload: Mapping[str, Any],
    selection: Mapping[str, Any],
    backup: Mapping[str, Any],
) -> dict[str, Any]:
    """Load every frozen normalized candidate without granting account authority."""

    expected_selection = dict(selection)
    expected_selection.pop("integrity_status", None)
    recommendation = selection.get("research_recommendation")
    candidate_outcomes = selection.get("candidate_outcomes")
    ranked_candidates = (
        recommendation.get("ranked_candidates")
        if isinstance(recommendation, Mapping)
        else None
    )
    candidate_snapshots = payload.get("candidates")
    expected_count = selection.get("expected_candidate_count")
    if (
        selection.get("schema_version") != DAILY_STRATEGY_SELECTION_SCHEMA
        or selection.get("integrity_status") != "verified"
        or selection.get("status") != "no_selection"
        or selection.get("winner_candidate_id") is not None
        or selection.get("selection_scope") != "new_candidate_research_only"
        or selection.get("daily_trading_decision_status") != "not_evaluated"
        or selection.get("human_paper_shadow_approval_required") is not True
        or selection.get("automatic_strategy_replacement_enabled") is not False
        or selection.get("broker_submission_enabled") is not False
        or selection.get("does_not_change_capital_authority") is not True
        or selection.get("authority_effect") != "research_only"
        or backup.get("schema_version") != DAILY_STRATEGY_BACKUP_RECEIPT_SCHEMA
        or backup.get("verification_status") != "verified"
        or payload.get("schema_version") != DAILY_STRATEGY_BACKUP_SCHEMA
        or payload.get("run_status") != "completed"
        or payload.get("selection") != expected_selection
        or not isinstance(recommendation, Mapping)
        or not is_valid_normalized_research_recommendation(recommendation)
        or recommendation.get("status") != "best_available_for_further_research"
        or recommendation.get("account_qualification_status") != "not_evaluated"
        or recommendation.get("account_qualified") is not False
        or recommendation.get("promotion_eligible") is not False
        or recommendation.get("paper_shadow_eligible") is not False
        or recommendation.get("decision_eligible") is not False
        or recommendation.get("execution_eligible") is not False
        or recommendation.get("authority_effect") != "none"
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count != 5
        or selection.get("observed_candidate_count") != expected_count
        or recommendation.get("expected_candidate_count") != expected_count
        or recommendation.get("evaluated_candidate_count") != expected_count
        or not isinstance(candidate_outcomes, list)
        or not isinstance(ranked_candidates, list)
        or not isinstance(candidate_snapshots, list)
        or len(candidate_outcomes) != expected_count
        or len(ranked_candidates) != expected_count
        or len(candidate_snapshots) != expected_count
        or payload.get("run_id") != selection.get("run_id")
        or payload.get("market_date") != selection.get("market_date")
        or backup.get("run_id") != selection.get("run_id")
        or backup.get("market_date") != selection.get("market_date")
        or backup.get("selection_id") != selection.get("selection_id")
        or backup.get("contains_private_account_identifiers") is not False
        or backup.get("contains_broker_export_rows") is not False
        or payload.get("contains_private_account_identifiers") is not False
        or payload.get("contains_broker_export_rows") is not False
        or payload.get("contains_provider_credentials") is not False
        or payload.get("automatic_strategy_replacement_enabled") is not False
        or payload.get("broker_submission_enabled") is not False
        or payload.get("authority_effect") != "research_only"
    ):
        raise DailyStrategyArtifactRejected(
            "daily_research_candidate_artifact_set_invalid"
        )

    outcomes_by_id = _unique_candidate_items(
        candidate_outcomes,
        error="daily_research_candidate_identity_conflict",
    )
    ranked_by_id = _unique_candidate_items(
        ranked_candidates,
        error="daily_research_candidate_identity_conflict",
    )
    snapshots_by_id = _unique_candidate_items(
        candidate_snapshots,
        error="daily_research_candidate_identity_conflict",
    )
    candidate_ids = set(outcomes_by_id)
    if (
        candidate_ids != set(ranked_by_id)
        or candidate_ids != set(snapshots_by_id)
        or recommendation.get("research_winner_candidate_id") not in candidate_ids
        or set(item.get("rank") for item in ranked_candidates)
        != set(range(1, expected_count + 1))
    ):
        raise DailyStrategyArtifactRejected(
            "daily_research_candidate_artifact_set_mismatch"
        )

    candidates: list[dict[str, Any]] = []
    source_research_selection: dict[str, Any] | None = None
    iteration_numbers: set[int] = set()
    for candidate_id, outcome in outcomes_by_id.items():
        ranked = ranked_by_id[candidate_id]
        snapshot = snapshots_by_id[candidate_id]
        strategy = snapshot.get("strategy")
        comparison_fingerprint = outcome.get("comparison_fingerprint")
        strategy_artifact_fingerprint = snapshot.get("strategy_artifact_fingerprint")
        formula_fingerprint = outcome.get("formula_fingerprint")
        dataset_snapshot_id = ranked.get("dataset_snapshot_id")
        iteration_number = outcome.get("iteration_number")
        strategy_universe = (
            _nonempty_text_list(strategy.get("selected_universe"))
            if isinstance(strategy, Mapping)
            else []
        )
        test_window = (
            strategy.get("test_window") if isinstance(strategy, Mapping) else None
        )
        if (
            outcome.get("run_id") != selection.get("run_id")
            or outcome.get("status") != "evaluated_research_only"
            or outcome.get("recommendation") != "formula_research_candidate"
            or outcome.get("research_capital_mode") != "normalized_notional"
            or outcome.get("account_qualification_status") != "not_evaluated"
            or outcome.get("eligible") is not False
            or outcome.get("draft_id") != ranked.get("draft_id")
            or outcome.get("draft_id") != snapshot.get("draft_id")
            or snapshot.get("status") != outcome.get("status")
            or snapshot.get("recommendation") != outcome.get("recommendation")
            or not _valid_content_fingerprint(comparison_fingerprint)
            or ranked.get("comparison_fingerprint") != comparison_fingerprint
            or snapshot.get("comparison_fingerprint") != comparison_fingerprint
        ):
            raise DailyStrategyArtifactRejected(
                "daily_research_candidate_comparison_mismatch"
            )
        if (
            not isinstance(strategy, Mapping)
            or not isinstance(strategy.get("formula_ast"), Mapping)
            or not strategy_universe
            or len(strategy_universe) != len(set(strategy_universe))
            or not _valid_content_fingerprint(strategy_artifact_fingerprint)
            or strategy_artifact_fingerprint != content_fingerprint(strategy)
            or strategy.get("draft_id") != outcome.get("draft_id")
            or not _valid_content_fingerprint(formula_fingerprint)
            or strategy.get("formula_fingerprint") != formula_fingerprint
            or ranked.get("formula_fingerprint") != formula_fingerprint
            or not _valid_content_fingerprint(dataset_snapshot_id)
            or strategy.get("dataset_snapshot_id") != dataset_snapshot_id
            or not isinstance(test_window, Mapping)
            or set(test_window) != {"start_date", "end_date"}
            or not _valid_research_window(
                start_date=test_window.get("start_date"),
                end_date=test_window.get("end_date"),
                market_date=selection.get("market_date"),
            )
            or strategy.get("frequency") != "1d"
            or strategy.get("cost_model_reference") != CANONICAL_COST_MODEL_REFERENCE
        ):
            raise DailyStrategyArtifactRejected(
                "daily_research_candidate_strategy_mismatch"
            )
        lineage_fields = (
            "iteration_number",
            "total_iterations",
            "parent_candidate_id",
            "parent_draft_id",
            "parent_formula_fingerprint",
        )
        if (
            any(outcome.get(key) != ranked.get(key) for key in lineage_fields)
            or not isinstance(iteration_number, int)
            or isinstance(iteration_number, bool)
            or outcome.get("total_iterations") != expected_count
            or outcome.get("sequential_feedback_bound") is not True
            or not _valid_content_fingerprint(
                outcome.get("iteration_context_fingerprint")
            )
        ):
            raise DailyStrategyArtifactRejected(
                "daily_research_candidate_lineage_mismatch"
            )
        iteration_numbers.add(iteration_number)
        candidate_source_selection = {
            "schema_version": "karkinos.ai.normalized_source_selection_binding.v1",
            "universe": strategy_universe,
            "asset_classes": ["stock"] * len(strategy_universe),
            "asset_class_policy": "daily_candidate_stock_only",
            "dataset_snapshot_id": dataset_snapshot_id,
            "start_date": test_window.get("start_date"),
            "end_date": test_window.get("end_date"),
            "frequency": strategy.get("frequency"),
            "initial_cash": NORMALIZED_RESEARCH_NOTIONAL,
            "notional_policy_id": NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
            "cost_model_reference": strategy.get("cost_model_reference"),
            "account_fact_binding": "not_applicable_strategy_only_research",
            "saved_backtest_result_id": None,
            "saved_backtest_result_id_status": (
                "not_present_in_privacy_minimized_backup"
            ),
            "contains_private_account_identifiers": False,
            "authority_effect": "research_only",
        }
        if source_research_selection is None:
            source_research_selection = candidate_source_selection
        elif source_research_selection != candidate_source_selection:
            raise DailyStrategyArtifactRejected(
                "daily_research_candidate_source_selection_mismatch"
            )
        source_selection_fingerprint = content_fingerprint(candidate_source_selection)
        core = {
            "schema_version": VERIFIED_RESEARCH_CANDIDATE_STRATEGY_SCHEMA,
            "candidate_id": candidate_id,
            "draft_id": outcome.get("draft_id"),
            "run_id": selection.get("run_id"),
            "market_date": selection.get("market_date"),
            "selection_id": selection.get("selection_id"),
            "selection_fingerprint": selection.get("selection_fingerprint"),
            "backup_id": backup.get("backup_id"),
            "backup_artifact_fingerprint": backup.get("artifact_fingerprint"),
            "source_research_recommendation_fingerprint": recommendation.get(
                "evidence_fingerprint"
            ),
            "source_research_selection_fingerprint": source_selection_fingerprint,
            "source_comparison_fingerprint": comparison_fingerprint,
            "strategy_artifact_fingerprint": strategy_artifact_fingerprint,
            "formula_fingerprint": formula_fingerprint,
            "dataset_snapshot_id": dataset_snapshot_id,
            "iteration_number": iteration_number,
            "total_iterations": expected_count,
            "research_rank": ranked.get("rank"),
            "strategy": dict(strategy),
            "account_qualification_status": "not_evaluated",
            "provider_contact_performed": False,
            "database_writes_performed": False,
            "read_only": True,
            "research_only": True,
            "authorizes_strategy_promotion": False,
            "authorizes_order_creation": False,
            "authorizes_execution": False,
            "changes_capital_authority": False,
            "authority_effect": "none",
        }
        candidates.append({**core, "evidence_fingerprint": content_fingerprint(core)})

    if iteration_numbers != set(range(1, expected_count + 1)):
        raise DailyStrategyArtifactRejected("daily_research_candidate_lineage_mismatch")
    candidates.sort(key=lambda item: item["iteration_number"])
    if source_research_selection is None:
        raise DailyStrategyArtifactRejected(
            "daily_research_candidate_source_selection_missing"
        )
    core = {
        "schema_version": VERIFIED_RESEARCH_CANDIDATE_STRATEGY_BATCH_SCHEMA,
        "run_id": selection.get("run_id"),
        "market_date": selection.get("market_date"),
        "selection_id": selection.get("selection_id"),
        "selection_fingerprint": selection.get("selection_fingerprint"),
        "backup_id": backup.get("backup_id"),
        "backup_artifact_fingerprint": backup.get("artifact_fingerprint"),
        "source_research_recommendation_fingerprint": recommendation.get(
            "evidence_fingerprint"
        ),
        "source_research_selection": source_research_selection,
        "source_research_selection_fingerprint": content_fingerprint(
            source_research_selection
        ),
        "research_winner_candidate_id": recommendation.get(
            "research_winner_candidate_id"
        ),
        "expected_candidate_count": expected_count,
        "candidate_strategies": candidates,
        "account_qualification_status": "not_evaluated",
        "provider_contact_performed": False,
        "database_writes_performed": False,
        "read_only": True,
        "research_only": True,
        "authorizes_strategy_promotion": False,
        "authorizes_order_creation": False,
        "authorizes_execution": False,
        "changes_capital_authority": False,
        "authority_effect": "none",
    }
    return {**core, "evidence_fingerprint": content_fingerprint(core)}


def _unique_candidate_items(
    values: Sequence[Any], *, error: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            raise DailyStrategyArtifactRejected(error)
        candidate_id = str(value.get("candidate_id") or "")
        if not candidate_id or candidate_id in result:
            raise DailyStrategyArtifactRejected(error)
        result[candidate_id] = value
    return result


def _valid_content_fingerprint(value: Any) -> bool:
    text = str(value or "")
    token = text.removeprefix("sha256:")
    return len(token) == 64 and all(
        char in "0123456789abcdef" for char in token.lower()
    )


def _valid_research_window(*, start_date: Any, end_date: Any, market_date: Any) -> bool:
    try:
        start = date.fromisoformat(str(start_date or ""))
        end = date.fromisoformat(str(end_date or ""))
        market = date.fromisoformat(str(market_date or ""))
    except ValueError:
        return False
    return start <= end == market


def _nonempty_text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    normalized = [str(item).strip() for item in value if str(item).strip()]
    if len(normalized) != len(value):
        return []
    return normalized


__all__ = [
    "VERIFIED_RESEARCH_CANDIDATE_STRATEGY_BATCH_SCHEMA",
    "VERIFIED_RESEARCH_CANDIDATE_STRATEGY_SCHEMA",
    "build_verified_research_candidate_strategy_batch",
]
