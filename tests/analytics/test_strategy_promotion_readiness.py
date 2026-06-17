from __future__ import annotations

import json

import strategy.examples  # noqa: F401

from analytics.strategy_promotion_readiness import (
    build_strategy_promotion_readiness,
)
from tests.analytics.test_strategy_validation_matrix import _backtest_row
from strategy.registry import StrategyRegistry


def _risk_decision(strategy_id: str, *, passed: bool) -> dict:
    return {
        "decision_id": f"RISK-{strategy_id}-{'PASS' if passed else 'BLOCK'}",
        "passed": 1 if passed else 0,
        "payload_json": json.dumps(
            {
                "intent": {"strategy_id": strategy_id},
                "decision": {
                    "passed": passed,
                    "reasons": [] if passed else ["unsafe test condition"],
                },
            }
        ),
    }


def _shadow_order(strategy_id: str, *, divergence_status: str | None = None) -> dict:
    payload = {
        "strategy_id": strategy_id,
        "run_id": "shadow:2026-04-19",
    }
    if divergence_status is not None:
        payload["divergence_status"] = divergence_status
    return {
        "order_id": f"SHADOW-{strategy_id}",
        "execution_mode": "paper_shadow",
        "status": "shadow_recorded",
        "payload_json": json.dumps(payload),
    }


def _with_research_gate(row: dict, *, status: str) -> dict:
    updated = dict(row)
    metrics_json = json.loads(str(updated["metrics_json"]))
    metrics_json["research_evidence_bundle"] = {
        "schema_version": "karkinos.research_evidence.v1",
        "gate_status": status,
        "promotion_gate": {
            "status": status,
            "manual_confirmation_required": True,
            "does_not_enable_execution": True,
        },
    }
    updated["metrics_json"] = json.dumps(metrics_json)
    return updated


def test_strategy_promotion_readiness_requires_risk_shadow_and_divergence_evidence():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_backtest_row("dual_ma")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma")],
    )

    by_strategy = {row.strategy_id: row for row in readiness.rows}
    row = by_strategy["dual_ma"]

    assert readiness.required_strategy_count == 3
    assert readiness.promotable_strategy_count == 0
    assert readiness.is_complete is False
    assert row.has_after_cost_and_oos_evidence is True
    assert row.has_risk_block_evidence is True
    assert row.has_paper_shadow_evidence is True
    assert row.has_paper_shadow_divergence_review is False
    assert row.is_promotable is False
    assert row.promotion_status == "not_promotable"
    assert row.missing_requirements == ["paper_shadow_divergence_review"]


def test_strategy_promotion_readiness_marks_strategy_promotable_only_when_all_gates_pass():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [
            _backtest_row("dual_ma"),
            _backtest_row("monthly_rebalance"),
            _backtest_row("bollinger"),
        ],
        [
            _risk_decision("dual_ma", passed=False),
            _risk_decision("monthly_rebalance", passed=False),
            _risk_decision("bollinger", passed=False),
        ],
        [
            _shadow_order("dual_ma", divergence_status="within_expectations"),
            _shadow_order(
                "monthly_rebalance",
                divergence_status="within_expectations",
            ),
            _shadow_order("bollinger", divergence_status="within_expectations"),
        ],
    )

    assert readiness.required_strategy_count == 3
    assert readiness.promotable_strategy_count == 3
    assert readiness.is_complete is True
    assert all(row.is_promotable for row in readiness.rows)
    assert all(
        row.promotion_status == "promotable_for_paper_review" for row in readiness.rows
    )
    assert "not investment advice" in readiness.limitations[0]


def test_strategy_promotion_readiness_blocks_when_research_evidence_gate_blocks():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [
            _with_research_gate(_backtest_row("dual_ma"), status="blocked"),
            _backtest_row("monthly_rebalance"),
            _backtest_row("bollinger"),
        ],
        [
            _risk_decision("dual_ma", passed=False),
            _risk_decision("monthly_rebalance", passed=False),
            _risk_decision("bollinger", passed=False),
        ],
        [
            _shadow_order("dual_ma", divergence_status="within_expectations"),
            _shadow_order(
                "monthly_rebalance",
                divergence_status="within_expectations",
            ),
            _shadow_order("bollinger", divergence_status="within_expectations"),
        ],
    )

    by_strategy = {row.strategy_id: row for row in readiness.rows}
    row = by_strategy["dual_ma"]

    assert row.is_promotable is False
    assert row.promotion_status == "not_promotable"
    assert row.missing_requirements == ["research_evidence_gate_pass"]
    assert readiness.promotable_strategy_count == 2
    assert readiness.is_complete is False


def test_strategy_promotion_readiness_blocks_when_research_evidence_gate_degrades():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_with_research_gate(_backtest_row("dual_ma"), status="degraded")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma", divergence_status="within_expectations")],
    )

    row = {item.strategy_id: item for item in readiness.rows}["dual_ma"]

    assert row.is_promotable is False
    assert row.missing_requirements == ["research_evidence_gate_pass"]
