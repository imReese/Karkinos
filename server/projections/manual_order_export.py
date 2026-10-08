"""Read-only CSV projection of saved /api/trading/orders response rows."""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from decimal import Decimal

from server.contracts.financial_values import (
    EXACT_DECIMAL_WRITE_PROVENANCE,
    LEGACY_REAL_BACKFILL_PROVENANCE,
    decimal_from_mapping,
    real_projection_matches,
)

_COLUMNS = (
    "purpose",
    "order_id",
    "timestamp",
    "symbol",
    "side",
    "order_type",
    "quantity",
    "price",
    "currency_code",
    "execution_mode",
    "status",
    "intent_id",
    "risk_decision_id",
    "decimal_provenance",
)


def _text(row: Mapping[str, object], field: str, *, optional: bool = False) -> str:
    value = row.get(field)
    if optional and value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"order_export_{field}_required")
    # CSV quoting alone does not stop spreadsheet formula evaluation.
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(
        ("\t", "\r", "\n")
    ):
        return "'" + value
    return value


def export_manual_order_review_csv(rows: Sequence[Mapping[str, object]]) -> str:
    """Preserve existing tickets and statuses; never size or authorize orders.

    Input is a saved current manual-order API response, including decimal
    storage mirrors. No broker-format compatibility or current readiness is
    inferred from that snapshot. The complete batch is checked before output.
    """
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_COLUMNS)
    writer.writeheader()
    seen: set[str] = set()
    for row in rows:
        order_id = _text(row, "order_id")
        if order_id in seen:
            raise ValueError("order_export_duplicate_order_id")
        seen.add(order_id)
        if row.get("side") not in ("buy", "sell"):
            raise ValueError("order_export_side_invalid")
        if row.get("order_type") not in ("market", "limit"):
            raise ValueError("order_export_order_type_invalid")
        if row.get("execution_mode") != "manual":
            raise ValueError("order_export_manual_ticket_required")
        if row.get("status") not in ("pending_confirm", "confirmed", "rejected"):
            raise ValueError("order_export_status_invalid")
        if row.get("decimal_provenance") not in (
            EXACT_DECIMAL_WRITE_PROVENANCE,
            LEGACY_REAL_BACKFILL_PROVENANCE,
        ):
            raise ValueError("order_export_decimal_provenance_required")
        for field in ("quantity", "price"):
            numeric = row.get(field)
            exact = row.get(f"{field}_decimal")
            if (
                isinstance(numeric, bool)
                or (
                    numeric is not None
                    and not isinstance(numeric, (int, float, Decimal, str))
                )
                or (exact is not None and not isinstance(exact, str))
            ):
                raise ValueError(f"order_export_{field}_invalid")
            if not real_projection_matches(row, field):
                raise ValueError(f"order_export_{field}_projection_conflict")
        quantity = decimal_from_mapping(row, "quantity")
        price = decimal_from_mapping(row, "price", allow_none=True)
        if quantity <= 0 or (price is not None and price <= 0):
            raise ValueError("order_export_positive_values_required")
        if row["order_type"] == "limit" and price is None:
            raise ValueError("order_export_limit_price_required")
        writer.writerow(
            {
                "purpose": "review_only",
                "order_id": order_id,
                **{
                    field: _text(row, field)
                    for field in (
                        "timestamp",
                        "symbol",
                        "side",
                        "order_type",
                        "currency_code",
                        "execution_mode",
                        "status",
                        "decimal_provenance",
                    )
                },
                "quantity": format(quantity, "f"),
                "price": format(price, "f") if price is not None else "",
                "intent_id": _text(row, "intent_id", optional=True),
                "risk_decision_id": _text(row, "risk_decision_id", optional=True),
            }
        )
    return output.getvalue()
