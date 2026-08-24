"""Pure narrowing policy for paused controlled-session replacements."""

from __future__ import annotations

from typing import Any

from server.services.controlled_session_runtime_values import json_list as _json_list
from server.services.controlled_session_runtime_values import (
    json_object as _json_object,
)
from server.services.controlled_session_runtime_values import (
    parse_timestamp as _parse_timestamp,
)


def replacement_bound_blockers(
    *,
    predecessor: dict[str, Any],
    pause_state: dict[str, Any],
    old_reservation: dict[str, Any],
    new_reservation: dict[str, Any],
    target: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if not old_reservation or not new_reservation:
        return ["runtime_session_replacement_reservation_missing"]
    for field in ("authorization_id", "account_alias", "strategy_id"):
        if str(old_reservation.get(field) or "") != str(
            new_reservation.get(field) or ""
        ):
            blockers.append(f"runtime_session_replacement_scope_widened:{field}")
    for field in (
        "reserved_gross_units",
        "reserved_buy_units",
        "reserved_turnover_units",
        "reserved_order_count",
    ):
        try:
            widened = int(new_reservation.get(field) or 0) > int(
                old_reservation.get(field) or 0
            )
        except (TypeError, ValueError):
            widened = True
        if widened:
            blockers.append(f"runtime_session_replacement_budget_widened:{field}")
    old_symbols = {
        str(key): int(value)
        for key, value in _json_object(
            old_reservation.get("reserved_by_symbol_json")
        ).items()
    }
    replacement_symbols = {
        str(key): int(value)
        for key, value in _json_object(
            new_reservation.get("reserved_by_symbol_json")
        ).items()
    }
    if not replacement_symbols or not set(replacement_symbols).issubset(old_symbols):
        blockers.append("runtime_session_replacement_symbol_scope_widened")
    elif any(
        value > old_symbols[symbol] for symbol, value in replacement_symbols.items()
    ):
        blockers.append("runtime_session_replacement_symbol_budget_widened")
    old_orders = set(_json_list(predecessor.get("order_ids_json")))
    target_orders = {str(item) for item in target.get("order_ids") or []}
    if not target_orders or not target_orders.issubset(old_orders):
        blockers.append("runtime_session_replacement_order_scope_widened")
    try:
        if int(target.get("max_order_rate_per_minute") or 0) > int(
            predecessor.get("max_order_rate_per_minute") or 0
        ):
            blockers.append("runtime_session_replacement_rate_widened")
    except (TypeError, ValueError):
        blockers.append("runtime_session_replacement_rate_invalid")
    target_start = _parse_timestamp(target.get("effective_at"))
    target_expiry = _parse_timestamp(target.get("expires_at"))
    old_start = _parse_timestamp(predecessor.get("effective_at"))
    old_expiry = _parse_timestamp(predecessor.get("expires_at"))
    paused_at_ms = int(pause_state.get("paused_at_epoch_ms") or 0)
    if target_start is None or int(target_start.timestamp() * 1000) < paused_at_ms:
        blockers.append("runtime_session_replacement_starts_before_pause")
    if (
        target_start is None
        or target_expiry is None
        or old_start is None
        or old_expiry is None
        or target_expiry <= target_start
        or target_expiry - target_start > old_expiry - old_start
    ):
        blockers.append("runtime_session_replacement_duration_widened")
    return blockers
