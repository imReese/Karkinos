"""Portfolio routes — /api/portfolio/*"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from server.http.portfolio_endpoints.analysis import (
    create_router as _create_analysis_router,
)
from server.http.portfolio_endpoints.cash_flows import (
    create_router as _create_cash_flows_router,
)
from server.http.portfolio_endpoints.dependencies import (
    PortfolioAnalysisDependencies,
    PortfolioCashFlowDependencies,
    PortfolioEndpointDependencies,
    PortfolioPerformanceDependencies,
    PortfolioSnapshotDependencies,
    PortfolioTradeDependencies,
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
from server.models import (
    AccountOverview,
    AccountStateResponse,
    EquitySeriesPoint,
    LiveHoldingGroupResponse,
    LiveHoldingItemResponse,
    LiveHoldingsResponse,
    PortfolioSnapshot,
    TradeCreate,
)
from server.projections.portfolio_application import (
    build_account_state_response as _build_account_state_response,
)
from server.projections.portfolio_application import (
    build_portfolio_snapshot as _build_portfolio_snapshot,
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
from server.projections.portfolio_application import has_rows as _has_rows
from server.projections.portfolio_application import (
    hydrate_missing_position_quotes as _hydrate_missing_position_quotes,
)
from server.projections.portfolio_application import (
    position_quote_presentation as _position_quote_presentation,
)
from server.projections.portfolio_application import (
    quote_stale_reason as _quote_stale_reason,
)
from server.projections.portfolio_application import (
    quotes_from_valuation_snapshot as _quotes_from_valuation_snapshot,
)
from server.projections.portfolio_application import (
    read_daily_ledger_entries as _read_daily_ledger_entries,
)
from server.projections.portfolio_application import (
    resolve_position_today_change as _resolve_position_today_change,
)
from server.projections.portfolio_application import (
    resolve_projection_sources as _resolve_projection_sources,
)
from server.projections.portfolio_application import (
    with_overview_quote_metadata as _raw_with_overview_quote_metadata,
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
    equity_series_components_by_date as _equity_series_components_by_date,
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
    equity_series_matches_valuation as _equity_series_matches_valuation,
)
from server.projections.portfolio_views.historical_series import (
    equity_series_metadata_by_date as _equity_series_metadata_by_date,
)
from server.projections.portfolio_views.historical_series import (
    flat_intraday_equity_series_from_current as _flat_intraday_equity_series_from_current,
)
from server.projections.portfolio_views.historical_series import (
    historical_quote_for_equity_day as _historical_quote_for_equity_day,
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
    build_intraday_equity_curve_series as _build_intraday_equity_curve_series,
)
from server.projections.portfolio_views.intraday_series import (
    current_equity_series_point as _current_equity_series_point,
)
from server.projections.portfolio_views.live_holdings import (
    build_live_holdings_response as _raw_build_live_holdings_response,
)
from server.projections.portfolio_views.manual_trade import (
    manual_trade_preview_payload as _manual_trade_preview_payload,
)
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
    portfolio_construction_recommendations as _portfolio_construction_recommendations,
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
)
from server.services.account_state import build_account_state_projection
from server.services.current_holding_market_evidence_review import (
    build_current_holding_market_evidence_review,
)
from server.services.market_hours import get_shanghai_now
from server.services.portfolio_cash_flow_commands import (
    PortfolioCashFlowCommandService,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.portfolio_trade_commands import (
    PortfolioTradeCommandService,
)
from server.services.risk_engine import build_risk_summary
from server.services.risk_workspace import build_risk_workspace
from server.services.valuation_snapshot import (
    build_current_valuation_snapshot,
    valuation_snapshot_from_row,
)

logger = logging.getLogger(__name__)


async def build_portfolio_snapshot(state) -> PortfolioSnapshot:
    """Bind the route clock while delegating projection ownership."""

    return await _build_portfolio_snapshot(state, now=get_shanghai_now())


async def build_account_state_response(
    state,
    *,
    snapshot: PortfolioSnapshot | None = None,
) -> AccountStateResponse:
    """Bind the route clock while delegating account-state composition."""

    return await _build_account_state_response(
        state,
        snapshot=snapshot,
        now=get_shanghai_now(),
    )


def _build_live_holdings_response(
    state,
    valuation_snapshot: dict | None = None,
) -> LiveHoldingsResponse:
    """Bind the request clock for live-holding evidence semantics."""

    return _raw_build_live_holdings_response(
        state,
        valuation_snapshot,
        now=get_shanghai_now(),
    )


def _with_overview_quote_metadata(
    overview: AccountOverview,
    snapshot: PortfolioSnapshot,
) -> AccountOverview:
    """Bind the request clock for overview quote metadata."""

    return _raw_with_overview_quote_metadata(
        overview,
        snapshot,
        now=get_shanghai_now(),
    )


def _get_portfolio_state():
    """Resolve request state through one explicit composition-root provider."""

    from server.dependencies import get_app_state

    return get_app_state()


def build_portfolio_endpoint_dependencies() -> PortfolioEndpointDependencies:
    """Bind every portfolio endpoint dependency without dynamic lookup."""

    return PortfolioEndpointDependencies(
        performance=PortfolioPerformanceDependencies(
            get_state=_get_portfolio_state,
            append_current_equity_series_point=lambda *args, **kwargs: (
                _append_current_equity_series_point(*args, **kwargs)
            ),
            bind_current_equity_valuation=lambda *args, **kwargs: (
                _bind_current_equity_valuation(*args, **kwargs)
            ),
            bind_equity_series_valuation=lambda *args, **kwargs: (
                _bind_equity_series_valuation(*args, **kwargs)
            ),
            build_activity_items=lambda *args, **kwargs: _build_activity_items(
                *args, **kwargs
            ),
            build_intraday_equity_curve_series=lambda *args, **kwargs: (
                _build_intraday_equity_curve_series(*args, **kwargs)
            ),
            collect_latest_quotes=lambda *args, **kwargs: _collect_latest_quotes(
                *args, **kwargs
            ),
            current_equity_series_point=lambda *args, **kwargs: (
                _current_equity_series_point(*args, **kwargs)
            ),
            current_valuation_snapshot=lambda *args, **kwargs: (
                _current_valuation_snapshot(*args, **kwargs)
            ),
            daily_equity_series_for_range=lambda *args, **kwargs: (
                _daily_equity_series_for_range(*args, **kwargs)
            ),
            daily_equity_series_from_ledger_history=lambda *args, **kwargs: (
                _daily_equity_series_from_ledger_history(*args, **kwargs)
            ),
            flat_intraday_equity_series_from_current=lambda *args, **kwargs: (
                _flat_intraday_equity_series_from_current(*args, **kwargs)
            ),
            has_rows=lambda *args, **kwargs: _has_rows(*args, **kwargs),
            hydrate_missing_position_quotes=lambda *args, **kwargs: (
                _hydrate_missing_position_quotes(*args, **kwargs)
            ),
            parse_quote_timestamp=lambda *args, **kwargs: _parse_quote_timestamp(
                *args, **kwargs
            ),
            quotes_from_valuation_snapshot=lambda *args, **kwargs: (
                _quotes_from_valuation_snapshot(*args, **kwargs)
            ),
            resolve_projection_sources=lambda *args, **kwargs: (
                _resolve_projection_sources(*args, **kwargs)
            ),
            series_point_from_intraday=lambda *args, **kwargs: (
                _series_point_from_intraday(*args, **kwargs)
            ),
            should_fetch_intraday_equity_curve=lambda *args, **kwargs: (
                _should_fetch_intraday_equity_curve(*args, **kwargs)
            ),
            synthetic_intraday_equity_series_from_current_quotes=(
                lambda *args, **kwargs: (
                    _synthetic_intraday_equity_series_from_current_quotes(
                        *args, **kwargs
                    )
                )
            ),
            build_equity_curve_from_db=lambda *args, **kwargs: (
                build_equity_curve_from_db(*args, **kwargs)
            ),
            build_equity_series_from_db=lambda *args, **kwargs: (
                build_equity_series_from_db(*args, **kwargs)
            ),
            get_shanghai_now=lambda *args, **kwargs: get_shanghai_now(*args, **kwargs),
            async_runtime=asyncio,
            logger=logger,
        ),
        snapshot=PortfolioSnapshotDependencies(
            get_state=_get_portfolio_state,
            build_live_holdings_response=lambda *args, **kwargs: (
                _build_live_holdings_response(*args, **kwargs)
            ),
            cash_flow_adjusted_equity_points_from_series=lambda *args, **kwargs: (
                _cash_flow_adjusted_equity_points_from_series(*args, **kwargs)
            ),
            collect_latest_quote_timestamps=lambda *args, **kwargs: (
                _collect_latest_quote_timestamps(*args, **kwargs)
            ),
            equity_series_matches_valuation=lambda *args, **kwargs: (
                _equity_series_matches_valuation(*args, **kwargs)
            ),
            overview_daily_operations_summary=lambda *args, **kwargs: (
                _overview_daily_operations_summary(*args, **kwargs)
            ),
            overview_today_pnl_update=lambda *args, **kwargs: (
                _overview_today_pnl_update(*args, **kwargs)
            ),
            portfolio_account_truth_gate_status=lambda *args, **kwargs: (
                _portfolio_account_truth_gate_status(*args, **kwargs)
            ),
            portfolio_construction_recommendations=lambda *args, **kwargs: (
                _portfolio_construction_recommendations(*args, **kwargs)
            ),
            with_overview_quote_metadata=lambda *args, **kwargs: (
                _with_overview_quote_metadata(*args, **kwargs)
            ),
            build_account_state_projection=lambda *args, **kwargs: (
                build_account_state_projection(*args, **kwargs)
            ),
            build_account_state_response=lambda *args, **kwargs: (
                build_account_state_response(*args, **kwargs)
            ),
            build_current_holding_market_evidence_review=(
                lambda *args, **kwargs: build_current_holding_market_evidence_review(
                    *args, **kwargs
                )
            ),
            build_current_valuation_snapshot=lambda *args, **kwargs: (
                build_current_valuation_snapshot(*args, **kwargs)
            ),
            build_portfolio_snapshot=lambda *args, **kwargs: build_portfolio_snapshot(
                *args, **kwargs
            ),
            build_risk_summary=lambda *args, **kwargs: build_risk_summary(
                *args, **kwargs
            ),
            build_risk_workspace=lambda *args, **kwargs: build_risk_workspace(
                *args, **kwargs
            ),
            get_shanghai_now=lambda *args, **kwargs: get_shanghai_now(*args, **kwargs),
            valuation_snapshot_from_row=lambda *args, **kwargs: (
                valuation_snapshot_from_row(*args, **kwargs)
            ),
        ),
        analysis=PortfolioAnalysisDependencies(
            get_state=_get_portfolio_state,
            build_equity_bridge=lambda *args, **kwargs: _build_equity_bridge(
                *args, **kwargs
            ),
            build_position_drivers=lambda *args, **kwargs: _build_position_drivers(
                *args, **kwargs
            ),
            build_recent_drivers=lambda *args, **kwargs: _build_recent_drivers(
                *args, **kwargs
            ),
            build_timeline=lambda *args, **kwargs: _build_timeline(*args, **kwargs),
            cash_flow_adjusted_equity_points_from_series=lambda *args, **kwargs: (
                _cash_flow_adjusted_equity_points_from_series(*args, **kwargs)
            ),
            collect_latest_quote_timestamps=lambda *args, **kwargs: (
                _collect_latest_quote_timestamps(*args, **kwargs)
            ),
            dedupe_equity_series_points_by_date=lambda *args, **kwargs: (
                _dedupe_equity_series_points_by_date(*args, **kwargs)
            ),
            equity_points_from_series=lambda *args, **kwargs: (
                _equity_points_from_series(*args, **kwargs)
            ),
            equity_series_components_by_date=lambda *args, **kwargs: (
                _equity_series_components_by_date(*args, **kwargs)
            ),
            equity_series_matches_valuation=lambda *args, **kwargs: (
                _equity_series_matches_valuation(*args, **kwargs)
            ),
            equity_series_metadata_by_date=lambda *args, **kwargs: (
                _equity_series_metadata_by_date(*args, **kwargs)
            ),
            trim_intraday_terminal_series_point=lambda *args, **kwargs: (
                _trim_intraday_terminal_series_point(*args, **kwargs)
            ),
            trim_non_trading_terminal_series_point=lambda *args, **kwargs: (
                _trim_non_trading_terminal_series_point(*args, **kwargs)
            ),
            build_account_state_projection=lambda *args, **kwargs: (
                build_account_state_projection(*args, **kwargs)
            ),
            build_risk_summary=lambda *args, **kwargs: build_risk_summary(
                *args, **kwargs
            ),
            build_risk_workspace=lambda *args, **kwargs: build_risk_workspace(
                *args, **kwargs
            ),
            get_shanghai_now=lambda *args, **kwargs: get_shanghai_now(*args, **kwargs),
        ),
        cash_flows=PortfolioCashFlowDependencies(
            get_state=_get_portfolio_state,
            command_service_factory=lambda state: PortfolioCashFlowCommandService(
                state
            ),
            manual_trade_preview_payload=lambda *args, **kwargs: (
                _manual_trade_preview_payload(*args, **kwargs)
            ),
        ),
        trades=PortfolioTradeDependencies(
            get_state=_get_portfolio_state,
            command_service_factory=lambda state: PortfolioTradeCommandService(state),
        ),
    )


def create_router(
    dependencies: PortfolioEndpointDependencies | None = None,
) -> APIRouter:
    dependencies = dependencies or build_portfolio_endpoint_dependencies()
    performance = _create_performance_router(dependencies.performance)
    snapshot = _create_snapshot_router(
        dependencies.snapshot,
        performance.operations,
    )
    analysis = _create_analysis_router(
        dependencies.analysis,
        snapshot.operations,
        performance.operations,
    )
    router = APIRouter()
    router.routes.extend(snapshot.router.routes)
    router.routes.extend(performance.router.routes)
    router.routes.extend(analysis.routes)
    router.routes.extend(_create_cash_flows_router(dependencies.cash_flows).routes)
    router.routes.extend(_create_trades_router(dependencies.trades).routes)
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
