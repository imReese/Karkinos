"""Normalize read-only broker connector facts into account-truth evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from account_truth.broker_connector import (
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerPositionFact,
)
from account_truth.broker_statement import (
    BROKER_STATEMENT_SCHEMA_VERSION,
    BrokerEvidenceEvent,
    BrokerStatementPreview,
    ValidationStatus,
)

BROKER_CONNECTOR_SOURCE_TYPE = "read_only_broker_connector"
BROKER_CONNECTOR_LIMITATIONS = [
    "Read-only broker connector evidence does not mutate the production ledger.",
    "Connector evidence is audit tooling and does not submit broker orders.",
]


def build_broker_connector_evidence_preview(
    snapshot: BrokerConnectorSnapshot,
) -> BrokerStatementPreview:
    """Build a broker-evidence preview from one read-only connector snapshot."""

    event_payloads = _event_payloads(snapshot)
    events = _events_from_payloads(event_payloads)
    return BrokerStatementPreview(
        schema_version=BROKER_STATEMENT_SCHEMA_VERSION,
        source_type=BROKER_CONNECTOR_SOURCE_TYPE,
        generated_at=datetime.now(UTC).isoformat(),
        file_fingerprint=_fingerprint_snapshot(snapshot, event_payloads),
        normalized_columns=(),
        row_count=len(events),
        valid_row_count=len(events),
        invalid_row_count=0,
        duplicate_row_count=sum(1 for event in events if event.is_duplicate),
        validation_status=_validation_status(snapshot, events),
        limitations=_limitations(snapshot),
        events=events,
        errors=[],
    )


def _event_payloads(snapshot: BrokerConnectorSnapshot) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for fill in snapshot.fills:
        payloads.append(_fill_payload(snapshot, fill))
    if snapshot.cash is not None:
        payloads.append(
            {
                "event_id": (
                    f"{snapshot.connector_id}:cash:"
                    f"{snapshot.cash.currency}:{snapshot.captured_at}"
                ),
                "event_type": "cash_snapshot",
                "occurred_at": snapshot.captured_at,
                "settled_at": _date_part(snapshot.captured_at),
                "symbol": "",
                "instrument_name": "",
                "asset_class": "cash",
                "currency": snapshot.cash.currency,
                "quantity": Decimal("0"),
                "price": Decimal("0"),
                "gross_amount": Decimal("0"),
                "fee": Decimal("0"),
                "tax": Decimal("0"),
                "net_amount": Decimal("0"),
                "cash_balance": snapshot.cash.balance,
                "position_quantity": None,
                "cost_basis": None,
                "note": _cash_note(snapshot),
            }
        )
    for position in snapshot.positions:
        payloads.append(_position_payload(snapshot, position))
    return payloads


def _fill_payload(
    snapshot: BrokerConnectorSnapshot,
    fill: BrokerFillFact,
) -> dict[str, Any]:
    side = fill.side.lower().strip()
    return {
        "event_id": f"{snapshot.connector_id}:fill:{fill.fill_id}",
        "event_type": "trade_sell" if side == "sell" else "trade_buy",
        "occurred_at": fill.filled_at,
        "settled_at": _date_part(fill.filled_at),
        "symbol": fill.symbol,
        "instrument_name": "",
        "asset_class": "stock",
        "currency": "CNY",
        "quantity": fill.quantity,
        "price": fill.price,
        "gross_amount": fill.quantity * fill.price,
        "fee": fill.fee,
        "tax": fill.tax,
        "net_amount": fill.net_amount,
        "cash_balance": None,
        "position_quantity": None,
        "cost_basis": None,
        "note": (
            f"Read-only connector fill evidence from {snapshot.connector_id}; "
            f"order_id={fill.order_id}"
        ),
    }


def _position_payload(
    snapshot: BrokerConnectorSnapshot,
    position: BrokerPositionFact,
) -> dict[str, Any]:
    return {
        "event_id": (
            f"{snapshot.connector_id}:position:{position.symbol}:"
            f"{snapshot.captured_at}"
        ),
        "event_type": "position_snapshot",
        "occurred_at": snapshot.captured_at,
        "settled_at": _date_part(snapshot.captured_at),
        "symbol": position.symbol,
        "instrument_name": position.instrument_name,
        "asset_class": position.asset_class,
        "currency": "CNY",
        "quantity": Decimal("0"),
        "price": position.market_price or Decimal("0"),
        "gross_amount": Decimal("0"),
        "fee": Decimal("0"),
        "tax": Decimal("0"),
        "net_amount": Decimal("0"),
        "cash_balance": None,
        "position_quantity": position.quantity,
        "cost_basis": position.cost_basis,
        "note": _position_note(snapshot, position),
    }


def _events_from_payloads(payloads: list[dict[str, Any]]) -> list[BrokerEvidenceEvent]:
    seen: dict[str, int] = {}
    events: list[BrokerEvidenceEvent] = []
    for row_number, payload in enumerate(payloads, start=1):
        row_fingerprint = _fingerprint_payload(payload)
        duplicate_of = seen.get(row_fingerprint)
        if duplicate_of is None:
            seen[row_fingerprint] = row_number
        events.append(
            BrokerEvidenceEvent(
                row_number=row_number,
                row_fingerprint=row_fingerprint,
                event_id=str(payload["event_id"]),
                event_type=str(payload["event_type"]),
                occurred_at=str(payload["occurred_at"]),
                settled_at=str(payload["settled_at"]),
                symbol=str(payload["symbol"]),
                instrument_name=str(payload["instrument_name"]),
                asset_class=str(payload["asset_class"]),
                currency=str(payload["currency"]),
                quantity=_decimal(payload["quantity"]),
                price=_decimal(payload["price"]),
                gross_amount=_decimal(payload["gross_amount"]),
                fee=_decimal(payload["fee"]),
                tax=_decimal(payload["tax"]),
                net_amount=_decimal(payload["net_amount"]),
                cash_balance=_optional_decimal(payload["cash_balance"]),
                position_quantity=_optional_decimal(payload["position_quantity"]),
                cost_basis=_optional_decimal(payload["cost_basis"]),
                note=str(payload["note"]),
                is_duplicate=duplicate_of is not None,
                duplicate_of_row_number=duplicate_of,
            )
        )
    return events


def _validation_status(
    snapshot: BrokerConnectorSnapshot,
    events: list[BrokerEvidenceEvent],
) -> ValidationStatus:
    if snapshot.health.status == "disconnected":
        return "blocked"
    if snapshot.health.status in {"stale", "permission_limited", "incomplete"}:
        return "warning"
    if any(event.is_duplicate for event in events):
        return "warning"
    return "pass"


def _limitations(snapshot: BrokerConnectorSnapshot) -> list[str]:
    limitations = list(BROKER_CONNECTOR_LIMITATIONS)
    limitations.extend(snapshot.limitations)
    limitations.extend(snapshot.health.limitations)
    if snapshot.health.message:
        limitations.append(snapshot.health.message)
    if snapshot.orders:
        limitations.append(
            "Order facts are read-only connector context; reconciliation uses fills, "
            "cash snapshots, and position snapshots."
        )
    return _unique(limitations)


def _fingerprint_snapshot(
    snapshot: BrokerConnectorSnapshot,
    event_payloads: list[dict[str, Any]],
) -> str:
    payload = {
        "source_type": BROKER_CONNECTOR_SOURCE_TYPE,
        "snapshot": _jsonable(asdict(snapshot)),
        "events": [_jsonable(payload) for payload in event_payloads],
    }
    return _fingerprint_json(payload)


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    return _fingerprint_json(_jsonable(payload))


def _fingerprint_json(value: object) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _date_part(value: str) -> str:
    return value.split("T", 1)[0] if "T" in value else value


def _cash_note(snapshot: BrokerConnectorSnapshot) -> str:
    available = snapshot.cash.available if snapshot.cash is not None else None
    if available is None:
        return f"Read-only connector cash snapshot from {snapshot.connector_id}"
    return (
        f"Read-only connector cash snapshot from {snapshot.connector_id}; "
        f"available={format(available, 'f')}"
    )


def _position_note(
    snapshot: BrokerConnectorSnapshot,
    position: BrokerPositionFact,
) -> str:
    available = position.available_quantity
    if available is None:
        return f"Read-only connector position snapshot from {snapshot.connector_id}"
    return (
        f"Read-only connector position snapshot from {snapshot.connector_id}; "
        f"available_quantity={format(available, 'f')}"
    )


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value)


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
