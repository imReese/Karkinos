"""Application boundary for building or publishing valuation projections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from server.persistence.valuation_publication_recovery import (
    require_valuation_recovery_clear as require_valuation_recovery_clear,
)
from server.projections.valuation_snapshot import (
    VALUATION_POLICY_VERSION,
    is_asset_class_valuation_healthy,
    ledger_identity_from_rows,
    load_persisted_quote_rows,
    select_latest_observation_rows,
    validate_valuation_snapshot,
    valuation_identity_fields,
    valuation_lane_status,
    valuation_snapshot_from_row,
)
from server.projections.valuation_snapshot import (
    build_current_valuation_snapshot as _build_current_valuation_snapshot,
)


def build_current_valuation_snapshot(
    db: Any,
    *,
    valuation_policy: str = VALUATION_POLICY_VERSION,
    persist: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a projection or atomically publish it with an explicit choice."""

    if persist:
        publisher = getattr(db, "publish_current_valuation_snapshot_sync", None)
        if not callable(publisher):
            raise RuntimeError("valuation snapshot publication is unavailable")
        if valuation_policy == VALUATION_POLICY_VERSION:
            return publisher() if now is None else publisher(now=now)
        if now is None:
            return publisher(valuation_policy=valuation_policy)
        return publisher(valuation_policy=valuation_policy, now=now)

    payload = _build_current_valuation_snapshot(
        db,
        valuation_policy=valuation_policy,
        persist=False,
        now=now,
    )
    return payload


def portfolio_equity_from_valuation(db: Any, valuation: Mapping[str, Any]) -> Decimal:
    """Replay the exact current ledger against one complete valuation's marks."""
    from server.ledger.models import LedgerEntry
    from server.projections.service import build_portfolio_projection

    if valuation.get("status") != "complete":
        raise ValueError("portfolio_equity_valuation_incomplete")
    identity = ledger_identity_from_rows(
        [dict(row) for row in db.get_all_ledger_entries_sync()]
    )
    if any(
        identity[key] != valuation.get(key)
        for key in ("ledger_cutoff_id", "ledger_fingerprint")
    ):
        raise ValueError("portfolio_equity_ledger_identity_changed")
    projection = build_portfolio_projection(
        [LedgerEntry.from_row(row) for row in identity["rows"]],
        latest_quotes={
            str(row["symbol"]): dict(row) for row in valuation.get("quotes", [])
        },
    )
    equity = projection.total_equity
    if equity is None or not equity.is_finite() or equity <= 0:
        raise ValueError("portfolio_equity_not_positive_or_valued")
    return equity


def portfolio_stock_valuation_from_snapshot(
    db: Any,
    valuation: Mapping[str, Any],
    *,
    config: Any = None,
) -> dict[str, Any]:
    """Replay ledger cash and stock-only holdings against a healthy stock-lane snapshot."""
    from core.types import InstrumentType
    from domain.position_presence import is_economically_zero_quantity
    from server.ledger.models import LedgerEntry
    from server.projections.service import build_portfolio_projection
    from server.services.portfolio.ledger import resolve_instrument_types_by_symbol

    if not is_asset_class_valuation_healthy(valuation, "stock"):
        raise ValueError("portfolio_stock_valuation_incomplete")
    identity = ledger_identity_from_rows(
        [dict(row) for row in db.get_all_ledger_entries_sync()]
    )
    if any(
        identity[key] != valuation.get(key)
        for key in ("ledger_cutoff_id", "ledger_fingerprint")
    ):
        raise ValueError("portfolio_equity_ledger_identity_changed")
    entries = [LedgerEntry.from_row(row) for row in identity["rows"]]
    instrument_types = resolve_instrument_types_by_symbol(config, entries)
    projection = build_portfolio_projection(
        entries,
        latest_quotes={
            str(row["symbol"]): dict(row) for row in valuation.get("quotes", [])
        },
        instrument_types=instrument_types,
    )
    stock_symbols = sorted(
        symbol
        for symbol, pos in projection.positions.items()
        if not is_economically_zero_quantity(pos.quantity)
        and instrument_types.get(symbol) is InstrumentType.STOCK
    )
    for symbol in stock_symbols:
        pos = projection.positions[symbol]
        if not pos.valuation_available or symbol in projection.missing_price_symbols:
            raise ValueError(f"portfolio_stock_valuation_incomplete:{symbol}")
    stock_position_market_values = {
        symbol: projection.positions[symbol].market_value for symbol in stock_symbols
    }
    stock_equity = projection.cash + sum(
        stock_position_market_values.values(), Decimal("0")
    )
    total_equity = (
        projection.total_equity
        if valuation.get("status") == "complete"
        and not projection.missing_price_symbols
        else None
    )
    evaluation_equity = total_equity if total_equity is not None else stock_equity
    if (
        not stock_equity.is_finite()
        or stock_equity <= 0
        or not evaluation_equity.is_finite()
        or evaluation_equity <= 0
    ):
        raise ValueError("portfolio_equity_not_positive_or_valued")
    return {
        "cash": projection.cash,
        "total_equity": total_equity,
        "stock_equity": stock_equity,
        "evaluation_equity": evaluation_equity,
        "stock_position_market_values": stock_position_market_values,
        "stock_symbols": stock_symbols,
        "held_symbols": sorted(
            symbol
            for symbol, pos in projection.positions.items()
            if not is_economically_zero_quantity(pos.quantity)
        ),
    }


__all__ = [
    "VALUATION_POLICY_VERSION",
    "build_current_valuation_snapshot",
    "is_asset_class_valuation_healthy",
    "ledger_identity_from_rows",
    "load_persisted_quote_rows",
    "portfolio_equity_from_valuation",
    "portfolio_stock_valuation_from_snapshot",
    "require_valuation_recovery_clear",
    "select_latest_observation_rows",
    "validate_valuation_snapshot",
    "valuation_identity_fields",
    "valuation_lane_status",
    "valuation_snapshot_from_row",
]
