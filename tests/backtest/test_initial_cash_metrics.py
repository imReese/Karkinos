"""The first measured session includes losses and fees against starting cash."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from analytics.backtest_drawdown_evidence import (
    build_backtest_drawdown_evidence,
    is_valid_complete_backtest_drawdown_evidence,
)
from backtest.metrics import calculate_backtest_metrics


def test_first_session_loss_is_in_return_drawdown_and_annualization():
    curve = [
        (datetime(2026, 1, 5) + timedelta(days=i), Decimal("90")) for i in range(2)
    ]
    metrics = calculate_backtest_metrics(
        curve, initial_cash=Decimal("100"), final_equity=Decimal("90")
    )
    assert metrics.total_return == pytest.approx(-0.1)
    assert metrics.max_drawdown == pytest.approx(0.1)
    assert metrics.annual_return == pytest.approx(0.9 ** (252 / 2) - 1)
    assert metrics.volatility > 0
    assert metrics.win_rate == 0


def test_one_session_cost_drawdown_replays_against_explicit_cash_anchor():
    curve = [(datetime(2026, 1, 5), Decimal("99"))]
    metrics = calculate_backtest_metrics(
        curve, initial_cash=Decimal("100"), final_equity=Decimal("99")
    )
    evidence = build_backtest_drawdown_evidence(equity_curve=curve, initial_cash=100)
    assert metrics.max_drawdown == pytest.approx(0.01)
    assert metrics.annual_return == pytest.approx(0.99**252 - 1)
    assert evidence["points"][0]["equity"] == "99"
    assert evidence["points"][0]["peak_equity"] == "100"
    assert is_valid_complete_backtest_drawdown_evidence(
        evidence,
        expected_equity_curve=curve,
        expected_initial_equity=100,
        expected_final_equity=99,
        expected_max_drawdown=metrics.max_drawdown,
    )
    assert not is_valid_complete_backtest_drawdown_evidence(
        evidence,
        expected_equity_curve=curve,
        expected_initial_equity=101,
        expected_final_equity=99,
        expected_max_drawdown=metrics.max_drawdown,
    )
