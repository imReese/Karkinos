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
from analytics.dataset_snapshot import dataset_research_use
from analytics.research_account_capital_evidence import (
    is_valid_passed_research_account_capital_evidence,
)
from analytics.strategy_advancement_evidence import difference as _difference
from analytics.strategy_advancement_evidence import (
    drawdown_check,
    market_regime_robustness_check,
    parameter_robustness_check,
    research_execution_policy_matches,
)
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
from analytics.strategy_advancement_evidence import number as _number
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

GATE_SCHEMA = "karkinos.strategy_advancement_gate"
LEGACY_GATE_SCHEMAS = frozenset({"karkinos.strategy_advancement_gate.v2"})
MANUAL_FINAL_ADVANCEMENT_GATE_SCHEMA = "karkinos.strategy_advancement_gate.manual_final"
MANUAL_FINAL_REQUIRED_CHECK_NAMES = (
    "frozen_dataset_identity",
    "rolling_out_of_sample",
    "after_cost_oos_excess",
    "parameter_robustness",
    "market_regime_robustness",
    "drawdown_accounting",
    "turnover_accounting",
    "real_account_capital_constraint",
    "capacity_and_liquidity",
    "baseline_realistic_cost_and_tax_evidence",
    "candidate_realistic_cost_and_tax_evidence",
    "after_tax_excess_return",
    "independent_critique",
    "independent_final_evaluation",
    "reviewed_account_evaluation",
)
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
    manual_profile: Mapping[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass" and not self.blockers

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": GATE_SCHEMA,
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
        if self.manual_profile is not None:
            payload.update(
                schema_version=MANUAL_FINAL_ADVANCEMENT_GATE_SCHEMA,
                **dict(self.manual_profile),
            )
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
    manual = payload.get("schema_version") == MANUAL_FINAL_ADVANCEMENT_GATE_SCHEMA
    normalized_checks = [dict(check) for check in checks if isinstance(check, Mapping)]
    check_names = tuple(check.get("name") for check in normalized_checks)
    required_names = STRATEGY_ADVANCEMENT_REQUIRED_CHECK_NAMES
    optional_names = STRATEGY_ADVANCEMENT_OPTIONAL_CHECK_NAMES
    names_valid = check_names in {
        required_names,
        required_names + optional_names,
        required_names + ("independent_final_evaluation",),
        required_names + optional_names + ("independent_final_evaluation",),
    }
    if manual:
        names_valid = check_names == MANUAL_FINAL_REQUIRED_CHECK_NAMES
        try:
            from server.contracts.ai_shadow_research_qualification import (
                qualification_source_binding,
            )

            source = qualification_source_binding(
                {"source_binding": payload.get("source_binding")}
            )
            by_name = {check["name"]: check for check in normalized_checks}
            final = by_name["independent_final_evaluation"]["evidence"]
            reviewed = by_name["reviewed_account_evaluation"]["evidence"]
            diagnostics = payload["legacy_gate_diagnostics"]
            if (
                source is None
                or source != final["source_binding"]
                or final["research_policy_fingerprint"]
                != payload["research_policy_fingerprint"]
                or reviewed["reviewed_replay_fingerprint"]
                != payload["reviewed_replay_fingerprint"]
                or reviewed["source_binding"] != source
                or not _valid_snapshot_id(payload["research_policy_fingerprint"])
                or not _valid_fingerprint(payload["reviewed_replay_fingerprint"])
                or diagnostics.get("schema_version")
                not in ({GATE_SCHEMA} | LEGACY_GATE_SCHEMAS)
                or not _self_hashed(diagnostics)
            ):
                return False
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
    return (
        len(normalized_checks) == len(checks)
        and names_valid
        and all(
            check.get("status") == "pass"
            and check.get("blocker") is None
            and isinstance(check.get("evidence"), Mapping)
            for check in normalized_checks
        )
        and (
            payload.get("schema_version") == MANUAL_FINAL_ADVANCEMENT_GATE_SCHEMA
            if manual
            else payload.get("schema_version") in ({GATE_SCHEMA} | LEGACY_GATE_SCHEMAS)
        )
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


def replay_advancement_gate_schema(
    replayed: dict[str, Any], recorded: Mapping[str, Any]
) -> dict[str, Any]:
    """Serialize freshly computed evidence under its original, supported schema."""
    schema = recorded.get("schema_version")
    if (
        replayed.get("schema_version") != GATE_SCHEMA
        or not isinstance(schema, str)
        or schema not in LEGACY_GATE_SCHEMAS
        or not _self_hashed(replayed)
    ):
        return replayed
    payload = {k: v for k, v in replayed.items() if k != "evidence_fingerprint"}
    payload["schema_version"] = schema
    return {**payload, "evidence_fingerprint": _payload_fingerprint(payload)}


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
    account_replay = _json_object(metrics.get("simulation_account_replay"))
    reviewed_replay = _json_object(account_replay.get("reviewed_replay"))
    reviewed_assessment = _json_object(reviewed_replay.get("deployment_assessment"))
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
        "normalized_market_data": bool(dataset.get("market_data_binding")),
        "research_execution_policy": {
            key: _json_object(metrics.get("signal_execution_evidence")).get(key)
            for key in (
                "execution_policy",
                "allocation_slots",
                "canonical_target_weight",
            )
        },
        "cost_assumptions": _json_object(metrics.get("cost_assumptions")),
        "dataset_snapshot": dataset,
        "dataset_quality_status": dataset_quality.get("status"),
        "dataset_issue_count": len(dataset_quality.get("issues") or []),
        **(
            {"dataset_research_use": dataset_research_use(dataset)}
            if "research_use" in dataset or "market_data_binding" in dataset
            else {}
        ),
        **(
            {"immutable_dataset_id": dataset["immutable_dataset_id"]}
            if "immutable_dataset_id" in dataset
            else {}
        ),
        "parameter_robustness": _json_object(
            metrics.get("parameter_robustness") or metrics.get("sweep_robustness")
        ),
        "formula_ast": _json_object(
            _json_object(metrics.get("formula_binding")).get("formula_ast")
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
        **(
            {"independent_evaluation": metrics["independent_evaluation"]}
            if "independent_evaluation" in metrics
            else {}
        ),
        **(
            {
                "simulation_account_replay": dict(account_replay),
                "formula_fingerprint": metrics.get("formula_fingerprint"),
            }
            if account_replay.get("manual_source_binding") is not None
            else {}
        ),
        **(
            {
                "account_deployment_validation": {
                    "status": reviewed_assessment.get("status"),
                    "checkpoint": reviewed_assessment.get("effective_checkpoint"),
                    "fee_cost_model_reference": account_replay.get(
                        "cost_model_reference"
                    ),
                    "blockers": reviewed_assessment.get("blockers"),
                    "validation_provenance": "reviewed_account_cost_replay",
                    "evidence_fingerprint": account_replay.get("evidence_fingerprint"),
                }
            }
            if "simulation_account_replay" in metrics
            else {}
        ),
    }


def build_strategy_advancement_gate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    critique_evidence: Mapping[str, Any],
    require_independent_evaluation: bool = False,
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
    admission_blocker = None
    from analytics.sealed_holdout import final_research_evaluation_blocker

    final = candidate.get("independent_evaluation") or {}
    independent_deployment = (
        bool(final.get("reservation", {}).get("deployment_scope"))
        and final_research_evaluation_blocker(final) is None
    )
    if independent_deployment:
        admission_blocker = None
    elif candidate.get("dataset_research_use") == "exploratory_backtest":
        admission_blocker = "candidate_dataset_exploratory_only"
    elif "dataset_research_use" in candidate or "immutable_dataset_id" in candidate:
        admission_blocker = "candidate_dataset_research_use_not_admitted"
    elif "dataset_research_use" in baseline or "immutable_dataset_id" in baseline:
        admission_blocker = "baseline_dataset_research_use_not_admitted"
    record(
        "frozen_dataset_identity",
        passed=research_execution_policy_matches(baseline, candidate)
        and _valid_snapshot_id(baseline_snapshot)
        and _valid_snapshot_id(candidate_snapshot)
        and candidate_snapshot == baseline_snapshot
        and candidate.get("dataset_quality_status") == "ok"
        and _integer(candidate.get("dataset_issue_count")) == 0
        and admission_blocker is None,
        blocker=(
            "research_execution_policy_mismatch"
            if not research_execution_policy_matches(baseline, candidate)
            else "candidate_dataset_snapshot_missing"
            if not candidate_snapshot
            else (
                "candidate_dataset_snapshot_mismatch"
                if candidate_snapshot != baseline_snapshot
                else admission_blocker or "candidate_dataset_quality_not_clear"
            )
        ),
        evidence={
            "baseline_snapshot_id": baseline_snapshot or None,
            "candidate_snapshot_id": candidate_snapshot or None,
            "candidate_quality_status": candidate.get("dataset_quality_status"),
            "candidate_issue_count": candidate.get("dataset_issue_count"),
            **(
                {"candidate_research_use": candidate["dataset_research_use"]}
                if "dataset_research_use" in candidate
                else {}
            ),
            **(
                {"candidate_immutable_dataset_id": candidate["immutable_dataset_id"]}
                if "immutable_dataset_id" in candidate
                else {}
            ),
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

    record("drawdown", **drawdown_check(baseline, candidate))

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
        and (
            candidate_turnover <= baseline_turnover
            or (
                candidate_capacity.get("status") == "pass"
                and _number(candidate_capacity.get("capacity_utilization_pct"))
                is not None
                and _number(candidate_capacity.get("capacity_utilization_pct")) <= 1.0
            )
        )
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
    ) == candidate_fee_binding.get("account_truth_scope_fingerprint")
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

    if require_independent_evaluation or "independent_evaluation" in candidate:
        from analytics.sealed_holdout import final_research_evaluation_blocker

        independent = candidate.get("independent_evaluation")
        independent_blocker = final_research_evaluation_blocker(independent)
        if independent_blocker is None and (
            not candidate.get("formula_ast")
            or "sha256:" + _payload_fingerprint(candidate["formula_ast"])
            != independent["reservation"]["champion_formula_fingerprint"]
        ):
            independent_blocker = "independent_final_formula_mismatch"
        record(
            "independent_final_evaluation",
            passed=independent_blocker is None,
            blocker=independent_blocker or "independent_final_evaluation_invalid",
            evidence=independent if isinstance(independent, Mapping) else {},
        )
    unique_blockers = tuple(dict.fromkeys(blockers))
    return StrategyAdvancementGate(
        status="pass" if not unique_blockers else "blocked",
        blockers=unique_blockers,
        checks=tuple(checks),
    )


def _self_hashed(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    core = dict(value)
    fingerprint = core.pop("evidence_fingerprint", None)
    try:
        return fingerprint == _payload_fingerprint(core)
    except (TypeError, ValueError):
        return False


def _manual_final_binding(candidate, source_binding):
    """Check full frozen evidence and identities, never a caller's pass flag."""
    from decimal import Decimal

    from analytics.sealed_holdout import final_research_evaluation_blocker
    from server.contracts.ai_shadow_research_qualification import (
        qualification_source_binding,
    )
    from server.contracts.recommendation_publication import (
        is_final_statistical_policy,
    )

    source = qualification_source_binding({"source_binding": source_binding})
    final = candidate["independent_evaluation"]
    binding = final["reservation"]
    sim = binding["simulation_policy"]
    profile = sim["statistical_policy"]
    refs = source["manual_source_refs"]
    expected = {
        "source_kind": binding.get("source_kind"),
        "manual_source_refs": binding.get("manual_source_refs"),
        "manual_source_fingerprint": binding.get("manual_source_fingerprint"),
        "final_evaluation_id": final.get("sealed_test_id"),
        "final_evidence_fingerprint": final.get("evidence_fingerprint"),
    }
    if (
        source != expected
        or source["source_kind"] != "manual_research"
        or final_research_evaluation_blocker(final) is not None
        or not is_final_statistical_policy(profile)
        or profile.get("primary_comparator") != "Gen7"
        or not _valid_snapshot_id(profile.get("research_policy_fingerprint"))
        or any(
            binding[key] != refs[ref]
            for key, ref in (
                ("session_id", "session_id"),
                ("draft_id", "draft_id"),
                ("backtest_run_id", "backtest_run_id"),
                ("candidate_result_id", "canonical_backtest_result_id"),
            )
        )
        or "sha256:" + _payload_fingerprint(candidate["formula_ast"])
        != binding["champion_formula_fingerprint"]
        or Decimal(str(candidate["initial_cash"])) != Decimal(binding["initial_cash"])
        or sim["max_final_tests"] != 1
        or Decimal(sim["total_error_budget"]) != Decimal("0.05")
        or Decimal(profile["significance_level"]) != Decimal("0.05")
        or binding["error_budget"]["attempt_count"] != 1
        or Decimal(binding["error_budget"]["allocated_alpha"]) != Decimal("0.05")
        or Decimal(binding["error_budget"]["error_budget_spent"]) != Decimal("0.05")
    ):
        raise ValueError("manual_final_binding_invalid")
    return source, final, binding, sim, profile


def _manual_reviewed_binding(candidate, source, final, binding, sim, profile):
    from decimal import Decimal

    from analytics.backtest_drawdown_evidence import build_backtest_drawdown_evidence
    from analytics.deployment_validation import compare_session_curves
    from server.contracts.content_identity import content_fingerprint

    replay = candidate["simulation_account_replay"]
    derived = replay["reviewed_replay"]
    assessment = derived["deployment_assessment"]
    fee = candidate["fee_component_evidence"]["fee_schedule_binding"]
    fee_schedule = {
        "review_id": fee["fee_schedule_review_id"],
        "review_fingerprint": fee["fee_schedule_review_fingerprint"],
        "cost_model_reference": candidate["cost_assumptions"][
            "commission_model_reference"
        ],
        "fee_evidence": fee,
    }
    expected = {
        "manual_source_binding": source,
        "final_evaluation_id": final["sealed_test_id"],
        "final_evidence_fingerprint": final["evidence_fingerprint"],
        "reservation_fingerprint": _payload_fingerprint(binding),
        "qualified_formula_fingerprint": candidate["formula_fingerprint"],
        "review_id": fee_schedule["review_id"],
        "review_fingerprint": fee_schedule["review_fingerprint"],
        "cost_model_reference": fee_schedule["cost_model_reference"],
        "fee_evidence_fingerprint": _payload_fingerprint(fee),
        "initial_cash": binding["initial_cash"],
        "code_fingerprint": binding["code_binding"]["fingerprint"],
        "curves_fingerprint": _payload_fingerprint(final["session_curves"]),
        "portfolio_fingerprint": content_fingerprint(final["portfolio_observations"]),
        "account_scope_fingerprint": fee["account_truth_scope_fingerprint"],
        "statistical_requirements": {
            k: v for k, v in profile.items() if k != "comparator_bindings"
        },
    }
    uncertainty = assessment["uncertainty"]
    reviewed_policy = uncertainty["policy"]
    curves = derived["session_curves"]
    if (
        replay.get("schema_version") != "karkinos.simulation_account_cost_replay.v2"
        or not _self_hashed(replay)
        or not _self_hashed(assessment)
        or any(replay.get(k) != v for k, v in expected.items())
        or derived["fee_schedule"] != fee_schedule
        or {k: v for k, v in reviewed_policy.items() if k != "comparator_bindings"}
        != expected["statistical_requirements"]
        or set(curves["comparators"]) != set(final["session_curves"]["comparators"])
        or [row[0] for row in curves["candidate"]]
        != [row[0] for row in final["session_curves"]["candidate"]]
        or assessment["deployment_scope_fingerprint"]
        != binding["deployment_scope"]["deployment_scope_fingerprint"]
        or assessment["effective_checkpoint"]
        != final["deployment_assessment"]["effective_checkpoint"]
        or assessment["membership_sessions"]
        != final["deployment_assessment"]["membership_sessions"]
        or any(
            Decimal(str(assessment["risk_limits"][k])) > Decimal(str(limit))
            for k, limit in sim["risk_limits"].items()
        )
        or assessment.get("status") != "pass"
        or assessment.get("blockers") != []
    ):
        raise ValueError("manual_reviewed_binding_invalid")
    computed = compare_session_curves(
        candidate=curves["candidate"],
        comparators=curves["comparators"],
        initial_cash=binding["initial_cash"],
        policy=reviewed_policy,
        seed=final["sealed_test_id"],
        policy_fingerprint=uncertainty["policy_fingerprint"],
        comparator_bindings=reviewed_policy["comparator_bindings"],
        effective_checkpoint=assessment["effective_checkpoint"],
    )
    drawdown = build_backtest_drawdown_evidence(
        equity_curve=curves["candidate"], initial_cash=binding["initial_cash"]
    )
    if (
        computed != uncertainty
        or computed["status"] != "pass"
        or drawdown["status"] != "complete"
        or Decimal(str(assessment["risk_limits"]["max_drawdown"]))
        != Decimal(drawdown["max_drawdown_pct"])
        or assessment["statistical_policy_fingerprint"]
        != uncertainty["policy_fingerprint"]
    ):
        raise ValueError("manual_reviewed_economic_evidence_invalid")
    return replay


def build_manual_final_strategy_advancement_gate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    critique_evidence: Mapping[str, Any],
    source_binding: Mapping[str, Any],
) -> StrategyAdvancementGate:
    """Apply the frozen manual final policy, retaining all legacy diagnostics.

    Financial evidence is checked by its existing owners. Original rolling,
    drawdown and turnover preferences remain recorded under their original gate.
    Future economics are re-evaluated from exact original and reviewed evidence.
    Publication consumers must additionally reopen canonical source/fee/account
    facts and the full final calculation; this artifact itself grants no authority.
    """
    from analytics.backtest_drawdown_evidence import (
        is_valid_complete_backtest_drawdown_evidence,
    )

    legacy = build_strategy_advancement_gate(
        baseline=baseline,
        candidate=candidate,
        critique_evidence=critique_evidence,
        require_independent_evaluation=True,
    ).to_json_dict()
    by_name = {check["name"]: check for check in legacy["checks"]}
    checks = []

    def record(name, passed, blocker, evidence):
        checks.append(
            {
                "name": name,
                "status": "pass" if passed else "blocked",
                "blocker": None if passed else blocker,
                "evidence": evidence,
            }
        )

    for name in (
        "frozen_dataset_identity",
        "rolling_out_of_sample",
        "after_cost_oos_excess",
        "parameter_robustness",
        "market_regime_robustness",
    ):
        checks.append(by_name[name])
    dd_complete = all(
        is_valid_complete_backtest_drawdown_evidence(
            view.get("drawdown_evidence"),
            expected_max_drawdown=view.get("max_drawdown"),
            expected_equity_curve=view.get("equity_curve"),
            expected_initial_equity=view.get("initial_cash"),
            expected_final_equity=view.get("final_equity"),
        )
        for view in (baseline, candidate)
    )
    record(
        "drawdown_accounting",
        dd_complete,
        "drawdown_accounting_not_reproducible",
        by_name["drawdown"]["evidence"],
    )
    turnover_complete = all(
        _turnover_ratio(view) is not None
        and is_valid_passed_backtest_capacity_evidence(
            view.get("capacity_review"),
            expected_initial_cash=view.get("initial_cash"),
            expected_gross_turnover=view.get("gross_turnover"),
        )
        for view in (baseline, candidate)
    )
    record(
        "turnover_accounting",
        turnover_complete,
        "turnover_accounting_not_reproducible",
        by_name["turnover"]["evidence"],
    )
    for name in (
        "real_account_capital_constraint",
        "capacity_and_liquidity",
        "baseline_realistic_cost_and_tax_evidence",
        "candidate_realistic_cost_and_tax_evidence",
        "after_tax_excess_return",
    ):
        checks.append(by_name[name])
    source = dict(source_binding) if isinstance(source_binding, Mapping) else {}
    critique = by_name["independent_critique"]
    record(
        "independent_critique",
        critique["status"] == "pass"
        and critique_evidence.get("critique_id")
        == _mapping(source.get("manual_source_refs")).get("critique_id"),
        "completed_manual_research_critique_missing",
        critique["evidence"],
    )
    final_ok = reviewed_ok = False
    policy_fingerprint = replay_fingerprint = None
    try:
        source, final, binding, sim, profile = _manual_final_binding(candidate, source)
        policy_fingerprint = profile["research_policy_fingerprint"]
        final_ok = True
        replay = _manual_reviewed_binding(
            candidate, source, final, binding, sim, profile
        )
        replay_fingerprint = replay["evidence_fingerprint"]
        reviewed_ok = True
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        pass
    record(
        "independent_final_evaluation",
        final_ok,
        "manual_final_evidence_invalid",
        {"source_binding": source, "research_policy_fingerprint": policy_fingerprint},
    )
    record(
        "reviewed_account_evaluation",
        reviewed_ok,
        "manual_reviewed_evidence_invalid",
        {"source_binding": source, "reviewed_replay_fingerprint": replay_fingerprint},
    )
    blockers = tuple(
        dict.fromkeys(
            check["blocker"] for check in checks if check["blocker"] is not None
        )
    )
    return StrategyAdvancementGate(
        status="blocked" if blockers else "pass",
        blockers=blockers,
        checks=tuple(checks),
        manual_profile={
            "source_binding": source,
            "research_policy_fingerprint": policy_fingerprint,
            "reviewed_replay_fingerprint": replay_fingerprint,
            "legacy_gate_diagnostics": legacy,
        },
    )
