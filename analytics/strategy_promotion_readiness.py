"""Promotion readiness gates for v0.2 benchmark strategies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from analytics.strategy_validation_matrix import build_strategy_validation_matrix

_DIVERGENCE_PASS_STATUSES = {
    "within_expectations",
    "reviewed_within_expectations",
}


@dataclass(frozen=True)
class StrategyPromotionReadinessRow:
    strategy_id: str
    benchmark_role: str
    backtest_result_id: int | None
    has_after_cost_and_oos_evidence: bool
    has_risk_block_evidence: bool
    has_paper_shadow_evidence: bool
    has_paper_shadow_divergence_review: bool
    missing_requirements: list[str]

    @property
    def is_promotable(self) -> bool:
        return not self.missing_requirements

    @property
    def promotion_status(self) -> str:
        return "promotable_for_paper_review" if self.is_promotable else "not_promotable"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "benchmark_role": self.benchmark_role,
            "backtest_result_id": self.backtest_result_id,
            "has_after_cost_and_oos_evidence": self.has_after_cost_and_oos_evidence,
            "has_risk_block_evidence": self.has_risk_block_evidence,
            "has_paper_shadow_evidence": self.has_paper_shadow_evidence,
            "has_paper_shadow_divergence_review": (
                self.has_paper_shadow_divergence_review
            ),
            "missing_requirements": list(self.missing_requirements),
            "promotion_status": self.promotion_status,
            "is_promotable": self.is_promotable,
        }


@dataclass(frozen=True)
class StrategyPromotionReadiness:
    rows: list[StrategyPromotionReadinessRow]

    @property
    def required_strategy_count(self) -> int:
        return len(self.rows)

    @property
    def promotable_strategy_count(self) -> int:
        return sum(1 for row in self.rows if row.is_promotable)

    @property
    def is_complete(self) -> bool:
        return self.required_strategy_count > 0 and all(
            row.is_promotable for row in self.rows
        )

    @property
    def limitations(self) -> list[str]:
        return [
            "Promotion readiness is audit evidence, not investment advice.",
            "Promotable here means eligible for paper/shadow review; manual confirmation remains required for live-like execution.",
            "Paper/shadow divergence review must be supplied as explicit operator evidence.",
        ]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "required_strategy_count": self.required_strategy_count,
            "promotable_strategy_count": self.promotable_strategy_count,
            "is_complete": self.is_complete,
            "rows": [row.to_json_dict() for row in self.rows],
            "limitations": self.limitations,
        }


def build_strategy_promotion_readiness(
    strategy_infos: list[dict[str, Any]],
    backtest_results: list[dict[str, Any]],
    risk_decisions: list[dict[str, Any]],
    order_facts: list[dict[str, Any]],
) -> StrategyPromotionReadiness:
    """Combine validation, risk, and paper/shadow evidence into promotion gates."""
    validation_matrix = build_strategy_validation_matrix(
        strategy_infos,
        backtest_results,
    )
    blocked_risk_strategies = _strategies_with_blocked_risk_decision(risk_decisions)
    shadow_strategies, divergence_reviewed_strategies = _paper_shadow_evidence(
        order_facts
    )

    rows: list[StrategyPromotionReadinessRow] = []
    for validation_row in validation_matrix.rows:
        strategy_id = validation_row.strategy_id
        has_validation = validation_row.is_ready
        has_risk_block = strategy_id in blocked_risk_strategies
        has_shadow = strategy_id in shadow_strategies
        has_divergence_review = strategy_id in divergence_reviewed_strategies
        missing_requirements: list[str] = []
        if not has_validation:
            missing_requirements.extend(validation_row.missing_requirements)
        if not has_risk_block:
            missing_requirements.append("risk_gate_block_evidence")
        if not has_shadow:
            missing_requirements.append("paper_shadow_evidence")
        if not has_divergence_review:
            missing_requirements.append("paper_shadow_divergence_review")

        rows.append(
            StrategyPromotionReadinessRow(
                strategy_id=strategy_id,
                benchmark_role=validation_row.benchmark_role,
                backtest_result_id=validation_row.backtest_result_id,
                has_after_cost_and_oos_evidence=has_validation,
                has_risk_block_evidence=has_risk_block,
                has_paper_shadow_evidence=has_shadow,
                has_paper_shadow_divergence_review=has_divergence_review,
                missing_requirements=missing_requirements,
            )
        )

    return StrategyPromotionReadiness(rows=rows)


def _strategies_with_blocked_risk_decision(
    risk_decisions: list[dict[str, Any]],
) -> set[str]:
    strategies: set[str] = set()
    for row in risk_decisions:
        if bool(row.get("passed")):
            continue
        payload = _json_object(row.get("payload_json") or row.get("payload"))
        strategy_id = payload.get("intent", {}).get("strategy_id") or row.get(
            "strategy_id"
        )
        if strategy_id:
            strategies.add(str(strategy_id))
    return strategies


def _paper_shadow_evidence(
    order_facts: list[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    shadow_strategies: set[str] = set()
    divergence_reviewed_strategies: set[str] = set()
    for row in order_facts:
        if row.get("execution_mode") != "paper_shadow":
            continue
        payload = _json_object(row.get("payload_json") or row.get("payload"))
        strategy_id = payload.get("strategy_id")
        if not strategy_id:
            continue
        strategy_id = str(strategy_id)
        shadow_strategies.add(strategy_id)
        if payload.get("divergence_status") in _DIVERGENCE_PASS_STATUSES:
            divergence_reviewed_strategies.add(strategy_id)
    return shadow_strategies, divergence_reviewed_strategies


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
