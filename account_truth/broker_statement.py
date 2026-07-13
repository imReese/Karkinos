"""Canonical broker statement CSV preview parsing.

The preview parser deliberately returns broker-evidence objects only. It does
not write production ledger entries or mutate portfolio state.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Literal

BROKER_STATEMENT_SCHEMA_VERSION = "karkinos.broker_statement.v2"
BROKER_STATEMENT_SOURCE_TYPE = "canonical_broker_statement_csv"

BROKER_STATEMENT_EVENT_TYPES = (
    "trade_buy",
    "trade_sell",
    "dividend",
    "fee",
    "tax",
    "transfer_in",
    "transfer_out",
    "position_snapshot",
    "cash_snapshot",
)

BROKER_STATEMENT_REQUIRED_COLUMNS = (
    "event_id",
    "event_type",
    "occurred_at",
    "settled_at",
    "symbol",
    "instrument_name",
    "asset_class",
    "currency",
    "quantity",
    "price",
    "gross_amount",
    "fee",
    "tax",
    "net_amount",
    "cash_balance",
    "position_quantity",
    "cost_basis",
    "note",
)
BROKER_STATEMENT_OPTIONAL_COLUMNS = (
    "transfer_fee",
    "cost_basis_method",
    "broker_order_id",
    "client_order_id",
)

BROKER_STATEMENT_LIMITATIONS = [
    "Import preview is broker evidence only; it does not mutate the production ledger.",
    "Order identifiers are evidence fields only; they do not authorize broker writes.",
    "Synthetic examples are safe for tests and docs, but real broker exports must stay local.",
]

_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_DECIMAL_COLUMNS = {
    "quantity",
    "price",
    "gross_amount",
    "fee",
    "tax",
    "net_amount",
    "cash_balance",
    "position_quantity",
    "cost_basis",
    "transfer_fee",
}
_SYMBOL_REQUIRED_EVENT_TYPES = {
    "trade_buy",
    "trade_sell",
    "dividend",
    "position_snapshot",
}


ValidationStatus = Literal["pass", "warning", "blocked"]


@dataclass(frozen=True)
class BrokerStatementValidationError:
    row_number: int | None
    code: str
    message: str


@dataclass(frozen=True)
class BrokerEvidenceEvent:
    row_number: int
    row_fingerprint: str
    event_id: str
    event_type: str
    occurred_at: str
    settled_at: str
    symbol: str
    instrument_name: str
    asset_class: str
    currency: str
    quantity: Decimal
    price: Decimal
    gross_amount: Decimal
    fee: Decimal
    tax: Decimal
    net_amount: Decimal
    cash_balance: Decimal | None
    position_quantity: Decimal | None
    cost_basis: Decimal | None
    note: str
    is_duplicate: bool = False
    duplicate_of_row_number: int | None = None
    transfer_fee: Decimal = Decimal("0")
    cost_basis_method: str = ""
    broker_order_id: str = ""
    client_order_id: str = ""


@dataclass(frozen=True)
class BrokerStatementPreview:
    schema_version: str
    source_type: str
    generated_at: str
    file_fingerprint: str
    normalized_columns: tuple[str, ...]
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    duplicate_row_count: int
    validation_status: ValidationStatus
    limitations: list[str] = field(default_factory=list)
    events: list[BrokerEvidenceEvent] = field(default_factory=list)
    errors: list[BrokerStatementValidationError] = field(default_factory=list)


def parse_broker_statement_csv(
    content: str | bytes,
    *,
    source_type: str = BROKER_STATEMENT_SOURCE_TYPE,
) -> BrokerStatementPreview:
    """Parse a canonical broker statement CSV into a read-only preview."""

    raw_text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    file_fingerprint = _fingerprint_bytes(raw_text.encode("utf-8"))
    generated_at = datetime.now(UTC).isoformat()
    reader = csv.DictReader(StringIO(raw_text))
    columns = tuple((reader.fieldnames or []))
    missing_columns = [
        column for column in BROKER_STATEMENT_REQUIRED_COLUMNS if column not in columns
    ]
    if missing_columns:
        return BrokerStatementPreview(
            schema_version=BROKER_STATEMENT_SCHEMA_VERSION,
            source_type=source_type,
            generated_at=generated_at,
            file_fingerprint=file_fingerprint,
            normalized_columns=columns,
            row_count=0,
            valid_row_count=0,
            invalid_row_count=0,
            duplicate_row_count=0,
            validation_status="blocked",
            limitations=list(BROKER_STATEMENT_LIMITATIONS),
            errors=[
                BrokerStatementValidationError(
                    row_number=None,
                    code="missing_required_columns",
                    message=(
                        "missing required columns: "
                        + ", ".join(sorted(missing_columns))
                    ),
                )
            ],
        )

    events: list[BrokerEvidenceEvent] = []
    errors: list[BrokerStatementValidationError] = []
    seen_rows: dict[str, int] = {}
    duplicate_count = 0
    row_count = 0
    invalid_count = 0

    for index, raw_row in enumerate(reader, start=2):
        row_count += 1
        row = _normalize_raw_row(raw_row)
        row_errors = _validate_row(row, index)
        if row_errors:
            invalid_count += 1
            errors.extend(row_errors)
            continue

        row_fingerprint = _fingerprint_row(row)
        duplicate_of = seen_rows.get(row_fingerprint)
        if duplicate_of is not None:
            duplicate_count += 1
        else:
            seen_rows[row_fingerprint] = index

        events.append(
            BrokerEvidenceEvent(
                row_number=index,
                row_fingerprint=row_fingerprint,
                event_id=row["event_id"],
                event_type=row["event_type"],
                occurred_at=row["occurred_at"],
                settled_at=row["settled_at"],
                symbol=row["symbol"],
                instrument_name=row["instrument_name"],
                asset_class=row["asset_class"],
                currency=row["currency"],
                quantity=_required_decimal(row["quantity"]),
                price=_required_decimal(row["price"]),
                gross_amount=_required_decimal(row["gross_amount"]),
                fee=_required_decimal(row["fee"]),
                tax=_required_decimal(row["tax"]),
                net_amount=_required_decimal(row["net_amount"]),
                cash_balance=_optional_decimal(row["cash_balance"]),
                position_quantity=_optional_decimal(row["position_quantity"]),
                cost_basis=_optional_decimal(row["cost_basis"]),
                note=row["note"],
                is_duplicate=duplicate_of is not None,
                duplicate_of_row_number=duplicate_of,
                transfer_fee=_optional_decimal(row["transfer_fee"]) or Decimal("0"),
                cost_basis_method=row["cost_basis_method"],
                broker_order_id=row["broker_order_id"],
                client_order_id=row["client_order_id"],
            )
        )

    return BrokerStatementPreview(
        schema_version=BROKER_STATEMENT_SCHEMA_VERSION,
        source_type=source_type,
        generated_at=generated_at,
        file_fingerprint=file_fingerprint,
        normalized_columns=columns,
        row_count=row_count,
        valid_row_count=len(events),
        invalid_row_count=invalid_count,
        duplicate_row_count=duplicate_count,
        validation_status=_validation_status(errors, duplicate_count),
        limitations=list(BROKER_STATEMENT_LIMITATIONS),
        events=events,
        errors=errors,
    )


def _normalize_raw_row(raw_row: dict[str, str | None]) -> dict[str, str]:
    return {
        column: (raw_row.get(column) or "").strip()
        for column in BROKER_STATEMENT_REQUIRED_COLUMNS
        + BROKER_STATEMENT_OPTIONAL_COLUMNS
    }


def _validate_row(
    row: dict[str, str],
    row_number: int,
) -> list[BrokerStatementValidationError]:
    errors: list[BrokerStatementValidationError] = []
    event_type = row["event_type"]

    if not row["event_id"]:
        errors.append(
            BrokerStatementValidationError(
                row_number=row_number,
                code="missing_event_id",
                message="event_id is required",
            )
        )
    if event_type not in BROKER_STATEMENT_EVENT_TYPES:
        errors.append(
            BrokerStatementValidationError(
                row_number=row_number,
                code="unsupported_event_type",
                message=f"unsupported event_type: {event_type or '<blank>'}",
            )
        )
    if event_type in _SYMBOL_REQUIRED_EVENT_TYPES and not row["symbol"]:
        errors.append(
            BrokerStatementValidationError(
                row_number=row_number,
                code="missing_symbol",
                message=f"symbol is required for {event_type}",
            )
        )

    for column in ("broker_order_id", "client_order_id"):
        if row[column] and not _ORDER_ID_PATTERN.fullmatch(row[column]):
            errors.append(
                BrokerStatementValidationError(
                    row_number=row_number,
                    code="invalid_order_identity",
                    message=(
                        f"{column} must be a safe 1-128 character broker identity"
                    ),
                )
            )

    for column in _DECIMAL_COLUMNS:
        if row[column] and _optional_decimal(row[column]) is None:
            errors.append(
                BrokerStatementValidationError(
                    row_number=row_number,
                    code="invalid_decimal",
                    message=f"{column} must be a valid decimal",
                )
            )

    for column in (
        "quantity",
        "price",
        "gross_amount",
        "fee",
        "tax",
        "net_amount",
    ):
        if not row[column]:
            errors.append(
                BrokerStatementValidationError(
                    row_number=row_number,
                    code="missing_decimal",
                    message=f"{column} is required",
                )
            )

    return errors


def _validation_status(
    errors: list[BrokerStatementValidationError],
    duplicate_count: int,
) -> ValidationStatus:
    if errors:
        return "blocked"
    if duplicate_count:
        return "warning"
    return "pass"


def _required_decimal(value: str) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ValueError(f"invalid required decimal: {value!r}")
    return parsed


def _optional_decimal(value: str) -> Decimal | None:
    if value == "":
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _fingerprint_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fingerprint_row(row: dict[str, str]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _fingerprint_bytes(payload.encode("utf-8"))
