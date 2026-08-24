"""Pure fail-closed policy evaluation for controlled-session envelopes."""

from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from server.contracts.controlled_session_envelope import (
    CONTROLLED_SESSION_MAX_DURATION_SECONDS,
    CONTROLLED_SESSION_MAX_ORDER_COUNT,
)
from server.services.controlled_session_envelope_values import (
    decimal_string as _decimal_string,
)
from server.services.controlled_session_envelope_values import decimal_value as _decimal
from server.services.controlled_session_envelope_values import (
    order_payload as _order_payload,
)

REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, frozenset[str]]] = {
    "account_truth": ("gate_status", frozenset({"pass", "passed"})),
    "research_evidence": ("gate_status", frozenset({"pass", "passed"})),
    "risk": ("gate_status", frozenset({"pass", "passed"})),
    "paper_shadow": (
        "divergence_status",
        frozenset({"within_expectations"}),
    ),
}


def time_and_request_blockers(
    *,
    now: datetime,
    start_at: datetime,
    expires_at: datetime,
    requested_ids: list[str],
    normalized_ids: list[str],
) -> list[str]:
    blockers: list[str] = []
    if not normalized_ids:
        blockers.append("session_order_set_empty")
    if len(normalized_ids) > CONTROLLED_SESSION_MAX_ORDER_COUNT:
        blockers.append("session_order_count_exceeded")
    if len(requested_ids) != len(normalized_ids):
        blockers.append("session_order_ids_invalid_or_duplicate")
    if start_at < now and (now - start_at).total_seconds() > 60:
        blockers.append("session_start_in_past")
    if start_at > now.replace(microsecond=0) and (start_at - now).total_seconds() > 300:
        blockers.append("session_start_too_far_in_future")
    duration = (expires_at - start_at).total_seconds()
    if duration <= 0:
        blockers.append("session_window_invalid")
    elif duration > CONTROLLED_SESSION_MAX_DURATION_SECONDS:
        blockers.append("session_duration_exceeded")
    return blockers


def verification_reference_blockers(
    order_ids: list[str],
    verification_fingerprints: dict[str, str],
) -> list[str]:
    blockers: list[str] = []
    if set(verification_fingerprints) != set(order_ids):
        blockers.append("execution_gateway_verification_order_set_mismatch")
    for order_id, fingerprint in sorted(verification_fingerprints.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", order_id):
            blockers.append("execution_gateway_verification_order_id_invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
            blockers.append(
                f"execution_gateway_verification_fingerprint_invalid:{order_id}"
            )
    values = list(verification_fingerprints.values())
    if len(set(values)) != len(values):
        blockers.append("execution_gateway_verification_fingerprint_reused")
    return list(dict.fromkeys(blockers))


def per_symbol_runtime_limit_summary(
    *,
    requested_limits: dict[str, Any],
    projected_by_symbol: dict[str, Any],
    capital_decision: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    expected_symbols = {str(symbol) for symbol in projected_by_symbol}
    raw_limits = requested_limits if isinstance(requested_limits, dict) else {}
    submitted_symbols = {str(symbol) for symbol in raw_limits}
    blockers: list[str] = []
    if submitted_symbols != expected_symbols:
        blockers.append("per_symbol_runtime_limit_set_mismatch")
    effective_limits = (
        capital_decision.get("effective_limits")
        if isinstance(capital_decision.get("effective_limits"), dict)
        else {}
    )
    capital_symbol_ceiling = _decimal(effective_limits.get("symbol_capital_limit"))
    effective_capital = _decimal(effective_limits.get("effective_capital"))
    if capital_symbol_ceiling is None or capital_symbol_ceiling <= 0:
        blockers.append("capital_symbol_limit_missing_or_invalid")
    if effective_capital is None or effective_capital <= 0:
        blockers.append("capital_effective_limit_missing_or_invalid")
    ceiling = min(
        value
        for value in (
            capital_symbol_ceiling or Decimal("0"),
            effective_capital or Decimal("0"),
        )
    )
    results: dict[str, dict[str, str]] = {}
    canonical_limits: dict[str, str] = {}
    for raw_symbol, raw_limit in sorted(raw_limits.items()):
        symbol = str(raw_symbol)
        if symbol != symbol.strip() or not symbol:
            blockers.append("per_symbol_runtime_limit_symbol_invalid")
        limit = _decimal(raw_limit)
        projected = _decimal(projected_by_symbol.get(symbol))
        if limit is None or limit <= 0:
            blockers.append(f"per_symbol_runtime_limit_invalid:{symbol}")
            continue
        canonical_limits[symbol] = _decimal_string(limit)
        if ceiling <= 0 or limit > ceiling:
            blockers.append(f"per_symbol_runtime_limit_exceeds_cap:{symbol}")
        if projected is None or projected < 0:
            blockers.append(f"per_symbol_projection_invalid:{symbol}")
            projected = Decimal("0")
        if projected > limit:
            blockers.append(f"per_symbol_runtime_limit_projection_exceeded:{symbol}")
        results[symbol] = {
            "limit_value": _decimal_string(limit),
            "projected_gross_value": _decimal_string(projected),
            "remaining_after_projection": _decimal_string(
                max(Decimal("0"), limit - projected)
            ),
        }
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "status": "pass" if not unique_blockers else "blocked",
        "calculation_mode": "explicit_signed_map_capped_by_capital_evaluation",
        "capital_symbol_ceiling": _decimal_string(ceiling),
        "requested_limits": canonical_limits,
        "symbols": results,
        "blockers": unique_blockers,
        "authorizes_execution": False,
    }, unique_blockers


def budget_projection(
    *,
    orders: list[dict[str, Any]],
    policy: dict[str, Any],
    context: dict[str, Any],
    decision: dict[str, Any],
    duration_seconds: int,
) -> tuple[dict[str, Any], list[str]]:
    limits = policy.get("limits") if isinstance(policy.get("limits"), dict) else {}
    values: list[tuple[dict[str, Any], Decimal]] = []
    blockers: list[str] = []
    for order in orders:
        value = _decimal(order.get("projected_order_value"))
        if value is not None and value > 0:
            values.append((order, value))
    gross = sum((value for _, value in values), Decimal("0"))
    buy_value = sum(
        (value for order, value in values if order.get("side") == "buy"),
        Decimal("0"),
    )
    sell_value = sum(
        (value for order, value in values if order.get("side") == "sell"),
        Decimal("0"),
    )
    max_order_value = _decimal(limits.get("max_order_value")) or Decimal("0")
    max_position_change = _decimal(limits.get("max_position_change_value")) or Decimal(
        "0"
    )
    max_daily_turnover = _decimal(limits.get("max_daily_turnover")) or Decimal("0")
    effective_limits = (
        decision.get("effective_limits")
        if isinstance(decision.get("effective_limits"), dict)
        else {}
    )
    effective_capital = _decimal(effective_limits.get("effective_capital")) or Decimal(
        "0"
    )
    current_exposure = _decimal(context.get("current_authorized_exposure")) or Decimal(
        "0"
    )
    daily_turnover_used = _decimal(context.get("daily_turnover_used")) or Decimal("0")
    available_cash = _decimal(context.get("available_cash")) or Decimal("0")
    liquidity_limit = _decimal(context.get("liquidity_capital_limit")) or Decimal("0")
    for order, value in values:
        order_id = str(order.get("order_id") or "")
        if max_order_value <= 0 or value > max_order_value:
            blockers.append(f"session_order_value_exceeded:{order_id}")
        if max_position_change <= 0 or value > max_position_change:
            blockers.append(f"session_position_change_exceeded:{order_id}")
        if liquidity_limit <= 0 or value > liquidity_limit:
            blockers.append(f"session_liquidity_limit_exceeded:{order_id}")
    if effective_capital <= 0 or current_exposure + gross > effective_capital:
        blockers.append("session_authorized_capital_exceeded")
    if max_daily_turnover <= 0 or daily_turnover_used + gross > max_daily_turnover:
        blockers.append("session_daily_turnover_exceeded")
    if available_cash <= 0 or buy_value > available_cash:
        blockers.append("session_available_cash_exceeded")
    max_rate = int(limits.get("max_order_rate_per_minute") or 0)
    duration_minutes = max(1, math.ceil(duration_seconds / 60))
    projected_rate_capacity = max_rate * duration_minutes
    if max_rate <= 0 or len(orders) > projected_rate_capacity:
        blockers.append("session_projected_order_rate_exceeded")
    by_symbol: dict[str, Decimal] = {}
    for order, value in values:
        symbol = str(order.get("symbol") or "")
        by_symbol[symbol] = by_symbol.get(symbol, Decimal("0")) + value
    return {
        "calculation_mode": "conservative_gross_without_buy_sell_netting",
        "order_count": len(orders),
        "priced_order_count": len(values),
        "projected_gross_order_value": _decimal_string(gross),
        "projected_buy_value": _decimal_string(buy_value),
        "projected_sell_value": _decimal_string(sell_value),
        "projected_by_symbol": {
            symbol: _decimal_string(value)
            for symbol, value in sorted(by_symbol.items())
        },
        "effective_capital": _decimal_string(effective_capital),
        "current_authorized_exposure": _decimal_string(current_exposure),
        "remaining_authorized_capital_after_projection": _decimal_string(
            max(Decimal("0"), effective_capital - current_exposure - gross)
        ),
        "available_cash": _decimal_string(available_cash),
        "remaining_cash_after_projected_buys": _decimal_string(
            max(Decimal("0"), available_cash - buy_value)
        ),
        "daily_turnover_used": _decimal_string(daily_turnover_used),
        "remaining_daily_turnover_after_projection": _decimal_string(
            max(Decimal("0"), max_daily_turnover - daily_turnover_used - gross)
        ),
        "max_order_rate_per_minute": max_rate,
        "duration_minutes": duration_minutes,
        "projected_rate_capacity": projected_rate_capacity,
        "reserved": False,
        "does_not_consume_runtime_budget": True,
    }, list(dict.fromkeys(blockers))


def gateway_gate_summary(
    order: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    payload = _order_payload(order)
    evidence = payload.get("gateway_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    gates: dict[str, Any] = {}
    blockers: list[str] = []
    for gate, (status_field, passing_values) in REQUIRED_GATEWAY_EVIDENCE.items():
        item = evidence.get(gate)
        item = item if isinstance(item, dict) else {}
        raw_status = str(item.get(status_field) or "").lower()
        evidence_ref = str(item.get("evidence_ref") or "")
        passed = bool(evidence_ref) and raw_status in passing_values
        gates[gate] = {
            "status": "pass" if passed else (raw_status or "missing"),
            "evidence_ref": evidence_ref,
        }
        if not evidence_ref:
            blockers.append(f"gateway_evidence_missing:{gate}")
        elif not passed:
            blockers.append(f"gateway_evidence_not_passing:{gate}")
    return {
        "status": "pass" if not blockers else "blocked",
        "gates": gates,
    }, blockers
