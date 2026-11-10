import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from analytics.deployment_validation import compare_session_curves
from analytics.sealed_holdout import build_sealed_partition, sealed_return_from_result
from backtest.result import BacktestResult
from server.contracts.content_identity import content_fingerprint
from server.contracts.recommendation_publication import (
    FINAL_STATISTICAL_POLICY_SCHEMA,
    validate_final_statistical_policy,
)


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
    # Captured from the unchanged v1 owner before adding the v2 branch.
    assert first["evidence_fingerprint"] == (
        "1e8b269a544af42c56b7abb3de0e0b748303ca0d7dd3d0ce1e2e268d861442c2"
    )
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


def _future_curve(rate, count=60):
    rows = _curve(rate, count)
    start = datetime(2027, 2, 12) - timedelta(days=count - 1)
    return [
        [(start + timedelta(days=index)).isoformat(), row[1]]
        for index, row in enumerate(rows)
    ]


def _v2_arguments():
    bindings = {
        label: {
            "role": "primary" if label == "Gen7" else "diagnostic",
            "identity_fingerprint": "sha256:"
            + content_fingerprint({"synthetic_executable_source": label}),
        }
        for label in ("Gen7", "MA", "random")
    }
    policy = {
        **_policy(),
        "schema_version": FINAL_STATISTICAL_POLICY_SCHEMA,
        "research_policy_fingerprint": (
            "sha256:cbe4acc461643454490d81db9f2688c4938f4f49a14ba0131ff7be5c275ccbc4"
        ),
        "decision_checkpoint": "2027-02-13",
        "minimum_effective_blocks": 12,
        "bootstrap_samples": 100000,
        "minimum_net_excess": "0",
        "minimum_candidate_net_return": "0",
        "minimum_annualized_relative_wealth": "0.03",
        "maximum_drawdown": "0.15",
        "primary_comparator": "Gen7",
        "comparator_bindings": bindings,
    }
    return {
        "candidate": _future_curve(0.002),
        "comparators": {
            "Gen7": _future_curve(0.001),
            "MA": _future_curve(0.003),
            "random": _future_curve(0),
        },
        "initial_cash": 100000,
        "policy": policy,
        "policy_fingerprint": content_fingerprint(policy),
        "comparator_bindings": deepcopy(bindings),
        "effective_checkpoint": "2027-02-12",
        "seed": "frozen-v2-reservation",
    }


def test_v2_primary_advantage_retains_losing_secondary_and_full_alpha_denominator():
    arguments = _v2_arguments()
    result = compare_session_curves(**arguments)
    assert result["schema_version"] == "karkinos.deployment_uncertainty.v2"
    assert result["status"] == "pass"
    assert result["policy_fingerprint"] == arguments["policy_fingerprint"]
    assert result["policy"]["decision_checkpoint"] == "2027-02-13"
    assert result["effective_checkpoint"] == "2027-02-12"
    assert result["authority_effect"] == "none"
    comparisons = {row["label"]: row for row in result["comparisons"]}
    assert set(comparisons) == {"Gen7", "MA", "random"}
    assert comparisons["MA"]["net_excess_lower_bound"] < 0
    assert comparisons["Gen7"]["net_excess_lower_bound"] > 0
    assert all(row["one_sided_alpha"] == 0.05 / 3 for row in comparisons.values())
    arguments["comparators"]["Gen7"] = _future_curve(0.003)
    failed = compare_session_curves(**arguments)
    assert failed["status"] == "insufficient_evidence"
    assert "deployment_primary_net_excess_not_established" in failed["blockers"]


@pytest.mark.parametrize(
    "case", ["missing_curve", "missing_bindings", "wrong_identity"]
)
def test_v2_requires_every_frozen_executable_comparator_identity(case):
    arguments = _v2_arguments()
    if case == "missing_curve":
        arguments["comparators"].pop("MA")
    elif case == "missing_bindings":
        arguments.pop("comparator_bindings")
    else:
        arguments["comparator_bindings"]["Gen7"]["identity_fingerprint"] = (
            "sha256:" + "f" * 64
        )
    with pytest.raises(ValueError, match="identity_binding_mismatch"):
        compare_session_curves(**arguments)


def test_v2_secondary_misalignment_is_not_waived_by_diagnostic_role():
    arguments = _v2_arguments()
    arguments["comparators"]["MA"][0][0] = "2026-01-01"
    with pytest.raises(ValueError, match="interval_mismatch"):
        compare_session_curves(**arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minimum_observations", 59),
        ("block_length", 4),
        ("minimum_effective_blocks", 10),
        ("bootstrap_samples", 99999),
        ("significance_level", "0.051"),
        ("minimum_net_excess", "0.01"),
        ("minimum_candidate_net_return", "-0.01"),
        ("minimum_annualized_relative_wealth", "0.02"),
        ("maximum_drawdown", "0.30"),
        ("research_policy_fingerprint", "unbound"),
    ],
)
def test_v2_profile_requires_explicit_accepted_frozen_thresholds(field, value):
    policy = _v2_arguments()["policy"]
    policy[field] = value
    with pytest.raises(ValueError, match="statistical_frozen_profile_mismatch"):
        validate_final_statistical_policy(policy, content_fingerprint(policy))


def test_v2_rejects_ambiguous_roles_unknown_fields_and_unbound_policy():
    arguments = _v2_arguments()
    with pytest.raises(ValueError, match="policy_binding_invalid"):
        compare_session_curves(**{**arguments, "policy_fingerprint": "wrong"})
    for change in (
        "second_primary",
        "missing_role",
        "duplicate_identity",
        "unknown_field",
    ):
        policy = deepcopy(arguments["policy"])
        if change == "second_primary":
            policy["comparator_bindings"]["MA"]["role"] = "primary"
        elif change == "missing_role":
            policy["comparator_bindings"]["MA"].pop("role")
        elif change == "duplicate_identity":
            policy["comparator_bindings"]["MA"]["identity_fingerprint"] = policy[
                "comparator_bindings"
            ]["Gen7"]["identity_fingerprint"]
        else:
            policy["ignore_missing_secondary"] = True
        with pytest.raises(ValueError):
            validate_final_statistical_policy(policy, content_fingerprint(policy))
    policy = deepcopy(arguments["policy"])
    policy.pop("schema_version")
    with pytest.raises(ValueError, match="version_unsupported"):
        validate_final_statistical_policy(policy, content_fingerprint(policy))
    with pytest.raises(ValueError, match="version_unsupported"):
        compare_session_curves(**{**arguments, "policy": policy})


def test_v2_forbids_checkpoint_roll_forward_while_v1_keeps_existing_interval():
    v1 = {**_policy(), "checkpoint_interval_days": 120}
    assert validate_final_statistical_policy(v1, content_fingerprint(v1)) == v1
    arguments = _v2_arguments()
    arguments["policy"]["checkpoint_interval_days"] = 120
    arguments["policy_fingerprint"] = content_fingerprint(arguments["policy"])
    with pytest.raises(ValueError, match="statistical_frozen_profile_mismatch"):
        compare_session_curves(**arguments)


def test_v2_requires_real_checkpoint_mapping_and_sample_coverage():
    arguments = _v2_arguments()
    with pytest.raises(ValueError, match="effective_checkpoint_required"):
        compare_session_curves(**{**arguments, "effective_checkpoint": None})
    with pytest.raises(ValueError, match="after_frozen_deadline"):
        compare_session_curves(**{**arguments, "effective_checkpoint": "2027-02-14"})
    short = {
        **arguments,
        "candidate": arguments["candidate"][1:],
        "comparators": {
            key: rows[1:] for key, rows in arguments["comparators"].items()
        },
    }
    result = compare_session_curves(**short)
    assert "deployment_independent_sample_insufficient" in result["blockers"]
    assert result["observation_count"] == 59 and result["effective_blocks"] == 11
    assert all(row["net_excess_lower_bound"] is None for row in result["comparisons"])
    arguments["policy"]["significance_level"] = "0.0001"
    arguments["policy_fingerprint"] = content_fingerprint(arguments["policy"])
    underresolved = compare_session_curves(**arguments)
    assert "deployment_independent_sample_insufficient" in underresolved["blockers"]


@pytest.mark.parametrize(
    ("candidate_rate", "primary_rate", "expected"),
    [
        (-0.001, -0.002, "deployment_candidate_net_return_not_positive"),
        (0.00005, 0, "deployment_primary_relative_growth_below_floor"),
    ],
)
def test_v2_primary_lower_bound_alone_does_not_pass_point_economics(
    candidate_rate, primary_rate, expected
):
    arguments = _v2_arguments()
    arguments["candidate"] = _future_curve(candidate_rate)
    arguments["comparators"]["Gen7"] = _future_curve(primary_rate)
    result = compare_session_curves(**arguments)
    assert expected in result["blockers"]
    assert (
        next(row for row in result["comparisons"] if row["label"] == "Gen7")[
            "net_excess_lower_bound"
        ]
        > 0
    )


@pytest.mark.parametrize(
    ("first_equity", "breached"), [("85000", False), ("84999.99", True)]
)
def test_v2_drawdown_includes_initial_cash_and_preserves_exact_fifteen_percent_boundary(
    first_equity, breached
):
    arguments = _v2_arguments()
    arguments["candidate"][0][1] = first_equity
    result = compare_session_curves(**arguments)
    assert (
        "deployment_candidate_drawdown_budget_exceeded" in result["blockers"]
    ) is breached
    if not breached:
        assert Decimal(result["future_metrics"]["candidate_max_drawdown"]) == Decimal(
            "0.15"
        )
