"""Normalized-notional privacy boundary tests for external strategy research."""

from __future__ import annotations

import pytest

from server.ai_runtime.strategy_research_privacy import (
    NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID,
    build_normalized_lot_feasibility_evidence,
    build_normalized_research_pack,
    build_normalized_signal_execution_evidence,
    research_pack_privacy_violations,
)


@pytest.mark.unit
@pytest.mark.trading_safety
def test_normalized_pack_exports_ratios_bps_and_counts_without_absolutes() -> None:
    pack = build_normalized_research_pack(
        performance={
            "initial_cash": 100_000,
            "final_equity": 110_000,
            "total_return": 0.1,
            "sharpe": 1.2,
            "max_drawdown": 0.08,
        },
        after_cost_evidence={
            "net_pnl": 10_000,
            "gross_pnl_before_costs": 10_100,
            "total_cost": 100,
            "fill_count": 4,
            "gross_turnover": 200_000,
        },
        cost_summary={
            "total_commission": 80,
            "total_slippage": 20,
            "total_trades": 4,
            "gross_turnover": 200_000,
        },
        research_evidence_bundle={
            "schema_version": "karkinos.research_evidence.v1",
            "gate_status": "pass",
            "strategy": {
                "strategy_id": "baseline",
                "params": {"window": 20, "initial_cash": 100_000},
                "private_extension": {"quantity": 100},
            },
            "trade_statistics": {
                "fill_count": 4,
                "trade_count": 4,
                "gross_turnover": 200_000,
                "total_commission": 80,
                "total_slippage": 20,
            },
            "promotion_gate": {
                "status": "pass",
                "manual_confirmation_required": True,
                "does_not_enable_execution": True,
                "next_review": "human review",
                "raw_account_gate": {"total_equity": 100_000},
            },
        },
        oos_validation={
            "validation_mode": "rolling",
            "validation_status": "pass",
            "folds": [{"fold_index": 1}, {"fold_index": 2}],
            "aggregate": {
                "mean_out_of_sample_return": 0.0,
                "worst_out_of_sample_return": -0.02,
            },
        },
    )

    assert pack["notional_policy_id"] == NORMALIZED_RESEARCH_NOTIONAL_POLICY_ID
    assert pack["after_cost_summary"] == {
        "net_return_after_costs": 0.1,
        "gross_return_before_costs": 0.101,
        "total_cost_bps": 10.0,
        "fill_count": 4,
        "gross_turnover_ratio": 2.0,
        "limitations": [],
    }
    assert pack["cost_summary"]["total_commission_bps"] == 8.0
    assert pack["cost_summary"]["total_slippage_bps"] == 2.0
    assert pack["oos_validation"]["mean_out_of_sample_return"] == 0.0
    assert pack["oos_validation"]["fold_count"] == 2
    assert pack["research_evidence_bundle"]["strategy"] == {
        "strategy_id": "baseline",
        "name": None,
        "display_name": None,
        "params": {"window": 20},
    }
    assert pack["research_evidence_bundle"]["promotion_gate"] == {
        "status": "pass",
        "manual_confirmation_required": True,
        "does_not_enable_execution": True,
        "next_review": "human review",
    }
    assert research_pack_privacy_violations(pack) == []


@pytest.mark.unit
@pytest.mark.trading_safety
def test_privacy_guard_reports_nested_absolute_account_and_notional_keys() -> None:
    violations = research_pack_privacy_violations(
        {
            "saved_backtest": {"initial_cash": 100_000},
            "account": {"positions": [{"quantity": 100}]},
            "cost": {"total_commission": 5},
            "lot": {"lot_size": 100},
        }
    )

    assert violations == [
        "saved_backtest.initial_cash",
        "account.positions",
        "account.positions[0].quantity",
        "cost.total_commission",
        "lot.lot_size",
    ]


@pytest.mark.unit
@pytest.mark.trading_safety
def test_critique_diagnostics_use_allowlists_and_remove_lot_size() -> None:
    signal = build_normalized_signal_execution_evidence(
        {
            "schema_version": "karkinos.ai.formula_signal_execution.v1",
            "entry_signal_count": 3,
            "exit_signal_count": 1,
            "entry_target_count": 2,
            "fill_count": 2,
            "allocation_slots": 1,
            "canonical_target_weight": 1.0,
            "contains_holding_quantity": False,
            "quantity": 100,
            "unreviewed_nested": {"cash": 50_000},
        }
    )
    lot = build_normalized_lot_feasibility_evidence(
        {
            "schema_version": "karkinos.ai.research_lot_feasibility.v1",
            "symbol_count": 3,
            "feasible_symbol_count": 2,
            "one_lot_too_expensive_count": 1,
            "lot_size": 100,
            "allocation_slots": 1,
            "target_weight": 1.0,
            "contains_holding_quantity": False,
            "unreviewed_nested": {"positions": []},
        }
    )

    assert "quantity" not in signal
    assert "unreviewed_nested" not in signal
    assert "lot_size" not in lot
    assert "unreviewed_nested" not in lot
    assert (
        research_pack_privacy_violations(
            {"signal_execution_evidence": signal, "lot_feasibility_evidence": lot}
        )
        == []
    )
