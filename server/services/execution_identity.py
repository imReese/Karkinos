"""Canonical immutable identity for persisted OMS order facts."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any


def build_order_contract(order: dict[str, Any]) -> dict[str, Any]:
    """Normalize the exact order fields bound by controlled-execution gates."""

    return {
        "order_id": str(order.get("order_id") or ""),
        "intent_key": str(order.get("intent_key") or ""),
        "symbol": str(order.get("symbol") or ""),
        "side": str(order.get("side") or "").lower(),
        "asset_class": str(order.get("asset_class") or ""),
        "quantity": _number_string(order.get("quantity")),
        "order_type": str(order.get("order_type") or "").lower(),
        "limit_price": (
            _number_string(order.get("limit_price"))
            if order.get("limit_price") is not None
            else None
        ),
        "source": str(order.get("source") or ""),
        "source_ref": str(order.get("source_ref") or ""),
    }


def build_order_fingerprint(order: dict[str, Any]) -> str:
    """Return the canonical fingerprint used by controlled-order evidence."""

    encoded = json.dumps(
        build_order_contract(order),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _number_string(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")
