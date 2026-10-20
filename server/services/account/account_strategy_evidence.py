"""Canonical strategy-to-signal/order/fill evidence linkage helpers.

Backward-compatible facade for server.services.account.strategy.
"""

from __future__ import annotations

from server.services.account.strategy import (
    assignment_matches_signal,
    fill_metadata,
    is_simulation_order,
    json_dict,
    linked_strategy_evidence,
    order_source_signal_id,
    same_symbol,
    source_signal_id,
)

__all__ = [
    "assignment_matches_signal",
    "fill_metadata",
    "is_simulation_order",
    "json_dict",
    "linked_strategy_evidence",
    "order_source_signal_id",
    "same_symbol",
    "source_signal_id",
]
