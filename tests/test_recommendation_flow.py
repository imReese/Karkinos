from __future__ import annotations

from server.services.recommendation_flow import build_recommendation_cycle


def test_build_recommendation_cycle_normalizes_tasks_and_counts():
    signals = [
        {
            "id": 1,
            "timestamp": "2026-04-18T09:30:00",
            "strategy_id": "dual_ma",
            "symbol": "600519",
            "direction": "buy",
            "target_weight": 0.2,
            "price": 1500.0,
            "asset_class": "stock",
        },
        {
            "id": 2,
            "timestamp": "2026-04-18T09:31:00",
            "strategy_id": "rsi",
            "symbol": "510300",
            "direction": "sell",
            "target_weight": 0.0,
            "price": 3.8,
            "asset_class": "etf",
        },
    ]

    cycle = build_recommendation_cycle(
        signals=signals,
        available_cash=100000,
        existing_positions={},
    )

    assert len(cycle.tasks) == 2
    assert cycle.tasks[0].source_signal_id == 1
    assert cycle.tasks[0].symbol == "600519"
    assert cycle.tasks[0].title == "建议增持 600519"
    assert cycle.tasks[0].detail == "dual_ma 触发，目标仓位 20%"
    assert cycle.tasks[1].asset_class == "etf"
    assert cycle.summary["task_count"] == 2
    assert cycle.summary["buy_count"] == 1
    assert cycle.summary["sell_count"] == 1


def test_build_recommendation_cycle_defaults_missing_asset_class():
    cycle = build_recommendation_cycle(
        signals=[
            {
                "id": 3,
                "timestamp": "2026-04-18T09:32:00",
                "strategy_id": "mom",
                "symbol": "000001",
                "direction": "buy",
                "target_weight": 0.5,
                "price": None,
            }
        ],
        available_cash=1000,
        existing_positions={"000001": 100},
    )

    assert cycle.tasks[0].asset_class == "stock"
