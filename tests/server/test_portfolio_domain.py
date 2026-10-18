"""Verification tests for the consolidated server.services.portfolio domain."""

from __future__ import annotations

import pytest

import server.services.portfolio as portfolio_domain

pytestmark = pytest.mark.unit


def test_portfolio_allocation_preserves_zero_equity_safety() -> None:
    """Allocation with empty/zero equity must produce zero allocated quantity."""

    class _EmptyPortfolio:
        cash = 0
        total_equity = 0
        positions = {}

    actions = [{"symbol": "600519", "direction": "buy", "target_weight": 0.2}]
    quotes = {"600519": {"price": 1800.0, "asset_class": "stock"}}
    result = portfolio_domain.allocate_action_tasks(
        actions,
        portfolio=_EmptyPortfolio(),
        quotes=quotes,
    )
    assert len(result) == 1
    assert result[0]["allocation_quantity"] == 0.0
