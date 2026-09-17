"""Exact decimal contracts for authoritative financial values."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, TypeAlias

MAX_SIGNIFICANT_DIGITS = 38
MAX_FRACTIONAL_DIGITS = 18
EXACT_DECIMAL_WRITE_PROVENANCE = "exact_decimal_write_v1"
LEGACY_REAL_BACKFILL_PROVENANCE = "legacy_real_backfill_v1"
DEFAULT_CURRENCY_CODE = "CNY"
FinancialValueInput: TypeAlias = Decimal | int | float | str


def decimal_value(
    value: object | None,
    *,
    field: str,
    allow_none: bool = False,
) -> Decimal | None:
    """Parse a finite bounded decimal without routing through binary arithmetic."""

    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field} must be a finite decimal")
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite decimal")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a finite decimal") from None
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    if parsed == 0:
        parsed = Decimal("0")
    sign, digits, exponent = parsed.as_tuple()
    del sign
    significant = len(digits) + max(exponent, 0)
    fractional = max(-exponent, 0)
    if significant > MAX_SIGNIFICANT_DIGITS or fractional > MAX_FRACTIONAL_DIGITS:
        raise ValueError(
            f"{field} exceeds decimal({MAX_SIGNIFICANT_DIGITS},{MAX_FRACTIONAL_DIGITS})"
        )
    return parsed


def decimal_text(
    value: object | None,
    *,
    field: str,
    allow_none: bool = False,
) -> str | None:
    parsed = decimal_value(value, field=field, allow_none=allow_none)
    if parsed is None:
        return None
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def decimal_storage_pair(
    value: object | None,
    *,
    field: str,
    allow_none: bool = False,
) -> tuple[float | None, str | None]:
    text = decimal_text(value, field=field, allow_none=allow_none)
    if text is None:
        return None, None
    return real_projection(text, field=field), text


def real_projection(
    value: object | None,
    *,
    field: str,
    allow_none: bool = False,
) -> float | None:
    parsed = decimal_value(value, field=field, allow_none=allow_none)
    if parsed is None:
        return None
    projected = float(parsed)
    if not math.isfinite(projected):
        raise ValueError(f"{field} cannot be represented by the legacy REAL projection")
    return projected


def decimal_from_mapping(
    row: Mapping[str, Any] | Any,
    field: str,
    *,
    allow_none: bool = False,
) -> Decimal | None:
    provenance = _row_value(row, "decimal_provenance")
    legacy = _row_value(row, field)
    exact = _row_value(row, f"{field}_decimal")
    if provenance == LEGACY_REAL_BACKFILL_PROVENANCE:
        # Historical REAL rows already lost their original decimal input. Keep
        # pre-v16 replay semantics instead of treating a CAST string as recovered
        # precision and invalidating historical correction/audit identities.
        return decimal_value(legacy, field=field, allow_none=allow_none)
    if exact not in {None, ""}:
        return decimal_value(exact, field=field, allow_none=allow_none)
    return decimal_value(legacy, field=field, allow_none=allow_none)


def decimal_text_from_mapping(
    row: Mapping[str, Any] | Any,
    field: str,
    *,
    allow_none: bool = False,
) -> str | None:
    value = decimal_from_mapping(row, field, allow_none=allow_none)
    return decimal_text(value, field=field, allow_none=allow_none)


def _row_value(row: Mapping[str, Any] | Any, field: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(field)
    try:
        return row[field]
    except (IndexError, KeyError, TypeError):
        return None


def strip_financial_storage_mirrors(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """Remove v16 persistence mirrors from pre-v16 economic identities."""

    items = (
        row.items()
        if isinstance(row, Mapping)
        else ((key, row[key]) for key in row.keys())
    )
    return {
        str(key): value
        for key, value in items
        if not str(key).endswith("_decimal")
        and str(key) not in {"currency_code", "decimal_provenance"}
    }


def real_projection_matches(
    row: Mapping[str, Any],
    field: str,
    *,
    legacy_backfill: bool = False,
) -> bool:
    legacy = row.get(field)
    exact = row.get(f"{field}_decimal")
    if legacy is None:
        return exact is None
    if exact in {None, ""}:
        return False
    try:
        expected = real_projection(exact, field=field)
        actual = float(legacy)
    except (TypeError, ValueError):
        return False
    if not legacy_backfill:
        return actual == expected
    # SQLite documents that only the first 15 significant decimal digits are
    # preserved when converting REAL to text. Legacy v16 backfill mirrors an
    # already-lossy REAL value, so tolerate only the text-rendering loss while
    # still rejecting economically meaningful drift.
    return math.isclose(actual, expected, rel_tol=1e-14, abs_tol=1e-14)


__all__ = [
    "DEFAULT_CURRENCY_CODE",
    "EXACT_DECIMAL_WRITE_PROVENANCE",
    "FinancialValueInput",
    "LEGACY_REAL_BACKFILL_PROVENANCE",
    "MAX_FRACTIONAL_DIGITS",
    "MAX_SIGNIFICANT_DIGITS",
    "decimal_from_mapping",
    "decimal_storage_pair",
    "decimal_text",
    "decimal_text_from_mapping",
    "decimal_value",
    "real_projection",
    "real_projection_matches",
    "strip_financial_storage_mirrors",
]
