"""Explicit composition contracts for portfolio HTTP endpoint modules."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from types import ModuleType
from typing import Any

from server.contracts.http.ledger_models import EquityPoint, EquitySeriesPoint
from server.contracts.http.portfolio_models import PortfolioSnapshot

Operation = Callable[..., Any]
StateProvider = Callable[[], Any]
ServiceFactory = Callable[[Any], Any]


@dataclass(frozen=True, slots=True)
class PortfolioPerformanceOperations:
    get_equity_curve: Callable[[], Awaitable[list[EquityPoint]]]
    get_equity_curve_series: Callable[[str], Awaitable[list[EquitySeriesPoint]]]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotOperations:
    get_portfolio: Callable[[], Awaitable[PortfolioSnapshot]]


@dataclass(frozen=True, slots=True)
class PortfolioPerformanceDependencies:
    get_state: StateProvider
    append_current_equity_series_point: Operation
    bind_current_equity_valuation: Operation
    bind_equity_series_valuation: Operation
    build_activity_items: Operation
    build_intraday_equity_curve_series: Operation
    collect_latest_quotes: Operation
    current_equity_series_point: Operation
    current_valuation_snapshot: Operation
    daily_equity_series_for_range: Operation
    daily_equity_series_from_ledger_history: Operation
    flat_intraday_equity_series_from_current: Operation
    has_rows: Operation
    hydrate_missing_position_quotes: Operation
    parse_quote_timestamp: Operation
    quotes_from_valuation_snapshot: Operation
    resolve_projection_sources: Operation
    series_point_from_intraday: Operation
    should_fetch_intraday_equity_curve: Operation
    synthetic_intraday_equity_series_from_current_quotes: Operation
    build_equity_curve_from_db: Operation
    build_equity_series_from_db: Operation
    get_shanghai_now: Operation
    async_runtime: ModuleType
    logger: Logger


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotDependencies:
    get_state: StateProvider
    build_live_holdings_response: Operation
    cash_flow_adjusted_equity_points_from_series: Operation
    collect_latest_quote_timestamps: Operation
    equity_series_matches_valuation: Operation
    overview_daily_operations_summary: Operation
    overview_today_pnl_update: Operation
    portfolio_account_truth_gate_status: Operation
    portfolio_construction_recommendations: Operation
    with_overview_quote_metadata: Operation
    build_account_state_projection: Operation
    build_account_state_response: Operation
    build_current_holding_market_evidence_review: Operation
    build_current_valuation_snapshot: Operation
    build_portfolio_snapshot: Operation
    build_risk_summary: Operation
    build_risk_workspace: Operation
    get_shanghai_now: Operation
    valuation_snapshot_from_row: Operation


@dataclass(frozen=True, slots=True)
class PortfolioAnalysisDependencies:
    get_state: StateProvider
    build_equity_bridge: Operation
    build_position_drivers: Operation
    build_recent_drivers: Operation
    build_timeline: Operation
    cash_flow_adjusted_equity_points_from_series: Operation
    collect_latest_quote_timestamps: Operation
    dedupe_equity_series_points_by_date: Operation
    equity_points_from_series: Operation
    equity_series_components_by_date: Operation
    equity_series_matches_valuation: Operation
    equity_series_metadata_by_date: Operation
    trim_intraday_terminal_series_point: Operation
    trim_non_trading_terminal_series_point: Operation
    build_account_state_projection: Operation
    build_risk_summary: Operation
    build_risk_workspace: Operation
    get_shanghai_now: Operation


@dataclass(frozen=True, slots=True)
class PortfolioCashFlowDependencies:
    get_state: StateProvider
    command_service_factory: ServiceFactory
    manual_trade_preview_payload: Operation


@dataclass(frozen=True, slots=True)
class PortfolioTradeDependencies:
    get_state: StateProvider
    command_service_factory: ServiceFactory


@dataclass(frozen=True, slots=True)
class PortfolioEndpointDependencies:
    performance: PortfolioPerformanceDependencies
    snapshot: PortfolioSnapshotDependencies
    analysis: PortfolioAnalysisDependencies
    cash_flows: PortfolioCashFlowDependencies
    trades: PortfolioTradeDependencies


__all__ = [
    "PortfolioAnalysisDependencies",
    "PortfolioCashFlowDependencies",
    "PortfolioEndpointDependencies",
    "PortfolioPerformanceDependencies",
    "PortfolioPerformanceOperations",
    "PortfolioSnapshotDependencies",
    "PortfolioSnapshotOperations",
    "PortfolioTradeDependencies",
]
