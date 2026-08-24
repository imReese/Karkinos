"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from core.types import Symbol
from server.http.portfolio_endpoints.analysis import (
    create_router as _create_analysis_router,
)
from server.http.portfolio_endpoints.cash_flows import (
    create_router as _create_cash_flows_router,
)
from server.http.portfolio_endpoints.performance import (
    create_router as _create_performance_router,
)
from server.http.portfolio_endpoints.snapshot import (
    create_router as _create_snapshot_router,
)
from server.http.portfolio_endpoints.trades import (
    create_router as _create_trades_router,
)
from server.ledger.models import LedgerEntry
from server.models import (
    AccountOverview,
    AccountStateResponse,
    ActionCard,
    ActivityItem,
    AllocationItem,
    CashFlowCreate,
    CashFlowResponse,
    CurrentHoldingMarketEvidenceReviewResponse,
    DailyOperationsSummary,
    EquityPoint,
    EquitySeriesPoint,
    ExplainabilityBridgeItem,
    ExplainabilityDriver,
    ExplainabilityPositionDriver,
    ExplainabilityResponse,
    ExplainabilityTimelineBreakdownItem,
    ExplainabilityTimelineEvent,
    ExplainabilityTimelinePoint,
    LiveHoldingGroupResponse,
    LiveHoldingItemResponse,
    LiveHoldingsResponse,
    PendingFundOrderResponse,
    PortfolioCockpitPosition,
    PortfolioCockpitResponse,
    PortfolioConstructionRecommendation,
    PortfolioSnapshot,
    PositionResponse,
    RiskSummaryItem,
    RiskWorkspaceResponse,
    TodayPnlBreakdown,
    TodayPnlContributor,
    TradeCreate,
    TradePreviewResponse,
    TradeResponse,
)
from server.projections.portfolio_application import (
    build_account_state_response,
    build_portfolio_snapshot,
)
from server.projections.portfolio_application import (
    collect_latest_quote_timestamps as _collect_latest_quote_timestamps,
)
from server.projections.portfolio_application import (
    collect_latest_quotes as _collect_latest_quotes,
)
from server.projections.portfolio_application import (
    current_valuation_snapshot as _current_valuation_snapshot,
)
from server.projections.portfolio_application import (
    ensure_asset_config as _ensure_asset_config,
)
from server.projections.portfolio_application import has_rows as _has_rows
from server.projections.portfolio_application import (
    hydrate_missing_position_quotes as _hydrate_missing_position_quotes,
)
from server.projections.portfolio_application import (
    ledger_entry_shanghai_date as _ledger_entry_shanghai_date,
)
from server.projections.portfolio_application import (
    ledger_entry_trade_total_fee as _ledger_entry_trade_total_fee,
)
from server.projections.portfolio_application import (
    normalize_asset_class as _normalize_asset_class,
)
from server.projections.portfolio_application import (
    normalize_asset_class_value as _normalize_asset_class_value,
)
from server.projections.portfolio_application import (
    parse_fee_breakdown as _parse_fee_breakdown,
)
from server.projections.portfolio_application import (
    position_quote_presentation as _position_quote_presentation,
)
from server.projections.portfolio_application import (
    quote_age_seconds as _quote_age_seconds,
)
from server.projections.portfolio_application import (
    quote_market_timestamp as _quote_market_timestamp,
)
from server.projections.portfolio_application import quote_source as _quote_source
from server.projections.portfolio_application import (
    quote_stale_reason as _quote_stale_reason,
)
from server.projections.portfolio_application import (
    quotes_from_valuation_snapshot as _quotes_from_valuation_snapshot,
)
from server.projections.portfolio_application import (
    read_daily_ledger_entries as _read_daily_ledger_entries,
)
from server.projections.portfolio_application import refresh_policy as _refresh_policy
from server.projections.portfolio_application import (
    resolve_fund_buy_fill as _resolve_fund_buy_fill,
)
from server.projections.portfolio_application import (
    resolve_live_holding_baseline as _resolve_live_holding_baseline,
)
from server.projections.portfolio_application import (
    resolve_position_today_change as _resolve_position_today_change,
)
from server.projections.portfolio_application import (
    resolve_projection_sources as _resolve_projection_sources,
)
from server.projections.portfolio_application import (
    same_day_buy_lots as _same_day_buy_lots,
)
from server.projections.portfolio_application import (
    same_day_sell_lots as _same_day_sell_lots,
)
from server.projections.portfolio_application import (
    using_persistent_cache as _using_persistent_cache,
)
from server.projections.portfolio_application import (
    with_overview_quote_metadata as _with_overview_quote_metadata,
)
from server.projections.portfolio_views.explainability import (
    build_activity_items as _build_activity_items,
)
from server.projections.portfolio_views.explainability import (
    build_equity_bridge as _build_equity_bridge,
)
from server.projections.portfolio_views.explainability import (
    build_position_drivers as _build_position_drivers,
)
from server.projections.portfolio_views.explainability import (
    build_recent_drivers as _build_recent_drivers,
)
from server.projections.portfolio_views.explainability import (
    build_timeline as _build_timeline,
)
from server.projections.portfolio_views.explainability import (
    build_timeline_breakdown_items as _build_timeline_breakdown_items,
)
from server.projections.portfolio_views.explainability import (
    equity_series_components_by_date as _equity_series_components_by_date,
)
from server.projections.portfolio_views.explainability import (
    is_missing_equity_quote_status as _is_missing_equity_quote_status,
)
from server.projections.portfolio_views.explainability import (
    ledger_entry_display_label as _ledger_entry_display_label,
)
from server.projections.portfolio_views.explainability import (
    ledger_entry_notional as _ledger_entry_notional,
)
from server.projections.portfolio_views.explainability import (
    ledger_entry_structured_explainability_fields as _ledger_entry_structured_explainability_fields,
)
from server.projections.portfolio_views.explainability import (
    merge_equity_series_quote_status as _merge_equity_series_quote_status,
)
from server.projections.portfolio_views.explainability import (
    optional_float as _optional_float,
)
from server.projections.portfolio_views.explainability import (
    timeline_date_from_timestamp as _timeline_date_from_timestamp,
)
from server.projections.portfolio_views.historical_series import (
    bind_current_equity_valuation as _bind_current_equity_valuation,
)
from server.projections.portfolio_views.historical_series import (
    bind_equity_series_valuation as _bind_equity_series_valuation,
)
from server.projections.portfolio_views.historical_series import (
    cash_flow_adjusted_equity_points_from_series as _cash_flow_adjusted_equity_points_from_series,
)
from server.projections.portfolio_views.historical_series import (
    daily_equity_series_for_range as _daily_equity_series_for_range,
)
from server.projections.portfolio_views.historical_series import (
    daily_equity_series_from_ledger_history as _daily_equity_series_from_ledger_history,
)
from server.projections.portfolio_views.historical_series import (
    dedupe_equity_series_points_by_date as _dedupe_equity_series_points_by_date,
)
from server.projections.portfolio_views.historical_series import (
    equity_points_from_series as _equity_points_from_series,
)
from server.projections.portfolio_views.historical_series import (
    equity_series_bucket as _equity_series_bucket,
)
from server.projections.portfolio_views.historical_series import (
    equity_series_matches_valuation as _equity_series_matches_valuation,
)
from server.projections.portfolio_views.historical_series import (
    equity_series_metadata_by_date as _equity_series_metadata_by_date,
)
from server.projections.portfolio_views.historical_series import (
    equity_series_status_rank as _equity_series_status_rank,
)
from server.projections.portfolio_views.historical_series import (
    flat_intraday_equity_series_from_current as _flat_intraday_equity_series_from_current,
)
from server.projections.portfolio_views.historical_series import (
    historical_quote_for_equity_day as _historical_quote_for_equity_day,
)
from server.projections.portfolio_views.historical_series import (
    ledger_capital_flow_amount as _ledger_capital_flow_amount,
)
from server.projections.portfolio_views.historical_series import (
    ledger_entry_timestamp as _ledger_entry_timestamp,
)
from server.projections.portfolio_views.historical_series import (
    load_ledger_entries_for_equity_series as _load_ledger_entries_for_equity_series,
)
from server.projections.portfolio_views.historical_series import (
    quote_valuation_date as _quote_valuation_date,
)
from server.projections.portfolio_views.historical_series import (
    trim_intraday_terminal_series_point as _trim_intraday_terminal_series_point,
)
from server.projections.portfolio_views.historical_series import (
    trim_non_trading_terminal_series_point as _trim_non_trading_terminal_series_point,
)
from server.projections.portfolio_views.intraday_series import (
    append_current_equity_series_point as _append_current_equity_series_point,
)
from server.projections.portfolio_views.intraday_series import (
    build_cn_session_ticks as _build_cn_session_ticks,
)
from server.projections.portfolio_views.intraday_series import (
    build_intraday_equity_curve_series as _build_intraday_equity_curve_series,
)
from server.projections.portfolio_views.intraday_series import (
    combine_session_time as _combine_session_time,
)
from server.projections.portfolio_views.intraday_series import (
    current_equity_series_point as _current_equity_series_point,
)
from server.projections.portfolio_views.intraday_series import (
    floor_session_timestamp as _floor_session_timestamp,
)
from server.projections.portfolio_views.intraday_series import (
    load_intraday_price_points as _load_intraday_price_points,
)
from server.projections.portfolio_views.intraday_series import (
    load_local_intraday_quote_points as _load_local_intraday_quote_points,
)
from server.projections.portfolio_views.intraday_series import (
    normalize_intraday_timestamp as _normalize_intraday_timestamp,
)
from server.projections.portfolio_views.live_holdings import (
    build_live_holdings_response as _build_live_holdings_response,
)
from server.projections.portfolio_views.live_holdings import (
    get_recent_quote_snapshots as _get_recent_quote_snapshots,
)
from server.projections.portfolio_views.live_holdings import (
    has_same_day_sell as _has_same_day_sell,
)
from server.projections.portfolio_views.live_holdings import (
    resolve_live_holding_latest_price as _resolve_live_holding_latest_price,
)
from server.projections.portfolio_views.live_holdings import (
    session_closed_market_bar_price as _session_closed_market_bar_price,
)
from server.projections.portfolio_views.manual_trade import (
    fund_target_trade_date as _fund_target_trade_date,
)
from server.projections.portfolio_views.manual_trade import (
    manual_trade_fee_breakdown as _manual_trade_fee_breakdown,
)
from server.projections.portfolio_views.manual_trade import (
    manual_trade_net_cash_impact as _manual_trade_net_cash_impact,
)
from server.projections.portfolio_views.manual_trade import (
    manual_trade_preview_payload as _manual_trade_preview_payload,
)
from server.projections.portfolio_views.manual_trade import (
    resolve_display_name as _resolve_display_name,
)
from server.projections.portfolio_views.manual_trade import (
    resolve_fund_identity as _resolve_fund_identity,
)
from server.projections.portfolio_views.overview import dict_payload as _dict_payload
from server.projections.portfolio_views.overview import (
    overview_daily_operations_summary as _overview_daily_operations_summary,
)
from server.projections.portfolio_views.overview import (
    overview_today_pnl_update as _overview_today_pnl_update,
)
from server.projections.portfolio_views.overview import (
    portfolio_account_truth_gate_status as _portfolio_account_truth_gate_status,
)
from server.projections.portfolio_views.overview import (
    portfolio_construction_rationale as _portfolio_construction_rationale,
)
from server.projections.portfolio_views.overview import (
    portfolio_construction_recommendations as _portfolio_construction_recommendations,
)
from server.projections.portfolio_views.overview import (
    portfolio_construction_required_actions as _portfolio_construction_required_actions,
)
from server.projections.portfolio_views.overview import (
    portfolio_construction_status as _portfolio_construction_status,
)
from server.projections.portfolio_views.synthetic_series import (
    series_point_from_intraday as _series_point_from_intraday,
)
from server.projections.portfolio_views.synthetic_series import (
    should_fetch_intraday_equity_curve as _should_fetch_intraday_equity_curve,
)
from server.projections.portfolio_views.synthetic_series import (
    synthetic_intraday_equity_series_from_current_quotes as _synthetic_intraday_equity_series_from_current_quotes,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.quote_status import quote_status as _quote_status
from server.projections.service import (
    build_equity_curve_from_db,
    build_equity_series_from_db,
    build_portfolio_projection,
)
from server.services.account_state import build_account_state_projection
from server.services.asset_metadata import resolve_asset_metadata
from server.services.current_holding_market_evidence_review import (
    build_current_holding_market_evidence_review,
)
from server.services.daily_operations import build_daily_operations_summary
from server.services.daily_performance import (
    build_position_daily_context,
    calculate_account_daily_performance,
    mark_position_daily,
    price_at_tick,
)
from server.services.manual_trade_fees import (
    MANUAL_FEE_INPUT_RULE_ID,
    MANUAL_FEE_INPUT_RULE_VERSION,
    manual_fee_input_payload,
    resolve_manual_trade_fee_breakdown,
)
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.position_presence import (
    is_economically_zero_quantity,
)
from server.services.risk_engine import build_risk_summary
from server.services.risk_workspace import build_risk_workspace
from server.services.valuation_snapshot import (
    build_current_valuation_snapshot,
    valuation_identity_fields,
    valuation_snapshot_from_row,
)

logger = logging.getLogger(__name__)
_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)
_CN_MORNING_OPEN = time(9, 30)
_CN_MORNING_CLOSE = time(11, 30)
_CN_AFTERNOON_OPEN = time(13, 0)
_CN_AFTERNOON_CLOSE = time(15, 0)
_INTRADAY_STEP_MINUTES = 5
_SH_TZ = ZoneInfo("Asia/Shanghai")
_EQUITY_SERIES_RANGE_DAYS = {
    "5d": 5,
    "1m": 31,
    "6m": 183,
    "1y": 366,
}

_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


_TIMELINE_MARKET_COMPONENTS = (
    ("stock", "stocks"),
    ("fund", "funds"),
    ("other", "others"),
)

_EXTERNAL_FLOW_LABELS = {
    "cash_deposit": "入金",
    "cash_withdrawal": "出金",
    "cash_interest": "现金利息",
    "dividend": "分红",
    "manual_adjustment": "手工调整",
}

_CASH_INCOME_LEDGER_TYPES = {"cash_interest", "dividend"}

_CAPITAL_INFLOW_LEDGER_TYPES = {"cash_deposit", "deposit"}
_CAPITAL_OUTFLOW_LEDGER_TYPES = {"cash_withdrawal", "cash_withdraw", "withdraw"}


def create_router() -> APIRouter:
    facade = sys.modules[__name__]
    endpoints = {}
    router = APIRouter()
    router.routes.extend(_create_snapshot_router(facade, endpoints).routes)
    router.routes.extend(_create_performance_router(facade, endpoints).routes)
    router.routes.extend(_create_analysis_router(facade, endpoints).routes)
    router.routes.extend(_create_cash_flows_router(facade, endpoints).routes)
    router.routes.extend(_create_trades_router(facade, endpoints).routes)
    return router


def current_valuation_snapshot(state) -> dict:
    """Compatibility port for non-HTTP composition callers."""

    return _current_valuation_snapshot(state)


def quotes_from_valuation_snapshot(payload: dict) -> dict[str, dict]:
    """Compatibility port for non-HTTP composition callers."""

    return _quotes_from_valuation_snapshot(payload)


def resolve_projection_sources(
    state,
    *,
    latest_quotes: dict[str, dict] | None = None,
) -> tuple[object | None, dict]:
    """Compatibility port for non-HTTP composition callers."""

    return _resolve_projection_sources(state, latest_quotes=latest_quotes)
