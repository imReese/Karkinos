"""Pure evidence projections for controlled-submission clearance."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from server.contracts.controlled_submission_reconciliation_clearance import (
    CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
)
from server.services.controlled_submission_clearance_values import (
    decimal_string,
    decimal_value,
    fingerprint,
    mapping,
)


def controlled_post_trade_account_truth_delta(
    raw: dict[str, Any],
    *,
    broker_evidence: list[dict[str, Any]],
    order: dict[str, Any],
) -> dict[str, Any]:
    """Prove that every Account Truth delta is this one unposted order."""

    if not broker_evidence:
        return {"status": "not_required", "fingerprint": "", "blockers": []}
    items = [
        mapping(item)
        for item in raw.get("reconciliation_items") or []
        if isinstance(item, dict)
    ]
    if not items:
        return {
            "status": "unavailable",
            "fingerprint": "",
            "blockers": ["account_truth_reconciliation_items_missing"],
        }

    symbol = str(order.get("symbol") or "")
    side = str(order.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        return {
            "status": "blocked",
            "fingerprint": "",
            "blockers": ["account_truth_controlled_order_side_invalid"],
        }
    signed_quantity = Decimal("1") if side == "buy" else Decimal("-1")
    quantity = sum(
        (
            abs(decimal_value(item.get("quantity")) or Decimal("0"))
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    gross = sum(
        (
            abs(decimal_value(item.get("gross_amount")) or Decimal("0"))
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    fee = sum(
        (
            abs(decimal_value(item.get("fee")) or Decimal("0"))
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    tax = sum(
        (
            abs(decimal_value(item.get("tax")) or Decimal("0"))
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    transfer_fee = sum(
        (
            abs(decimal_value(item.get("transfer_fee")) or Decimal("0"))
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    net_amount = sum(
        (
            decimal_value(item.get("net_amount")) or Decimal("0")
            for item in broker_evidence
        ),
        Decimal("0"),
    )
    expected = {
        "cash": net_amount,
        f"position:{symbol}": signed_quantity * quantity,
        f"trade_gross_amount:{symbol}": gross,
        f"net_cash_impact:{symbol}": net_amount,
        f"fee:{symbol}": fee,
        f"tax:{symbol}": tax,
        f"transfer_fee:{symbol}": transfer_fee,
        "fee": fee,
        "tax": tax,
    }
    money_tolerance = Decimal("0.005")
    quantity_tolerance = Decimal("0.00000001")
    non_pass = [item for item in items if str(item.get("status") or "") != "pass"]
    blockers: list[str] = []
    seen: set[str] = set()
    for item in non_pass:
        item_key = str(item.get("item_key") or "")
        category = str(item.get("category") or "")
        if category == "cost_basis":
            continue
        if item_key not in expected:
            blockers.append(f"unexpected_account_truth_delta:{item_key or category}")
            continue
        actual = decimal_value(item.get("difference"))
        tolerance = quantity_tolerance if category == "position" else money_tolerance
        if actual is None or abs(actual - expected[item_key]) > tolerance:
            blockers.append(f"account_truth_delta_mismatch:{item_key}")
        seen.add(item_key)

    required_keys = {key for key, value in expected.items() if value != 0}
    for item_key in sorted(required_keys - seen):
        blockers.append(f"account_truth_expected_delta_missing:{item_key}")

    position_item = next(
        (item for item in items if item.get("item_key") == f"position:{symbol}"),
        None,
    )
    cost_item = next(
        (item for item in items if item.get("item_key") == f"cost_basis:{symbol}"),
        None,
    )
    if position_item is None or cost_item is None:
        blockers.append("account_truth_position_or_cost_basis_snapshot_missing")
    else:
        current_quantity = decimal_value(position_item.get("karkinos_value"))
        broker_quantity = decimal_value(position_item.get("broker_value"))
        current_cost = decimal_value(cost_item.get("karkinos_value"))
        broker_cost = decimal_value(cost_item.get("broker_value"))
        if current_quantity is None or broker_quantity is None or broker_cost is None:
            blockers.append("account_truth_position_or_cost_basis_value_missing")
        elif current_quantity != 0 and current_cost is None:
            blockers.append("account_truth_current_cost_basis_missing")
        else:
            current_cost = current_cost or Decimal("0")
            if side == "buy" and broker_quantity > 0:
                expected_cost = (
                    current_quantity * current_cost + gross + fee + tax + transfer_fee
                ) / broker_quantity
            elif side == "sell" and broker_quantity > 0:
                expected_cost = (
                    current_quantity * current_cost - net_amount
                ) / broker_quantity
            else:
                expected_cost = Decimal("0")
            if abs(broker_cost - expected_cost) > money_tolerance:
                blockers.append("account_truth_post_trade_cost_basis_mismatch")

    expected_contract = {
        "symbol": symbol,
        "side": side,
        "quantity": decimal_string(quantity),
        "gross_amount": decimal_string(gross),
        "fee": decimal_string(fee),
        "tax": decimal_string(tax),
        "transfer_fee": decimal_string(transfer_fee),
        "net_amount": decimal_string(net_amount),
        "account_truth_source_fingerprint": str(raw.get("source_fingerprint") or ""),
        "non_pass_item_keys": sorted(
            str(item.get("item_key") or "") for item in non_pass
        ),
    }
    return {
        "status": "exact" if not blockers else "blocked",
        "fingerprint": fingerprint(expected_contract),
        "expected": expected_contract,
        "blockers": list(dict.fromkeys(blockers)),
    }


def fill_descriptor(
    event: dict[str, Any],
    *,
    order: dict[str, Any],
    intent: dict[str, Any],
    clearance_id: str,
    clearance_reconciliation_run_id: str,
    review_reconciliation_run_id: str,
    account_truth: dict[str, Any],
) -> dict[str, Any]:
    fill_id = fingerprint(
        {
            "domain": "karkinos.controlled_submission.real_fill.v1",
            "submit_intent_id": intent.get("submit_intent_id"),
            "import_run_id": event.get("import_run_id"),
            "row_fingerprint": event.get("row_fingerprint"),
        }
    )
    return {
        "fill_id": fill_id,
        "broker_event_id": str(event.get("event_id") or ""),
        "broker_row_fingerprint": str(event.get("row_fingerprint") or ""),
        "account_truth_import_run_id": str(event.get("import_run_id") or ""),
        "timestamp": str(event.get("occurred_at") or ""),
        "symbol": str(event.get("symbol") or ""),
        "side": str(order.get("side") or ""),
        "asset_class": str(event.get("asset_class") or ""),
        "fill_price": str(event.get("price") or ""),
        "fill_quantity": str(abs(decimal_value(event.get("quantity")) or Decimal("0"))),
        "fee": str(event.get("fee") or "0"),
        "tax": str(event.get("tax") or "0"),
        "transfer_fee": str(event.get("transfer_fee") or "0"),
        "provider_name": str(account_truth.get("source_type") or "broker_evidence"),
        "metadata": {
            "schema_version": CONTROLLED_SUBMISSION_CLEARANCE_SCHEMA_VERSION,
            "clearance_id": clearance_id,
            "submit_intent_id": str(intent.get("submit_intent_id") or ""),
            "account_truth_import_run_id": str(event.get("import_run_id") or ""),
            "account_truth_source_fingerprint": str(
                account_truth.get("source_fingerprint") or ""
            ),
            "execution_reconciliation_run_id": clearance_reconciliation_run_id,
            "review_reconciliation_run_id": review_reconciliation_run_id,
            "broker_event_id": str(event.get("event_id") or ""),
            "broker_row_fingerprint": str(event.get("row_fingerprint") or ""),
            "broker_order_id": str(event.get("broker_order_id") or ""),
            "client_order_id": str(event.get("client_order_id") or ""),
            "fee": str(event.get("fee") or "0"),
            "tax": str(event.get("tax") or "0"),
            "transfer_fee": str(event.get("transfer_fee") or "0"),
            "production_ledger_mutated": False,
        },
    }


def broker_event_contract(event: Any) -> dict[str, Any]:
    return {
        "import_run_id": str(getattr(event, "import_run_id", "") or ""),
        "row_fingerprint": str(getattr(event, "row_fingerprint", "") or ""),
        "event_id": str(getattr(event, "event_id", "") or ""),
        "event_type": str(getattr(event, "event_type", "") or ""),
        "occurred_at": str(getattr(event, "occurred_at", "") or ""),
        "symbol": str(getattr(event, "symbol", "") or ""),
        "asset_class": str(getattr(event, "asset_class", "") or ""),
        "currency": str(getattr(event, "currency", "") or ""),
        "quantity": str(getattr(event, "quantity", "") or ""),
        "price": str(getattr(event, "price", "") or ""),
        "gross_amount": str(getattr(event, "gross_amount", "") or ""),
        "fee": str(getattr(event, "fee", "") or ""),
        "tax": str(getattr(event, "tax", "") or ""),
        "transfer_fee": str(getattr(event, "transfer_fee", "") or ""),
        "net_amount": str(getattr(event, "net_amount", "") or ""),
        "broker_order_id": str(getattr(event, "broker_order_id", "") or ""),
        "client_order_id": str(getattr(event, "client_order_id", "") or ""),
    }


def terminal_cancel_statement_blockers(
    terminal_lifecycle: dict[str, Any],
    broker_evidence: list[dict[str, Any]],
) -> list[str]:
    """Require partial-cancel statement facts to match lifecycle fill totals."""

    lifecycle_fills = [
        mapping(item)
        for item in terminal_lifecycle.get("lifecycle_fills") or []
        if isinstance(item, dict)
    ]
    if not lifecycle_fills:
        return [
            "controlled_submission_clearance_partial_cancel_lifecycle_fills_missing"
        ]

    def total(rows: list[dict[str, Any]], field: str) -> Decimal:
        return sum(
            (decimal_value(row.get(field)) or Decimal("0") for row in rows),
            Decimal("0"),
        )

    lifecycle_quantity = sum(
        (
            abs(decimal_value(row.get("quantity")) or Decimal("0"))
            for row in lifecycle_fills
        ),
        Decimal("0"),
    )
    statement_quantity = sum(
        (
            abs(decimal_value(row.get("quantity")) or Decimal("0"))
            for row in broker_evidence
        ),
        Decimal("0"),
    )
    lifecycle_gross = sum(
        (
            abs(decimal_value(row.get("quantity")) or Decimal("0"))
            * abs(decimal_value(row.get("price")) or Decimal("0"))
            for row in lifecycle_fills
        ),
        Decimal("0"),
    )
    statement_gross = sum(
        (
            abs(decimal_value(row.get("gross_amount")) or Decimal("0"))
            for row in broker_evidence
        ),
        Decimal("0"),
    )
    blockers: list[str] = []
    comparisons = {
        "quantity": (lifecycle_quantity, statement_quantity),
        "gross_amount": (lifecycle_gross, statement_gross),
        "fee": (total(lifecycle_fills, "fee"), total(broker_evidence, "fee")),
        "tax": (total(lifecycle_fills, "tax"), total(broker_evidence, "tax")),
        "transfer_fee": (
            total(lifecycle_fills, "transfer_fee"),
            total(broker_evidence, "transfer_fee"),
        ),
        "net_amount": (
            total(lifecycle_fills, "net_amount"),
            total(broker_evidence, "net_amount"),
        ),
    }
    for field, (lifecycle_value, statement_value) in comparisons.items():
        if lifecycle_value != statement_value:
            blockers.append(
                f"controlled_submission_clearance_partial_cancel_{field}_mismatch"
            )
    return blockers


def reconciliation_item_contract(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in (
            "id",
            "run_id",
            "order_id",
            "item_status",
            "suggested_action",
            "gateway_event_count",
            "broker_event_count",
            "detail",
            "payload_json",
            "created_at",
        )
    }
