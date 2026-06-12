from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from analytics.oos_validation import build_out_of_sample_validation
from backtest.result import BacktestResult
from core.events import FillEvent
from core.types import OrderSide, Symbol


def _fill(timestamp: datetime, commission: str, slippage: str) -> FillEvent:
    return FillEvent(
        timestamp=timestamp,
        fill_id=f"FILL-{timestamp.day}",
        order_id=f"ORD-{timestamp.day}",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        fill_price=Decimal("10"),
        fill_quantity=Decimal("100"),
        commission=Decimal(commission),
        slippage=Decimal(slippage),
    )


def test_build_out_of_sample_validation_splits_after_cost_evidence():
    result = BacktestResult(
        equity_curve=[
            (datetime(2026, 1, 2), Decimal("100000")),
            (datetime(2026, 1, 9), Decimal("102000")),
            (datetime(2026, 1, 16), Decimal("103000")),
            (datetime(2026, 1, 23), Decimal("104000")),
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("104000"),
        fills=[
            _fill(datetime(2026, 1, 6), "5", "1"),
            _fill(datetime(2026, 1, 17), "7", "2"),
        ],
    )

    evidence = build_out_of_sample_validation(
        strategy_id="dual_ma",
        benchmark_role="etf_rotation_trend_following",
        result=result,
        split_timestamp=datetime(2026, 1, 10),
        benchmark_return=Decimal("0.015"),
    )

    assert evidence.strategy_id == "dual_ma"
    assert evidence.benchmark_role == "etf_rotation_trend_following"
    assert evidence.split_timestamp == datetime(2026, 1, 10)
    assert evidence.in_sample.net_return == Decimal("0.02")
    assert evidence.in_sample.total_cost == Decimal("6")
    assert evidence.in_sample.fill_count == 1
    assert evidence.out_of_sample.net_return == pytest.approx(
        Decimal("0.01960784313725490196078431373")
    )
    assert evidence.out_of_sample.total_cost == Decimal("9")
    assert evidence.out_of_sample.fill_count == 1
    assert evidence.benchmark_return == Decimal("0.015")
    assert evidence.excess_return == pytest.approx(
        Decimal("0.00460784313725490196078431373")
    )
    assert evidence.passed_benchmark is True
    assert evidence.validation_status == "benchmark_passed"

    payload = evidence.to_json_dict()
    assert payload["strategy_id"] == "dual_ma"
    assert payload["out_of_sample"]["fill_count"] == 1
    assert payload["benchmark_return"] == 0.015
    assert payload["passed_benchmark"] is True
    assert "not investment advice" in payload["limitations"][0]


def test_build_out_of_sample_validation_rejects_split_without_oos_points():
    result = BacktestResult(
        equity_curve=[
            (datetime(2026, 1, 2), Decimal("100000")),
            (datetime(2026, 1, 9), Decimal("102000")),
        ],
        positions={},
        initial_cash=Decimal("100000"),
        final_equity=Decimal("102000"),
    )

    with pytest.raises(
        ValueError, match="at least one in-sample and one out-of-sample"
    ):
        build_out_of_sample_validation(
            strategy_id="dual_ma",
            benchmark_role="etf_rotation_trend_following",
            result=result,
            split_timestamp=datetime(2026, 1, 30),
        )
