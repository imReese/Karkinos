"""Canonical persisted account-strategy assignment projection.

Backward-compatible facade for server.services.account.strategy.
"""

from __future__ import annotations

from server.services.account.strategy import (
    ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY,
    ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION,
    account_strategy_assignment_from_payload,
    default_account_strategy_assignment,
)

__all__ = [
    "ACCOUNT_STRATEGY_ASSIGNMENT_CONTROL_KEY",
    "ACCOUNT_STRATEGY_ASSIGNMENT_LIMITATION",
    "default_account_strategy_assignment",
    "account_strategy_assignment_from_payload",
]
