from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd

from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
from analytics.backtest_market_regime_evidence import (
    build_backtest_market_regime_evidence,
)
from analytics.oos_validation import build_rolling_out_of_sample_validation
from analytics.research_account_capital_evidence import (
    build_research_account_capital_evidence,
)
from analytics.strategy_advancement_gate import (
    STRATEGY_ADVANCEMENT_OPTIONAL_CHECK_NAMES,
    STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES,
    build_strategy_advancement_gate,
    is_valid_passed_strategy_advancement_gate,
    strategy_advancement_backtest_view,
)
from analytics.sweep_robustness import build_sweep_robustness_evidence
from backtest.result import BacktestResult


def _fingerprinted(payload: dict) -> dict:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {**payload, "evidence_fingerprint": hashlib.sha256(encoded).hexdigest()}


def _market_regime_evidence() -> dict:
    start = datetime(2026, 1, 1)
    timestamps = [start + timedelta(days=index) for index in range(5)]
    return build_backtest_market_regime_evidence(
        result=SimpleNamespace(
            equity_curve=[
                (timestamp, equity)
                for timestamp, equity in zip(
                    timestamps, [100.0, 101.0, 102.0, 103.0, 104.0], strict=True
                )
            ]
        ),
        data_handlers={
            "510300.SH": SimpleNamespace(
                _df=pd.DataFrame(
                    {
                        "timestamp": timestamps,
                        "close": [100.0, 110.0, 100.0, 105.0, 100.0],
                    }
                )
            )
        },
    )


def _rolling_oos_evidence(*, candidate: bool) -> dict:
    start = datetime(2026, 1, 1)
    timestamps = [start + timedelta(days=index) for index in range(6)]
    values = (
        [100_000, 102_000, 104_000, 106_000, 108_000, 110_000]
        if candidate
        else [100_000, 101_000, 102_000, 103_000, 104_000, 105_000]
    )
    return build_rolling_out_of_sample_validation(
        strategy_id="candidate" if candidate else "baseline",
        benchmark_role="reviewed_persisted_baseline",
        result=BacktestResult(
            equity_curve=[
                (timestamp, Decimal(value))
                for timestamp, value in zip(timestamps, values, strict=True)
            ],
            positions={},
            initial_cash=Decimal(values[0]),
            final_equity=Decimal(values[-1]),
        ),
        min_train_points=2,
        test_window_points=2,
        step_points=1,
    ).to_json_dict()


def _view(*, candidate: bool) -> dict:
    total_return = 0.08 if candidate else 0.05
    gross_turnover = 18_000 if candidate else 20_000
    max_drawdown = Decimal("0.08") if candidate else Decimal("0.12")
    equity_values = (
        [Decimal("100000"), Decimal("92000"), Decimal("108000")]
        if candidate
        else [Decimal("100000"), Decimal("88000"), Decimal("105000")]
    )
    equity_timestamps = [
        datetime(2026, 1, 1),
        datetime(2026, 1, 2),
        datetime(2026, 1, 3),
    ]
    equity_curve = [
        {"timestamp": timestamp.isoformat(), "equity": float(equity)}
        for timestamp, equity in zip(equity_timestamps, equity_values, strict=True)
    ]
    drawdown_evidence = build_backtest_drawdown_evidence(
        equity_curve=list(zip(equity_timestamps, equity_values, strict=True))
    )
    capacity_utilization = format(Decimal(gross_turnover) / Decimal("100000"), "f")
    total_commission = 9.2
    total_slippage = 2.0
    total_cost = total_commission + total_slippage
    net_pnl = total_return * 100_000
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
    oos_validation = _rolling_oos_evidence(candidate=candidate)
    oos_aggregate = oos_validation["aggregate"]
    return {
        "initial_cash": 100_000,
        "final_equity": 100_000 + net_pnl,
        "total_return": total_return,
        "max_drawdown": float(max_drawdown),
        "equity_curve": equity_curve,
        "drawdown_evidence": drawdown_evidence,
        "total_cost": total_cost,
        "net_pnl": net_pnl,
        "gross_pnl_before_costs": net_pnl + total_cost,
        "net_return": total_return,
        "gross_return_before_costs": (net_pnl + total_cost) / 100_000,
        "cost_to_initial_cash": total_cost / 100_000,
        "evidence_fill_count": 1,
        "evidence_gross_turnover": gross_turnover,
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "total_trades": 1,
        "gross_turnover": gross_turnover,
        "dataset_snapshot_id": "sha256:" + "a" * 64,
        "dataset_quality_status": "ok",
        "dataset_issue_count": 0,
        "formula_parameter_values": {"window": 5},
        "oos_validation": oos_validation,
        "oos_validation_mode": oos_validation["validation_mode"],
        "oos_fold_count": oos_validation["fold_count"],
        "oos_pass_rate": oos_aggregate["pass_rate"],
        "oos_validation_status": oos_validation["validation_status"],
        "oos_folds": [
            {
                "fold_index": fold["fold_index"],
                "split_timestamp": fold["split_timestamp"],
                "net_return": fold["out_of_sample"]["net_return"],
                "total_cost": fold["out_of_sample"]["total_cost"],
            }
            for fold in oos_validation["folds"]
        ],
        "mean_oos_return": oos_aggregate["mean_out_of_sample_return"],
        "worst_oos_return": oos_aggregate["worst_out_of_sample_return"],
        "parameter_robustness": build_sweep_robustness_evidence(
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
        ),
        "market_regime_robustness": _market_regime_evidence(),
        "capacity_review": _fingerprinted(
            {
                "schema_version": "karkinos.backtest_capacity.v1",
                "status": "pass",
                "capacity_model_ref": (
                    "karkinos.backtest.capacity.daily_bar_participation.v1"
                ),
                "capacity_utilization_pct": capacity_utilization,
                "liquidity_utilization_pct": "0.5",
                "max_daily_volume_participation": "0.1",
                "gross_turnover": str(gross_turnover),
                "fill_count": 1,
                "observation_count": 1,
                "observations": [
                    {
                        "fill_index": 0,
                        "symbol": "510300.SH",
                        "timestamp": "2026-01-05T00:00:00",
                        "fill_notional": str(gross_turnover),
                        "bar_notional": "800000",
                        "raw_volume_participation": "0.05",
                        "capacity_utilization_pct": capacity_utilization,
                        "liquidity_utilization_pct": "0.5",
                    }
                ],
                "issues": [],
                "assumptions": ["deterministic fixture assumption"],
                "limitations": ["deterministic fixture limitation"],
                "persisted_market_data_only": True,
                "human_review_required": True,
                "authorizes_execution": False,
                "does_not_change_capital_authority": True,
            }
        ),
        "account_capital_constraint": account_capital_constraint,
        "fee_component_evidence": _fingerprinted(
            {
                "schema_version": "karkinos.backtest_fee_tax_evidence.v1",
                "status": "complete",
                "includes_taxes": True,
                "cost_model_reference": cost_model_reference,
                "fee_rule_id": cost_model_reference,
                "fee_rule_version": cost_model_reference,
                "fill_rule_ids": [cost_model_reference],
                "fill_rule_versions": [cost_model_reference],
                "fill_count": 1,
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
                    "other_fees": 0.0,
                    "slippage": 2.0,
                },
                "component_reconciliation_status": "pass",
                "issues": [],
                "model_limitations": [],
                "persisted_fill_evidence_only": True,
                "does_not_recalculate_backtest_pnl": True,
                "human_review_required": True,
                "authorizes_execution": False,
                "does_not_change_capital_authority": True,
                "limitations": [],
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


def test_strategy_advancement_gate_blocks_when_dsr_not_significant():
    candidate = deepcopy(_view(candidate=True))
    candidate["sharpe"] = 0.5
    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
        num_trials=100,
    )
    names = [check["name"] for check in gate.checks]
    assert tuple(names) == (
        STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
        + STRATEGY_ADVANCEMENT_OPTIONAL_CHECK_NAMES
    )
    assert "multiple_testing_correction_not_significant" in gate.blockers
    assert gate.passed is False


def test_strategy_advancement_gate_passes_dsr_with_strong_sharpe_and_one_trial():
    candidate = deepcopy(_view(candidate=True))
    candidate["sharpe"] = 10.0
    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
        num_trials=1,
    )
    assert "multiple_testing_correction" not in gate.blockers
    assert gate.passed is True


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
        "candidate_drawdown_evidence_not_reproducible",
        "candidate_turnover_evidence_not_reproducible",
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


def test_strategy_advancement_gate_rejects_rehashed_rolling_oos_conflict():
    candidate = deepcopy(_view(candidate=True))
    oos_core = {
        key: value
        for key, value in candidate["oos_validation"].items()
        if key != "evidence_fingerprint"
    }
    oos_core["aggregate"]["mean_out_of_sample_return"] = 0.999
    candidate["oos_validation"] = _fingerprinted(oos_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_rolling_oos_evidence_not_reproducible" in gate.blockers


def test_strategy_advancement_gate_requires_same_rolling_oos_configuration():
    candidate = deepcopy(_view(candidate=True))
    oos_core = {
        key: value
        for key, value in candidate["oos_validation"].items()
        if key != "evidence_fingerprint"
    }
    oos_core["step_points"] = 2
    oos_core["equity_point_count"] = 8
    candidate["oos_validation"] = _fingerprinted(oos_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_rolling_oos_configuration_mismatch" in gate.blockers


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


def test_strategy_advancement_gate_treats_missing_risk_numbers_as_blocked():
    candidate = deepcopy(_view(candidate=True))
    candidate.pop("max_drawdown")
    candidate.pop("gross_turnover")

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_drawdown_evidence_not_reproducible" in gate.blockers
    assert "candidate_turnover_evidence_not_reproducible" in gate.blockers
    assert "candidate_capacity_or_liquidity_not_passing" in gate.blockers


def test_strategy_advancement_gate_requires_baseline_turnover_source_value():
    baseline = deepcopy(_view(candidate=False))
    baseline.pop("gross_turnover")

    gate = build_strategy_advancement_gate(
        baseline=baseline,
        candidate=_view(candidate=True),
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "baseline_turnover_evidence_not_reproducible" in gate.blockers


def test_strategy_advancement_gate_rejects_conflicting_rolling_fold_count():
    candidate = deepcopy(_view(candidate=True))
    candidate["oos_fold_count"] = 4

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_rolling_oos_fold_count_mismatch" in gate.blockers


def test_strategy_advancement_gate_requires_distinct_market_regimes():
    candidate = deepcopy(_view(candidate=True))
    regime_core = {
        key: value
        for key, value in candidate["market_regime_robustness"].items()
        if key != "evidence_fingerprint"
    }
    regime_core["regimes"][1]["name"] = regime_core["regimes"][0]["name"]
    candidate["market_regime_robustness"] = _fingerprinted(regime_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_market_regime_robustness_not_passing" in gate.blockers


def test_backtest_projection_preserves_missing_turnover_and_return_evidence():
    view = strategy_advancement_backtest_view(
        {
            "id": 7,
            "initial_cash": 100_000,
            "metrics_json": "{}",
            "cost_summary_json": "{}",
        }
    )

    assert view["total_return"] is None
    assert view["max_drawdown"] is None
    assert view["gross_turnover"] is None
    assert view["total_cost"] is None


def test_strategy_advancement_gate_rejects_rehashed_drawdown_conflict():
    candidate = deepcopy(_view(candidate=True))
    drawdown_core = {
        key: value
        for key, value in candidate["drawdown_evidence"].items()
        if key != "evidence_fingerprint"
    }
    drawdown_core["max_drawdown_pct"] = "0.01"
    candidate["drawdown_evidence"] = _fingerprinted(drawdown_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_drawdown_evidence_not_reproducible" in gate.blockers


def test_strategy_advancement_gate_rejects_conflicting_account_truth_bindings():
    candidate = deepcopy(_view(candidate=True))
    capital_core = {
        key: value
        for key, value in candidate["account_capital_constraint"].items()
        if key != "evidence_fingerprint"
    }
    capital_core["account_truth_source_fingerprint"] = "sha256:" + "7" * 64
    candidate["account_capital_constraint"] = _fingerprinted(capital_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_real_account_capital_constraint_not_passing" in gate.blockers
    capital_check = next(
        check
        for check in gate.checks
        if check["name"] == "real_account_capital_constraint"
    )
    assert (
        capital_check["evidence"]["account_truth_binding_matches_fee_schedule"] is False
    )


def test_strategy_advancement_gate_rejects_rehashed_capacity_aggregate_conflict():
    candidate = deepcopy(_view(candidate=True))
    capacity_core = {
        key: value
        for key, value in candidate["capacity_review"].items()
        if key != "evidence_fingerprint"
    }
    capacity_core["capacity_utilization_pct"] = "0.3"
    candidate["capacity_review"] = _fingerprinted(capacity_core)

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_turnover_evidence_not_reproducible" in gate.blockers
    assert "candidate_capacity_or_liquidity_not_passing" in gate.blockers


def test_strategy_advancement_gate_rejects_after_cost_reconciliation_conflict():
    candidate = deepcopy(_view(candidate=True))
    candidate["total_cost"] = 999

    gate = build_strategy_advancement_gate(
        baseline=_view(candidate=False),
        candidate=candidate,
        critique_evidence={
            "status": "completed",
            "critique_id": "critique-reviewed",
            "artifact_fingerprint": "e" * 64,
        },
    )

    assert gate.status == "blocked"
    assert "candidate_fee_or_tax_evidence_incomplete" in gate.blockers
    assert "candidate_after_tax_excess_return_not_positive" in gate.blockers
