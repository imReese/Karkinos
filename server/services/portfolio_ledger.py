"""Rebuild runtime portfolio state from the canonical persisted ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from core.event_bus import EventBus
from core.types import AssetClass, InstrumentType, Symbol
from data.manager import DataManager
from domain.portfolio import Portfolio
from domain.position import Position
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection

_INSTRUMENT_ASSET_CLASS_MAP = {
    InstrumentType.STOCK: AssetClass.STOCK,
    InstrumentType.ETF: AssetClass.FUND,
    InstrumentType.OPEN_END_FUND: AssetClass.FUND,
    InstrumentType.GOLD: AssetClass.GOLD,
    InstrumentType.BOND: AssetClass.BOND,
    InstrumentType.INDEX: AssetClass.INDEX,
}


def rebuild_portfolio_from_ledger(
    config: Any,
    db: Any,
    latest_quotes: dict[str, dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Recreate runtime state exclusively from canonical ledger facts."""

    ledger_entries = _load_ledger_entries(db)
    return rebuild_portfolio_from_entries(
        config,
        ledger_entries,
        latest_quotes=latest_quotes,
    )


def rebuild_portfolio_from_entries(
    config: Any,
    entries: Sequence[LedgerEntry | Mapping[str, Any]],
    latest_quotes: dict[str, dict[str, Any]] | None = None,
) -> SimpleNamespace:
    """Recreate runtime state from one caller-owned immutable ledger snapshot."""

    ledger_entries = [
        entry if isinstance(entry, LedgerEntry) else LedgerEntry.from_row(dict(entry))
        for entry in entries
    ]
    latest_quotes = latest_quotes or {}
    instrument_types = _instrument_types_by_symbol(config, ledger_entries)
    valuation_quotes = _quotes_matching_instrument_types(
        latest_quotes,
        instrument_types,
    )
    projection = build_portfolio_projection(
        ledger_entries,
        initial_cash=Decimal("0"),
        latest_quotes=valuation_quotes,
    )

    portfolio = Portfolio(
        EventBus(),
        initial_cash=Decimal("0"),
    )
    portfolio.cash = projection.cash
    portfolio.total_deposits = projection.total_deposits
    instruments: dict[Symbol, object] = {}

    def ensure_instrument(symbol: str, instrument_type: InstrumentType) -> object:
        symbol_value = Symbol(symbol)
        if symbol_value not in instruments:
            mapped = _INSTRUMENT_ASSET_CLASS_MAP.get(instrument_type)
            if mapped is None:
                raise ValueError(
                    "authoritative instrument type is unsupported: "
                    f"{instrument_type.value!r}"
                )
            instrument = DataManager.get_instrument_by_type(
                symbol_value,
                instrument_type,
            )
            instruments[symbol_value] = instrument
            portfolio.add_instrument(instrument)
        return instruments[symbol_value]

    for asset in _configured_assets(config):
        symbol = str(asset["symbol"]).strip()
        ensure_instrument(symbol, instrument_types[symbol])

    for symbol, projected in projection.positions.items():
        instrument_type = instrument_types.get(symbol)
        if instrument_type is None:
            raise ValueError(
                f"authoritative instrument type is unresolved for {symbol}"
            )
        ensure_instrument(symbol, instrument_type)
        position = Position(Symbol(symbol))
        position.quantity = projected.quantity
        position.frozen_qty = projected.frozen_qty
        position.avg_cost = projected.avg_cost
        position.realized_pnl = projected.realized_pnl
        position.commission_paid = projected.commission_paid
        position.market_value = projected.market_value
        position.unrealized_pnl = projected.unrealized_pnl
        position.valuation_available = projected.valuation_available
        position.valuation_price = projected.valuation_price
        position.closed_at = projected.closed_at
        position.broker_displayed_cost_basis = projected.broker_displayed_cost_basis
        position.broker_displayed_unit_cost = projected.broker_displayed_unit_cost
        position.broker_cost_basis_difference = projected.broker_cost_basis_difference
        position.broker_cost_basis_method = projected.broker_cost_basis_method
        position.broker_cost_basis_status = projected.broker_cost_basis_status
        portfolio.positions[Symbol(symbol)] = position

    portfolio.valuation_status = projection.valuation_status
    portfolio.missing_price_symbols = tuple(projection.missing_price_symbols)

    return SimpleNamespace(
        portfolio=portfolio,
        instruments=instruments,
        valuation_status=projection.valuation_status,
        missing_price_symbols=tuple(projection.missing_price_symbols),
    )


def _load_ledger_entries(db: Any, *, batch_size: int = 500) -> list[LedgerEntry]:
    snapshot_reader = getattr(db, "get_all_ledger_entries_sync", None)
    if callable(snapshot_reader):
        return [LedgerEntry.from_row(dict(row)) for row in (snapshot_reader() or [])]

    reader = getattr(db, "get_ledger_entries_sync", None)
    if not callable(reader):
        raise RuntimeError("canonical ledger reader is unavailable")
    rows = reader(limit=batch_size, offset=0) or []
    if len(rows) >= batch_size:
        raise RuntimeError(
            "canonical ledger snapshot exceeds legacy single-read compatibility limit"
        )
    return [LedgerEntry.from_row(dict(row)) for row in rows]


def _instrument_types_by_symbol(
    config: Any,
    entries: Sequence[LedgerEntry],
) -> dict[str, InstrumentType]:
    evidence: dict[str, list[str]] = {}
    for asset in _configured_assets(config):
        symbol = str(asset.get("symbol") or "").strip()
        value = asset.get("instrument_type") or asset.get("asset_class")
        if symbol and value not in {None, ""}:
            evidence.setdefault(symbol, []).append(str(value))
    for entry in entries:
        symbol = str(entry.symbol or "").strip()
        if symbol:
            evidence.setdefault(symbol, []).append(str(entry.asset_class or ""))

    result: dict[str, InstrumentType] = {}
    for symbol, raw_values in evidence.items():
        result[symbol] = _resolve_instrument_type(symbol, raw_values)
    return result


def _quotes_matching_instrument_types(
    latest_quotes: Mapping[str, Mapping[str, Any]],
    instrument_types: Mapping[str, InstrumentType],
) -> dict[str, dict[str, Any]]:
    matched: dict[str, dict[str, Any]] = {}
    for raw_symbol, quote in latest_quotes.items():
        symbol = str(raw_symbol).strip()
        expected = instrument_types.get(symbol)
        if expected is None:
            continue
        raw_identity = (
            quote.get("instrument_type")
            or quote.get("asset_type")
            or quote.get("asset_class")
        )
        try:
            observed = InstrumentType.from_persisted(raw_identity)
        except ValueError:
            continue
        if observed is expected:
            matched[symbol] = dict(quote)
    return matched


def _resolve_instrument_type(
    symbol: str,
    raw_values: Sequence[str],
) -> InstrumentType:
    explicit: set[InstrumentType] = set()
    legacy_fund = False
    for raw in raw_values:
        normalized = str(raw or "").strip().lower().replace("-", "_")
        if normalized == "fund":
            legacy_fund = True
            continue
        explicit.add(InstrumentType.from_persisted(normalized))

    if len(explicit) > 1:
        kinds = ",".join(sorted(item.value for item in explicit))
        raise ValueError(
            f"authoritative instrument identity conflicts for {symbol}: {kinds}"
        )
    if explicit:
        resolved = next(iter(explicit))
        if legacy_fund and resolved not in {
            InstrumentType.ETF,
            InstrumentType.OPEN_END_FUND,
        }:
            raise ValueError(
                f"authoritative instrument identity conflicts for {symbol}: "
                f"{resolved.value},fund"
            )
        return resolved
    if legacy_fund:
        return InstrumentType.OPEN_END_FUND
    raise ValueError(f"authoritative instrument type is unresolved for {symbol}")


def _configured_assets(config: Any) -> list[Mapping[str, Any]]:
    configured = getattr(config, "assets", []) or []
    if isinstance(configured, Mapping):
        values: list[Mapping[str, Any]] = []
        for key, value in configured.items():
            if isinstance(value, str):
                # Legacy ``assets={symbol: display_name}`` mappings contain
                # presentation metadata, not instrument-identity evidence.
                values.append({"symbol": str(key), "display_name": value})
            elif isinstance(value, Mapping):
                values.append(
                    value if value.get("symbol") else {**value, "symbol": str(key)}
                )
        return values
    return [asset for asset in configured if isinstance(asset, Mapping)]


__all__ = ["rebuild_portfolio_from_entries", "rebuild_portfolio_from_ledger"]
