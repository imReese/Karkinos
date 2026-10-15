import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from analytics.deployment_validation import compare_session_curves
from analytics.sealed_holdout import build_sealed_partition, sealed_return_from_result
from backtest.result import BacktestResult


def _curve(rate, count=60):
    equity = Decimal("100000")
    result = []
    for index in range(count):
        equity *= Decimal(1) + Decimal(str(rate))
        result.append(
            [(datetime(2026, 1, 1) + timedelta(days=index)).isoformat(), str(equity)]
        )
    return result


def _policy(count=60):
    return {
        "method": "paired_moving_block_bootstrap.v1",
        "minimum_observations": 60,
        "block_length": 5,
        "minimum_effective_blocks": 10,
        "bootstrap_samples": 4000,
        "significance_level": "0.05",
        "minimum_net_excess": "0.001",
        "decision_checkpoint": _curve(0, count)[-1][0][:10],
    }


def test_paired_uncertainty_requires_all_comparators_and_replays():
    arguments = dict(
        candidate=_curve(0.002),
        comparators={"baseline": _curve(0), "simple": _curve(0.001)},
        initial_cash=100000,
        policy=_policy(),
        seed="frozen-reservation",
    )
    first = compare_session_curves(**arguments)
    assert first["status"] == "pass"
    assert first == compare_session_curves(**arguments)
    assert all(row["net_excess_lower_bound"] > 0.001 for row in first["comparisons"])
    arguments["comparators"]["incumbent"] = _curve(0.003)
    failed = compare_session_curves(**arguments)
    assert failed["status"] == "insufficient_evidence"
    assert "deployment_net_excess_not_established" in failed["blockers"]


def test_short_or_underresolved_sample_cannot_pass_despite_large_return():
    result = compare_session_curves(
        candidate=_curve(0.03, 59),
        comparators={"baseline": _curve(0, 59)},
        initial_cash=100000,
        policy=_policy(59),
        seed="fixed",
    )
    assert result["status"] == "insufficient_evidence"
    assert result["comparisons"][0]["net_excess_lower_bound"] is None
    policy = {**_policy(), "bootstrap_samples": 100}
    result = compare_session_curves(
        candidate=_curve(0.03),
        comparators={"baseline": _curve(0)},
        initial_cash=100000,
        policy=policy,
        seed="fixed",
    )
    assert result["status"] == "insufficient_evidence"


def test_positive_realized_excess_without_stable_advantage_cannot_publish():
    case = json.loads(
        (
            Path(__file__).parent / "fixtures/synthetic_deployment_rejection.json"
        ).read_text()
    )
    result = compare_session_curves(**case["arguments"])
    assert result["status"] == case["expected_status"] == "insufficient_evidence"
    assert result["observation_count"] == 60
    assert len(result["comparisons"]) == 9
    assert all(row["relative_net_excess"] > 0 for row in result["comparisons"])
    assert any(row["net_excess_lower_bound"] < 0 for row in result["comparisons"])
    assert result["blockers"] == ["deployment_net_excess_not_established"]


def test_paired_dates_must_match_exactly():
    benchmark = _curve(0)
    benchmark[0][0] = "2025-12-31T00:00:00"
    with pytest.raises(ValueError, match="interval_mismatch"):
        compare_session_curves(
            candidate=_curve(0.002),
            comparators={"baseline": benchmark},
            initial_cash=100000,
            policy=_policy(),
            seed="fixed",
        )


def test_sealed_session_boundary_accepts_real_utc_dataset_timestamps():
    from datetime import timezone
    from types import SimpleNamespace

    partition = build_sealed_partition(
        research_start="2025-01-01", research_end="2025-12-31", sealed_end="2026-03-01"
    )
    result = SimpleNamespace(
        equity_curve=[(datetime(2026, 1, 1, 7, tzinfo=timezone.utc), Decimal("900"))],
        initial_cash=Decimal("1000"),
        execution_timing={
            "evaluation_start": "2026-01-01",
            "warmup_basis": "strategy_history_only_fresh_book",
            "warmup_final_bar_targets": True,
        },
    )
    assert sealed_return_from_result(result, partition) == Decimal("-0.1")
