"""Synthetic full manual evidence; no real observations or account authority."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal

import pytest

from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.deployment_validation import compare_session_curves
from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from analytics.sealed_holdout import final_research_evaluation_blocker
from analytics.strategy_advancement_gate import (
    MANUAL_FINAL_V2_ADVANCEMENT_GATE_SCHEMA,
    build_manual_final_strategy_advancement_gate,
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from server.contracts.content_identity import content_fingerprint
from tests.analytics.test_strategy_advancement_gate import _view
from tests.server.test_manual_final_v2_gate import late_calendar_final  # noqa: F401
from tests.server.test_research_final_evaluation import harness  # noqa: F401
from tests.server.test_research_final_statistical_v2 import v2  # noqa: F401


def seal(value):
    value.pop("evidence_fingerprint", None)
    value["evidence_fingerprint"] = content_fingerprint(value)
    return value


def account_view(*, candidate, cash):
    value = _view(candidate=candidate)
    scale = cash / Decimal(value["initial_cash"])
    for key in ("initial_cash", "final_equity", "net_pnl"):
        value[key] = float(Decimal(str(value[key])) * scale)
    for point in value["equity_curve"]:
        point["equity"] = float(Decimal(str(point["equity"])) * scale)
    value["drawdown_evidence"] = build_backtest_drawdown_evidence(
        equity_curve=value["equity_curve"], initial_cash=cash
    )
    value["gross_pnl_before_costs"] = value["net_pnl"] + value["total_cost"]
    value["gross_return_before_costs"] = value["gross_pnl_before_costs"] / float(cash)
    value["cost_to_initial_cash"] = value["total_cost"] / float(cash)
    capacity = value["capacity_review"]
    capacity["capacity_utilization_pct"] = str(Decimal(value["gross_turnover"]) / cash)
    capacity["observations"][0]["capacity_utilization_pct"] = capacity[
        "capacity_utilization_pct"
    ]
    seal(capacity)
    value["account_capital_constraint"] = build_research_account_capital_evidence(
        initial_cash=cash,
        account_evidence={
            "status": "complete",
            "persisted_facts_only": True,
            "record_fingerprint": "8" * 64,
            "valuation_snapshot_id": "valuation-reviewed-fixture",
            "ledger_cutoff_id": 42,
            "payload": {
                key: {
                    "valuation_snapshot_id": "valuation-reviewed-fixture",
                    "ledger_cutoff_id": 42,
                    "valuation_status": "complete",
                    "total_equity": float(cash),
                }
                for key in ("summary", "snapshot")
            },
        },
        fee_schedule_evidence={
            "account_specific": True,
            "broker_statement_reconciled": True,
            "account_truth_source_fingerprint": "sha256:" + "d" * 64,
            "account_truth_scope_fingerprint": "sha256:" + "e" * 64,
        },
        expected_valuation_snapshot_id="valuation-reviewed-fixture",
        expected_ledger_cutoff_id=42,
    )
    fee = value["fee_component_evidence"]["fee_schedule_binding"]
    fee["fee_schedule_fingerprint"] = "sha256:" + "f" * 64
    seal(value["fee_component_evidence"])
    value["cost_assumptions"] = {
        "commission_model_reference": "karkinos.backtest.reviewed_account_fee_schedule.v1:"
        + fee["fee_schedule_review_id"]
        + ":"
        + fee["fee_schedule_review_fingerprint"].removeprefix("sha256:")
    }
    return value


@pytest.fixture
def manual_gate_inputs(late_calendar_final, v2):
    final = deepcopy(late_calendar_final)
    binding = final["reservation"]
    sim = binding["simulation_policy"]
    sim.update(max_final_tests=1, total_error_budget="0.05")
    binding["error_budget"] = {
        "attempt_count": 1,
        "allocated_alpha": "0.05",
        "error_budget_spent": "0.05",
    }
    refs = {key: binding[key] for key in ("session_id", "draft_id", "backtest_run_id")}
    refs.update(
        critique_id="synthetic-critique",
        canonical_backtest_result_id=binding["candidate_result_id"],
    )
    binding.update(
        source_kind="manual_research",
        manual_source_refs=refs,
        manual_source_fingerprint="sha256:" + "1" * 64,
    )
    # The existing producer fixture isolates the uncertainty owner; attach its
    # explicit actual risk measurements rather than borrowing risk budgets.
    original_assessment = final["deployment_assessment"]
    original_assessment["risk_limits"] = {
        "max_drawdown": "0",
        "max_gross_weight": "0",
        "max_symbol_weight": "0",
        "max_positions": 0,
    }
    original_assessment["statistical_policy_fingerprint"] = sim[
        "statistical_policy_fingerprint"
    ]
    seal(original_assessment)
    seal(final)
    assert final_research_evaluation_blocker(final) is None
    source = {
        "source_kind": "manual_research",
        "manual_source_refs": refs,
        "manual_source_fingerprint": binding["manual_source_fingerprint"],
        "final_evaluation_id": final["sealed_test_id"],
        "final_evidence_fingerprint": final["evidence_fingerprint"],
    }
    cash = Decimal(binding["initial_cash"])
    baseline = account_view(candidate=False, cash=cash)
    candidate = account_view(candidate=True, cash=cash)
    candidate.update(
        formula_ast=v2.h.draft["formula_ast"],
        formula_fingerprint="sha256:" + "2" * 64,
        independent_evaluation=final,
    )
    fee = candidate["fee_component_evidence"]["fee_schedule_binding"]
    profile = deepcopy(sim["statistical_policy"])
    # Fee-rebound comparator identities deliberately differ from original ones.
    profile["comparator_bindings"] = {
        label: {
            "role": value["role"],
            "identity_fingerprint": "sha256:"
            + content_fingerprint({"label": label, "fee": fee}),
        }
        for label, value in profile["comparator_bindings"].items()
    }
    uncertainty = compare_session_curves(
        candidate=final["session_curves"]["candidate"],
        comparators=final["session_curves"]["comparators"],
        initial_cash=binding["initial_cash"],
        policy=profile,
        seed=final["sealed_test_id"],
        policy_fingerprint=content_fingerprint(profile),
        comparator_bindings=profile["comparator_bindings"],
        effective_checkpoint=original_assessment["effective_checkpoint"],
    )
    assessment = seal(
        {
            **original_assessment,
            "uncertainty": uncertainty,
            "statistical_policy_fingerprint": content_fingerprint(profile),
        }
    )
    proof = {
        "schema_version": "karkinos.simulation_account_cost_replay.v2",
        "manual_source_binding": source,
        "final_evaluation_id": final["sealed_test_id"],
        "final_evidence_fingerprint": final["evidence_fingerprint"],
        "reservation_fingerprint": content_fingerprint(binding),
        "qualified_formula_fingerprint": candidate["formula_fingerprint"],
        "review_id": fee["fee_schedule_review_id"],
        "review_fingerprint": fee["fee_schedule_review_fingerprint"],
        "cost_model_reference": candidate["cost_assumptions"][
            "commission_model_reference"
        ],
        "fee_evidence_fingerprint": content_fingerprint(fee),
        "initial_cash": binding["initial_cash"],
        "code_fingerprint": binding["code_binding"]["fingerprint"],
        "curves_fingerprint": content_fingerprint(final["session_curves"]),
        "portfolio_fingerprint": content_fingerprint(final["portfolio_observations"]),
        "account_scope_fingerprint": fee["account_truth_scope_fingerprint"],
        "statistical_requirements": {
            k: v for k, v in profile.items() if k != "comparator_bindings"
        },
        "reviewed_replay": {
            "deployment_assessment": assessment,
            "session_curves": deepcopy(final["session_curves"]),
            "fee_schedule": {
                "review_id": fee["fee_schedule_review_id"],
                "review_fingerprint": fee["fee_schedule_review_fingerprint"],
                "cost_model_reference": candidate["cost_assumptions"][
                    "commission_model_reference"
                ],
                "fee_evidence": fee,
            },
        },
    }
    candidate["simulation_account_replay"] = seal(proof)
    return dict(
        baseline=baseline,
        candidate=candidate,
        source_binding=source,
        critique_evidence={
            "status": "completed",
            "critique_id": refs["critique_id"],
            "artifact_fingerprint": "e" * 64,
        },
    )


def test_manual_profile_consumes_real_v2_evidence_retains_legacy_failures(
    manual_gate_inputs,
):
    inputs = manual_gate_inputs
    inputs["candidate"].pop("parameter_robustness")
    inputs["candidate"].pop("market_regime_robustness")
    before = deepcopy(inputs)
    payload = build_manual_final_strategy_advancement_gate(**inputs).to_json_dict()
    assert payload["status"] == "pass", payload["blockers"]
    assert payload["schema_version"] == MANUAL_FINAL_V2_ADVANCEMENT_GATE_SCHEMA
    assert is_valid_passed_strategy_advancement_gate(payload)
    legacy = build_strategy_advancement_gate(
        **{k: v for k, v in inputs.items() if k != "source_binding"},
        require_independent_evaluation=True,
    ).to_json_dict()
    assert legacy["status"] == "blocked"
    assert payload["legacy_gate_diagnostics"] == legacy
    assert inputs == before


@pytest.mark.parametrize(
    "change",
    [
        "source_ref",
        "policy",
        "second_attempt",
        "formula",
        "replay_source",
        "replay_curve",
        "replay_fee",
        "replay_policy",
        "drawdown",
        "turnover",
        "capacity",
        "account",
        "fees",
        "oos",
        "critique",
    ],
)
def test_manual_profile_rejects_real_binding_and_financial_gaps(
    manual_gate_inputs, change
):
    inputs = deepcopy(manual_gate_inputs)
    candidate = inputs["candidate"]
    replay = candidate["simulation_account_replay"]
    if change == "source_ref":
        inputs["source_binding"]["manual_source_refs"]["critique_id"] = "different"
    elif change == "policy":
        candidate["independent_evaluation"]["reservation"]["simulation_policy"][
            "statistical_policy"
        ]["maximum_drawdown"] = "0.25"
        seal(candidate["independent_evaluation"])
    elif change == "second_attempt":
        candidate["independent_evaluation"]["reservation"]["error_budget"][
            "attempt_count"
        ] = 2
        seal(candidate["independent_evaluation"])
    elif change == "formula":
        candidate["formula_ast"] = {"op": "constant", "value": 1}
    elif change == "replay_source":
        replay["manual_source_binding"]["manual_source_fingerprint"] = "f" * 64
        seal(replay)
    elif change == "replay_curve":
        replay["reviewed_replay"]["session_curves"]["candidate"][-1][1] = "1"
        seal(replay)
    elif change == "replay_fee":
        replay["review_fingerprint"] = "f" * 64
        seal(replay)
    elif change == "replay_policy":
        assessment = replay["reviewed_replay"]["deployment_assessment"]
        assessment["uncertainty"]["policy"]["minimum_observations"] = 2
        seal(assessment)
        seal(replay)
    elif change == "drawdown":
        candidate["drawdown_evidence"]["points"][1]["equity"] = "1"
        seal(candidate["drawdown_evidence"])
    elif change == "turnover":
        candidate["gross_turnover"] += 1
    elif change == "capacity":
        candidate["capacity_review"].pop("observations")
        seal(candidate["capacity_review"])
    elif change == "account":
        candidate["account_capital_constraint"] = {}
    elif change == "fees":
        candidate["fee_component_evidence"]["components"].pop("stamp_tax")
        seal(candidate["fee_component_evidence"])
    elif change == "oos":
        candidate["oos_validation"]["folds"].pop()
    else:
        inputs["critique_evidence"]["critique_id"] = "different"
    payload = build_manual_final_strategy_advancement_gate(**inputs).to_json_dict()
    assert payload["status"] == "blocked"
    assert not is_valid_passed_strategy_advancement_gate(payload)


def test_manual_backtest_view_carries_full_evidence_only_for_manual_source(
    manual_gate_inputs,
):
    candidate = manual_gate_inputs["candidate"]
    metrics = {
        key: candidate[key]
        for key in (
            "simulation_account_replay",
            "formula_fingerprint",
            "independent_evaluation",
        )
    }
    projected = strategy_advancement_backtest_view({"metrics_json": metrics})
    assert (
        projected["simulation_account_replay"] == metrics["simulation_account_replay"]
    )
    assert projected["formula_fingerprint"] == candidate["formula_fingerprint"]
    del metrics["simulation_account_replay"]["manual_source_binding"]
    legacy = strategy_advancement_backtest_view({"metrics_json": metrics})
    assert "simulation_account_replay" not in legacy
    assert "formula_fingerprint" not in legacy


def test_manual_gate_validator_rejects_malformed_self_hashed_projections(
    manual_gate_inputs,
):
    valid = build_manual_final_strategy_advancement_gate(
        **manual_gate_inputs
    ).to_json_dict()
    assert is_valid_passed_strategy_advancement_gate(valid)
    for key, value in (
        ("legacy_gate_diagnostics", "not-an-object"),
        ("source_binding", {}),
        ("research_policy_fingerprint", "invalid"),
    ):
        forged = deepcopy(valid)
        forged[key] = value
        assert not is_valid_passed_strategy_advancement_gate(seal(forged))
    malformed = deepcopy(manual_gate_inputs)
    malformed["source_binding"]["manual_source_refs"] = "not-an-object"
    assert not build_manual_final_strategy_advancement_gate(**malformed).passed
