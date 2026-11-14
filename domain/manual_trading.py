"""Domain models and pure financial rules for manual trading."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any

MANUAL_EXECUTION_LEDGER_DRAFT_SCHEMA_VERSION = (
    "karkinos.manual_execution_ledger_draft.v1"
)
MANUAL_EXECUTION_PREVIEW_FINGERPRINT_SCHEMA_VERSION = (
    "karkinos.manual_execution_preview_fingerprint.v1"
)


def clean_decimal(value: Any, field_name: str) -> Decimal:
    """Parse a mandatory numeric value as a finite Decimal."""
    if value is None or value == "":
        raise ValueError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric") from None
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


def optional_decimal(value: Any) -> Decimal:
    """Parse an optional numeric value as Decimal, defaulting to 0."""
    if value is None or value == "":
        return Decimal("0")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "fee, tax, and transfer_fee must be numeric when provided"
        ) from None
    if not parsed.is_finite():
        raise ValueError("fee, tax, and transfer_fee must be finite")
    return parsed


def money_string(value: Decimal) -> str:
    """Format a Decimal currency value with 2 decimal places."""
    return str(value.quantize(Decimal("0.01")))


def quantity_string(value: Decimal) -> str:
    """Format a Decimal quantity normalized without scientific notation."""
    normalized = value.normalize()
    return format(normalized, "f")


def clean_number(value: Any) -> int | float:
    """Convert a numeric value to int if whole, or float."""
    number = float(value)
    return int(number) if number.is_integer() else number


def format_ticket_copy_text(
    *,
    side: str,
    symbol: str,
    quantity: Any,
    order_type: str,
    limit_price: Any = None,
) -> str:
    """Format standardized copyable ticket text (e.g. 'BUY 600519 100 LIMIT 1720.25')."""
    normalized_side = str(side).upper().strip()
    normalized_symbol = str(symbol).strip()
    normalized_quantity = clean_number(quantity)
    normalized_type = str(order_type).upper().strip()

    parts = [
        normalized_side,
        normalized_symbol,
        str(normalized_quantity),
        normalized_type,
    ]
    if limit_price is not None:
        parts.append(str(clean_number(limit_price)))
    return " ".join(parts)


def compute_execution_cash_impact(
    *,
    side: str,
    fill_price: Decimal,
    quantity: Decimal,
    fee: Decimal,
    tax: Decimal,
    transfer_fee: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate gross amount, total cost, and net cash impact for a manual fill.

    Returns:
        (gross_amount, total_cost, net_cash_impact)
    """
    normalized_side = str(side).lower().strip()
    if normalized_side not in {"buy", "sell"}:
        raise ValueError(f"unsupported OMS side for manual execution: {side}")
    if fill_price <= 0:
        raise ValueError("fill_price must be positive")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if fee < 0 or tax < 0 or transfer_fee < 0:
        raise ValueError("costs must be non-negative")

    gross_amount = fill_price * quantity
    total_cost = fee + tax + transfer_fee
    net_cash_impact = (
        -(gross_amount + total_cost)
        if normalized_side == "buy"
        else gross_amount - total_cost
    )
    return gross_amount, total_cost, net_cash_impact


def compute_preview_fingerprint(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 fingerprint from a JSON-serializable preview dict."""
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_preview_fingerprint(provided: str, expected: str) -> bool:
    """Constant-time comparison between provided and expected fingerprint."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(str(provided).strip(), str(expected).strip())


def build_manual_execution_ledger_draft(
    *,
    order_id: str,
    symbol: str,
    side: str,
    asset_class: str,
    quantity: str,
    fill_price: str,
    gross_amount: str,
    fee: str,
    tax: str,
    transfer_fee: str,
    net_cash_impact: str,
) -> dict[str, Any]:
    """Construct a non-persisting manual execution ledger draft entry."""
    return {
        "schema_version": MANUAL_EXECUTION_LEDGER_DRAFT_SCHEMA_VERSION,
        "entry_type": "trade",
        "symbol": symbol,
        "side": side,
        "asset_class": asset_class,
        "quantity": quantity,
        "price": fill_price,
        "gross_amount": gross_amount,
        "fee": fee,
        "tax": tax,
        "transfer_fee": transfer_fee,
        "amount": net_cash_impact,
        "source_order_id": order_id,
        "source": "manual_ticket_execution_preview",
        "requires_operator_save": True,
        "does_not_mutate_production_ledger": True,
    }
