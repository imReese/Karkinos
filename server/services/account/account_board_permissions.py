"""Resolve locally reviewed broker board access for candidate eligibility.

Backward-compatible facade for server.services.account.permissions.
"""

from __future__ import annotations

from server.services.account.permissions import (
    BOARD_NAMES,
    BOARD_PERMISSION_REVIEW_DAYS,
    BOARD_PERMISSION_SOURCE,
    entry_board_policy_blocker,
    entry_board_policy_symbols,
    freeze_entry_board_policy,
    resolve_board_buy_permissions,
    validate_entry_board_policy,
)

__all__ = [
    "BOARD_NAMES",
    "BOARD_PERMISSION_REVIEW_DAYS",
    "BOARD_PERMISSION_SOURCE",
    "entry_board_policy_blocker",
    "entry_board_policy_symbols",
    "freeze_entry_board_policy",
    "resolve_board_buy_permissions",
    "validate_entry_board_policy",
]
