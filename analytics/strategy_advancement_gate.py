"""Deterministic evidence gate for strategy candidate advancement.

The gate is intentionally fail-closed.  It evaluates persisted, normalized
research evidence only and grants neither strategy registration nor trading
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from analytics.backtest_capacity_evidence import (
    is_valid_passed_backtest_capacity_evidence,
)
from analytics.backtest_drawdown_evidence import (
    is_valid_complete_backtest_drawdown_evidence,
)
from analytics.multiple_testing import build_deflated_sharpe
from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_evidence import difference as _difference
from analytics.strategy_advancement_evidence import (
    fee_component_evidence_complete as _fee_component_evidence_complete,
)
from analytics.strategy_advancement_evidence import (
    fee_component_gate_evidence as _fee_component_gate_evidence,
)
from analytics.strategy_advancement_evidence import (
    fee_schedule_bindings_match as _fee_schedule_bindings_match,
)
from analytics.strategy_advancement_evidence import integer as _integer
from analytics.strategy_advancement_evidence import json_list as _json_list
from analytics.strategy_advancement_evidence import json_object as _json_object
from analytics.strategy_advancement_evidence import mapping as _mapping
from analytics.strategy_advancement_evidence import (
    market_regime_robustness_check,
)
from analytics.strategy_advancement_evidence import number as _number
from analytics.strategy_advancement_evidence import (
    parameter_robustness_check,
)
from analytics.strategy_advancement_evidence import (
    payload_fingerprint as _payload_fingerprint,
)
from analytics.strategy_advancement_evidence import (
    rolling_oos_comparison as _rolling_oos_comparison,
)
from analytics.strategy_advancement_evidence import turnover_ratio as _turnover_ratio
from analytics.strategy_advancement_evidence import (
    valid_fingerprint as _valid_fingerprint,
)
from analytics.strategy_advancement_evidence import (
    valid_snapshot_id as _valid_snapshot_id,
)

STRATEGY_ADVANCEMENT_GATE_SCHEMA_VERSION = "karkinos.strategy_advancement_gate.v2"
STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES = (
    "frozen_dataset_identity",
    "rolling_out_of_sample",
    "after_cost_oos_excess",
    "parameter_robustness",
    "market_regime_robustness",
    "drawdown",
    "turnover",
    "real_account_capital_constraint",
    "capacity_and_liquidity",
    "baseline_realistic_cost_and_tax_evidence",
    "candidate_realistic_cost_and_tax_evidence",
    "after_tax_excess_return",
    "independent_critique",
)
STRATEGY_ADVANCEMENT_OPTIONAL_CHECK_NAMES = ("multiple_testing_correction",)


@dataclass(frozen=True)
class StrategyAdvancementGate:
    status: str
    blockers: tuple[str, ...]
    checks: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass" and not self.blockers

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": STRATEGY_ADVANCEMENT_GATE_SCHEMA_VERSION,
            "status": self.status,
            "blockers": list(self.blockers),
            "checks": [dict(check) for check in self.checks],
            "deterministic": True,
            "persisted_evidence_only": True,
            "human_confirmation_required": True,
            "does_not_register_strategy": True,
            "does_not_create_order": True,
            "does_not_authorize_execution": True,
            "does_not_change_capital_authority": True,
        }
        return {
            **payload,
            "evidence_fingerprint": _payload_fingerprint(payload),
        }


def is_valid_passed_strategy_advancement_gate(value: Any) -> bool:
    """Validate one persisted pass artifact before human paper/shadow approval."""

    if not isinstance(value, Mapping):
        return False
    payload = dict(value)
    evidence_fingerprint = payload.pop("evidence_fingerprint", None)
    checks = payload.get("checks")
    blockers = payload.get("blockers")
    if not isinstance(checks, list) or not isinstance(blockers, list):
        return False
    normalized_checks = [dict(check) for check in checks if isinstance(check, Mapping)]
    check_names = tuple(check.get("name") for check in normalized_checks)
    required_names = STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
    optional_names = STRATEGY_ADVANCEMENT_OPTIONAL_CHECK_NAMES
    names_valid = check_names in {
        required_names,
        required_names + optional_names,
    }
    return (
        len(normalized_checks) == len(checks)
        and names_valid
        and all(
            check.get("status") == "pass"
            and check.get("blocker") is None
            and isinstance(check.get("evidence"), Mapping)
            for check in normalized_checks
        )
        and payload.get("schema_version") == STRATEGY_ADVANCEMENT_GATE_SCHEMA_VERSION
        and payload.get("status") == "pass"
        and blockers == []
        and payload.get("deterministic") is True
        and payload.get("persisted_evidence_only") is True
        and payload.get("human_confirmation_required") is True
        and payload.get("does_not_register_strategy") is True
        and payload.get("does_not_create_order") is True
        and payload.get("does_not_authorize_execution") is True
        and payload.get("does_not_change_capital_authority") is True
        and _valid_fingerprint(evidence_fingerprint)
        and str(evidence_fingerprint).lower() == _payload_fingerprint(payload)
    )


def strategy_advancement_backtest_view(
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one persisted backtest row for deterministic gate replay.

    The same projection is used when a candidate comparison is created and
    when its current persisted sources are re-resolved before promotion.  This
    prevents a structurally valid, self-hashed gate summary from replacing the
    underlying frozen-dataset, cost, benchmark, and robustness evidence.
    """

    metrics = _json_object(source.get("metrics", source.get("metrics_json")))
    costs = _json_object(source.get("cost_summary", source.get("cost_summary_json")))
    evidence = _json_object(metrics.get("evidence_bundle"))
    research = _json_object(metrics.get("research_evidence_bundle"))
    oos = _json_object(metrics.get("oos_validation"))
    equity_curve = _json_list(
        source.get("equity_curve", source.get("equity_curve_json"))
    )
    aggregate = _json_object(oos.get("aggregate"))
    oos_folds = [
        {
            "fold_index": fold.get("fold_index"),
            "split_timestamp": fold.get("split_timestamp"),
            "net_return": _json_object(fold.get("out_of_sample")).get("net_return"),
            "total_cost": _json_object(fold.get("out_of_sample")).get("total_cost"),
        }
        for fold in oos.get("folds") or []
        if isinstance(fold, Mapping)
    ]
    dataset = _json_object(metrics.get("dataset_snapshot"))
    dataset_quality = _json_object(dataset.get("data_quality"))
    total_cost = _number(evidence.get("total_cost"))
    return {
        "result_id": int(source.get("id") or 0),
        "initial_cash": _number(source.get("initial_cash")),
        "final_equity": _number(source.get("final_equity")),
        "total_return": _number(source.get("total_return")),
        "sharpe": _number(source.get("sharpe")),
        "max_drawdown": _number(source.get("max_drawdown")),
        "total_cost": total_cost,
        "net_pnl": _number(evidence.get("net_pnl")),
        "gross_pnl_before_costs": _number(evidence.get("gross_pnl_before_costs")),
        "net_return": _number(evidence.get("net_return")),
        "gross_return_before_costs": _number(evidence.get("gross_return_before_costs")),
        "cost_to_initial_cash": _number(evidence.get("cost_to_initial_cash")),
        "evidence_fill_count": _integer(evidence.get("fill_count")),
        "evidence_gross_turnover": _number(evidence.get("gross_turnover")),
        "total_commission": _number(costs.get("total_commission")),
        "total_slippage": _number(costs.get("total_slippage")),
        "total_trades": _integer(costs.get("total_trades")),
        "gross_turnover": _number(costs.get("gross_turnover")),
        "equity_curve": equity_curve,
        "drawdown_evidence": _json_object(metrics.get("drawdown_evidence")),
        "oos_validation": oos,
        "oos_validation_mode": str(oos.get("validation_mode") or "missing"),
        "oos_fold_count": _integer(oos.get("fold_count")),
        "oos_pass_rate": aggregate.get("pass_rate"),
        "oos_folds": oos_folds,
        "mean_oos_return": _number(aggregate.get("mean_out_of_sample_return")),
        "worst_oos_return": _number(aggregate.get("worst_out_of_sample_return")),
        "oos_validation_status": str(oos.get("validation_status") or "missing"),
        "evidence_gate_status": str(research.get("gate_status") or "missing"),
        "dataset_snapshot_id": dataset.get("snapshot_id"),
        "dataset_quality_status": dataset_quality.get("status"),
        "dataset_issue_count": len(dataset_quality.get("issues") or []),
        "parameter_robustness": _json_object(
            metrics.get("parameter_robustness") or metrics.get("sweep_robustness")
        ),
        "formula_parameter_values": _json_object(
            _json_object(metrics.get("formula_binding")).get("parameter_values")
        ),
        "market_regime_robustness": _json_object(
            metrics.get("market_regime_robustness")
        ),
        "account_capital_constraint": _json_object(
            metrics.get("account_capital_constraint")
        ),
        "capacity_review": _json_object(metrics.get("capacity_review")),
        "fee_component_evidence": _json_object(metrics.get("fee_component_evidence")),
    }


def build_strategy_advancement_gate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    critique_evidence: Mapping[str, Any],
    num_trials: int | None = None,
) -> StrategyAdvancementGate:
    """Evaluate the complete evidence needed for paper/shadow advancement."""

    blockers: list[str] = []
    checks: list[dict[str, Any]] = []

    def record(
        name: str,
        *,
        passed: bool,
        blocker: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        if not passed:
            blockers.append(blocker)
        checks.append(
            {
                "name": name,
                "status": "pass" if passed else "blocked",
                "blocker": None if passed else blocker,
                "evidence": dict(evidence or {}),
            }
        )

    baseline_snapshot = str(baseline.get("dataset_snapshot_id") or "")
    candidate_snapshot = str(candidate.get("dataset_snapshot_id") or "")
    record(
        "frozen_dataset_identity",
        passed=_valid_snapshot_id(baseline_snapshot)
        and _valid_snapshot_id(candidate_snapshot)
        and candidate_snapshot == baseline_snapshot
        and candidate.get("dataset_quality_status") == "ok"
        and _integer(candidate.get("dataset_issue_count")) == 0,
        blocker=(
            "candidate_dataset_snapshot_missing"
            if not candidate_snapshot
            else (
                "candidate_dataset_snapshot_mismatch"
                if candidate_snapshot != baseline_snapshot
                else "candidate_dataset_quality_not_clear"
            )
        ),
        evidence={
            "baseline_snapshot_id": baseline_snapshot or None,
            "candidate_snapshot_id": candidate_snapshot or None,
            "candidate_quality_status": candidate.get("dataset_quality_status"),
            "candidate_issue_count": candidate.get("dataset_issue_count"),
        },
    )

    rolling_comparison = _rolling_oos_comparison(baseline, candidate)
    record(
        "rolling_out_of_sample",
        passed=bool(rolling_comparison["evidence_complete"]),
        blocker=str(rolling_comparison["evidence_blocker"]),
        evidence={
            "minimum_fold_count": 2,
            "baseline_mode": baseline.get("oos_validation_mode"),
            "baseline_fold_count": baseline.get("oos_fold_count"),
            "candidate_mode": candidate.get("oos_validation_mode"),
            "candidate_fold_count": candidate.get("oos_fold_count"),
            "aligned_fold_count": rolling_comparison["aligned_fold_count"],
        },
    )

    mean_excess = rolling_comparison["mean_excess_return"]
    worst_excess = rolling_comparison["worst_excess_return"]
    fold_pass_rate = rolling_comparison["fold_pass_rate"]
    record(
        "after_cost_oos_excess",
        passed=bool(rolling_comparison["evidence_complete"])
        and mean_excess is not None
        and worst_excess is not None
        and fold_pass_rate is not None
        and mean_excess > 0
        and worst_excess >= 0
        and fold_pass_rate >= 0.5,
        blocker="candidate_after_cost_oos_excess_not_positive",
        evidence={
            "benchmark_role": "reviewed_persisted_baseline",
            "mean_oos_excess_return": mean_excess,
            "worst_oos_excess_return": worst_excess,
            "fold_pass_rate": fold_pass_rate,
            "minimum_fold_pass_rate": 0.5,
        },
    )

    record(
        "parameter_robustness",
        **parameter_robustness_check(candidate),
    )

    record(
        "market_regime_robustness",
        **market_regime_robustness_check(candidate),
    )

    baseline_drawdown_evidence = _mapping(baseline.get("drawdown_evidence"))
    candidate_drawdown_evidence = _mapping(candidate.get("drawdown_evidence"))
    baseline_drawdown_value = _number(baseline.get("max_drawdown"))
    candidate_drawdown_value = _number(candidate.get("max_drawdown"))
    baseline_drawdown = (
        abs(baseline_drawdown_value) if baseline_drawdown_value is not None else None
    )
    candidate_drawdown = (
        abs(candidate_drawdown_value) if candidate_drawdown_value is not None else None
    )
    baseline_drawdown_complete = is_valid_complete_backtest_drawdown_evidence(
        baseline_drawdown_evidence,
        expected_max_drawdown=baseline.get("max_drawdown"),
        expected_equity_curve=baseline.get("equity_curve"),
        expected_initial_equity=baseline.get("initial_cash"),
        expected_final_equity=baseline.get("final_equity"),
    )
    candidate_drawdown_complete = is_valid_complete_backtest_drawdown_evidence(
        candidate_drawdown_evidence,
        expected_max_drawdown=candidate.get("max_drawdown"),
        expected_equity_curve=candidate.get("equity_curve"),
        expected_initial_equity=candidate.get("initial_cash"),
        expected_final_equity=candidate.get("final_equity"),
    )
    drawdown_passed = (
        baseline_drawdown_complete
        and candidate_drawdown_complete
        and baseline_drawdown is not None
        and candidate_drawdown is not None
        and candidate_drawdown <= baseline_drawdown
    )
    record(
        "drawdown",
        passed=drawdown_passed,
        blocker=(
            "baseline_drawdown_evidence_not_reproducible"
            if not baseline_drawdown_complete
            else (
                "candidate_drawdown_evidence_not_reproducible"
                if not candidate_drawdown_complete
                else "candidate_drawdown_exceeds_reviewed_baseline"
            )
        ),
        evidence={
            "baseline_max_drawdown": baseline_drawdown,
            "candidate_max_drawdown": candidate_drawdown,
            "baseline_evidence_fingerprint": baseline_drawdown_evidence.get(
                "evidence_fingerprint"
            ),
            "candidate_evidence_fingerprint": candidate_drawdown_evidence.get(
                "evidence_fingerprint"
            ),
        },
    )

    baseline_capacity = _mapping(baseline.get("capacity_review"))
    candidate_capacity = _mapping(candidate.get("capacity_review"))
    baseline_turnover = _turnover_ratio(baseline)
    candidate_turnover = _turnover_ratio(candidate)
    baseline_turnover_complete = (
        baseline_turnover is not None
        and is_valid_passed_backtest_capacity_evidence(
            baseline_capacity,
            expected_initial_cash=baseline.get("initial_cash"),
            expected_gross_turnover=baseline.get("gross_turnover"),
        )
    )
    candidate_turnover_complete = (
        candidate_turnover is not None
        and is_valid_passed_backtest_capacity_evidence(
            candidate_capacity,
            expected_initial_cash=candidate.get("initial_cash"),
            expected_gross_turnover=candidate.get("gross_turnover"),
        )
    )
    turnover_passed = (
        baseline_turnover_complete
        and candidate_turnover_complete
        and baseline_turnover is not None
        and candidate_turnover is not None
        and candidate_turnover <= baseline_turnover
    )
    record(
        "turnover",
        passed=turnover_passed,
        blocker=(
            "baseline_turnover_evidence_not_reproducible"
            if not baseline_turnover_complete
            else (
                "candidate_turnover_evidence_not_reproducible"
                if not candidate_turnover_complete
                else "candidate_turnover_exceeds_reviewed_baseline"
            )
        ),
        evidence={
            "baseline_turnover_to_initial_cash": baseline_turnover,
            "candidate_turnover_to_initial_cash": candidate_turnover,
            "baseline_evidence_fingerprint": baseline_capacity.get(
                "evidence_fingerprint"
            ),
            "candidate_evidence_fingerprint": candidate_capacity.get(
                "evidence_fingerprint"
            ),
        },
    )

    baseline_fees = _mapping(baseline.get("fee_component_evidence"))
    candidate_fees = _mapping(candidate.get("fee_component_evidence"))
    candidate_fee_binding = _mapping(candidate_fees.get("fee_schedule_binding"))
    account_capital = _mapping(candidate.get("account_capital_constraint"))
    account_truth_binding_matches_fee_schedule = account_capital.get(
        "account_truth_source_fingerprint"
    ) == candidate_fee_binding.get(
        "account_truth_source_fingerprint"
    ) and account_capital.get(
        "account_truth_scope_fingerprint"
    ) == candidate_fee_binding.get(
        "account_truth_scope_fingerprint"
    )
    account_capital_passed = is_valid_passed_research_account_capital_evidence(
        account_capital,
        expected_initial_cash=candidate.get("initial_cash"),
    ) and bool(account_truth_binding_matches_fee_schedule)
    record(
        "real_account_capital_constraint",
        passed=account_capital_passed,
        blocker="candidate_real_account_capital_constraint_not_passing",
        evidence={
            "status": account_capital.get("status"),
            "account_fact_binding_present": account_capital.get(
                "account_fact_binding_present"
            ),
            "account_evidence_identity_matches": account_capital.get(
                "account_evidence_identity_matches"
            ),
            "account_truth_reconciled": account_capital.get("account_truth_reconciled"),
            "initial_cash_within_current_account_equity": account_capital.get(
                "initial_cash_within_current_account_equity"
            ),
            "current_account_total_equity_redacted": account_capital.get(
                "current_account_total_equity_redacted"
            ),
            "account_truth_binding_matches_fee_schedule": (
                account_truth_binding_matches_fee_schedule
            ),
            "evidence_fingerprint": account_capital.get("evidence_fingerprint"),
        },
    )

    capacity = candidate_capacity
    capacity_utilization = _number(capacity.get("capacity_utilization_pct"))
    liquidity_utilization = _number(capacity.get("liquidity_utilization_pct"))
    capacity_passed = (
        candidate_turnover is not None
        and is_valid_passed_backtest_capacity_evidence(
            capacity,
            expected_initial_cash=candidate.get("initial_cash"),
            expected_gross_turnover=candidate.get("gross_turnover"),
        )
    )
    record(
        "capacity_and_liquidity",
        passed=capacity_passed,
        blocker="candidate_capacity_or_liquidity_not_passing",
        evidence={
            "status": capacity.get("status"),
            "capacity_utilization_pct": capacity_utilization,
            "liquidity_utilization_pct": liquidity_utilization,
            "capacity_model_ref": capacity.get("capacity_model_ref"),
            "evidence_fingerprint": capacity.get("evidence_fingerprint"),
        },
    )

    baseline_fee_components_complete = _fee_component_evidence_complete(
        baseline_fees,
        view=baseline,
    )
    candidate_fee_components_complete = _fee_component_evidence_complete(
        candidate_fees,
        view=candidate,
    )
    fee_schedule_bindings_match = _fee_schedule_bindings_match(
        baseline_fees, candidate_fees
    )
    record(
        "baseline_realistic_cost_and_tax_evidence",
        passed=baseline_fee_components_complete,
        blocker="baseline_fee_or_tax_evidence_incomplete",
        evidence=_fee_component_gate_evidence(baseline_fees),
    )
    record(
        "candidate_realistic_cost_and_tax_evidence",
        passed=candidate_fee_components_complete and fee_schedule_bindings_match,
        blocker="candidate_fee_or_tax_evidence_incomplete",
        evidence=_fee_component_gate_evidence(candidate_fees),
    )

    after_tax_excess = _difference(
        candidate.get("total_return"), baseline.get("total_return")
    )
    record(
        "after_tax_excess_return",
        passed=baseline_fee_components_complete
        and candidate_fee_components_complete
        and fee_schedule_bindings_match
        and after_tax_excess is not None
        and after_tax_excess > 0,
        blocker="candidate_after_tax_excess_return_not_positive",
        evidence={
            "benchmark_role": "reviewed_persisted_baseline",
            "after_tax_excess_return": after_tax_excess,
            "fee_schedule_bindings_match": fee_schedule_bindings_match,
        },
    )

    critique = _mapping(critique_evidence)
    critique_complete = (
        critique.get("status") == "completed"
        and bool(critique.get("critique_id"))
        and _valid_fingerprint(critique.get("artifact_fingerprint"))
    )
    record(
        "independent_critique",
        passed=critique_complete,
        blocker="completed_research_critique_missing",
        evidence={
            "status": critique.get("status"),
            "critique_id": critique.get("critique_id"),
            "artifact_fingerprint": critique.get("artifact_fingerprint"),
        },
    )

    if num_trials is not None:
        check = _multiple_testing_check(candidate, num_trials)
        record(
            "multiple_testing_correction",
            passed=check["passed"],
            blocker=check["blocker"],
            evidence=check["evidence"],
        )

    unique_blockers = tuple(dict.fromkeys(blockers))
    return StrategyAdvancementGate(
        status="pass" if not unique_blockers else "blocked",
        blockers=unique_blockers,
        checks=tuple(checks),
    )


def _multiple_testing_check(
    candidate: Mapping[str, Any],
    num_trials: int,
) -> dict[str, Any]:
    """Deflated-Sharpe evidence for the multiple-testing correction check."""

    candidate_sharpe = _number(candidate.get("sharpe"))
    num_periods = len(_json_list(candidate.get("equity_curve")))
    if candidate_sharpe is None or num_periods <= 1 or num_trials < 1:
        return {
            "passed": False,
            "blocker": "multiple_testing_correction_insufficient_evidence",
            "evidence": {
                "candidate_sharpe": candidate_sharpe,
                "num_periods": num_periods,
                "num_trials": num_trials,
            },
        }
    correction = build_deflated_sharpe(
        observed_sharpe=candidate_sharpe,
        num_periods=num_periods,
        num_trials=num_trials,
    )
    return {
        "passed": correction["significant_at_0.95"],
        "blocker": "multiple_testing_correction_not_significant",
        "evidence": {
            "method": "deflated_sharpe",
            "observed_sharpe": correction["observed_sharpe"],
            "num_periods": num_periods,
            "num_trials": num_trials,
            "expected_max_sharpe": correction["expected_max_sharpe"],
            "deflated_sharpe": correction["deflated_sharpe"],
            "threshold": 0.95,
        },
    }
