"""Canonical synchronous Portfolio snapshot composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.types import InstrumentType, Symbol
from server.models import (
    AllocationItem,
    ClosedPositionResponse,
    PortfolioSnapshot,
    PositionEvidenceReviewResponse,
    PositionResponse,
)
from server.projections.portfolio_assets import (
    build_grouped_allocation,
    normalize_asset_class,
)
from server.projections.portfolio_quotes import (
    broker_cost_basis_evidence_by_symbol,
    broker_cost_basis_fields,
    hydrate_missing_position_quotes,
    quote_age_seconds,
    quote_latest_price,
    quote_source,
    quotes_from_valuation_snapshot,
    refresh_policy,
    using_persistent_cache,
)
from server.projections.quote_status import (
    quote_valuation_blocker,
    quote_valuation_status,
)
from server.services.asset_metadata import resolve_asset_metadata
from server.services.position_presence import classify_position_presence
from server.services.valuation_snapshot import valuation_identity_fields

Operation = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotProjectionPorts:
    current_valuation_snapshot: Operation
    position_quote_presentation: Operation
    read_daily_ledger_entries: Operation
    resolve_position_today_change: Operation
    resolve_projection_sources: Operation


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotBuildResult:
    snapshot: PortfolioSnapshot
    needs_total_deposits: bool = False


def build_portfolio_snapshot_sync(
    state,
    *,
    ports: PortfolioSnapshotProjectionPorts,
    now: datetime | None = None,
) -> PortfolioSnapshotBuildResult:
    """Build the canonical Portfolio projection from persisted application facts."""
    scheduler = state.scheduler
    valuation_snapshot = (
        ports.current_valuation_snapshot(state)
        if now is None
        else ports.current_valuation_snapshot(state, now=now)
    )
    latest_quotes = quotes_from_valuation_snapshot(valuation_snapshot)
    portfolio, instruments = ports.resolve_projection_sources(
        state,
        latest_quotes=latest_quotes,
    )
    portfolio, instruments, _ = hydrate_missing_position_quotes(
        state,
        portfolio,
        instruments,
    )

    if portfolio is None:
        return PortfolioSnapshotBuildResult(
            snapshot=PortfolioSnapshot(
                cash=0.0,
                total_equity=0.0,
                total_deposits=0.0,
                positions=[],
                allocation=[],
                allocation_grouped=[],
                realized_pnl_total=0.0,
                valuation_lanes=valuation_snapshot.get("valuation_lanes") or [],
                **valuation_identity_fields(valuation_snapshot),
            )
        )

    broker_cost_basis_evidence = broker_cost_basis_evidence_by_symbol(
        state,
        {str(symbol) for symbol in portfolio.positions},
    )
    positions: list[PositionResponse] = []
    closed_positions: list[ClosedPositionResponse] = []
    position_review_items: list[PositionEvidenceReviewResponse] = []
    realized_pnl_total = 0.0
    missing_price_symbols: list[str] = []
    daily_ledger_entries = ports.read_daily_ledger_entries(state)
    ledger_asset_classes: dict[str, str] = {}
    for entry in daily_ledger_entries:
        ledger_symbol = str(entry.get("symbol") or "").strip()
        ledger_asset_class = str(entry.get("asset_class") or "").strip()
        if ledger_symbol and ledger_asset_class:
            ledger_asset_classes.setdefault(ledger_symbol, ledger_asset_class)
    for sym, pos in portfolio.positions.items():
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        asset_class = normalize_asset_class(
            (quote or {}).get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
            or ledger_asset_classes.get(symbol)
        )
        raw_instrument_type = (
            getattr(instrument, "instrument_type", None)
            or getattr(instrument, "asset_class", None)
            or ledger_asset_classes.get(symbol)
        )
        try:
            instrument_type = InstrumentType.from_persisted(raw_instrument_type).value
        except ValueError:
            instrument_type = ""
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=quote,
            fallback_name=getattr(instrument, "name", None) or symbol,
        )
        quantity = float(pos.quantity)
        avg_cost = float(pos.avg_cost)
        presence, reason_codes = classify_position_presence(pos)
        latest_price_value = quote_latest_price(quote)
        quote_evidence_status = (
            quote_valuation_status(quote) if quote is not None else "missing"
        )
        valuation_available = (
            latest_price_value is not None
            and quote_evidence_status == "complete"
            and bool(getattr(pos, "valuation_available", True))
        )
        (
            today_change,
            today_change_pct,
            baseline_price,
            baseline_timestamp,
            baseline_source,
        ) = ports.resolve_position_today_change(
            state,
            symbol=symbol,
            quantity=quantity,
            avg_cost=avg_cost,
            latest_quote=quote,
            latest_price_value=latest_price_value,
            instrument_type=instrument_type,
            ledger_entries=daily_ledger_entries,
            now=now,
        )
        if not valuation_available and presence != "closed":
            # Keep the persisted observation visible, but never derive account
            # PnL from stale, estimated, or otherwise incomplete evidence.
            today_change = None
            today_change_pct = None
        quote_status, stale_reason = ports.position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=metadata.asset_class,
            quote=quote,
            now=now,
        )
        cost_basis_fields = broker_cost_basis_fields(
            pos,
            broker_cost_basis_evidence.get(symbol),
            quantity=quantity,
            avg_cost=avg_cost,
        )
        response_position = PositionResponse(
            symbol=symbol,
            name=metadata.display_name,
            display_name=metadata.display_name,
            asset_class=metadata.asset_class,
            instrument_type=(
                getattr(getattr(instrument, "instrument_type", None), "value", None)
            ),
            quantity=quantity,
            available_qty=float(pos.available_qty),
            frozen_qty=float(pos.frozen_qty),
            avg_cost=avg_cost,
            **cost_basis_fields,
            latest_price=latest_price_value,
            market_value=float(pos.market_value) if valuation_available else None,
            unrealized_pnl=(float(pos.unrealized_pnl) if valuation_available else None),
            realized_pnl=float(pos.realized_pnl),
            commission_paid=float(pos.commission_paid),
            today_change=today_change,
            today_change_pct=today_change_pct,
            baseline_price=baseline_price,
            baseline_timestamp=baseline_timestamp,
            baseline_source=baseline_source,
            quote_timestamp=None if quote is None else quote.get("timestamp"),
            quote_status=quote_status,
            quote_source=quote_source(state, quote),
            quote_age_seconds=quote_age_seconds(quote, now=now),
            stale_reason=stale_reason,
            refresh_policy=refresh_policy(now),
            using_persistent_cache=using_persistent_cache(quote),
            nav_date=None if quote is None else quote.get("nav_date"),
            valuation_available=valuation_available,
            valuation_blockers=(
                []
                if valuation_available
                else [quote_valuation_blocker(quote, symbol=symbol)]
            ),
        )
        if not valuation_available and quantity != 0:
            missing_price_symbols.append(symbol)
        realized_pnl_total += response_position.realized_pnl
        if presence == "current":
            positions.append(response_position)
        elif presence == "closed":
            closed_positions.append(
                ClosedPositionResponse(
                    **response_position.model_dump(),
                    closed_at=getattr(pos, "closed_at", None),
                )
            )
        else:
            position_review_items.append(
                PositionEvidenceReviewResponse(
                    reason_codes=reason_codes,
                    position=response_position,
                )
            )

    total_equity: float | None = None
    aggregate_valuation_complete = (
        valuation_snapshot.get("status") == "complete" and not missing_price_symbols
    )
    if aggregate_valuation_complete:
        total_equity = float(portfolio.cash) + sum(
            float(pos.market_value or 0.0) for pos in positions
        )

    allocation: list[AllocationItem] = []
    if total_equity is not None and total_equity > 0:
        allocation.append(
            AllocationItem(
                symbol="CASH",
                name="现金",
                weight=float(portfolio.cash) / total_equity,
                value=float(portfolio.cash),
                asset_class="cash",
            )
        )
        for pos in positions:
            ac = "stock"
            if scheduler:
                for sym, asset_class in scheduler.watchlist:
                    if str(sym) == pos.symbol:
                        ac = asset_class.value
                        break
            if pos.symbol in {
                str(symbol)
                for symbol, instrument in instruments.items()
                if getattr(instrument, "asset_class", None) is not None
            }:
                instrument = instruments.get(Symbol(pos.symbol))
                if instrument is not None:
                    ac = instrument.asset_class.value
            name = pos.display_name or pos.name or pos.symbol

            allocation.append(
                AllocationItem(
                    symbol=pos.symbol,
                    name=name,
                    weight=float(pos.market_value or 0.0) / total_equity,
                    value=float(pos.market_value or 0.0),
                    asset_class=ac,
                )
            )

    allocation_grouped = build_grouped_allocation(allocation, total_equity or 0.0)

    needs_total_deposits = False
    if hasattr(portfolio, "total_deposits"):
        total_deposits = float(portfolio.total_deposits)
    elif state.db is not None:
        reader = getattr(state.db, "get_total_deposits_sync", None)
        if callable(reader):
            total_deposits = float(reader())
        else:
            total_deposits = 0.0
            needs_total_deposits = True
    else:
        total_deposits = 0.0

    valuation_blockers = sorted(
        {blocker for position in positions for blocker in position.valuation_blockers}
    )
    if valuation_snapshot.get("status") != "complete" and not valuation_blockers:
        valuation_blockers.append(
            f"portfolio_valuation_{valuation_snapshot.get('status') or 'missing'}"
        )
    valuation_identity = valuation_identity_fields(valuation_snapshot)
    if valuation_blockers and valuation_identity["valuation_status"] != "degraded":
        valuation_identity["valuation_status"] = "blocked"

    return PortfolioSnapshotBuildResult(
        snapshot=PortfolioSnapshot(
            cash=float(portfolio.cash),
            total_equity=total_equity,
            total_deposits=total_deposits,
            positions=positions,
            allocation=allocation,
            allocation_grouped=allocation_grouped,
            closed_positions=closed_positions,
            position_review_items=position_review_items,
            realized_pnl_total=realized_pnl_total,
            missing_price_symbols=sorted(missing_price_symbols),
            valuation_blockers=valuation_blockers,
            valuation_lanes=valuation_snapshot.get("valuation_lanes") or [],
            **valuation_identity,
        ),
        needs_total_deposits=needs_total_deposits,
    )


__all__ = [
    "PortfolioSnapshotBuildResult",
    "PortfolioSnapshotProjectionPorts",
    "build_portfolio_snapshot_sync",
]
