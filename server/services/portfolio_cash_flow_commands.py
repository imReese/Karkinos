"""Compatibility facade for portfolio cash flow commands.

Canonical domain implementation: `server.services.portfolio.cash_flows`
"""

from __future__ import annotations

from server.services.portfolio.cash_flows import (
    PortfolioCashFlowCommandService,
    PortfolioCashFlowDatabase,
    PortfolioCashFlowState,
    RuntimePortfolioInstaller,
)

# Canonical requirement: mutations update runtime via install_runtime_portfolio
_INSTALLER_CONTRACT = "install_runtime_portfolio"

__all__ = [
    "PortfolioCashFlowCommandService",
    "PortfolioCashFlowDatabase",
    "PortfolioCashFlowState",
    "RuntimePortfolioInstaller",
]
