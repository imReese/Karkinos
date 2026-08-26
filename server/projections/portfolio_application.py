"""Application projection extracted from the HTTP delivery adapter."""

from __future__ import annotations

from datetime import datetime

from core.types import Symbol
from server.models import (
    AccountOverview,
    AccountStateResponse,
    AllocationItem,
    ClosedPositionResponse,
    PortfolioSnapshot,
    PositionEvidenceReviewResponse,
    PositionResponse,
)
from server.projections.portfolio_assets import (
    build_grouped_allocation,
    normalize_asset_class,
    parse_fee_breakdown,
)
from server.projections.portfolio_positions import (
    has_position_ledger_entries,
    has_rows,
    ledger_entry_shanghai_date,
    ledger_entry_trade_total_fee,
    normalize_asset_class_value,
    read_daily_ledger_entries,
    resolve_live_holding_baseline,
    resolve_position_today_change,
    resolve_projection_sources,
    same_day_buy_lots,
    same_day_sell_lots,
    snapshot_quote_age_seconds,
    snapshot_quote_source,
    snapshot_quote_status,
    snapshot_stale_reason,
    snapshot_uses_persistent_cache,
    with_overview_quote_metadata,
)
from server.projections.portfolio_quotes import (
    adapt_persistent_quote_for_portfolio,
    asset_class_for_position,
    asset_class_from_config,
    asset_class_from_ledger,
    asset_class_from_metadata,
    asset_class_from_watchlist,
    broker_cost_basis_evidence_by_symbol,
    broker_cost_basis_fields,
    can_refresh_quotes,
    collect_latest_quote_timestamps,
    collect_latest_quotes,
    current_valuation_snapshot,
    hydrate_missing_position_quotes,
    is_unconfirmed_fund_estimate,
    merge_quote_identity,
    optional_float_attr,
    optional_float_value,
    position_quote_presentation,
    quote_age_seconds,
    quote_latest_price,
    quote_market_timestamp,
    quote_merge_timestamp,
    quote_source,
    quote_stale_reason,
    quotes_from_valuation_snapshot,
    refresh_policy,
    response_quote_status,
    store_runtime_quote,
    using_persistent_cache,
)
from server.services.account_state import build_account_state_projection
from server.services.asset_metadata import resolve_asset_metadata
from server.services.market_hours import get_shanghai_now
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.position_presence import (
    classify_position_presence,
)
from server.services.risk_engine import build_risk_summary
from server.services.valuation_snapshot import (
    valuation_identity_fields,
)


async def build_portfolio_snapshot(
    state,
    *,
    now: datetime | None = None,
) -> PortfolioSnapshot:
    """Build the canonical Portfolio projection from persisted application facts."""
    scheduler = state.scheduler
    valuation_snapshot = current_valuation_snapshot(state)
    latest_quotes = quotes_from_valuation_snapshot(valuation_snapshot)
    portfolio, instruments = resolve_projection_sources(
        state,
        latest_quotes=latest_quotes,
    )
    portfolio, instruments, _ = hydrate_missing_position_quotes(
        state,
        portfolio,
        instruments,
    )

    if portfolio is None:
        return PortfolioSnapshot(
            cash=0.0,
            total_equity=0.0,
            total_deposits=0.0,
            positions=[],
            allocation=[],
            allocation_grouped=[],
            realized_pnl_total=0.0,
            **valuation_identity_fields(valuation_snapshot),
        )

    broker_cost_basis_evidence = broker_cost_basis_evidence_by_symbol(
        state,
        {str(symbol) for symbol in portfolio.positions},
    )
    positions: list[PositionResponse] = []
    closed_positions: list[ClosedPositionResponse] = []
    position_review_items: list[PositionEvidenceReviewResponse] = []
    realized_pnl_total = 0.0
    daily_ledger_entries = read_daily_ledger_entries(state)
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
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=quote,
            fallback_name=getattr(instrument, "name", None) or symbol,
        )
        quantity = float(pos.quantity)
        avg_cost = float(pos.avg_cost)
        latest_price_value = quote_latest_price(quote)
        (
            today_change,
            today_change_pct,
            baseline_price,
            baseline_timestamp,
            baseline_source,
        ) = resolve_position_today_change(
            state,
            symbol=symbol,
            quantity=quantity,
            avg_cost=avg_cost,
            latest_quote=quote,
            latest_price_value=latest_price_value,
            ledger_entries=daily_ledger_entries,
            now=now,
        )
        quote_status, stale_reason = position_quote_presentation(
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
            quantity=quantity,
            available_qty=float(pos.available_qty),
            frozen_qty=float(pos.frozen_qty),
            avg_cost=avg_cost,
            **cost_basis_fields,
            latest_price=latest_price_value,
            market_value=float(pos.market_value),
            unrealized_pnl=float(pos.unrealized_pnl),
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
        )
        realized_pnl_total += response_position.realized_pnl
        presence, reason_codes = classify_position_presence(pos)
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

    total_equity = float(portfolio.cash)
    for pos in positions:
        total_equity += pos.market_value

    allocation: list[AllocationItem] = []
    if total_equity > 0:
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
                    weight=pos.market_value / total_equity,
                    value=pos.market_value,
                    asset_class=ac,
                )
            )

    allocation_grouped = build_grouped_allocation(allocation, total_equity)

    if hasattr(portfolio, "total_deposits"):
        total_deposits = float(portfolio.total_deposits)
    elif state.db is not None:
        total_deposits = await state.db.get_total_deposits()
    else:
        total_deposits = 0.0

    return PortfolioSnapshot(
        cash=float(portfolio.cash),
        total_equity=total_equity,
        total_deposits=total_deposits,
        positions=positions,
        allocation=allocation,
        allocation_grouped=allocation_grouped,
        closed_positions=closed_positions,
        position_review_items=position_review_items,
        realized_pnl_total=realized_pnl_total,
        **valuation_identity_fields(valuation_snapshot),
    )


async def build_account_state_response(
    state,
    *,
    snapshot: PortfolioSnapshot | None = None,
    now: datetime | None = None,
) -> AccountStateResponse:
    """Project canonical Account State from one exact Portfolio snapshot."""
    resolved_snapshot = snapshot or await build_portfolio_snapshot(state, now=now)
    risks = build_risk_summary(
        resolved_snapshot,
        collect_latest_quote_timestamps(state),
    )
    projection = build_account_state_projection(resolved_snapshot, risks)
    return AccountStateResponse(
        summary=with_overview_quote_metadata(
            projection.summary,
            resolved_snapshot,
        ),
        snapshot=projection.snapshot,
        risks=projection.risks,
        next_step=projection.next_step,
    )


__all__ = (
    "adapt_persistent_quote_for_portfolio",
    "asset_class_for_position",
    "asset_class_from_config",
    "asset_class_from_ledger",
    "asset_class_from_metadata",
    "asset_class_from_watchlist",
    "broker_cost_basis_evidence_by_symbol",
    "broker_cost_basis_fields",
    "build_account_state_response",
    "build_grouped_allocation",
    "build_portfolio_snapshot",
    "can_refresh_quotes",
    "collect_latest_quote_timestamps",
    "collect_latest_quotes",
    "current_valuation_snapshot",
    "has_position_ledger_entries",
    "has_rows",
    "hydrate_missing_position_quotes",
    "is_unconfirmed_fund_estimate",
    "ledger_entry_shanghai_date",
    "ledger_entry_trade_total_fee",
    "merge_quote_identity",
    "normalize_asset_class",
    "normalize_asset_class_value",
    "optional_float_attr",
    "optional_float_value",
    "parse_fee_breakdown",
    "position_quote_presentation",
    "quote_age_seconds",
    "quote_latest_price",
    "quote_market_timestamp",
    "quote_merge_timestamp",
    "quote_source",
    "quote_stale_reason",
    "quotes_from_valuation_snapshot",
    "read_daily_ledger_entries",
    "refresh_policy",
    "resolve_live_holding_baseline",
    "resolve_position_today_change",
    "resolve_projection_sources",
    "response_quote_status",
    "same_day_buy_lots",
    "same_day_sell_lots",
    "snapshot_quote_age_seconds",
    "snapshot_quote_source",
    "snapshot_quote_status",
    "snapshot_stale_reason",
    "snapshot_uses_persistent_cache",
    "store_runtime_quote",
    "using_persistent_cache",
    "with_overview_quote_metadata",
)
