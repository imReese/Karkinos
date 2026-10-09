"""Tests for execution/rebalance_order_generator.py."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.types import OrderSide, Symbol
from execution.rebalance_order_generator import (
    RebalancePlan,
    generate_rebalance_plan,
)


def test_rebalance_plan_sells_precede_buys_and_respect_lot_size():
    # Total equity: 100,000 CNY
    # Current holding: 510500 has 2000 shares @ 6.00 = 12,000 CNY (12%)
    # Target: 510300 weight = 0.5 (50%), 510500 weight = 0.0 (0%)
    # Prices: 510300 @ 4.00, 510500 @ 6.00
    plan = generate_rebalance_plan(
        target_weights={Symbol("510300"): 0.5, Symbol("510500"): 0.0},
        current_holdings={Symbol("510500"): 2000},
        latest_prices={Symbol("510300"): 4.00, Symbol("510500"): 6.00},
        total_equity=100000,
        lot_size=100,
        cash_buffer_ratio=Decimal("0.005"),  # 0.5% buffer
    )

    assert isinstance(plan, RebalancePlan)
    # Check sell orders
    assert len(plan.sell_orders) == 1
    sell_order = plan.sell_orders[0]
    assert sell_order.symbol == Symbol("510500")
    assert sell_order.side == OrderSide.SELL
    assert sell_order.quantity == 2000
    assert sell_order.estimated_amount == Decimal("12000.00")
    assert sell_order.reason == "清仓退出"

    # Check buy orders
    assert len(plan.buy_orders) == 1
    buy_order = plan.buy_orders[0]
    assert buy_order.symbol == Symbol("510300")
    assert buy_order.side == OrderSide.BUY
    # Target equity = 100,000 * 0.995 * 0.5 = 49,750
    # Desired shares @ 4.00 = 49750 / 4 = 12437.5 -> rounded down to 12400
    assert buy_order.quantity == 12400
    assert buy_order.quantity % 100 == 0
    assert buy_order.estimated_amount == Decimal("49600.00")

    # Sequencing: all_orders has sell first, then buy
    assert [o.side for o in plan.all_orders] == [OrderSide.SELL, OrderSide.BUY]


def test_rebalance_plan_exports_csv_and_markdown():
    plan = generate_rebalance_plan(
        target_weights={Symbol("510300"): 0.5},
        current_holdings={},
        latest_prices={Symbol("510300"): 4.00},
        total_equity=50000,
    )
    csv_text = plan.to_csv()
    assert "证券代码,证券名称,买卖方向,委托数量,预估价格,预估金额,调仓说明" in csv_text
    assert "510300,沪深300ETF,买入" in csv_text

    md_text = plan.to_markdown_table()
    assert "调仓执行清单" in md_text
    assert "510300" in md_text
    assert "沪深300ETF" in md_text
    assert "买入" in md_text

    miniqmt_script = plan.to_miniqmt_script("12345678")
    assert "xtquant" in miniqmt_script
    assert "510300.SH" in miniqmt_script
    assert "12345678" in miniqmt_script


def test_rebalance_plan_skips_trivial_amounts():
    # Only 100 CNY diff, less than min_trade_amount 200
    plan = generate_rebalance_plan(
        target_weights={Symbol("510300"): 0.5},
        current_holdings={Symbol("510300"): 5000},
        latest_prices={Symbol("510300"): 1.00},
        total_equity=10000,
        min_trade_amount=200,
    )
    # Trivial change is skipped
    assert len(plan.all_orders) == 0
    assert "无需调仓" in plan.to_markdown_table()


def test_rebalance_plan_validation_errors():
    with pytest.raises(ValueError, match="total_equity_must_be_positive"):
        generate_rebalance_plan(
            target_weights={},
            current_holdings={},
            latest_prices={},
            total_equity=-100,
        )

    with pytest.raises(ValueError, match="price_missing:510300"):
        generate_rebalance_plan(
            target_weights={Symbol("510300"): 0.5},
            current_holdings={},
            latest_prices={},
            total_equity=10000,
        )
