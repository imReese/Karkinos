"""Canonical replay derivation shared by append-only ledger corrections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from server.ledger.models import LedgerEntry
from server.projections.models import ProjectedPosition
from server.projections.service import build_portfolio_projection


class LedgerExclusionCorrectionPlanError(ValueError):
    """Raised when exact source facts cannot be safely removed by replay."""

    def __init__(self, blocker: str) -> None:
        super().__init__(blocker)
        self.blocker = blocker


def build_ledger_exclusion_correction_plan(
    *,
    ledger_rows: list[dict[str, Any]],
    original_entry_ids: list[int],
    required_sources: Collection[str],
    schema_version: str,
    correction_identity: dict[str, str],
    blocker_prefix: str,
    derivation: str = "canonical_replay_excluding_exact_original_ledger_entries",
) -> dict[str, Any]:
    """Derive an exact compensating state by excluding immutable source rows."""

    normalized_ids = sorted({int(value) for value in original_entry_ids if int(value)})
    if not normalized_ids:
        raise _error(blocker_prefix, "zero_entry_scope")
    original_id_set = set(normalized_ids)
    rows_by_id = {
        int(row["id"]): dict(row) for row in ledger_rows if row.get("id") is not None
    }
    if any(entry_id not in rows_by_id for entry_id in normalized_ids):
        raise _error(blocker_prefix, "original_entry_missing")
    original_rows = [rows_by_id[entry_id] for entry_id in normalized_ids]
    if any(
        str(row.get("source") or "") not in required_sources for row in original_rows
    ):
        raise _error(blocker_prefix, "original_lineage_invalid")

    symbols = {str(row.get("symbol") or "").strip() for row in original_rows}
    symbols.discard("")
    if len(symbols) != 1:
        raise _error(blocker_prefix, "symbol_scope_invalid")
    symbol = next(iter(symbols))
    asset_classes = {
        str(row.get("asset_class") or "stock").strip().lower() for row in original_rows
    }
    if len(asset_classes) != 1:
        raise _error(blocker_prefix, "asset_class_scope_invalid")

    try:
        current = build_portfolio_projection(
            [LedgerEntry.from_row(row) for row in ledger_rows]
        )
        target = build_portfolio_projection(
            [
                LedgerEntry.from_row(row)
                for row in ledger_rows
                if int(row.get("id") or 0) not in original_id_set
            ]
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        raise _error(blocker_prefix, "replay_invalid") from None

    all_symbols = set(current.positions) | set(target.positions)
    for other_symbol in all_symbols - {symbol}:
        if _position_state(current.positions.get(other_symbol)) != _position_state(
            target.positions.get(other_symbol)
        ):
            raise _error(blocker_prefix, "scope_expanded")
    if target.total_deposits - current.total_deposits != Decimal("0"):
        raise _error(blocker_prefix, "deposit_boundary_invalid")

    return {
        "schema_version": schema_version,
        **correction_identity,
        "original_ledger_entry_ids": normalized_ids,
        "effective_at": _next_ledger_timestamp(ledger_rows, blocker_prefix),
        "symbol": symbol,
        "asset_class": next(iter(asset_classes)),
        "cash_delta": _decimal_string(target.cash - current.cash),
        "total_deposits_delta": "0",
        "position_before": _position_state(current.positions.get(symbol)),
        "position_after": _position_state(target.positions.get(symbol)),
        "derivation": derivation,
        "arbitrary_financial_input_used": False,
    }


def correction_plan_fingerprint(plan: dict[str, Any]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _error(prefix: str, suffix: str) -> LedgerExclusionCorrectionPlanError:
    return LedgerExclusionCorrectionPlanError(f"{prefix}_{suffix}")


def _position_state(position: ProjectedPosition | None) -> dict[str, Any]:
    position = position or ProjectedPosition(symbol="")
    return {
        "quantity": _decimal_string(position.quantity),
        "available_qty": _decimal_string(position.available_qty),
        "frozen_qty": _decimal_string(position.frozen_qty),
        "avg_cost": _decimal_string(position.avg_cost),
        "realized_pnl": _decimal_string(position.realized_pnl),
        "commission_paid": _decimal_string(position.commission_paid),
        "broker_displayed_cost_basis": _decimal_string(
            position.broker_displayed_cost_basis
        ),
        "broker_displayed_unit_cost": _decimal_string(
            position.broker_displayed_unit_cost
        ),
        "broker_cost_basis_difference": _decimal_string(
            position.broker_cost_basis_difference
        ),
        "broker_cost_basis_method": position.broker_cost_basis_method,
        "broker_cost_basis_status": position.broker_cost_basis_status,
    }


def _next_ledger_timestamp(rows: list[dict[str, Any]], blocker_prefix: str) -> str:
    valid = [value for row in rows if (value := _parse_timestamp(row.get("timestamp")))]
    try:
        effective = max(valid, default=datetime(1970, 1, 1, tzinfo=timezone.utc))
        return (
            (effective + timedelta(seconds=1))
            .astimezone(timezone.utc)
            .isoformat(timespec="seconds")
        )
    except OverflowError:
        raise _error(blocker_prefix, "timestamp_unavailable") from None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decimal_string(value: Decimal | Any) -> str:
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


__all__ = [
    "LedgerExclusionCorrectionPlanError",
    "build_ledger_exclusion_correction_plan",
    "correction_plan_fingerprint",
]
