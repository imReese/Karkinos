"""Verification tests for the consolidated server.services.portfolio domain."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from server.services.portfolio.allocation import allocate_action_tasks

pytestmark = pytest.mark.unit


def test_cold_allocation_import_does_not_load_portfolio_commands() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            """
import sys
from server.services.portfolio.allocation import allocate_action_tasks

unexpected = {
    "server.services.portfolio.trades",
    "server.services.portfolio.cash_flows",
    "server.services.portfolio.ledger",
    "pandas",
}.intersection(sys.modules)
assert not unexpected, sorted(unexpected)
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_portfolio_allocation_preserves_zero_equity_safety() -> None:
    """Allocation with empty/zero equity must produce zero allocated quantity."""

    class _EmptyPortfolio:
        cash = 0
        total_equity = 0
        positions = {}

    actions = [{"symbol": "600519", "direction": "buy", "target_weight": 0.2}]
    quotes = {"600519": {"price": 1800.0, "asset_class": "stock"}}
    result = allocate_action_tasks(
        actions,
        portfolio=_EmptyPortfolio(),
        quotes=quotes,
    )
    assert len(result) == 1
    assert result[0]["allocation_quantity"] == 0.0
