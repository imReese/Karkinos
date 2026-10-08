"""Capacity constrains actual fills before cash/fees are booked."""

from decimal import Decimal

import pandas as pd
import pytest

from backtest.engine import BacktestExecutionConfig
from tests.backtest.test_buying_power import SYMBOL, _engine


def test_multiple_orders_share_one_bar_budget_and_cancel_remainder():
    engine = _engine(
        "100000",
        schedule={
            1: [("buy", "800"), ("buy", "800"), ("buy", "100")],
            2: [("buy", "1000")],
        },
        execution_config=BacktestExecutionConfig(
            max_volume_participation=Decimal("0.01")
        ),
    )
    result = engine.run()
    assert [fill.fill_quantity for fill in result.fills] == [
        Decimal("800"),
        Decimal("200"),
        Decimal("1000"),
    ]
    assert result.positions[SYMBOL].quantity == 2000
    assert result.execution_timing["capacity_unfilled_quantity"] == "700"
    assert result.execution_timing["capacity_blocked_count"] == 1
    assert result.execution_timing["capacity_resized_count"] == 2
    assert engine.portfolio.cash >= 0


def test_target_is_later_bar_partial_fill_without_automatic_residual_retry():
    result = _engine(
        "100000",
        execution_config=BacktestExecutionConfig(
            max_volume_participation=Decimal("0.01")
        ),
    ).run()
    assert len(result.fills) == 1
    assert result.fills[0].timestamp == pd.Timestamp("2026-01-06")
    assert result.fills[0].fill_quantity == 1000
    assert result.execution_timing["pending_signal_count"] == 0
    assert (
        result.execution_timing["unfilled_remainder_policy"]
        == "cancel_after_one_execution_attempt"
    )


@pytest.mark.parametrize("participation", ["0", "-0.1", "1.1", "NaN"])
def test_invalid_participation_cannot_run(participation):
    with pytest.raises(ValueError, match="backtest_volume_participation_invalid"):
        _engine(
            "10000",
            execution_config=BacktestExecutionConfig(
                max_volume_participation=Decimal(participation)
            ),
        )
