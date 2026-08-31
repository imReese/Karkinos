"""Typed commands for idempotent canonical-ledger mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from server.contracts.content_identity import content_fingerprint

LEDGER_APPEND_SCHEMA_VERSION = "karkinos.ledger.append.v1"
LEDGER_SETTLEMENT_SCHEMA_VERSION = "karkinos.ledger.trade_settlement.v1"
FEE_BREAKDOWN_COMPONENT_KEYS = (
    "commission",
    "stamp_tax",
    "transfer_fee",
    "other_fees",
)
FEE_BREAKDOWN_KEYS = frozenset((*FEE_BREAKDOWN_COMPONENT_KEYS, "total_fee"))
_SUPPORTED_ENTRY_TYPES = {
    "cash_deposit",
    "cash_interest",
    "cash_withdrawal",
    "dividend",
    "fee",
    "manual_adjustment",
    "trade_buy",
    "trade_sell",
}


@dataclass(frozen=True, slots=True)
class LedgerEntryDraft:
    """Uncommitted ledger fact carried by an append command."""

    entry_type: str
    timestamp: str
    amount: float | None = None
    symbol: str | None = None
    direction: str | None = None
    quantity: float | None = None
    price: float | None = None
    commission: float = 0.0
    gross_amount: float | None = None
    net_cash_impact: float | None = None
    fee_breakdown_json: str | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None
    cost_basis_method: str | None = None
    correction_payload_json: str | None = None
    asset_class: str = "stock"
    note: str = ""
    source: str = "manual"
    source_ref: str | None = None
    created_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("entry_type", "timestamp", "source", "asset_class"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        _validate_entry_draft(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_type": self.entry_type,
            "timestamp": self.timestamp,
            "amount": self.amount,
            "symbol": self.symbol,
            "direction": self.direction,
            "quantity": self.quantity,
            "price": self.price,
            "commission": self.commission,
            "gross_amount": self.gross_amount,
            "net_cash_impact": self.net_cash_impact,
            "fee_breakdown_json": self.fee_breakdown_json,
            "fee_rule_id": self.fee_rule_id,
            "fee_rule_version": self.fee_rule_version,
            "cost_basis_method": self.cost_basis_method,
            "correction_payload_json": self.correction_payload_json,
            "asset_class": self.asset_class,
            "note": self.note,
            "source": self.source,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class LedgerAppendCommand:
    """Append one immutable ledger fact under an explicit operator request."""

    operator_id: str
    request_id: str
    entry: LedgerEntryDraft
    schema_version: str = LEDGER_APPEND_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_identity(self.operator_id, self.request_id, self.schema_version)

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "request_id": self.request_id,
            "entry": self.entry.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LedgerTradeSettlementCommand:
    """CAS-bound broker settlement confirmation for one existing trade."""

    operator_id: str
    request_id: str
    entry_id: int
    expected_entry_fingerprint: str
    commission: float
    net_cash_impact: float
    fee_breakdown_json: str
    settled_at: str
    settlement_source: str
    settlement_source_ref: str
    settlement_note: str = ""
    fee_rule_id: str = "broker_settlement_confirmation"
    fee_rule_version: str = "broker_settlement_confirmation.v1"
    schema_version: str = LEDGER_SETTLEMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_identity(self.operator_id, self.request_id, self.schema_version)
        if isinstance(self.entry_id, bool) or not isinstance(self.entry_id, int):
            raise ValueError("entry_id must be a positive integer")
        if self.entry_id <= 0:
            raise ValueError("entry_id must be positive")
        for name in (
            "expected_entry_fingerprint",
            "fee_breakdown_json",
            "settled_at",
            "settlement_source",
            "settlement_source_ref",
            "fee_rule_id",
            "fee_rule_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must not be empty")
        if not _is_sha256(self.expected_entry_fingerprint):
            raise ValueError("expected_entry_fingerprint must be a SHA-256 digest")
        commission = _decimal("commission", self.commission)
        if commission < 0:
            raise ValueError("commission must not be negative")
        _decimal("net_cash_impact", self.net_cash_impact)
        validate_fee_breakdown(self.fee_breakdown_json, commission=commission)

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_id": self.operator_id,
            "request_id": self.request_id,
            "entry_id": self.entry_id,
            "expected_entry_fingerprint": self.expected_entry_fingerprint,
            "commission": self.commission,
            "net_cash_impact": self.net_cash_impact,
            "fee_breakdown_json": self.fee_breakdown_json,
            "settled_at": self.settled_at,
            "settlement_source": self.settlement_source,
            "settlement_source_ref": self.settlement_source_ref,
            "settlement_note": self.settlement_note,
            "fee_rule_id": self.fee_rule_id,
            "fee_rule_version": self.fee_rule_version,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class LedgerMutationResult:
    """Committed mutation identity returned for both first write and replay."""

    request_id: str
    operator_id: str
    request_fingerprint: str
    entry: dict[str, Any]
    entry_fingerprint: str
    valuation_snapshot_id: str
    valuation_snapshot_status: str
    replayed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operator_id": self.operator_id,
            "request_fingerprint": self.request_fingerprint,
            "entry": self.entry,
            "entry_fingerprint": self.entry_fingerprint,
            "valuation_snapshot_id": self.valuation_snapshot_id,
            "valuation_snapshot_status": self.valuation_snapshot_status,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any], *, replayed: bool
    ) -> LedgerMutationResult:
        entry = payload.get("entry")
        if not isinstance(entry, dict):
            raise RuntimeError("stored ledger mutation result has no entry")
        return cls(
            request_id=str(payload["request_id"]),
            operator_id=str(payload["operator_id"]),
            request_fingerprint=str(payload["request_fingerprint"]),
            entry=dict(entry),
            entry_fingerprint=str(payload["entry_fingerprint"]),
            valuation_snapshot_id=str(payload["valuation_snapshot_id"]),
            valuation_snapshot_status=str(payload["valuation_snapshot_status"]),
            replayed=replayed,
        )


class LedgerMutationConflict(ValueError):
    """Raised when an append or CAS mutation cannot be applied safely."""


def validate_trade_settlement_economics(
    command: LedgerTradeSettlementCommand,
    entry: Mapping[str, Any],
) -> None:
    """Fail closed unless settled cash equals gross less exact fee evidence."""

    entry_type = str(entry.get("entry_type") or "")
    if entry_type not in {"trade_buy", "trade_sell"}:
        raise ValueError("only trade ledger entries can be settled")
    gross_value = entry.get("gross_amount")
    if gross_value is None:
        quantity = _decimal("quantity", entry.get("quantity"))
        price = _decimal("price", entry.get("price"))
        gross = quantity * price
    else:
        gross = _decimal("gross_amount", gross_value)
    if gross <= 0:
        raise ValueError("trade gross_amount must be positive")
    fee_breakdown = validate_fee_breakdown(
        command.fee_breakdown_json,
        commission=_decimal("commission", command.commission),
    )
    total_fee = _decimal("fee_breakdown.total_fee", fee_breakdown["total_fee"])
    expected_net = (
        -(gross + total_fee) if entry_type == "trade_buy" else gross - total_fee
    )
    actual_net = _decimal("net_cash_impact", command.net_cash_impact)
    if not _nearly_equal(actual_net, expected_net):
        raise ValueError(
            "settled net_cash_impact does not match trade gross amount and fees"
        )


def ledger_entry_state_fingerprint(entry: Mapping[str, Any]) -> str:
    """Fingerprint the complete persisted state used by settlement CAS."""

    payload = {
        "id": entry.get("id"),
        "entry_type": entry.get("entry_type"),
        "timestamp": entry.get("timestamp"),
        "amount": entry.get("amount"),
        "symbol": entry.get("symbol"),
        "direction": entry.get("direction"),
        "quantity": entry.get("quantity"),
        "price": entry.get("price"),
        "commission": entry.get("commission"),
        "gross_amount": entry.get("gross_amount"),
        "net_cash_impact": entry.get("net_cash_impact"),
        "fee_breakdown": _json_value(
            entry.get("fee_breakdown", entry.get("fee_breakdown_json"))
        ),
        "fee_rule_id": entry.get("fee_rule_id"),
        "fee_rule_version": entry.get("fee_rule_version"),
        "estimated_commission": entry.get("estimated_commission"),
        "estimated_net_cash_impact": entry.get("estimated_net_cash_impact"),
        "estimated_fee_breakdown": _json_value(
            entry.get(
                "estimated_fee_breakdown",
                entry.get("estimated_fee_breakdown_json"),
            )
        ),
        "estimated_fee_rule_id": entry.get("estimated_fee_rule_id"),
        "estimated_fee_rule_version": entry.get("estimated_fee_rule_version"),
        "settlement_status": entry.get("settlement_status"),
        "settled_at": entry.get("settled_at"),
        "settlement_source": entry.get("settlement_source"),
        "settlement_source_ref": entry.get("settlement_source_ref"),
        "settlement_note": entry.get("settlement_note") or "",
        "cost_basis_method": entry.get("cost_basis_method"),
        "correction_payload": _json_value(
            entry.get("correction_payload", entry.get("correction_payload_json"))
        ),
        "asset_class": entry.get("asset_class") or "stock",
        "note": entry.get("note") or "",
        "source": entry.get("source") or "manual",
        "source_ref": entry.get("source_ref"),
        "created_at": entry.get("created_at"),
    }
    return content_fingerprint(payload)


def _validate_identity(operator_id: str, request_id: str, schema_version: str) -> None:
    for name, value in (
        ("operator_id", operator_id),
        ("request_id", request_id),
        ("schema_version", schema_version),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be empty")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _json_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _validate_entry_draft(entry: LedgerEntryDraft) -> None:
    if entry.entry_type not in _SUPPORTED_ENTRY_TYPES:
        raise ValueError(f"unsupported ledger entry_type: {entry.entry_type}")
    numeric_fields = (
        "amount",
        "quantity",
        "price",
        "commission",
        "gross_amount",
        "net_cash_impact",
    )
    for name in numeric_fields:
        value = getattr(entry, name)
        if value is not None:
            _decimal(name, value)
    commission = _decimal("commission", entry.commission)
    if commission < 0:
        raise ValueError("commission must not be negative")
    if entry.correction_payload_json is not None:
        _json_object("correction_payload_json", entry.correction_payload_json)

    if entry.entry_type in {"trade_buy", "trade_sell"}:
        _validate_trade_entry(entry, commission=commission)
    elif entry.entry_type in {"cash_deposit", "cash_withdrawal"}:
        if _decimal("amount", entry.amount) <= 0:
            raise ValueError("cash ledger amount must be positive")
        if entry.asset_class != "cash":
            raise ValueError("cash ledger entries must use asset_class=cash")
    elif entry.entry_type == "dividend":
        if _decimal("amount", entry.amount) <= 0:
            raise ValueError("dividend amount must be positive")
        if not str(entry.symbol or "").strip():
            raise ValueError("dividend symbol must not be empty")
    elif entry.entry_type in {"cash_interest", "fee"}:
        if _decimal("amount", entry.amount) <= 0:
            raise ValueError(f"{entry.entry_type} amount must be positive")
        if entry.asset_class != "cash":
            raise ValueError(f"{entry.entry_type} entries must use asset_class=cash")
    elif entry.entry_type == "manual_adjustment":
        _validate_adjustment_entry(entry)


def _validate_trade_entry(entry: LedgerEntryDraft, *, commission: Decimal) -> None:
    direction = entry.entry_type.removeprefix("trade_")
    if entry.direction != direction:
        raise ValueError("trade direction must match entry_type")
    if not str(entry.symbol or "").strip():
        raise ValueError("trade symbol must not be empty")
    quantity = _decimal("quantity", entry.quantity)
    price = _decimal("price", entry.price)
    amount = _decimal("amount", entry.amount)
    gross = _decimal("gross_amount", entry.gross_amount)
    net_cash = _decimal("net_cash_impact", entry.net_cash_impact)
    if quantity <= 0:
        raise ValueError("trade quantity must be positive")
    if price <= 0:
        raise ValueError("trade price must be positive")
    expected_gross = quantity * price
    if not _nearly_equal(gross, expected_gross):
        raise ValueError("trade gross_amount must equal quantity multiplied by price")
    if not _nearly_equal(amount, gross):
        raise ValueError("trade amount must equal gross_amount")
    total_fee = commission
    if entry.fee_breakdown_json is not None:
        fee_breakdown = validate_fee_breakdown(
            entry.fee_breakdown_json,
            commission=commission,
        )
        total_fee = _decimal("fee_breakdown.total_fee", fee_breakdown["total_fee"])
    expected_net = -(gross + total_fee) if direction == "buy" else gross - total_fee
    if not _nearly_equal(net_cash, expected_net):
        raise ValueError(
            "trade net_cash_impact must equal signed gross amount and total fees"
        )


def _validate_adjustment_entry(entry: LedgerEntryDraft) -> None:
    amount = None if entry.amount is None else _decimal("amount", entry.amount)
    quantity = None if entry.quantity is None else _decimal("quantity", entry.quantity)
    if (amount is None or amount == 0) and (quantity is None or quantity == 0):
        raise ValueError("manual adjustment requires a non-zero amount or quantity")
    if entry.price is not None and _decimal("price", entry.price) <= 0:
        raise ValueError("manual adjustment price must be positive")
    if (quantity is not None or entry.price is not None) and not str(
        entry.symbol or ""
    ).strip():
        raise ValueError("quantity adjustment symbol must not be empty")


def validate_fee_breakdown(
    value: str,
    *,
    commission: Decimal,
) -> dict[str, Any]:
    payload = _json_object("fee_breakdown_json", value)
    if "total_fee" not in payload:
        raise ValueError("fee_breakdown_json must include total_fee")
    total_fee = _decimal("fee_breakdown.total_fee", payload["total_fee"])
    if total_fee < 0:
        raise ValueError("fee_breakdown total_fee must not be negative")
    component_total = Decimal("0")
    component_found = False
    for name in FEE_BREAKDOWN_COMPONENT_KEYS:
        if name not in payload:
            continue
        component = _decimal(f"fee_breakdown.{name}", payload[name])
        if component < 0:
            raise ValueError(f"fee_breakdown {name} must not be negative")
        component_total += component
        component_found = True
        if name == "commission" and not _nearly_equal(component, commission):
            raise ValueError("fee_breakdown commission does not match commission")
    if component_found and not _nearly_equal(component_total, total_fee):
        raise ValueError("fee_breakdown components do not sum to total_fee")
    if total_fee + _TOLERANCE < commission:
        raise ValueError("fee_breakdown total_fee must include commission")
    return payload


def _json_object(name: str, value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise ValueError(f"{name} must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be a JSON object")
    return payload


def _decimal(name: str, value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if not decimal_value.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return decimal_value


_TOLERANCE = Decimal("0.005")


def _nearly_equal(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= _TOLERANCE


__all__ = [
    "FEE_BREAKDOWN_COMPONENT_KEYS",
    "FEE_BREAKDOWN_KEYS",
    "LEDGER_APPEND_SCHEMA_VERSION",
    "LEDGER_SETTLEMENT_SCHEMA_VERSION",
    "LedgerAppendCommand",
    "LedgerEntryDraft",
    "LedgerMutationConflict",
    "LedgerMutationResult",
    "LedgerTradeSettlementCommand",
    "ledger_entry_state_fingerprint",
    "validate_fee_breakdown",
    "validate_trade_settlement_economics",
]
