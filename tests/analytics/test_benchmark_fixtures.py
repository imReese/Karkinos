from __future__ import annotations

import json

from analytics.benchmark_fixtures import build_benchmark_fixture_backtest_rows
from analytics.strategy_validation_matrix import build_strategy_validation_matrix
from strategy.registry import StrategyRegistry
from tests.analytics.test_strategy_validation_matrix import REQUIRED_STRATEGY_IDS


def test_fixture_backtests_generate_validation_evidence_for_all_benchmarks():
    rows = build_benchmark_fixture_backtest_rows()
    matrix = build_strategy_validation_matrix(StrategyRegistry.get_info(), rows)

    assert matrix.required_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert matrix.ready_strategy_count == len(REQUIRED_STRATEGY_IDS)
    assert matrix.is_complete is True

    by_strategy = {json.loads(row["config_json"])["strategy"]: row for row in rows}
    assert set(by_strategy) == REQUIRED_STRATEGY_IDS

    for strategy_id, row in by_strategy.items():
        metrics_json = json.loads(row["metrics_json"])
        cost_summary = json.loads(row["cost_summary_json"])
        evidence = metrics_json["evidence_bundle"]
        oos = metrics_json["oos_validation"]

        assert cost_summary["total_trades"] > 0
        assert cost_summary["gross_turnover"] > 0
        assert "gross_return_before_costs" in evidence
        assert evidence["total_cost"] >= 0
        assert "profitability claim" in evidence["limitations"][0]
        assert oos["strategy_id"] == strategy_id
        assert oos["out_of_sample"]["fill_count"] >= 0
        assert oos["validation_status"] in {
            "benchmark_passed",
            "benchmark_failed",
            "benchmark_not_supplied",
        }
        assert "not investment advice" in oos["limitations"][0]
