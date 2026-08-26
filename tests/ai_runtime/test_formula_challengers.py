from __future__ import annotations

import pytest

from server.ai_runtime.formula_challengers import (
    build_challenger_comparison,
    generate_deterministic_challenger_formulas,
    generate_random_challenger_formulas,
)
from server.ai_runtime.formula_dsl import validate_formula_ast


def _validate_all(formulas: list[dict]) -> None:
    for item in formulas:
        validate_formula_ast(item["formula_ast"], universe_size=4)


def test_deterministic_challenger_formulas_are_valid_and_unique():
    formulas = generate_deterministic_challenger_formulas()
    assert len(formulas) == 14  # 5 MA + 6 RSI + 3 momentum
    _validate_all(formulas)
    labels = [item["label"] for item in formulas]
    assert len(labels) == len(set(labels))
    assert formulas == generate_deterministic_challenger_formulas()


def test_random_challenger_formulas_are_seeded_and_valid():
    formulas = generate_random_challenger_formulas(seed=42, count=12)
    assert len(formulas) == 12
    _validate_all(formulas)
    labels = [item["label"] for item in formulas]
    assert len(labels) == len(set(labels))
    assert formulas == generate_random_challenger_formulas(seed=42, count=12)
    assert formulas != generate_random_challenger_formulas(seed=43, count=12)


def test_random_challenger_formulas_reject_invalid_count():
    with pytest.raises(ValueError):
        generate_random_challenger_formulas(seed=1, count=0)


def test_challenger_comparison_ranks_champion():
    evidence = build_challenger_comparison(
        champion_return=0.05,
        challenger_returns=[0.01, 0.02, 0.03, 0.04],
    )
    assert evidence["champion_rank_percentile"] == 1.0
    assert evidence["champion_beats_all_challengers"] is True
    assert evidence["ai_increment_over_max_challenger"] == pytest.approx(0.01)
    assert evidence["challenger_mean_return"] == pytest.approx(0.025)
    assert len(evidence["evidence_fingerprint"]) == 64


def test_challenger_comparison_reports_negative_increment():
    evidence = build_challenger_comparison(
        champion_return=0.01,
        challenger_returns=[0.02, 0.03],
    )
    assert evidence["champion_rank_percentile"] == 0.0
    assert evidence["champion_beats_all_challengers"] is False
    assert evidence["ai_increment_over_max_challenger"] == pytest.approx(-0.02)


def test_challenger_comparison_rejects_invalid_inputs():
    with pytest.raises(ValueError):
        build_challenger_comparison(champion_return=0.01, challenger_returns=[])
    with pytest.raises(ValueError):
        build_challenger_comparison(
            champion_return=0.01, challenger_returns=[0.01, float("nan")]
        )
