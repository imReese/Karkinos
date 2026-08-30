"""Research-winner ranking stays separate from promotion eligibility."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from server.contracts.content_identity import content_fingerprint
from server.projections.normalized_research_operation_preview import (
    build_normalized_research_operation_preview,
)
from server.projections.normalized_research_recommendation import (
    build_normalized_research_recommendation,
    is_valid_normalized_research_recommendation,
)


def _candidate(ordinal: int, *, total_return: float) -> dict:
    candidate_id = f"candidate-{ordinal}"
    return {
        "candidate_id": candidate_id,
        "run_id": "run-normalized",
        "draft_id": f"draft-{ordinal}",
        "critique_id": f"critique-{ordinal}",
        "status": "evaluated_research_only",
        "recommendation": "formula_research_candidate",
        "comparison": {
            "research_capital_mode": "normalized_notional",
            "account_qualification_status": "not_evaluated",
            "baseline_source_fingerprint": "sha256:" + "a" * 64,
            "candidate_source_fingerprint": "sha256:" + str(ordinal) * 64,
            "normalized_research_operation_preview": (
                build_normalized_research_operation_preview(
                    formula_ast={
                        "schema_version": "karkinos.ai.formula_ast.v1",
                        "entry": {
                            "op": "gt",
                            "left": {"op": "field", "name": "close"},
                            "right": {"op": "constant", "value": 10},
                        },
                        "exit": {
                            "op": "lt",
                            "left": {"op": "field", "name": "close"},
                            "right": {"op": "constant", "value": 9},
                        },
                        "position_size": {"op": "equal_weight"},
                    },
                    frames={
                        f"60000{ordinal}": pd.DataFrame(
                            {
                                "timestamp": ["2026-08-28"],
                                "open": [12],
                                "high": [12],
                                "low": [12],
                                "close": [12],
                                "volume": [100_000],
                            }
                        )
                    },
                    dataset_snapshot_id="sha256:" + "d" * 64,
                    formula_fingerprint="sha256:" + "f" * 64,
                    research_window_end_date="2026-08-28",
                    allocation_slots=1,
                )
            ),
            "candidate": {
                "dataset_snapshot_id": "sha256:" + "d" * 64,
                "initial_cash": 1_000_000,
                "total_return": total_return,
                "mean_oos_return": total_return / 2,
                "worst_oos_return": total_return / 4,
                "sharpe": 1 + ordinal / 10,
                "max_drawdown": 0.1,
                "total_cost": 1_000,
            },
            "iteration_lineage": {
                "iteration_number": ordinal,
                "total_iterations": 2,
                "formula_fingerprint": "sha256:" + "f" * 64,
                "parent_candidate_id": (
                    f"candidate-{ordinal - 1}" if ordinal > 1 else None
                ),
                "parent_draft_id": f"draft-{ordinal - 1}" if ordinal > 1 else None,
                "parent_formula_fingerprint": (
                    "sha256:" + "f" * 64 if ordinal > 1 else None
                ),
                "sequential_feedback_bound": True,
            },
        },
    }


@pytest.mark.unit
@pytest.mark.trading_safety
def test_selects_best_available_formula_without_promotion_authority() -> None:
    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[
            _candidate(1, total_return=0.05),
            _candidate(2, total_return=0.08),
        ],
        expected_candidate_count=2,
    )

    assert result["status"] == "best_available_for_further_research"
    assert result["research_winner_candidate_id"] == "candidate-2"
    assert result["account_qualification_status"] == "not_evaluated"
    assert result["account_qualified"] is False
    assert result["promotion_eligible"] is False
    assert result["paper_shadow_eligible"] is False
    assert result["decision_eligible"] is False
    assert result["execution_eligible"] is False
    operation_preview = result["research_operation_preview"]
    assert operation_preview["status"] == "available"
    assert operation_preview["research_winner_candidate_id"] == "candidate-2"
    assert operation_preview["dataset_snapshot_id"] == "sha256:" + "d" * 64
    assert operation_preview["formula_fingerprint"] == "sha256:" + "f" * 64
    assert operation_preview["operations"][0]["symbol"] == "600002"
    assert operation_preview["operations"][0]["operation"] == "buy_candidate"
    assert operation_preview["executable"] is False
    assert all(
        "normalized_research_operation_preview" not in item
        and "_operation_preview" not in item
        for item in result["ranked_candidates"]
    )
    assert is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_incomplete_candidate_set_has_no_research_recommendation() -> None:
    candidate = _candidate(1, total_return=0.05)
    candidate["comparison"]["iteration_lineage"]["total_iterations"] = 1
    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[candidate],
        expected_candidate_count=2,
    )

    assert result["status"] == "no_recommendation"
    assert result["research_winner_candidate_id"] is None
    assert "configured_normalized_candidate_set_incomplete" in result["blockers"]
    assert is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_tampered_recommendation_fails_validation() -> None:
    candidate = _candidate(1, total_return=0.05)
    candidate["comparison"]["iteration_lineage"]["total_iterations"] = 1
    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[candidate],
        expected_candidate_count=1,
    )

    result["promotion_eligible"] = True

    assert is_valid_normalized_research_recommendation(result) is False


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize("location", ["recommendation", "ranked_candidate"])
def test_rehashed_extra_fields_fail_the_public_recommendation_allowlist(
    location: str,
) -> None:
    candidate = _candidate(1, total_return=0.05)
    candidate["comparison"]["iteration_lineage"]["total_iterations"] = 1
    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[candidate],
        expected_candidate_count=1,
    )

    if location == "recommendation":
        result["account_id"] = "must-not-be-projected"
    else:
        result["ranked_candidates"][0]["quantity"] = 100
    core = dict(result)
    core.pop("evidence_fingerprint")
    result["evidence_fingerprint"] = content_fingerprint(core)

    assert is_valid_normalized_research_recommendation(result) is False


@pytest.mark.unit
@pytest.mark.trading_safety
def test_duplicate_or_broken_lineage_cannot_publish_research_winner() -> None:
    first = _candidate(1, total_return=0.05)
    duplicate = _candidate(2, total_return=0.08)
    duplicate["candidate_id"] = first["candidate_id"]

    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[first, duplicate],
        expected_candidate_count=2,
    )

    assert result["status"] == "no_recommendation"
    assert result["research_winner_candidate_id"] is None
    assert "normalized_candidate_identity_conflict" in result["blockers"]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_broken_parent_lineage_cannot_publish_research_winner() -> None:
    first = _candidate(1, total_return=0.05)
    second = _candidate(2, total_return=0.08)
    second["comparison"]["iteration_lineage"][
        "parent_candidate_id"
    ] = "candidate-from-another-run"

    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[first, second],
        expected_candidate_count=2,
    )

    assert result["status"] == "no_recommendation"
    assert result["research_winner_candidate_id"] is None
    assert "normalized_candidate_iteration_lineage_invalid" in result["blockers"]


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize("identity", ["formula_fingerprint", "dataset_snapshot_id"])
def test_rehashed_preview_with_mismatched_formula_or_dataset_is_not_published(
    identity: str,
) -> None:
    candidate = _candidate(1, total_return=0.05)
    candidate["comparison"]["iteration_lineage"]["total_iterations"] = 1
    preview = deepcopy(candidate["comparison"]["normalized_research_operation_preview"])
    preview[identity] = "sha256:" + "9" * 64
    core = dict(preview)
    core.pop("evidence_fingerprint")
    preview["evidence_fingerprint"] = content_fingerprint(core)
    candidate["comparison"]["normalized_research_operation_preview"] = preview

    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[candidate],
        expected_candidate_count=1,
    )

    assert result["status"] == "best_available_for_further_research"
    assert result["research_operation_preview"]["status"] == "unavailable"
    assert result["research_operation_preview"]["operations"] == []
    assert is_valid_normalized_research_recommendation(result)
