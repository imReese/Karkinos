"""Research-stage advancement checks for normalized-notional Formula candidates.

This gate is intentionally narrower than the account-bound strategy advancement
gate. It validates research quality and reproducibility only. Account Truth,
reviewed broker fees, real-account capacity, sizing, and manual-trade authority
remain deferred to the provider-free account qualification stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from analytics.backtest_drawdown_evidence import (
    is_valid_complete_backtest_drawdown_evidence,
)
from analytics.backtest_fee_tax_evidence import (
    is_valid_complete_backtest_fee_tax_evidence,
)
from analytics.strategy_advancement_evidence import (
    market_regime_robustness_check,
    parameter_robustness_check,
    payload_fingerprint,
    research_execution_policy_matches,
    rolling_oos_comparison,
    turnover_ratio,
    valid_snapshot_id,
)

NORMALIZED_RESEARCH_GATE_SCHEMA_VERSION = (
    "karkinos.normalized_research_advancement_gate.v1"
)
NORMALIZED_RESEARCH_REQUIRED_CHECK_NAMES = (
    "frozen_dataset_identity",
    "rolling_out_of_sample",
    "after_cost_oos_excess",
    "parameter_robustness",
    "market_regime_robustness",
    "drawdown",
    "turnover",
    "baseline_estimated_cost_and_tax_evidence",
    "candidate_estimated_cost_and_tax_evidence",
    "estimated_after_cost_excess_return",
    "independent_critique",
)


@dataclass(frozen=True)
class NormalizedResearchAdvancementGate:
    status: str
    blockers: tuple[str, ...]
    checks: tuple[dict[str, Any], ...]

    @property
    def passed(self) -> bool:
        return self.status == "pass" and not self.blockers

    def to_json_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": NORMALIZED_RESEARCH_GATE_SCHEMA_VERSION,
            "status": self.status,
            "blockers": list(self.blockers),
            "checks": [dict(check) for check in self.checks],
            "deterministic": True,
            "normalized_notional_only": True,
            "account_qualification_required": True,
            "human_confirmation_required": True,
            "does_not_register_strategy": True,
            "does_not_create_order": True,
            "does_not_authorize_execution": True,
            "does_not_change_capital_authority": True,
        }
        return {**payload, "evidence_fingerprint": payload_fingerprint(payload)}


def build_normalized_research_advancement_gate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    critique_evidence: Mapping[str, Any],
) -> NormalizedResearchAdvancementGate:
    """Validate normalized research without borrowing account execution gates."""

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
        passed=(
            research_execution_policy_matches(baseline, candidate)
            and valid_snapshot_id(baseline_snapshot)
            and valid_snapshot_id(candidate_snapshot)
            and baseline_snapshot == candidate_snapshot
            and candidate.get("dataset_quality_status") == "ok"
            and int(candidate.get("dataset_issue_count") or 0) == 0
        ),
        blocker=(
            "research_execution_policy_mismatch"
            if not research_execution_policy_matches(baseline, candidate)
            else "candidate_dataset_snapshot_missing"
            if not candidate_snapshot
            else (
                "candidate_dataset_snapshot_mismatch"
                if baseline_snapshot != candidate_snapshot
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

    rolling = rolling_oos_comparison(baseline, candidate)
    record(
        "rolling_out_of_sample",
        passed=bool(rolling["evidence_complete"]),
        blocker=str(rolling["evidence_blocker"]),
        evidence={
            "minimum_fold_count": 2,
            "aligned_fold_count": rolling["aligned_fold_count"],
            "baseline_fold_count": baseline.get("oos_fold_count"),
            "candidate_fold_count": candidate.get("oos_fold_count"),
        },
    )
    mean_excess = rolling["mean_excess_return"]
    worst_excess = rolling["worst_excess_return"]
    fold_pass_rate = rolling["fold_pass_rate"]
    record(
        "after_cost_oos_excess",
        passed=(
            bool(rolling["evidence_complete"])
            and mean_excess is not None
            and worst_excess is not None
            and fold_pass_rate is not None
            and mean_excess > 0
            and worst_excess >= 0
            and fold_pass_rate >= 0.5
        ),
        blocker="candidate_after_cost_oos_excess_not_positive",
        evidence={
            "mean_oos_excess_return": mean_excess,
            "worst_oos_excess_return": worst_excess,
            "fold_pass_rate": fold_pass_rate,
            "minimum_fold_pass_rate": 0.5,
        },
    )

    record("parameter_robustness", **parameter_robustness_check(candidate))
    record("market_regime_robustness", **market_regime_robustness_check(candidate))

    baseline_drawdown = _drawdown_evidence_valid(baseline)
    candidate_drawdown = _drawdown_evidence_valid(candidate)
    baseline_drawdown_value = _number(baseline.get("max_drawdown"))
    candidate_drawdown_value = _number(candidate.get("max_drawdown"))
    record(
        "drawdown",
        passed=(
            baseline_drawdown
            and candidate_drawdown
            and baseline_drawdown_value is not None
            and candidate_drawdown_value is not None
            and abs(candidate_drawdown_value) <= abs(baseline_drawdown_value)
        ),
        blocker=(
            "baseline_drawdown_evidence_not_reproducible"
            if not baseline_drawdown
            else (
                "candidate_drawdown_evidence_not_reproducible"
                if not candidate_drawdown
                else "candidate_drawdown_exceeds_reviewed_baseline"
            )
        ),
        evidence={
            "baseline_max_drawdown": baseline_drawdown_value,
            "candidate_max_drawdown": candidate_drawdown_value,
        },
    )

    baseline_turnover = turnover_ratio(baseline)
    candidate_turnover = turnover_ratio(candidate)
    record(
        "turnover",
        passed=(
            baseline_turnover is not None
            and candidate_turnover is not None
            and candidate_turnover <= baseline_turnover
        ),
        blocker=(
            "baseline_turnover_evidence_missing"
            if baseline_turnover is None
            else (
                "candidate_turnover_evidence_missing"
                if candidate_turnover is None
                else "candidate_turnover_exceeds_reviewed_baseline"
            )
        ),
        evidence={
            "baseline_turnover_to_initial_cash": baseline_turnover,
            "candidate_turnover_to_initial_cash": candidate_turnover,
        },
    )

    baseline_fee_ok = _estimated_fee_evidence_valid(baseline)
    candidate_fee_ok = _estimated_fee_evidence_valid(candidate)
    record(
        "baseline_estimated_cost_and_tax_evidence",
        passed=baseline_fee_ok,
        blocker="baseline_estimated_fee_or_tax_evidence_incomplete",
        evidence=_research_fee_summary(baseline),
    )
    record(
        "candidate_estimated_cost_and_tax_evidence",
        passed=candidate_fee_ok,
        blocker="candidate_estimated_fee_or_tax_evidence_incomplete",
        evidence=_research_fee_summary(candidate),
    )
    estimated_excess = _difference(
        candidate.get("total_return"),
        baseline.get("total_return"),
    )
    record(
        "estimated_after_cost_excess_return",
        passed=(
            baseline_fee_ok
            and candidate_fee_ok
            and estimated_excess is not None
            and estimated_excess > 0
        ),
        blocker="candidate_estimated_after_cost_excess_not_positive",
        evidence={
            "after_cost_excess_return": estimated_excess,
            "account_specific_fee_review_required_later": True,
        },
    )

    critique = dict(critique_evidence or {})
    critique_fingerprint = str(critique.get("artifact_fingerprint") or "")
    critique_complete = (
        critique.get("status") == "completed"
        and bool(str(critique.get("critique_id") or "").strip())
        and len(critique_fingerprint.removeprefix("sha256:")) == 64
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
    return NormalizedResearchAdvancementGate(
        status="pass" if not unique_blockers else "blocked",
        blockers=unique_blockers,
        checks=tuple(checks),
    )


def baseline_research_evidence_blockers(
    baseline: Mapping[str, Any],
) -> list[str]:
    """Provider-free infrastructure preflight before any external model call."""

    return research_backtest_infrastructure_blockers(
        baseline,
        prefix="research_baseline",
        require_parameter_panel=False,
    )


def candidate_research_evidence_blockers(
    candidate: Mapping[str, Any],
) -> list[str]:
    """Block a critique call when local candidate evidence is structurally unusable."""

    return research_backtest_infrastructure_blockers(
        candidate,
        prefix="research_candidate",
        require_parameter_panel=True,
    )


def research_backtest_infrastructure_blockers(
    view: Mapping[str, Any],
    *,
    prefix: str,
    require_parameter_panel: bool,
) -> list[str]:
    from analytics.oos_validation import (
        is_valid_rolling_out_of_sample_validation_evidence,
    )

    blockers: list[str] = []
    if not valid_snapshot_id(str(view.get("dataset_snapshot_id") or "")):
        blockers.append(f"{prefix}_dataset_snapshot_invalid")
    if not _drawdown_evidence_valid(view):
        blockers.append(f"{prefix}_drawdown_evidence_invalid")
    if not is_valid_rolling_out_of_sample_validation_evidence(
        view.get("oos_validation"),
        minimum_fold_count=2,
    ):
        blockers.append(f"{prefix}_rolling_oos_evidence_invalid")
    if not _estimated_fee_evidence_valid(view):
        blockers.append(f"{prefix}_estimated_fee_evidence_invalid")
    if turnover_ratio(view) is None:
        blockers.append(f"{prefix}_turnover_evidence_invalid")
    if require_parameter_panel:
        parameter = view.get("parameter_robustness")
        parameter = dict(parameter) if isinstance(parameter, Mapping) else {}
        if (
            int(parameter.get("tested_count") or 0) < 3
            or not isinstance(parameter.get("selected_params"), Mapping)
            or not parameter.get("selected_params")
            or len(str(parameter.get("evidence_fingerprint") or "")) != 64
        ):
            blockers.append(f"{prefix}_parameter_panel_invalid")
    return blockers


def _drawdown_evidence_valid(view: Mapping[str, Any]) -> bool:
    return is_valid_complete_backtest_drawdown_evidence(
        view.get("drawdown_evidence"),
        expected_max_drawdown=view.get("max_drawdown"),
        expected_equity_curve=view.get("equity_curve"),
        expected_initial_equity=view.get("initial_cash"),
        expected_final_equity=view.get("final_equity"),
    )


def _estimated_fee_evidence_valid(view: Mapping[str, Any]) -> bool:
    evidence = view.get("fee_component_evidence")
    if not isinstance(evidence, Mapping):
        return False
    return (
        is_valid_complete_backtest_fee_tax_evidence(
            evidence,
            expected_total_commission=view.get("total_commission"),
            expected_total_slippage=view.get("total_slippage"),
            expected_total_cost=view.get("total_cost"),
            expected_fill_count=view.get("total_trades"),
        )
        and evidence.get("account_specific") is False
        and evidence.get("fee_schedule_source") == "canonical_default_estimate"
        and evidence.get("broker_statement_reconciled") is False
    )


def _research_fee_summary(view: Mapping[str, Any]) -> dict[str, Any]:
    evidence = view.get("fee_component_evidence")
    evidence = dict(evidence) if isinstance(evidence, Mapping) else {}
    return {
        "status": evidence.get("status"),
        "cost_model_reference": evidence.get("cost_model_reference"),
        "account_specific": evidence.get("account_specific"),
        "fee_schedule_source": evidence.get("fee_schedule_source"),
        "includes_taxes": evidence.get("includes_taxes"),
        "evidence_fingerprint": evidence.get("evidence_fingerprint"),
    }


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _difference(left: Any, right: Any) -> float | None:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


__all__ = [
    "NORMALIZED_RESEARCH_GATE_SCHEMA_VERSION",
    "NormalizedResearchAdvancementGate",
    "baseline_research_evidence_blockers",
    "build_normalized_research_advancement_gate",
    "candidate_research_evidence_blockers",
    "research_backtest_infrastructure_blockers",
]
