from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
)


def _fingerprinted(payload: dict) -> dict:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {**payload, "evidence_fingerprint": hashlib.sha256(encoded).hexdigest()}


def _view(*, candidate: bool) -> dict:
    review_id = "fee_review_" + "a" * 32
    review_fingerprint = "sha256:" + "b" * 64
    cost_model_reference = (
        "karkinos.backtest.reviewed_account_fee_schedule.v1:"
        f"{review_id}:{review_fingerprint.removeprefix('sha256:')}"
    )
    fee_schedule_binding = {
        "fee_schedule_review_id": review_id,
        "fee_schedule_review_fingerprint": review_fingerprint,
        "fee_schedule_preview_fingerprint": "sha256:" + "c" * 64,
        "account_truth_import_run_id": "import_reviewed_fixture",
        "account_truth_source_fingerprint": "sha256:" + "d" * 64,
        "account_truth_scope_fingerprint": "sha256:" + "e" * 64,
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-12-31",
        "fee_notional_envelope_enforced": True,
        "fee_notional_envelope_fingerprint": "sha256:" + "9" * 64,
        "fee_notional_covered_asset_classes": ["etf", "stock"],
    }
    account_capital_constraint = build_research_account_capital_evidence(
        initial_cash=100_000,
        account_evidence={
            "status": "complete",
            "persisted_facts_only": True,
            "record_fingerprint": "8" * 64,
            "valuation_snapshot_id": "valuation-reviewed-fixture",
            "ledger_cutoff_id": 42,
            "payload": {
                "summary": {
                    "valuation_snapshot_id": "valuation-reviewed-fixture",
                    "ledger_cutoff_id": 42,
                    "valuation_status": "complete",
                    "total_equity": 100_000,
                },
                "snapshot": {
                    "valuation_snapshot_id": "valuation-reviewed-fixture",
                    "ledger_cutoff_id": 42,
                    "valuation_status": "complete",
                    "total_equity": 100_000,
                },
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
    return {
        "initial_cash": 100_000,
        "total_return": 0.08 if candidate else 0.05,
        "max_drawdown": 0.08 if candidate else 0.12,
        "gross_turnover": 18_000 if candidate else 20_000,
        "dataset_snapshot_id": "sha256:" + "a" * 64,
        "dataset_quality_status": "ok",
        "dataset_issue_count": 0,
        "formula_parameter_values": {"window": 5},
        "oos_validation_mode": "rolling",
        "oos_fold_count": 3,
        "oos_pass_rate": 2 / 3,
        "oos_validation_status": "benchmark_passed",
        "oos_folds": [
            {
                "fold_index": index,
                "split_timestamp": f"2026-0{index + 1}-01T00:00:00",
                "net_return": (
                    (0.02 + index * 0.005) if candidate else (0.01 + index * 0.005)
                ),
                "total_cost": 3.0,
            }
            for index in range(1, 4)
        ],
        "mean_oos_return": 0.04 if candidate else 0.02,
        "worst_oos_return": 0.01 if candidate else 0.0,
        "parameter_robustness": _fingerprinted(
            {
                "schema_version": "karkinos.sweep_robustness.v1",
                "tested_count": 5,
                "selected_params": {"window": 5},
                "best_params": {"window": 5},
                "local_stability": {
                    "neighbor_count": 2,
                    "stability_ratio": 0.9,
                },
                "overfitting_warnings": [],
            }
        ),
        "market_regime_robustness": _fingerprinted(
            {
                "schema_version": "karkinos.market_regime_robustness.v1",
                "status": "pass",
                "regime_count": 2,
                "failed_regime_count": 0,
                "regimes": [
                    {"name": "rising", "status": "pass", "observation_count": 3},
                    {"name": "falling", "status": "pass", "observation_count": 3},
                ],
            }
        ),
        "capacity_review": _fingerprinted(
            {
                "status": "pass",
                "capacity_utilization_pct": 0.4,
                "liquidity_utilization_pct": 0.5,
                "capacity_model_ref": "capacity:reviewed-fixture",
            }
        ),
        "account_capital_constraint": account_capital_constraint,
        "fee_component_evidence": _fingerprinted(
            {
                "status": "complete",
                "includes_taxes": True,
                "cost_model_reference": cost_model_reference,
                "fee_rule_id": cost_model_reference,
                "fee_rule_version": cost_model_reference,
                "fill_rule_versions": [cost_model_reference],
                "account_specific": True,
                "fee_schedule_source": (
                    "reviewed_account_truth_or_reconciled_fee_schedule"
                ),
                "fee_schedule_fingerprint": "sha256:" + "f" * 64,
                "broker_statement_reconciled": True,
                "fee_schedule_binding": fee_schedule_binding,
                "components": {
                    "commission": 8.0,
                    "stamp_tax": 1.0,
                    "transfer_fee": 0.2,
                    "slippage": 2.0,
                },
            }
        ),
    }


def test_strategy_advancement_gate_passes_only_complete_deterministic_evidence():
    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=_view(candidate=True),
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.passed is True
    assert gate.status == "pass"
    assert gate.blockers == ()
    payload = gate.to_json_dict()
    assert payload["schema_version"] == "karkinos.strategy_advancement_gate.v2"
    assert payload["does_not_create_order"] is True
    assert payload["does_not_authorize_execution"] is True
    assert payload["does_not_change_capital_authority"] is True
    assert len(payload["evidence_fingerprint"]) == 64
    assert is_valid_passed_strategy_advancement_gate(payload) is True
    assert all(check["status"] == "pass" for check in payload["checks"])

    drifted = deepcopy(payload)
    drifted["checks"][0]["evidence"]["candidate_snapshot_id"] = "sha256:" + "f" * 64
    assert is_valid_passed_strategy_advancement_gate(drifted) is False


def test_strategy_advancement_gate_fails_closed_for_every_named_evidence_gap():
    candidate = deepcopy(_view(candidate=True))
    candidate.update(
        {
            "dataset_quality_status": "warning",
            "oos_validation_mode": "single_split",
            "parameter_robustness": {},
            "market_regime_robustness": {},
            "max_drawdown": 0.2,
            "gross_turnover": 30_000,
            "account_capital_constraint": {},
            "capacity_review": {},
            "fee_component_evidence": {},
            "total_return": 0.01,
        }
    )

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={},
    )

    assert gate.passed is False
    assert gate.status == "blocked"
    assert {
        "candidate_dataset_quality_not_clear",
        "candidate_rolling_oos_not_passing",
        "candidate_parameter_robustness_not_passing",
        "candidate_market_regime_robustness_not_passing",
        "candidate_drawdown_exceeds_reviewed_baseline",
        "candidate_turnover_exceeds_reviewed_baseline",
        "candidate_real_account_capital_constraint_not_passing",
        "candidate_capacity_or_liquidity_not_passing",
        "candidate_fee_or_tax_evidence_incomplete",
        "candidate_after_tax_excess_return_not_positive",
        "completed_research_critique_missing",
    }.issubset(gate.blockers)


def test_strategy_advancement_gate_rejects_unreviewed_benchmark_or_dataset_drift():
    candidate = deepcopy(_view(candidate=True))
    candidate["dataset_snapshot_id"] = "sha256:" + "f" * 64
    candidate["oos_folds"][1]["split_timestamp"] = "2026-12-31T00:00:00"

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.passed is False
    assert "candidate_dataset_snapshot_mismatch" in gate.blockers
    assert "candidate_rolling_oos_fold_identity_mismatch" in gate.blockers


def test_strategy_advancement_gate_requires_fee_tax_evidence_for_baseline_too():
    baseline = deepcopy(_view(candidate=False))
    baseline["fee_component_evidence"] = {}

    gate = build_strategy_advancement_gate(
        baseline=baseline,
        candidate=_view(candidate=True),
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.passed is False
    assert "baseline_fee_or_tax_evidence_incomplete" in gate.blockers


def test_strategy_advancement_gate_rejects_forged_nested_evidence_fingerprint():
    candidate = deepcopy(_view(candidate=True))
    candidate["parameter_robustness"]["tested_count"] = 999

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.passed is False
    assert "candidate_parameter_robustness_not_passing" in gate.blockers


def test_strategy_advancement_gate_rejects_generic_estimated_fee_model():
    candidate = deepcopy(_view(candidate=True))
    candidate["fee_component_evidence"] = _fingerprinted(
        {
            **{
                key: value
                for key, value in candidate["fee_component_evidence"].items()
                if key != "evidence_fingerprint"
            },
            "account_specific": False,
            "fee_schedule_source": "canonical_default_estimate",
            "fee_schedule_fingerprint": "",
            "broker_statement_reconciled": False,
        }
    )

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.passed is False
    assert "candidate_fee_or_tax_evidence_incomplete" in gate.blockers
    assert "candidate_after_tax_excess_return_not_positive" in gate.blockers
