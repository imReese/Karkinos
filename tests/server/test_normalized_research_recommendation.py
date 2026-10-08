"""Research-winner ranking stays separate from promotion eligibility."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from backtest.costs import RESEARCH_COST_STRESS_BPS, research_friction_assumptions
from server.ai_runtime.strategy_research_privacy import (
    build_normalized_robustness_evidence,
)
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


def _add_stress(
    candidate: dict,
    returns: tuple[float, float],
    *,
    baseline_returns: tuple[float, float] = (0.04, 0.03),
) -> dict:
    comparison = candidate["comparison"]
    costs = {
        **research_friction_assumptions(),
        "commission_model_reference": "canonical-default-estimate",
    }
    comparison["baseline"] = {
        "result_id": 1,
        "dataset_snapshot_id": comparison["candidate"]["dataset_snapshot_id"],
        "cost_assumptions": costs,
    }
    comparison["candidate"].update(result_id=2, cost_assumptions=costs)
    comparison["research_feedback"] = {
        "comparison_reference": "baseline",
        "return_unit": "fraction",
        **{
            label: {
                "result_id": comparison[label]["result_id"],
                **build_normalized_robustness_evidence(
                    {
                        "cost_sensitivity": [
                            {
                                **research_friction_assumptions(bps),
                                "total_return": net_return,
                            }
                            for bps, net_return in zip(
                                RESEARCH_COST_STRESS_BPS, outcomes, strict=True
                            )
                        ]
                    }
                ),
            }
            for label, outcomes in (
                ("baseline", baseline_returns),
                ("candidate", returns),
            )
        },
    }
    return candidate


def _recommend(candidates: list[dict]) -> dict:
    return build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=candidates,
        expected_candidate_count=2,
    )


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
    assert all(
        item["cost_stress"]
        == {
            "status": "unavailable",
            "reason": "cost_stress_evidence_missing",
            "scenarios": [],
            "worst_excess_return": None,
        }
        for item in result["ranked_candidates"]
    )


@pytest.mark.unit
@pytest.mark.trading_safety
def test_worst_stress_net_excess_beats_higher_base_net_return() -> None:
    result = _recommend(
        [
            _add_stress(_candidate(1, total_return=0.12), (0.08, 0.02)),
            _add_stress(_candidate(2, total_return=0.10), (0.07, 0.06)),
        ]
    )
    assert result["research_winner_candidate_id"] == "candidate-2"
    winner, loser = result["ranked_candidates"]
    assert winner["cost_stress"]["worst_excess_return"] == pytest.approx(0.03)
    assert loser["cost_stress"]["worst_excess_return"] == pytest.approx(-0.01)
    assert (
        result["research_operation_preview"]["research_winner_candidate_id"]
        == "candidate-2"
    )
    assert is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_stress_excess_pairs_the_same_baseline_scenario_in_any_input_order() -> None:
    first = _add_stress(
        _candidate(1, total_return=0.12), (0.10, 0.02), baseline_returns=(0.09, 0.01)
    )
    second = _add_stress(
        _candidate(2, total_return=0.15), (0.08, 0.08), baseline_returns=(0.09, 0.01)
    )
    first["comparison"]["research_feedback"]["baseline"]["cost_sensitivity"].reverse()
    result = _recommend([second, first])
    assert result["research_winner_candidate_id"] == "candidate-1"
    stress = result["ranked_candidates"][0]["cost_stress"]
    assert [row["slippage_bps"] for row in stress["scenarios"]] == [10, 25]
    assert [row["excess_return"] for row in stress["scenarios"]] == pytest.approx(
        [0.01, 0.01]
    )


@pytest.mark.unit
@pytest.mark.trading_safety
@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "partial",
        "duplicate",
        "failed",
        "running",
        "failure_code",
        "nan",
        "infinite",
        "model",
        "slippage_bps",
        "participation",
        "result_id",
        "snapshot",
        "commission",
        "unit",
    ],
)
def test_incomplete_stress_never_becomes_zero_excess_or_outranks_measured_losses(
    defect,
) -> None:
    unknown = _add_stress(_candidate(1, total_return=0.90), (0.50, 0.40))
    comparison = unknown["comparison"]
    panel = comparison["research_feedback"]["candidate"]
    scenarios = panel["cost_sensitivity"]
    if defect == "missing":
        panel.pop("cost_sensitivity")
    elif defect == "partial":
        scenarios.pop()
    elif defect == "duplicate":
        scenarios[1] = deepcopy(scenarios[0])
    elif defect in {"failed", "running"}:
        scenarios[0]["status"] = defect
    elif defect == "failure_code":
        scenarios[0]["status"] = "completed"
        scenarios[0]["failure_code"] = "stress_replay_failed"
    elif defect in {"nan", "infinite"}:
        scenarios[0]["total_return"] = "nan" if defect == "nan" else "inf"
    elif defect == "model":
        scenarios[0]["execution_cost_model_id"] = "different-model"
    elif defect == "slippage_bps":
        scenarios[0]["slippage_bps"] = 11
    elif defect == "participation":
        scenarios[0]["max_volume_participation"] = 0.05
    elif defect == "result_id":
        panel["result_id"] = 99
    elif defect == "snapshot":
        comparison["baseline"]["dataset_snapshot_id"] = "sha256:" + "e" * 64
    elif defect == "commission":
        comparison["baseline"]["cost_assumptions"] = {
            "commission_model_reference": "other"
        }
    elif defect == "unit":
        comparison["research_feedback"]["return_unit"] = "percent"
    measured = _add_stress(_candidate(2, total_return=0.1), (-0.02, -0.08))
    result = _recommend([unknown, measured])
    assert result["research_winner_candidate_id"] == "candidate-2"
    assert result["ranked_candidates"][0]["cost_stress"][
        "worst_excess_return"
    ] == pytest.approx(-0.11)
    unavailable = result["ranked_candidates"][1]["cost_stress"]
    assert unavailable["status"] == "unavailable"
    assert unavailable["worst_excess_return"] is None
    assert unavailable["scenarios"] == []
    assert unavailable["reason"]
    assert is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_equal_stress_keeps_existing_base_net_return_tiebreak() -> None:
    result = _recommend(
        [
            _add_stress(_candidate(1, total_return=0.10), (0.07, 0.06)),
            _add_stress(_candidate(2, total_return=0.12), (0.07, 0.06)),
        ]
    )
    assert result["research_winner_candidate_id"] == "candidate-2"


@pytest.mark.unit
@pytest.mark.trading_safety
def test_rehashed_stress_summary_must_reconcile_its_excess_return() -> None:
    result = _recommend(
        [
            _add_stress(_candidate(1, total_return=0.1), (0.07, 0.06)),
            _candidate(2, total_return=0.12),
        ]
    )
    result["ranked_candidates"][0]["cost_stress"]["worst_excess_return"] = 0.90
    result.pop("evidence_fingerprint")
    result["evidence_fingerprint"] = content_fingerprint(result)
    assert not is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_provider_free_blocked_iteration_does_not_poison_later_viable_candidate() -> (
    None
):
    first = _add_stress(_candidate(1, total_return=0.90), (0.80, 0.70))
    first["status"] = "research_blocked"
    first["recommendation"] = "keep_researching"
    first["critique_id"] = None
    first["comparison"]["research_gate"] = {
        "schema_version": "karkinos.normalized_research_provider_preflight.v1",
        "status": "blocked",
        "blockers": ["candidate_after_cost_oos_excess_not_positive"],
        "provider_call_performed": False,
    }
    second = _add_stress(_candidate(2, total_return=0.08), (0.07, 0.06))

    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=[first, second],
        expected_candidate_count=2,
    )

    assert result["status"] == "best_available_for_further_research"
    assert result["research_winner_candidate_id"] == "candidate-2"
    assert result["evaluated_candidate_count"] == 1
    assert result["blockers"] == []
    assert is_valid_normalized_research_recommendation(result)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_all_provider_free_blocked_iterations_publish_no_recommendation() -> None:
    candidates = [
        _candidate(1, total_return=0.01),
        _candidate(2, total_return=0.02),
    ]
    for candidate in candidates:
        candidate["status"] = "research_blocked"
        candidate["recommendation"] = "keep_researching"
        candidate["critique_id"] = None
        candidate["comparison"]["research_gate"] = {
            "schema_version": "karkinos.normalized_research_provider_preflight.v1",
            "status": "blocked",
            "blockers": ["candidate_after_cost_oos_excess_not_positive"],
            "provider_call_performed": False,
        }

    result = build_normalized_research_recommendation(
        run_id="run-normalized",
        market_date="2026-08-28",
        candidates=candidates,
        expected_candidate_count=2,
    )

    assert result["status"] == "no_recommendation"
    assert result["research_winner_candidate_id"] is None
    assert result["evaluated_candidate_count"] == 0
    assert result["blockers"] == ["no_normalized_candidate_passed_provider_free_gate"]
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
    second["comparison"]["iteration_lineage"]["parent_candidate_id"] = (
        "candidate-from-another-run"
    )

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
