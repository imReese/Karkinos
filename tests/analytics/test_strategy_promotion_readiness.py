from __future__ import annotations

import json

import strategy.builtins  # noqa: F401
from analytics.strategy_promotion_readiness import (
    build_strategy_promotion_readiness,
)
from strategy.registry import StrategyRegistry
from tests.analytics.test_strategy_validation_matrix import (
    REQUIRED_STRATEGY_IDS,
    _backtest_row,
)


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


def _all_backtest_rows() -> list[dict]:
    return [_backtest_row(strategy_id) for strategy_id in sorted(REQUIRED_STRATEGY_IDS)]


def _all_risk_decisions(*, passed: bool = False) -> list[dict]:
    return [
        _risk_decision(strategy_id, passed=passed)
        for strategy_id in sorted(REQUIRED_STRATEGY_IDS)
    ]


def _all_shadow_orders(*, divergence_status: str | None = None) -> list[dict]:
    return [
        _shadow_order(strategy_id, divergence_status=divergence_status)
        for strategy_id in sorted(REQUIRED_STRATEGY_IDS)
    ]


def test_strategy_promotion_readiness_requires_risk_shadow_and_divergence_evidence():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_backtest_row("dual_ma")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma")],
    )

    by_strategy = {row.strategy_id: row for row in readiness.rows}
    row = by_strategy["dual_ma"]

    assert readiness.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
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
        _all_backtest_rows(),
        _all_risk_decisions(),
        _all_shadow_orders(divergence_status="within_expectations"),
    )

    assert readiness.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert readiness.promotable_strategy_count == len(REQUIRED_STRATEGY_IDS)
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
            *[
                _backtest_row(strategy_id)
                for strategy_id in sorted(REQUIRED_STRATEGY_IDS - {"dual_ma"})
            ],
        ],
        _all_risk_decisions(),
        _all_shadow_orders(divergence_status="within_expectations"),
    )

    by_strategy = {row.strategy_id: row for row in readiness.rows}
    row = by_strategy["dual_ma"]

    assert row.is_promotable is False
    assert row.promotion_status == "not_promotable"
    assert row.missing_requirements == ["research_evidence_gate_pass"]
    assert readiness.promotable_strategy_count == len(REQUIRED_STRATEGY_IDS) - 1
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


def test_strategy_promotion_readiness_blocks_when_account_truth_gate_blocks():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        _all_backtest_rows(),
        _all_risk_decisions(),
        _all_shadow_orders(divergence_status="within_expectations"),
        account_truth_scores=[
            {
                "gate_status": "blocked",
                "score": 40,
                "blocking_reasons": ["unresolved_account_truth_mismatch"],
            }
        ],
    )

    by_strategy = {row.strategy_id: row for row in readiness.rows}

    assert readiness.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert readiness.promotable_strategy_count == 0
    assert readiness.is_complete is False
    assert all(row.account_truth_gate_status == "blocked" for row in readiness.rows)
    assert all(row.account_truth_score == 40 for row in readiness.rows)
    assert by_strategy["dual_ma"].has_account_truth_evidence is False
    assert by_strategy["dual_ma"].missing_requirements == ["account_truth_gate_pass"]


def test_strategy_promotion_readiness_blocks_when_account_truth_gate_is_enabled_but_missing():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_backtest_row("dual_ma")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma", divergence_status="within_expectations")],
        account_truth_scores=[],
    )

    row = {item.strategy_id: item for item in readiness.rows}["dual_ma"]

    assert row.is_promotable is False
    assert row.has_account_truth_evidence is False
    assert row.account_truth_gate_status == "blocked"
    assert row.account_truth_score is None
    assert row.missing_requirements == ["account_truth_gate_pass"]


def test_strategy_promotion_readiness_allows_when_account_truth_gate_passes():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        _all_backtest_rows(),
        _all_risk_decisions(),
        _all_shadow_orders(divergence_status="within_expectations"),
        account_truth_scores=[{"gate_status": "pass", "score": 100}],
    )

    assert readiness.promotable_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert readiness.is_complete is True
    assert all(row.has_account_truth_evidence for row in readiness.rows)
    assert all(row.account_truth_gate_status == "pass" for row in readiness.rows)
    assert all(row.account_truth_score == 100 for row in readiness.rows)


def test_strategy_promotion_readiness_blocks_assigned_strategy_when_attribution_is_pending():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_backtest_row("dual_ma")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma", divergence_status="within_expectations")],
        account_strategy_assignments=[
            {
                "strategy_id": "dual_ma",
                "status": "research_only",
                "scope": "account",
                "auto_trade_enabled": False,
            }
        ],
        account_strategy_attributions=[
            {
                "strategy_id": "dual_ma",
                "attribution_status": "evidence_linked_pnl_pending",
                "fill_count": 1,
            }
        ],
    )

    row = {item.strategy_id: item for item in readiness.rows}["dual_ma"]

    assert row.has_strategy_attribution_evidence is False
    assert row.strategy_attribution_status == "evidence_linked_pnl_pending"
    assert row.missing_requirements == ["strategy_attribution_ready"]
    assert row.promotion_status == "not_promotable"


def test_strategy_promotion_readiness_allows_assigned_strategy_when_contribution_is_estimated():
    readiness = build_strategy_promotion_readiness(
        StrategyRegistry.get_info(),
        [_backtest_row("dual_ma")],
        [_risk_decision("dual_ma", passed=False)],
        [_shadow_order("dual_ma", divergence_status="within_expectations")],
        account_strategy_assignments=[
            {
                "strategy_id": "dual_ma",
                "status": "research_only",
                "scope": "account",
                "auto_trade_enabled": False,
            }
        ],
        account_strategy_attributions=[
            {
                "strategy_id": "dual_ma",
                "attribution_status": "evidence_linked_pnl_pending",
                "contribution_status": "estimated_from_linked_fills",
                "linked_fill_count": 1,
            }
        ],
    )

    row = {item.strategy_id: item for item in readiness.rows}["dual_ma"]

    assert row.has_strategy_attribution_evidence is True
    assert row.strategy_attribution_status == "estimated_from_linked_fills"
    assert row.missing_requirements == []
    assert row.promotion_status == "promotable_for_paper_review"
