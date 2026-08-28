"""Application projection extracted from the HTTP delivery adapter."""

from __future__ import annotations

import asyncio
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
from server.projections.portfolio_snapshot_projection import (
    PortfolioSnapshotBuildResult,
    PortfolioSnapshotProjectionPorts,
)
from server.projections.portfolio_snapshot_projection import (
    build_portfolio_snapshot_sync as _build_portfolio_snapshot_sync,
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
    """Build Portfolio without blocking the application event loop on SQLite."""

    db = getattr(state, "db", None)
    ports = PortfolioSnapshotProjectionPorts(
        current_valuation_snapshot=current_valuation_snapshot,
        position_quote_presentation=position_quote_presentation,
        read_daily_ledger_entries=read_daily_ledger_entries,
        resolve_position_today_change=resolve_position_today_change,
        resolve_projection_sources=resolve_projection_sources,
    )
    result: PortfolioSnapshotBuildResult = await asyncio.to_thread(
        _build_portfolio_snapshot_sync,
        state,
        ports=ports,
        now=now,
    )
    if not result.needs_total_deposits:
        return result.snapshot

    reader = getattr(db, "get_total_deposits", None)
    if not callable(reader):
        raise AttributeError("database does not provide get_total_deposits")
    total_deposits = await reader()
    return result.snapshot.model_copy(
        update={"total_deposits": float(total_deposits)},
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
