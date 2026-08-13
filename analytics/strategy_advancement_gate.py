"""Deterministic evidence gate for strategy candidate advancement.

The gate is intentionally fail-closed.  It evaluates persisted, normalized
research evidence only and grants neither strategy registration nor trading
authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
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
_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REVIEWED_COST_MODEL_PATTERN = re.compile(
    r"^karkinos\.backtest\.reviewed_account_fee_schedule\.v1:"
    r"fee_review_[0-9a-f]{32}:[0-9a-f]{64}$"
)


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
    return (
        len(normalized_checks) == len(checks)
        and check_names == STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
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


def build_strategy_advancement_gate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    critique_evidence: Mapping[str, Any],
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
        and int(candidate.get("dataset_issue_count") or 0) == 0,
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

    parameter = _mapping(candidate.get("parameter_robustness"))
    local_stability = _mapping(parameter.get("local_stability"))
    parameter_warnings_raw = parameter.get("overfitting_warnings")
    parameter_warnings = (
        parameter_warnings_raw if isinstance(parameter_warnings_raw, list) else []
    )
    selected_params = _mapping(parameter.get("selected_params"))
    formula_parameter_values = _mapping(candidate.get("formula_parameter_values"))
    parameter_passed = (
        parameter.get("schema_version") == "karkinos.sweep_robustness.v1"
        and _valid_evidence_fingerprint(parameter)
        and int(parameter.get("tested_count") or 0) >= 3
        and int(local_stability.get("neighbor_count") or 0) >= 1
        and (_number(local_stability.get("stability_ratio")) or 0) >= 0.8
        and isinstance(parameter_warnings_raw, list)
        and not parameter_warnings
        and bool(formula_parameter_values)
        and selected_params == formula_parameter_values
        and _mapping(parameter.get("best_params")) == formula_parameter_values
    )
    record(
        "parameter_robustness",
        passed=parameter_passed,
        blocker="candidate_parameter_robustness_not_passing",
        evidence={
            "tested_count": parameter.get("tested_count"),
            "neighbor_count": local_stability.get("neighbor_count"),
            "stability_ratio": local_stability.get("stability_ratio"),
            "warning_count": len(parameter_warnings),
            "selected_params": selected_params,
            "formula_parameter_values": formula_parameter_values,
            "best_params": _mapping(parameter.get("best_params")),
            "evidence_fingerprint": parameter.get("evidence_fingerprint"),
        },
    )

    regimes = _mapping(candidate.get("market_regime_robustness"))
    regime_rows_raw = regimes.get("regimes")
    regime_rows = (
        [dict(row) for row in regime_rows_raw if isinstance(row, Mapping)]
        if isinstance(regime_rows_raw, list)
        else []
    )
    record(
        "market_regime_robustness",
        passed=regimes.get("schema_version") == "karkinos.market_regime_robustness.v1"
        and regimes.get("status") == "pass"
        and _valid_evidence_fingerprint(regimes)
        and int(regimes.get("regime_count") or 0) >= 2
        and int(regimes.get("failed_regime_count") or 0) == 0
        and len(regime_rows) == int(regimes.get("regime_count") or 0)
        and all(
            row.get("status") == "pass" and int(row.get("observation_count") or 0) >= 2
            for row in regime_rows
        ),
        blocker="candidate_market_regime_robustness_not_passing",
        evidence={
            "status": regimes.get("status"),
            "regime_count": regimes.get("regime_count"),
            "failed_regime_count": regimes.get("failed_regime_count"),
            "regime_names": [row.get("name") for row in regime_rows],
            "evidence_fingerprint": regimes.get("evidence_fingerprint"),
        },
    )

    baseline_drawdown = abs(_number(baseline.get("max_drawdown")) or 0)
    candidate_drawdown = abs(_number(candidate.get("max_drawdown")) or 0)
    record(
        "drawdown",
        passed=candidate_drawdown <= baseline_drawdown,
        blocker="candidate_drawdown_exceeds_reviewed_baseline",
        evidence={
            "baseline_max_drawdown": baseline_drawdown,
            "candidate_max_drawdown": candidate_drawdown,
        },
    )

    baseline_turnover = _turnover_ratio(baseline)
    candidate_turnover = _turnover_ratio(candidate)
    record(
        "turnover",
        passed=baseline_turnover is not None
        and candidate_turnover is not None
        and candidate_turnover <= baseline_turnover,
        blocker="candidate_turnover_exceeds_reviewed_baseline",
        evidence={
            "baseline_turnover_to_initial_cash": baseline_turnover,
            "candidate_turnover_to_initial_cash": candidate_turnover,
        },
    )

    account_capital = _mapping(candidate.get("account_capital_constraint"))
    account_capital_passed = is_valid_passed_research_account_capital_evidence(
        account_capital,
        expected_initial_cash=candidate.get("initial_cash"),
    )
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
            "evidence_fingerprint": account_capital.get("evidence_fingerprint"),
        },
    )

    capacity = _mapping(candidate.get("capacity_review"))
    capacity_utilization = _number(capacity.get("capacity_utilization_pct"))
    liquidity_utilization = _number(capacity.get("liquidity_utilization_pct"))
    capacity_passed = (
        capacity.get("status") == "pass"
        and _valid_evidence_fingerprint(capacity)
        and bool(capacity.get("capacity_model_ref"))
        and capacity_utilization is not None
        and liquidity_utilization is not None
        and 0 <= capacity_utilization <= 1
        and 0 <= liquidity_utilization <= 1
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

    baseline_fees = _mapping(baseline.get("fee_component_evidence"))
    candidate_fees = _mapping(candidate.get("fee_component_evidence"))
    baseline_fee_components_complete = _fee_component_evidence_complete(baseline_fees)
    candidate_fee_components_complete = _fee_component_evidence_complete(candidate_fees)
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

    unique_blockers = tuple(dict.fromkeys(blockers))
    return StrategyAdvancementGate(
        status="pass" if not unique_blockers else "blocked",
        blockers=unique_blockers,
        checks=tuple(checks),
    )


def _rolling_oos_comparison(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    baseline_folds = baseline.get("oos_folds")
    candidate_folds = candidate.get("oos_folds")
    baseline_folds = baseline_folds if isinstance(baseline_folds, list) else []
    candidate_folds = candidate_folds if isinstance(candidate_folds, list) else []
    if (
        baseline.get("oos_validation_mode") != "rolling"
        or int(baseline.get("oos_fold_count") or 0) < 2
        or len(baseline_folds) < 2
    ):
        return _missing_rolling_comparison("baseline_rolling_oos_not_passing")
    if (
        candidate.get("oos_validation_mode") != "rolling"
        or int(candidate.get("oos_fold_count") or 0) < 2
        or len(candidate_folds) < 2
    ):
        return _missing_rolling_comparison("candidate_rolling_oos_not_passing")
    if len(candidate_folds) != len(baseline_folds):
        return _missing_rolling_comparison("candidate_rolling_oos_fold_mismatch")

    excess_returns: list[float] = []
    for baseline_fold, candidate_fold in zip(
        baseline_folds, candidate_folds, strict=True
    ):
        baseline_fold = _mapping(baseline_fold)
        candidate_fold = _mapping(candidate_fold)
        if baseline_fold.get("fold_index") != candidate_fold.get(
            "fold_index"
        ) or baseline_fold.get("split_timestamp") != candidate_fold.get(
            "split_timestamp"
        ):
            return _missing_rolling_comparison(
                "candidate_rolling_oos_fold_identity_mismatch"
            )
        baseline_return = _number(baseline_fold.get("net_return"))
        candidate_return = _number(candidate_fold.get("net_return"))
        baseline_cost = _number(baseline_fold.get("total_cost"))
        candidate_cost = _number(candidate_fold.get("total_cost"))
        if (
            baseline_return is None
            or candidate_return is None
            or baseline_cost is None
            or candidate_cost is None
            or baseline_cost < 0
            or candidate_cost < 0
        ):
            return _missing_rolling_comparison(
                "candidate_rolling_oos_fold_cost_or_return_missing"
            )
        excess_returns.append(candidate_return - baseline_return)

    return {
        "evidence_complete": True,
        "evidence_blocker": "",
        "aligned_fold_count": len(excess_returns),
        "mean_excess_return": sum(excess_returns) / len(excess_returns),
        "worst_excess_return": min(excess_returns),
        "fold_pass_rate": (
            sum(1 for value in excess_returns if value > 0) / len(excess_returns)
        ),
    }


def _missing_rolling_comparison(blocker: str) -> dict[str, Any]:
    return {
        "evidence_complete": False,
        "evidence_blocker": blocker,
        "aligned_fold_count": 0,
        "mean_excess_return": None,
        "worst_excess_return": None,
        "fold_pass_rate": None,
    }


def _turnover_ratio(view: Mapping[str, Any]) -> float | None:
    turnover = _number(view.get("gross_turnover"))
    initial_cash = _number(view.get("initial_cash"))
    if turnover is None or initial_cash is None or initial_cash <= 0:
        return None
    return turnover / initial_cash


def _difference(left: Any, right: Any) -> float | None:
    normalized_left = _number(left)
    normalized_right = _number(right)
    if normalized_left is None or normalized_right is None:
        return None
    return normalized_left - normalized_right


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _nonnegative_number(value: Any) -> bool:
    normalized = _number(value)
    return normalized is not None and normalized >= 0


def _fee_component_evidence_complete(fees: Mapping[str, Any]) -> bool:
    components = _mapping(fees.get("components"))
    binding = _mapping(fees.get("fee_schedule_binding"))
    required_components = {"commission", "stamp_tax", "transfer_fee", "slippage"}
    cost_model_reference = str(fees.get("cost_model_reference") or "")
    fill_rule_versions = fees.get("fill_rule_versions")
    return (
        fees.get("status") == "complete"
        and _valid_evidence_fingerprint(fees)
        and fees.get("includes_taxes") is True
        and bool(fees.get("fee_rule_id"))
        and bool(fees.get("fee_rule_version"))
        and fees.get("account_specific") is True
        and fees.get("fee_schedule_source")
        == "reviewed_account_truth_or_reconciled_fee_schedule"
        and _valid_snapshot_id(fees.get("fee_schedule_fingerprint"))
        and fees.get("broker_statement_reconciled") is True
        and bool(_REVIEWED_COST_MODEL_PATTERN.fullmatch(cost_model_reference))
        and _reviewed_cost_model_binding_matches(cost_model_reference, binding)
        and fees.get("fee_rule_version") == cost_model_reference
        and fill_rule_versions == [cost_model_reference]
        and _fee_schedule_binding_complete(binding)
        and required_components.issubset(components)
        and all(_nonnegative_number(components.get(key)) for key in required_components)
    )


def _fee_component_gate_evidence(fees: Mapping[str, Any]) -> dict[str, Any]:
    components = _mapping(fees.get("components"))
    binding = _mapping(fees.get("fee_schedule_binding"))
    return {
        "status": fees.get("status"),
        "includes_taxes": fees.get("includes_taxes"),
        "fee_rule_id": fees.get("fee_rule_id"),
        "fee_rule_version": fees.get("fee_rule_version"),
        "account_specific": fees.get("account_specific"),
        "fee_schedule_source": fees.get("fee_schedule_source"),
        "fee_schedule_fingerprint": fees.get("fee_schedule_fingerprint"),
        "broker_statement_reconciled": fees.get("broker_statement_reconciled"),
        "fee_schedule_review_id": binding.get("fee_schedule_review_id"),
        "fee_schedule_review_fingerprint": binding.get(
            "fee_schedule_review_fingerprint"
        ),
        "component_keys": sorted(components),
        "evidence_fingerprint": fees.get("evidence_fingerprint"),
    }


def _fee_schedule_binding_complete(binding: Mapping[str, Any]) -> bool:
    review_id = str(binding.get("fee_schedule_review_id") or "")
    import_run_id = str(binding.get("account_truth_import_run_id") or "")
    if not review_id.startswith("fee_review_") or not import_run_id:
        return False
    for key in (
        "fee_schedule_review_fingerprint",
        "fee_schedule_preview_fingerprint",
        "account_truth_source_fingerprint",
        "account_truth_scope_fingerprint",
        "fee_notional_envelope_fingerprint",
    ):
        if not _valid_snapshot_id(binding.get(key)):
            return False
    covered_assets = binding.get("fee_notional_covered_asset_classes")
    if (
        binding.get("fee_notional_envelope_enforced") is not True
        or not isinstance(covered_assets, list)
        or not covered_assets
        or any(str(item) not in {"stock", "etf"} for item in covered_assets)
        or covered_assets != sorted(set(covered_assets))
    ):
        return False
    try:
        start_date = date.fromisoformat(str(binding.get("effective_start_date") or ""))
        end_date = date.fromisoformat(str(binding.get("effective_end_date") or ""))
    except ValueError:
        return False
    return start_date <= end_date


def _reviewed_cost_model_binding_matches(
    cost_model_reference: str,
    binding: Mapping[str, Any],
) -> bool:
    matched = _REVIEWED_COST_MODEL_PATTERN.fullmatch(cost_model_reference)
    if matched is None:
        return False
    suffix = cost_model_reference.rsplit(":", maxsplit=2)
    if len(suffix) != 3:
        return False
    review_id, fingerprint = suffix[1], suffix[2]
    return (
        binding.get("fee_schedule_review_id") == review_id
        and binding.get("fee_schedule_review_fingerprint") == f"sha256:{fingerprint}"
    )


def _fee_schedule_bindings_match(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> bool:
    return (
        baseline.get("cost_model_reference") == candidate.get("cost_model_reference")
        and baseline.get("fee_schedule_fingerprint")
        == candidate.get("fee_schedule_fingerprint")
        and _mapping(baseline.get("fee_schedule_binding"))
        == _mapping(candidate.get("fee_schedule_binding"))
    )


def _valid_fingerprint(value: Any) -> bool:
    return bool(_FINGERPRINT_PATTERN.fullmatch(str(value or "").lower()))


def _valid_evidence_fingerprint(value: Mapping[str, Any]) -> bool:
    payload = dict(value)
    fingerprint = payload.pop("evidence_fingerprint", None)
    return _valid_fingerprint(fingerprint) and str(
        fingerprint
    ).lower() == _payload_fingerprint(payload)


def _valid_snapshot_id(value: Any) -> bool:
    normalized = str(value or "").lower()
    prefix, separator, fingerprint = normalized.partition(":")
    return prefix == "sha256" and separator == ":" and _valid_fingerprint(fingerprint)


def _payload_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
