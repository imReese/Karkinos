"""Server-owned correction guardrails for Account Truth snapshot roll-forward.

Backward-compatible facade for server.services.account.roll_forward.
"""

from __future__ import annotations

from server.services.account.roll_forward import (
    roll_forward_daily_broker_statement_for_state,
)

__all__ = ["roll_forward_daily_broker_statement_for_state"]
