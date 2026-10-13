"""Verification tests for the consolidated server.services.portfolio domain."""

from __future__ import annotations

import pytest

import server.services.portfolio as portfolio_domain
import server.services.portfolio_allocation as legacy_allocation
import server.services.portfolio_cash_flow_commands as legacy_cash_flow
import server.services.portfolio_ledger as legacy_ledger
import server.services.portfolio_trade_commands as legacy_trades

pytestmark = pytest.mark.unit


def test_portfolio_domain_exports_preserve_facade_identity() -> None:
    """Ensure facades re-export exact canonical domain symbols."""
    # Allocation
    assert (
        portfolio_domain.allocate_action_tasks
        is legacy_allocation.allocate_action_tasks
    )

    # Ledger
    assert (
        portfolio_domain.rebuild_portfolio_from_ledger
        is legacy_ledger.rebuild_portfolio_from_ledger
    )
    assert (
        portfolio_domain.rebuild_portfolio_from_entries
        is legacy_ledger.rebuild_portfolio_from_entries
    )
    assert (
        portfolio_domain.build_portfolio_projection
        is legacy_ledger.build_portfolio_projection
    )

    # Cash flows
    assert (
        portfolio_domain.PortfolioCashFlowCommandService
        is legacy_cash_flow.PortfolioCashFlowCommandService
    )

    # Trades
    assert (
        portfolio_domain.PortfolioTradeCommandService
        is legacy_trades.PortfolioTradeCommandService
    )
    assert portfolio_domain.ManualTradeRequest is legacy_trades.ManualTradeRequest
    assert portfolio_domain.CreatedManualTrade is legacy_trades.CreatedManualTrade
    assert (
        portfolio_domain.CreatedPendingFundOrder
        is legacy_trades.CreatedPendingFundOrder
    )


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
