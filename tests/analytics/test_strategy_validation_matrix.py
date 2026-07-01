from __future__ import annotations

import json

import strategy.builtins  # noqa: F401
from analytics.strategy_validation_matrix import build_strategy_validation_matrix
from strategy.registry import StrategyRegistry

REQUIRED_STRATEGY_IDS = {
    "dual_ma",
    "monthly_rebalance",
    "bollinger",
    "time_series_momentum",
    "donchian_breakout",
    "volatility_target_trend",
    "pairs_ratio_mean_reversion",
}


def _backtest_row(
    strategy: str,
    *,
    include_oos: bool = True,
    include_after_cost: bool = True,
) -> dict:
    result_ids = {
        "dual_ma": 101,
        "monthly_rebalance": 102,
        "bollinger": 103,
        "time_series_momentum": 104,
        "donchian_breakout": 105,
        "volatility_target_trend": 106,
        "pairs_ratio_mean_reversion": 107,
    }
    metrics_json = {
        "total_commission": 12.5,
        "total_slippage": 3.5,
        "gross_turnover": 24000.0,
    }
    if include_oos:
        metrics_json["oos_validation"] = {
            "strategy_id": strategy,
            "benchmark_role": f"{strategy}_role",
            "validation_status": "benchmark_passed",
            "out_of_sample": {
                "net_return": 0.04,
                "total_cost": 16.0,
                "fill_count": 2,
            },
            "limitations": ["Validation evidence is not investment advice."],
        }
    if include_after_cost:
        metrics_json["evidence_bundle"] = {
            "net_return": 0.05,
            "gross_return_before_costs": 0.052,
            "total_cost": 16.0,
            "fill_count": 2,
            "limitations": ["Backtest evidence is not a profitability claim."],
        }

    return {
        "id": result_ids[strategy],
        "config_json": json.dumps({"strategy": strategy}),
        "metrics_json": json.dumps(metrics_json),
        "cost_summary_json": json.dumps(
            {
                "total_commission": 12.5,
                "total_slippage": 3.5,
                "gross_turnover": 24000.0,
                "total_trades": 2,
            }
        ),
    }


def test_strategy_validation_matrix_marks_all_benchmarks_ready():
    matrix = build_strategy_validation_matrix(
        StrategyRegistry.get_info(),
        [
            _backtest_row("dual_ma"),
            _backtest_row("monthly_rebalance"),
            _backtest_row("bollinger"),
            _backtest_row("time_series_momentum"),
            _backtest_row("donchian_breakout"),
            _backtest_row("volatility_target_trend"),
            _backtest_row("pairs_ratio_mean_reversion"),
        ],
    )

    assert matrix.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert matrix.ready_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert matrix.is_complete is True
    assert {row.strategy_id for row in matrix.rows} == REQUIRED_STRATEGY_IDS
    assert all(row.has_after_cost_report for row in matrix.rows)
    assert all(row.has_out_of_sample_validation for row in matrix.rows)
    assert all(row.missing_requirements == [] for row in matrix.rows)


def test_strategy_validation_matrix_reports_missing_evidence():
    matrix = build_strategy_validation_matrix(
        StrategyRegistry.get_info(),
        [
            _backtest_row("dual_ma"),
            _backtest_row("monthly_rebalance", include_oos=False),
            _backtest_row("bollinger", include_after_cost=False),
            _backtest_row("time_series_momentum"),
            _backtest_row("donchian_breakout"),
            _backtest_row("volatility_target_trend"),
            _backtest_row("pairs_ratio_mean_reversion"),
        ],
    )

    by_strategy = {row.strategy_id: row for row in matrix.rows}

    assert matrix.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert matrix.ready_strategy_count == len(REQUIRED_STRATEGY_IDS) - 2
    assert matrix.is_complete is False
    assert by_strategy["monthly_rebalance"].missing_requirements == [
        "out_of_sample_validation"
    ]
    assert by_strategy["bollinger"].missing_requirements == ["after_cost_report"]
