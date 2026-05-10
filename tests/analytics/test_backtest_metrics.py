"""Backtest metrics aggregation tests."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from analytics.backtest_metrics import (
    CostSummary,
    calculate_backtest_metrics,
    summarize_fill_costs,
)
from core.events import FillEvent
from core.types import OrderSide, Symbol


def test_calculate_backtest_metrics_includes_calmar_and_costs():
    equity_curve = [
        (datetime(2024, 1, 1), Decimal("100")),
        (datetime(2024, 1, 2), Decimal("120")),
        (datetime(2024, 1, 3), Decimal("90")),
        (datetime(2024, 1, 4), Decimal("130")),
    ]
    cost_summary = CostSummary(
        total_commission=Decimal("8.5"),
        total_slippage=Decimal("1.5"),
        total_trades=2,
        gross_turnover=Decimal("10000"),
    )

    metrics = calculate_backtest_metrics(
        equity_curve,
        initial_cash=Decimal("100"),
        final_equity=Decimal("130"),
        cost_summary=cost_summary,
    )

    assert metrics.total_return == 0.3
    assert metrics.max_drawdown == 0.25
    assert metrics.calmar > 0
    assert metrics.total_commission == 8.5
    assert metrics.total_slippage == 1.5


def test_summarize_fill_costs_aggregates_commission_slippage_and_turnover():
    fills = [
        FillEvent(
            timestamp=datetime(2024, 1, 1),
            fill_id="FILL-1",
            order_id="ORD-1",
            symbol=Symbol("600519"),
            side=OrderSide.BUY,
            fill_price=Decimal("10"),
            fill_quantity=Decimal("100"),
            commission=Decimal("5"),
            slippage=Decimal("1"),
        ),
        FillEvent(
            timestamp=datetime(2024, 1, 2),
            fill_id="FILL-2",
            order_id="ORD-2",
            symbol=Symbol("600519"),
            side=OrderSide.SELL,
            fill_price=Decimal("11"),
            fill_quantity=Decimal("100"),
            commission=Decimal("6"),
            slippage=Decimal("2"),
        ),
    ]

    summary = summarize_fill_costs(fills)

    assert summary.total_commission == Decimal("11")
    assert summary.total_slippage == Decimal("3")
    assert summary.total_trades == 2
    assert summary.gross_turnover == Decimal("2100")
