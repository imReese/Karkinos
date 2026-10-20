"""Paper order generation, simulated outcome transitions, and fill building.

Canonical module in server.services.paper_shadow.
"""

from __future__ import annotations

from server.services.paper_shadow.paper_shadow_execution import (
    build_shadow_failed_order,
    build_shadow_fill,
    build_shadow_order,
    expire_order,
    json_dict,
    json_list,
    matching_latest_run,
    order_payload_oms_transition_refs,
    paper_order_request,
    paper_shadow_oms_intent_key,
    shadow_oms_commands,
    simulate_outcome,
)

__all__ = [
    "build_shadow_failed_order",
    "build_shadow_fill",
    "build_shadow_order",
    "expire_order",
    "json_dict",
    "json_list",
    "matching_latest_run",
    "order_payload_oms_transition_refs",
    "paper_order_request",
    "paper_shadow_oms_intent_key",
    "shadow_oms_commands",
    "simulate_outcome",
]
