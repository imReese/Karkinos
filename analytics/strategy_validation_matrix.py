"""Validation matrix for v0.2 benchmark strategy evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyValidationRow:
    strategy_id: str
    benchmark_role: str
    requires_out_of_sample_validation: bool
    requires_after_cost_report: bool
    has_out_of_sample_validation: bool
    has_after_cost_report: bool
    validation_status: str | None
    backtest_result_id: int | None
    missing_requirements: list[str]

    @property
    def is_ready(self) -> bool:
        return not self.missing_requirements

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "requires_out_of_sample_validation": (
                self.requires_out_of_sample_validation
            ),
            "requires_after_cost_report": self.requires_after_cost_report,
            "has_out_of_sample_validation": self.has_out_of_sample_validation,
            "has_after_cost_report": self.has_after_cost_report,
            "validation_status": self.validation_status,
            "backtest_result_id": self.backtest_result_id,
            "missing_requirements": list(self.missing_requirements),
            "is_ready": self.is_ready,
        }


@dataclass(frozen=True)
class StrategyValidationMatrix:
    rows: list[StrategyValidationRow]

    @property
    def required_strategy_count(self) -> int:
        return len(self.rows)

    @property
    def ready_strategy_count(self) -> int:
        return sum(1 for row in self.rows if row.is_ready)

    @property
    def is_complete(self) -> bool:
        return self.required_strategy_count > 0 and all(
            row.is_ready for row in self.rows
        )

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "required_strategy_count": self.required_strategy_count,
            "ready_strategy_count": self.ready_strategy_count,
            "is_complete": self.is_complete,
            "rows": [row.to_json_dict() for row in self.rows],
            "limitations": [
                "Validation matrix records evidence presence only; it is not investment advice.",
                "Strategy promotion still requires benchmark, drawdown, turnover, liquidity, and paper/shadow review.",
            ],
        }


def build_strategy_validation_matrix(
    strategy_infos: list[dict[str, Any]],
    backtest_results: list[dict[str, Any]],
) -> StrategyValidationMatrix:
    """Summarize whether required benchmark strategies have validation evidence."""
    latest_by_strategy = _latest_result_by_strategy(backtest_results)
    rows: list[StrategyValidationRow] = []

    for strategy_info in strategy_infos:
        requires_oos = bool(strategy_info.get("requires_out_of_sample_validation"))
        requires_after_cost = bool(strategy_info.get("requires_after_cost_report"))
        if not requires_oos and not requires_after_cost:
            continue

        strategy_id = str(strategy_info["name"])
        result = latest_by_strategy.get(strategy_id)
        metrics_json = _json_object(result.get("metrics_json") if result else None)
        cost_summary_json = _json_object(
            result.get("cost_summary_json") if result else None
        )
        oos_payload = _json_object(metrics_json.get("oos_validation"))
        after_cost_payload = _json_object(metrics_json.get("evidence_bundle"))
        has_oos = _has_oos_validation(oos_payload)
        has_after_cost = _has_after_cost_report(after_cost_payload, cost_summary_json)
        missing_requirements: list[str] = []
        if requires_after_cost and not has_after_cost:
            missing_requirements.append("after_cost_report")
        if requires_oos and not has_oos:
            missing_requirements.append("out_of_sample_validation")

        rows.append(
            StrategyValidationRow(
                strategy_id=strategy_id,
                benchmark_role=str(strategy_info.get("benchmark_role") or ""),
                requires_out_of_sample_validation=requires_oos,
                requires_after_cost_report=requires_after_cost,
                has_out_of_sample_validation=has_oos,
                has_after_cost_report=has_after_cost,
                validation_status=(
                    oos_payload.get("validation_status") if has_oos else None
                ),
                backtest_result_id=_result_id(result),
                missing_requirements=missing_requirements,
            )
        )

    return StrategyValidationMatrix(rows=rows)


def _latest_result_by_strategy(
    backtest_results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in backtest_results:
        config_json = _json_object(row.get("config_json"))
        strategy_id = config_json.get("strategy")
        if not strategy_id:
            continue
        existing = latest.get(str(strategy_id))
        if existing is None or (_result_id(row) or -1) > (_result_id(existing) or -1):
            latest[str(strategy_id)] = row
    return latest


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _has_oos_validation(payload: dict[str, Any]) -> bool:
    out_of_sample = _json_object(payload.get("out_of_sample"))
    return bool(
        payload.get("validation_status")
        and "net_return" in out_of_sample
        and "total_cost" in out_of_sample
    )


def _has_after_cost_report(
    evidence_payload: dict[str, Any],
    cost_summary_payload: dict[str, Any],
) -> bool:
    return bool(
        "net_return" in evidence_payload
        and "gross_return_before_costs" in evidence_payload
        and "total_cost" in evidence_payload
        and "total_commission" in cost_summary_payload
        and "total_slippage" in cost_summary_payload
        and "gross_turnover" in cost_summary_payload
    )


def _result_id(row: dict[str, Any] | None) -> int | None:
    if not row or row.get("id") is None:
        return None
    try:
        return int(row["id"])
    except (TypeError, ValueError):
        return None
