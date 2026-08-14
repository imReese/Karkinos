from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from analytics.sweep_robustness import (
    build_sweep_robustness_evidence,
    is_valid_passed_sweep_robustness_evidence,
)


def _passing_evidence() -> dict:
    return build_sweep_robustness_evidence(
        results=[
            {"params": {"window": window}, "score": score}
            for window, score in (
                (3, 0.85),
                (4, 0.9),
                (5, 1.0),
                (6, 0.9),
                (7, 0.85),
            )
        ],
        rank_by="after_cost_total_return",
        rank_direction="desc",
        selected_params={"window": 5},
    )


def test_sweep_robustness_validator_replays_complete_tested_grid() -> None:
    evidence = _passing_evidence()

    assert evidence["tested_count"] == 5
    assert len(evidence["tested_results"]) == 5
    assert evidence["best_params"] == {"window": 5}
    assert evidence["overfitting_warnings"] == []
    assert (
        is_valid_passed_sweep_robustness_evidence(
            evidence,
            expected_selected_params={"window": 5},
        )
        is True
    )


def test_sweep_robustness_validator_rejects_rehashed_summary_or_grid_conflict() -> None:
    evidence = _passing_evidence()
    summary_conflict = deepcopy(evidence)
    summary_conflict["local_stability"]["stability_ratio"] = 0.99
    summary_conflict = _refingerprint(summary_conflict)
    grid_conflict = deepcopy(evidence)
    grid_conflict["tested_results"][0]["score"] = 99
    grid_conflict = _refingerprint(grid_conflict)
    duplicate_grid = deepcopy(evidence)
    duplicate_grid["tested_results"][0] = deepcopy(duplicate_grid["tested_results"][1])
    duplicate_grid = _refingerprint(duplicate_grid)

    for value in (summary_conflict, grid_conflict, duplicate_grid):
        assert (
            is_valid_passed_sweep_robustness_evidence(
                value,
                expected_selected_params={"window": 5},
            )
            is False
        )


def _refingerprint(value: dict) -> dict:
    payload = deepcopy(value)
    payload.pop("evidence_fingerprint", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **payload,
        "evidence_fingerprint": hashlib.sha256(encoded).hexdigest(),
    }
