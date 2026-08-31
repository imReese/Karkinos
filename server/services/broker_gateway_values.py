"""Pure values and response projections for the broker gateway boundary."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CONTROLLED_BRIDGE_REQUIRED_GATES = (
    "account_truth",
    "research_evidence",
    "risk",
    "paper_shadow",
    "manual_confirmation",
    "kill_switch_clear",
    "connector_health",
    "execution_reconciliation",
)
REQUIRED_GATEWAY_EVIDENCE: dict[str, tuple[str, set[str]]] = {
    "account_truth": ("gate_status", {"pass", "passed"}),
    "research_evidence": ("gate_status", {"pass", "passed"}),
    "risk": ("gate_status", {"pass", "passed"}),
    "paper_shadow": ("divergence_status", {"within_expectations"}),
}


def manual_execution_preview(
    order: dict[str, Any],
    *,
    fill_price: Any,
    quantity: Any,
    fee: Any,
    tax: Any,
    transfer_fee: Any,
) -> dict[str, Any]:
    side = str(order.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        raise ValueError(f"unsupported OMS side for manual execution preview: {side}")
    price_value = required_decimal(fill_price, "fill_price")
    quantity_value = required_decimal(quantity, "quantity")
    if price_value <= 0:
        raise ValueError("fill_price must be positive")
    if quantity_value <= 0:
        raise ValueError("quantity must be positive")
    fee_value = optional_decimal(fee)
    tax_value = optional_decimal(tax)
    transfer_fee_value = optional_decimal(transfer_fee)
    gross_amount = price_value * quantity_value
    total_cost = fee_value + tax_value + transfer_fee_value
    net_cash_impact = (
        -(gross_amount + total_cost) if side == "buy" else gross_amount - total_cost
    )
    return {
        "source": "manual_ticket_operator_entry",
        "symbol": str(order.get("symbol") or ""),
        "side": side,
        "asset_class": str(order.get("asset_class") or ""),
        "quantity": quantity_string(quantity_value),
        "fill_price": money_string(price_value),
        "gross_amount": money_string(gross_amount),
        "fee": money_string(fee_value),
        "tax": money_string(tax_value),
        "transfer_fee": money_string(transfer_fee_value),
        "total_cost": money_string(total_cost),
        "net_cash_impact": money_string(net_cash_impact),
        "currency": "CNY",
        "notes": [
            "Broker client fill and fee/tax statement remains authoritative.",
            "Preview is an operator review draft before any production ledger save.",
        ],
    }


def manual_execution_ledger_draft(
    order: dict[str, Any],
    *,
    execution_preview: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "karkinos.manual_execution_ledger_draft.v1",
        "entry_type": "trade",
        "symbol": execution_preview["symbol"],
        "side": execution_preview["side"],
        "asset_class": execution_preview["asset_class"],
        "quantity": execution_preview["quantity"],
        "price": execution_preview["fill_price"],
        "gross_amount": execution_preview["gross_amount"],
        "fee": execution_preview["fee"],
        "tax": execution_preview["tax"],
        "transfer_fee": execution_preview["transfer_fee"],
        "amount": execution_preview["net_cash_impact"],
        "source_order_id": order["order_id"],
        "source": "manual_ticket_execution_preview",
        "requires_operator_save": True,
        "does_not_mutate_production_ledger": True,
    }


def fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def required_decimal(value: Any, field_name: str) -> Decimal:
    parsed = decimal_value(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be numeric")
    return parsed


def optional_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    parsed = decimal_value(value)
    if parsed is None:
        raise ValueError("fee, tax, and transfer_fee must be numeric when provided")
    return parsed


def money_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def quantity_string(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def clean_number(value: Any) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, list | tuple | set):
        values = value
    else:
        values = ()
    return sorted({str(item).strip() for item in values if str(item).strip()})


def operator_account_alias(policy: dict[str, Any]) -> str:
    aliases = policy.get("allowed_account_aliases")
    if isinstance(aliases, list) and aliases:
        return str(aliases[0])
    return "manual-review"


def fee_tax_assumptions(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    fee_components = mapping_value(
        source_payload.get("fee_breakdown"),
        source_payload.get("fee_components"),
    )
    return {
        "source": "oms_order_payload_or_fee_rule",
        "estimated_total_fee": optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "fee_rule_id": optional_string(source_payload.get("fee_rule_id")),
        "fee_rule_version": optional_string(source_payload.get("fee_rule_version")),
        "fee_components": dict(sorted(fee_components.items())),
        "notes": [
            "Broker client final fee and tax preview remains authoritative.",
            "Karkinos fee/tax values are execution-review assumptions only.",
        ],
    }


def cash_impact_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    return {
        "source": "oms_order_payload_or_order_intent",
        "estimated_gross_amount": optional_clean_number(
            source_payload.get("estimated_gross_amount")
        ),
        "estimated_total_fee": optional_clean_number(
            source_payload.get("estimated_total_fee")
        ),
        "estimated_net_cash_impact": optional_clean_number(
            source_payload.get("estimated_net_cash_impact")
        ),
        "available_cash_before": optional_clean_number(
            source_payload.get("available_cash_before")
        ),
        "available_cash_after": optional_clean_number(
            source_payload.get("available_cash_after")
        ),
        "cash_status": optional_string(source_payload.get("cash_status")),
        "cash_shortfall": optional_clean_number(source_payload.get("cash_shortfall")),
    }


def position_cost_preview(order: dict[str, Any]) -> dict[str, Any]:
    source_payload = order_intent_payload(order)
    position_effect = mapping_value(
        source_payload.get("position_effect"),
        source_payload.get("position_cost_preview"),
    )
    return {
        "source": "daily_trading_plan_position_effect",
        "current_quantity": optional_clean_number(
            position_effect.get("current_quantity")
        ),
        "current_avg_cost": optional_clean_number(
            position_effect.get("current_avg_cost")
        ),
        "current_market_value": optional_clean_number(
            position_effect.get("current_market_value")
        ),
        "estimated_quantity_after": optional_clean_number(
            position_effect.get("estimated_quantity_after")
        ),
        "estimated_avg_cost_after": optional_clean_number(
            position_effect.get("estimated_avg_cost_after")
        ),
        "cost_basis_method": optional_string(position_effect.get("cost_basis_method")),
    }


def trading_session_constraints(order: dict[str, Any]) -> dict[str, Any]:
    asset_class = str(order.get("asset_class") or "").lower()
    notes = [
        "Operator must enter this ticket only while the broker client accepts regular-session orders.",
        "Broker client availability and exchange rules remain authoritative.",
    ]
    if asset_class == "stock" and str(order.get("side") or "").lower() == "sell":
        notes.append(
            "For A-share sells, verify broker available quantity and T+1 state."
        )
    return {
        "market": "China exchange session",
        "timezone": "Asia/Shanghai",
        "allowed_session": "regular_exchange_session_only",
        "asset_class": asset_class or "unknown",
        "notes": notes,
    }


def first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def mapping_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def optional_clean_number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return clean_number(value)
    except (TypeError, ValueError):
        return None


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def order_intent_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order_payload(order)
    return first_mapping(
        payload.get("order_intent"),
        payload.get("daily_trading_plan_intent"),
        payload,
    )


def order_payload(order: dict[str, Any]) -> dict[str, Any]:
    payload = order.get("payload")
    if isinstance(payload, dict):
        return payload
    payload_json = order.get("payload_json")
    if not isinstance(payload_json, str) or not payload_json:
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def gateway_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["id"],
        "gateway_id": event["gateway_id"],
        "event_type": event["event_type"],
        "status": event["status"],
        "actor": event.get("actor"),
        "created_at": event["created_at"],
    }


def broker_fill_payload(
    event: Any, *, order_quantity: Decimal | None
) -> dict[str, Any]:
    event_quantity = decimal_value(getattr(event, "quantity", None))
    match_status = (
        "matched"
        if order_quantity is not None
        and event_quantity is not None
        and abs(order_quantity) == abs(event_quantity)
        else "quantity_mismatch"
    )
    return {
        "source": "staged_broker_evidence",
        "import_run_id": getattr(event, "import_run_id", ""),
        "event_id": getattr(event, "event_id", ""),
        "event_type": getattr(event, "event_type", ""),
        "symbol": getattr(event, "symbol", ""),
        "side": "buy" if getattr(event, "event_type", "") == "trade_buy" else "sell",
        "quantity": getattr(event, "quantity", ""),
        "price": getattr(event, "price", ""),
        "fee": getattr(event, "fee", ""),
        "tax": getattr(event, "tax", ""),
        "net_amount": getattr(event, "net_amount", ""),
        "occurred_at": getattr(event, "occurred_at", ""),
        "settled_at": getattr(event, "settled_at", ""),
        "match_status": match_status,
    }


def cash_balance_payloads(events: list[Any]) -> list[dict[str, Any]]:
    by_currency: dict[str, dict[str, Any]] = {}
    for event in events:
        cash_balance = getattr(event, "cash_balance", None)
        currency = str(getattr(event, "currency", "") or "")
        if cash_balance is None or not currency or currency in by_currency:
            continue
        by_currency[currency] = {
            "source": "staged_broker_evidence",
            "import_run_id": getattr(event, "import_run_id", ""),
            "event_id": getattr(event, "event_id", ""),
            "currency": currency,
            "cash_balance": cash_balance,
            "occurred_at": getattr(event, "occurred_at", ""),
            "settled_at": getattr(event, "settled_at", ""),
        }
    return list(by_currency.values())


def position_payloads(events: list[Any]) -> list[dict[str, Any]]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for event in events:
        quantity = getattr(event, "position_quantity", None)
        symbol = str(getattr(event, "symbol", "") or "")
        if quantity is None or not symbol or symbol in by_symbol:
            continue
        by_symbol[symbol] = {
            "source": "staged_broker_evidence",
            "import_run_id": getattr(event, "import_run_id", ""),
            "event_id": getattr(event, "event_id", ""),
            "symbol": symbol,
            "instrument_name": getattr(event, "instrument_name", ""),
            "asset_class": getattr(event, "asset_class", ""),
            "currency": getattr(event, "currency", ""),
            "quantity": quantity,
            "cost_basis": getattr(event, "cost_basis", None),
            "cost_basis_method": getattr(event, "cost_basis_method", ""),
            "occurred_at": getattr(event, "occurred_at", ""),
            "settled_at": getattr(event, "settled_at", ""),
        }
    return list(by_symbol.values())


def broker_account_fill_payload(event: Any) -> dict[str, Any]:
    event_type = str(getattr(event, "event_type", "") or "")
    if event_type == "trade_buy":
        side = "buy"
    elif event_type == "trade_sell":
        side = "sell"
    else:
        side = "unknown"
    return {
        "source": "staged_broker_evidence",
        "import_run_id": getattr(event, "import_run_id", ""),
        "event_id": getattr(event, "event_id", ""),
        "event_type": event_type,
        "symbol": getattr(event, "symbol", ""),
        "side": side,
        "quantity": getattr(event, "quantity", ""),
        "price": getattr(event, "price", ""),
        "gross_amount": getattr(event, "gross_amount", ""),
        "fee": getattr(event, "fee", ""),
        "tax": getattr(event, "tax", ""),
        "net_amount": getattr(event, "net_amount", ""),
        "occurred_at": getattr(event, "occurred_at", ""),
        "settled_at": getattr(event, "settled_at", ""),
    }


def decimal_value(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
