"""Evidence-specific checks and normalization for strategy advancement."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from typing import Any, Mapping

from analytics.backtest_capacity_evidence import (
    is_valid_passed_backtest_capacity_evidence,
)
from analytics.backtest_fee_tax_evidence import (
    is_valid_complete_backtest_fee_tax_evidence,
)
from analytics.backtest_market_regime_evidence import (
    MARKET_REGIME_EVIDENCE_SCHEMA_VERSION,
    is_valid_passed_backtest_market_regime_evidence,
)
from analytics.oos_validation import (
    is_valid_rolling_out_of_sample_validation_evidence,
)
from analytics.sweep_robustness import (
    is_valid_passed_sweep_robustness_evidence,
)

_FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_REVIEWED_COST_MODEL_PATTERN = re.compile(
    r"^karkinos\.backtest\.reviewed_account_fee_schedule\.v1:"
    r"fee_review_[0-9a-f]{32}:[0-9a-f]{64}$"
)


def parameter_robustness_check(candidate: Mapping[str, Any]) -> dict[str, Any]:
    parameter = _mapping(candidate.get("parameter_robustness"))
    local_stability = _mapping(parameter.get("local_stability"))
    warnings_value = parameter.get("overfitting_warnings")
    warnings = warnings_value if isinstance(warnings_value, list) else []
    selected_params = _mapping(parameter.get("selected_params"))
    formula_values = _mapping(candidate.get("formula_parameter_values"))
    passed = (
        is_valid_passed_sweep_robustness_evidence(
            parameter,
            expected_selected_params=formula_values,
        )
        and parameter.get("schema_version") == "karkinos.sweep_robustness.v1"
        and _valid_evidence_fingerprint(parameter)
        and isinstance(warnings_value, list)
        and not warnings
        and bool(formula_values)
        and selected_params == formula_values
        and _mapping(parameter.get("best_params")) == formula_values
    )
    return {
        "passed": passed,
        "blocker": "candidate_parameter_robustness_not_passing",
        "evidence": {
            "tested_count": parameter.get("tested_count"),
            "neighbor_count": local_stability.get("neighbor_count"),
            "stability_ratio": local_stability.get("stability_ratio"),
            "warning_count": len(warnings),
            "selected_params": selected_params,
            "formula_parameter_values": formula_values,
            "best_params": _mapping(parameter.get("best_params")),
            "evidence_fingerprint": parameter.get("evidence_fingerprint"),
        },
    }


def market_regime_robustness_check(candidate: Mapping[str, Any]) -> dict[str, Any]:
    regimes = _mapping(candidate.get("market_regime_robustness"))
    rows_value = regimes.get("regimes")
    rows = (
        [dict(row) for row in rows_value if isinstance(row, Mapping)]
        if isinstance(rows_value, list)
        else []
    )
    names = [str(row.get("name") or "").strip() for row in rows]
    count = _integer(regimes.get("regime_count"))
    failed_count = _integer(regimes.get("failed_regime_count"))
    passed = (
        is_valid_passed_backtest_market_regime_evidence(regimes)
        and regimes.get("schema_version") == MARKET_REGIME_EVIDENCE_SCHEMA_VERSION
        and regimes.get("status") == "pass"
        and _valid_evidence_fingerprint(regimes)
        and count is not None
        and count >= 2
        and failed_count == 0
        and len(rows) == count
        and all(names)
        and len(set(names)) == count
        and all(
            row.get("status") == "pass"
            and (_integer(row.get("observation_count")) or 0) >= 2
            for row in rows
        )
    )
    return {
        "passed": passed,
        "blocker": "candidate_market_regime_robustness_not_passing",
        "evidence": {
            "status": regimes.get("status"),
            "regime_count": regimes.get("regime_count"),
            "failed_regime_count": regimes.get("failed_regime_count"),
            "regime_names": names,
            "evidence_fingerprint": regimes.get("evidence_fingerprint"),
        },
    }


def _rolling_oos_comparison(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    if not is_valid_rolling_out_of_sample_validation_evidence(
        baseline.get("oos_validation"), minimum_fold_count=2
    ):
        return _missing_rolling_comparison(
            "baseline_rolling_oos_evidence_not_reproducible"
        )
    if not is_valid_rolling_out_of_sample_validation_evidence(
        candidate.get("oos_validation"), minimum_fold_count=2
    ):
        return _missing_rolling_comparison(
            "candidate_rolling_oos_evidence_not_reproducible"
        )
    baseline_oos = _mapping(baseline.get("oos_validation"))
    candidate_oos = _mapping(candidate.get("oos_validation"))
    if any(
        baseline_oos.get(key) != candidate_oos.get(key)
        for key in (
            "benchmark_role",
            "min_train_points",
            "test_window_points",
            "step_points",
            "equity_point_count",
        )
    ):
        return _missing_rolling_comparison(
            "candidate_rolling_oos_configuration_mismatch"
        )
    baseline_folds = baseline.get("oos_folds")
    candidate_folds = candidate.get("oos_folds")
    baseline_folds = baseline_folds if isinstance(baseline_folds, list) else []
    candidate_folds = candidate_folds if isinstance(candidate_folds, list) else []
    baseline_fold_count = _integer(baseline.get("oos_fold_count"))
    candidate_fold_count = _integer(candidate.get("oos_fold_count"))
    if (
        baseline.get("oos_validation_mode") != "rolling"
        or baseline_fold_count is None
        or baseline_fold_count < 2
        or len(baseline_folds) < 2
    ):
        return _missing_rolling_comparison("baseline_rolling_oos_not_passing")
    if len(baseline_folds) != baseline_fold_count:
        return _missing_rolling_comparison("baseline_rolling_oos_fold_count_mismatch")
    if (
        candidate.get("oos_validation_mode") != "rolling"
        or candidate_fold_count is None
        or candidate_fold_count < 2
        or len(candidate_folds) < 2
    ):
        return _missing_rolling_comparison("candidate_rolling_oos_not_passing")
    if len(candidate_folds) != candidate_fold_count:
        return _missing_rolling_comparison("candidate_rolling_oos_fold_count_mismatch")
    if len(candidate_folds) != len(baseline_folds):
        return _missing_rolling_comparison("candidate_rolling_oos_fold_mismatch")

    excess_returns: list[float] = []
    fold_identities: list[tuple[Any, str]] = []
    fold_indexes: list[int] = []
    split_timestamps: list[datetime] = []
    for baseline_fold, candidate_fold in zip(
        baseline_folds, candidate_folds, strict=True
    ):
        baseline_fold = _mapping(baseline_fold)
        candidate_fold = _mapping(candidate_fold)
        baseline_fold_index = _integer(baseline_fold.get("fold_index"))
        candidate_fold_index = _integer(candidate_fold.get("fold_index"))
        split_timestamp = str(baseline_fold.get("split_timestamp") or "").strip()
        if (
            baseline_fold_index is None
            or baseline_fold_index != candidate_fold_index
            or split_timestamp
            != str(candidate_fold.get("split_timestamp") or "").strip()
        ):
            return _missing_rolling_comparison(
                "candidate_rolling_oos_fold_identity_mismatch"
            )
        try:
            parsed_split_timestamp = datetime.fromisoformat(
                split_timestamp.replace("Z", "+00:00")
            )
        except ValueError:
            return _missing_rolling_comparison(
                "candidate_rolling_oos_fold_identity_invalid"
            )
        fold_identities.append((baseline_fold_index, split_timestamp))
        fold_indexes.append(baseline_fold_index)
        split_timestamps.append(parsed_split_timestamp)
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

    if len(set(fold_identities)) != len(fold_identities) or len(
        set(fold_indexes)
    ) != len(fold_indexes):
        return _missing_rolling_comparison(
            "candidate_rolling_oos_fold_identity_duplicate"
        )
    try:
        timestamps_increasing = all(
            right > left
            for left, right in zip(
                split_timestamps,
                split_timestamps[1:],
            )
        )
    except TypeError:
        timestamps_increasing = False
    if not timestamps_increasing:
        return _missing_rolling_comparison("candidate_rolling_oos_fold_order_invalid")

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


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if math.isfinite(normalized) else None


def _integer(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return normalized


def _nonnegative_number(value: Any) -> bool:
    normalized = _number(value)
    return normalized is not None and normalized >= 0


def _fee_component_evidence_complete(
    fees: Mapping[str, Any],
    *,
    view: Mapping[str, Any],
) -> bool:
    components = _mapping(fees.get("components"))
    binding = _mapping(fees.get("fee_schedule_binding"))
    required_components = {"commission", "stamp_tax", "transfer_fee", "slippage"}
    cost_model_reference = str(fees.get("cost_model_reference") or "")
    fill_rule_versions = fees.get("fill_rule_versions")
    return (
        is_valid_complete_backtest_fee_tax_evidence(
            fees,
            expected_total_commission=view.get("total_commission"),
            expected_total_slippage=view.get("total_slippage"),
            expected_total_cost=view.get("total_cost"),
            expected_fill_count=view.get("total_trades"),
        )
        and _after_cost_evidence_complete(view)
        and fees.get("status") == "complete"
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


def _after_cost_evidence_complete(view: Mapping[str, Any]) -> bool:
    initial_cash = _number(view.get("initial_cash"))
    final_equity = _number(view.get("final_equity"))
    total_return = _number(view.get("total_return"))
    total_cost = _number(view.get("total_cost"))
    net_pnl = _number(view.get("net_pnl"))
    gross_pnl = _number(view.get("gross_pnl_before_costs"))
    net_return = _number(view.get("net_return"))
    gross_return = _number(view.get("gross_return_before_costs"))
    cost_ratio = _number(view.get("cost_to_initial_cash"))
    gross_turnover = _number(view.get("gross_turnover"))
    evidence_turnover = _number(view.get("evidence_gross_turnover"))
    total_trades = _integer(view.get("total_trades"))
    evidence_fills = _integer(view.get("evidence_fill_count"))
    if (
        initial_cash is None
        or initial_cash <= 0
        or final_equity is None
        or total_return is None
        or total_cost is None
        or total_cost < 0
        or net_pnl is None
        or gross_pnl is None
        or net_return is None
        or gross_return is None
        or cost_ratio is None
        or gross_turnover is None
        or evidence_turnover is None
        or total_trades is None
        or evidence_fills != total_trades
    ):
        return False
    return all(
        (
            math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
            for left, right in (
                (final_equity - initial_cash, net_pnl),
                (net_pnl / initial_cash, total_return),
                (net_return, total_return),
                (net_pnl + total_cost, gross_pnl),
                (gross_pnl / initial_cash, gross_return),
                (total_cost / initial_cash, cost_ratio),
                (gross_turnover, evidence_turnover),
            )
        )
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


rolling_oos_comparison = _rolling_oos_comparison
turnover_ratio = _turnover_ratio
difference = _difference
mapping = _mapping
json_object = _json_object
json_list = _json_list
number = _number
integer = _integer
fee_component_evidence_complete = _fee_component_evidence_complete
fee_component_gate_evidence = _fee_component_gate_evidence
fee_schedule_bindings_match = _fee_schedule_bindings_match
valid_fingerprint = _valid_fingerprint
valid_snapshot_id = _valid_snapshot_id
payload_fingerprint = _payload_fingerprint
