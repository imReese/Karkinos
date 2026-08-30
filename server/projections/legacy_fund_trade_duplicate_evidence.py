"""Fingerprinting and exact pair validation for legacy fund duplicates."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from server.contracts.content_identity import content_fingerprint
from server.persistence.database_serialization import normalize_timestamp
from server.projections.legacy_fund_trade_duplicate_contract import (
    LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE,
    LegacyFundTradeDuplicateCorrectionError,
    legacy_fund_trade_duplicate_error,
)

_CANONICAL_SOURCE = "portfolio_trade"
_REPAIR_FINGERPRINT_SCHEMA_VERSION = (
    "karkinos.legacy_fund_trade_duplicate_repair_fingerprint.v1"
)
_GROUP_FINGERPRINT_SCHEMA_VERSION = (
    "karkinos.legacy_fund_trade_duplicate_group_fingerprint.v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TRADE_REF_RE = re.compile(r"^trade:([1-9][0-9]*)$")
_NUMERIC_FIELDS = frozenset(
    {
        "amount",
        "quantity",
        "price",
        "commission",
        "gross_amount",
        "net_cash_impact",
        "estimated_commission",
        "estimated_net_cash_impact",
    }
)
_TIMESTAMP_FIELDS = frozenset({"timestamp", "created_at", "settled_at"})
_JSON_FIELDS = frozenset(
    {
        "fee_breakdown_json",
        "estimated_fee_breakdown_json",
        "correction_payload_json",
    }
)


def legacy_fund_trade_economic_identity(row: dict[str, Any]) -> dict[str, str]:
    """Return the normalized financial identity required for a safe pair."""

    try:
        timestamp = normalize_timestamp(str(row.get("timestamp") or ""))
        values = {
            field: _required_decimal(row, field)
            for field in (
                "amount",
                "quantity",
                "price",
                "commission",
                "gross_amount",
                "net_cash_impact",
            )
        }
    except (InvalidOperation, TypeError, ValueError):
        raise _error("economic_identity_invalid") from None

    entry_type = str(row.get("entry_type") or "").strip().lower()
    direction = str(row.get("direction") or "").strip().lower()
    symbol = str(row.get("symbol") or "").strip()
    asset_class = str(row.get("asset_class") or "stock").strip().lower()
    if not symbol or entry_type != "trade_buy" or direction != "buy":
        raise _error("not_fund_buy")
    if asset_class != "fund":
        raise _error("not_fund_buy")
    if values["quantity"] <= 0 or values["price"] <= 0:
        raise _error("economic_identity_invalid")
    if values["commission"] < 0:
        raise _error("economic_identity_invalid")
    # Historical SQLite REAL multiplication is not decimal-exact.  The repair
    # therefore binds the persisted quantity, price, and gross fields exactly
    # across both rows, while checking the already-persisted amount/net
    # identities without introducing a tolerance.
    if values["amount"] != values["gross_amount"]:
        raise _error("economic_identity_invalid")
    if values["net_cash_impact"] != -(values["gross_amount"] + values["commission"]):
        raise _error("economic_identity_invalid")

    return {
        "entry_type": entry_type,
        "timestamp": timestamp,
        "symbol": symbol,
        "direction": direction,
        "amount": decimal_identity(values["amount"]),
        "quantity": decimal_identity(values["quantity"]),
        "price": decimal_identity(values["price"]),
        "commission": decimal_identity(values["commission"]),
        "gross_amount": decimal_identity(values["gross_amount"]),
        "net_cash_impact": decimal_identity(values["net_cash_impact"]),
        "asset_class": asset_class,
    }


def legacy_fund_trade_ledger_row_fingerprint(row: dict[str, Any]) -> str:
    """Bind a correction to the complete persisted source row, not only money."""

    normalized: dict[str, Any] = {}
    for key, value in sorted(dict(row).items()):
        if key in _NUMERIC_FIELDS:
            normalized[key] = (
                None if value is None else decimal_identity(as_finite_decimal(value))
            )
        elif key in _TIMESTAMP_FIELDS and value not in {None, ""}:
            try:
                normalized[key] = normalize_timestamp(str(value))
            except ValueError:
                normalized[key] = str(value)
        elif key in _JSON_FIELDS and value not in {None, ""}:
            normalized[key] = _json_value(value)
        else:
            normalized[key] = value
    return content_fingerprint(normalized)


def legacy_fund_trade_duplicate_group_fingerprint(
    *,
    ledger_rows: list[dict[str, Any]],
    pair_entry_ids: Sequence[tuple[int, int]],
) -> str:
    """Build one deterministic identity from complete paired-row evidence."""

    rows_by_id = ledger_rows_by_id(ledger_rows)
    evidence = _build_pair_evidence(rows_by_id, pair_entry_ids)
    symbols = {
        legacy_fund_trade_economic_identity(rows_by_id[manual_id])["symbol"]
        for manual_id, _ in normalize_pair_entry_ids(pair_entry_ids)
    }
    if len(symbols) != 1:
        raise _error("symbol_scope_invalid")
    return content_fingerprint(
        {
            "schema_version": _GROUP_FINGERPRINT_SCHEMA_VERSION,
            "pair_evidence": evidence,
        }
    )


def legacy_fund_trade_duplicate_repair_fingerprint(
    *,
    ledger_rows: list[dict[str, Any]],
    batch_pair_entry_ids: Sequence[tuple[int, int]],
    batch_group_fingerprints: Sequence[str],
) -> str:
    """Bind a repair to the full immutable pre-repair ledger and exact pairs."""

    rows_by_id = ledger_rows_by_id(ledger_rows)
    pair_evidence = _build_pair_evidence(rows_by_id, batch_pair_entry_ids)
    groups = sorted(set(batch_group_fingerprints))
    if not groups or len(groups) != len(batch_group_fingerprints):
        raise _error("batch_scope_invalid")
    if any(not _SHA256_RE.fullmatch(value) for value in groups):
        raise _error("batch_scope_invalid")
    ledger_evidence = [
        {
            "ledger_entry_id": row_id,
            "row_fingerprint": legacy_fund_trade_ledger_row_fingerprint(row),
        }
        for row_id, row in sorted(rows_by_id.items())
    ]
    return content_fingerprint(
        {
            "schema_version": _REPAIR_FINGERPRINT_SCHEMA_VERSION,
            "ledger_cutoff_id": max(rows_by_id, default=0),
            "ledger_entry_count": len(rows_by_id),
            "ledger_evidence": ledger_evidence,
            "pair_evidence": pair_evidence,
            "group_fingerprints": groups,
        }
    )


def validate_exact_pair(
    manual: dict[str, Any],
    canonical: dict[str, Any],
) -> dict[str, str]:
    if manual.get("source") != LEGACY_FUND_TRADE_DUPLICATE_ORIGINAL_SOURCE:
        raise _error("manual_lineage_invalid")
    if canonical.get("source") != _CANONICAL_SOURCE:
        raise _error("canonical_lineage_invalid")
    if not _TRADE_REF_RE.fullmatch(str(canonical.get("source_ref") or "")):
        raise _error("canonical_lineage_invalid")
    manual_identity = legacy_fund_trade_economic_identity(manual)
    canonical_identity = legacy_fund_trade_economic_identity(canonical)
    if manual_identity != canonical_identity:
        raise _error("economic_pair_drifted")
    return manual_identity


def _build_pair_evidence(
    rows_by_id: dict[int, dict[str, Any]],
    pair_entry_ids: Sequence[tuple[int, int]],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for manual_id, canonical_id in normalize_pair_entry_ids(pair_entry_ids):
        manual = rows_by_id.get(manual_id)
        canonical = rows_by_id.get(canonical_id)
        if manual is None or canonical is None:
            raise _error("paired_entry_missing")
        identity = validate_exact_pair(manual, canonical)
        evidence.append(build_pair_evidence_item(manual, canonical, identity))
    return evidence


def build_pair_evidence_item(
    manual: dict[str, Any],
    canonical: dict[str, Any],
    identity: dict[str, str],
) -> dict[str, Any]:
    return {
        "manual_ledger_entry_id": require_positive_int(manual.get("id")),
        "canonical_ledger_entry_id": require_positive_int(canonical.get("id")),
        "economic_fingerprint": content_fingerprint(identity),
        "manual_row_fingerprint": legacy_fund_trade_ledger_row_fingerprint(manual),
        "canonical_row_fingerprint": legacy_fund_trade_ledger_row_fingerprint(
            canonical
        ),
    }


def normalize_pair_entry_ids(
    pair_entry_ids: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    pairs = [
        (require_positive_int(left), require_positive_int(right))
        for left, right in pair_entry_ids
    ]
    normalized = sorted(set(pairs))
    if not normalized or len(normalized) != len(pairs):
        raise _error("pair_scope_invalid")
    manual_ids = [left for left, _ in normalized]
    canonical_ids = [right for _, right in normalized]
    if len(set(manual_ids)) != len(manual_ids):
        raise _error("original_scope_overlapped")
    if len(set(canonical_ids)) != len(canonical_ids):
        raise _error("canonical_scope_overlapped")
    return normalized


def ledger_rows_by_id(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        row_id = require_positive_int(row.get("id"))
        if row_id in result:
            raise _error("duplicate_ledger_id")
        result[row_id] = dict(row)
    return result


def _required_decimal(row: dict[str, Any], field: str) -> Decimal:
    if row.get(field) is None:
        raise _error("economic_identity_invalid")
    return as_finite_decimal(row[field])


def as_finite_decimal(value: Any) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite():
        raise InvalidOperation
    return number


def decimal_identity(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def require_positive_int(value: Any) -> int:
    if isinstance(value, bool):
        raise _error("integer_identity_invalid")
    parsed = int(value)
    if parsed <= 0 or str(parsed) != str(value):
        raise _error("integer_identity_invalid")
    return parsed


def require_sha256(value: str, field: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise _error(f"{field}_invalid")


def _error(suffix: str) -> LegacyFundTradeDuplicateCorrectionError:
    return legacy_fund_trade_duplicate_error(suffix)


__all__ = [
    "as_finite_decimal",
    "build_pair_evidence_item",
    "decimal_identity",
    "ledger_rows_by_id",
    "legacy_fund_trade_duplicate_group_fingerprint",
    "legacy_fund_trade_duplicate_repair_fingerprint",
    "legacy_fund_trade_economic_identity",
    "legacy_fund_trade_ledger_row_fingerprint",
    "normalize_pair_entry_ids",
    "require_positive_int",
    "require_sha256",
    "validate_exact_pair",
]
