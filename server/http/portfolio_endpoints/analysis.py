"""Portfolio analysis HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from server.contracts.http.ledger_models import EquityPoint, EquitySeriesPoint
from server.contracts.http.portfolio_models import (
    ExplainabilityResponse,
    RiskWorkspaceResponse,
)
from server.http.portfolio_endpoints.dependencies import (
    PortfolioAnalysisDependencies,
    PortfolioPerformanceOperations,
    PortfolioSnapshotOperations,
)
from server.projections.portfolio_read_snapshot_persistence import (
    portfolio_read_snapshot_for_state,
)


def create_router(
    dependencies: PortfolioAnalysisDependencies,
    snapshot: PortfolioSnapshotOperations,
    performance: PortfolioPerformanceOperations,
) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    _build_equity_bridge = dependencies.build_equity_bridge
    _build_position_drivers = dependencies.build_position_drivers
    _build_recent_drivers = dependencies.build_recent_drivers
    _build_timeline = dependencies.build_timeline
    _cash_flow_adjusted_equity_points_from_series = (
        dependencies.cash_flow_adjusted_equity_points_from_series
    )
    _collect_latest_quote_timestamps = dependencies.collect_latest_quote_timestamps
    _dedupe_equity_series_points_by_date = (
        dependencies.dedupe_equity_series_points_by_date
    )
    _equity_points_from_series = dependencies.equity_points_from_series
    _equity_series_components_by_date = dependencies.equity_series_components_by_date
    _equity_series_matches_valuation = dependencies.equity_series_matches_valuation
    _equity_series_metadata_by_date = dependencies.equity_series_metadata_by_date
    _trim_intraday_terminal_series_point = (
        dependencies.trim_intraday_terminal_series_point
    )
    _trim_non_trading_terminal_series_point = (
        dependencies.trim_non_trading_terminal_series_point
    )
    build_account_state_projection = dependencies.build_account_state_projection
    build_risk_summary = dependencies.build_risk_summary
    build_risk_workspace = dependencies.build_risk_workspace
    get_shanghai_now = dependencies.get_shanghai_now

    @r.get("/explainability", response_model=ExplainabilityResponse)
    async def get_explainability(
        limit: int = 50,
        from_date: str | None = None,
        to_date: str | None = None,
        event_kind: str | None = None,
    ) -> ExplainabilityResponse:
        """Return traceable drivers for equity, PnL, and current positions."""
        state = dependencies.get_state()
        portfolio_snapshot = await snapshot.get_portfolio()
        summary = build_account_state_projection(
            portfolio_snapshot,
            build_risk_summary(
                portfolio_snapshot,
                _collect_latest_quote_timestamps(state),
            ),
        ).summary
        equity_curve: list[EquityPoint | EquitySeriesPoint] = []
        equity_valuation_consistent = True
        valuation_status_by_date: dict[str, str] = {}
        missing_price_symbols_by_date: dict[str, list[str]] = {}
        component_values_by_date: dict[str, dict[str, float]] = {}
        if state.db is not None and (
            hasattr(state.db, "get_latest_daily_close_before_sync")
            or hasattr(state.db, "get_latest_quote_before_date_sync")
        ):
            equity_series = await performance.get_equity_curve_series("all")
            equity_valuation_consistent = _equity_series_matches_valuation(
                equity_series,
                portfolio_snapshot.valuation_snapshot_id,
            )
            equity_series = _trim_non_trading_terminal_series_point(equity_series)
            equity_series = _trim_intraday_terminal_series_point(equity_series)
            equity_series = _dedupe_equity_series_points_by_date(equity_series)
            equity_curve = equity_series
            component_values_by_date = _equity_series_components_by_date(equity_series)
            (
                valuation_status_by_date,
                missing_price_symbols_by_date,
            ) = _equity_series_metadata_by_date(equity_series)
        if equity_valuation_consistent and not equity_curve:
            equity_curve = await performance.get_equity_curve()

        read_snapshot = portfolio_read_snapshot_for_state(state)
        if read_snapshot is not None:
            entries = sorted(
                (dict(row) for row in read_snapshot.ledger_rows),
                key=lambda row: (
                    str(row.get("timestamp") or ""),
                    int(row.get("id") or 0),
                ),
                reverse=True,
            )[:limit]
        elif state.db is not None and hasattr(state.db, "get_ledger_entries_sync"):
            entries = state.db.get_ledger_entries_sync(limit=limit, offset=0)
        else:
            entries = []

        return ExplainabilityResponse(
            equity_bridge=_build_equity_bridge(portfolio_snapshot, summary),
            recent_drivers=_build_recent_drivers(state, entries),
            positions=_build_position_drivers(portfolio_snapshot, entries),
            timeline=(
                _build_timeline(
                    equity_curve,
                    entries,
                    state=state,
                    event_kind=event_kind,
                    from_date=from_date,
                    to_date=to_date,
                    valuation_status_by_date=valuation_status_by_date,
                    missing_price_symbols_by_date=missing_price_symbols_by_date,
                    component_values_by_date=component_values_by_date,
                )
                if equity_valuation_consistent
                else []
            ),
            valuation_snapshot_id=portfolio_snapshot.valuation_snapshot_id,
            valuation_as_of=portfolio_snapshot.valuation_as_of,
            valuation_trade_date=portfolio_snapshot.valuation_trade_date,
            valuation_policy=portfolio_snapshot.valuation_policy,
            valuation_status=(
                portfolio_snapshot.valuation_status
                if equity_valuation_consistent
                else "missing"
            ),
            ledger_cutoff_id=portfolio_snapshot.ledger_cutoff_id,
            ledger_fingerprint=portfolio_snapshot.ledger_fingerprint,
            quote_set_fingerprint=portfolio_snapshot.quote_set_fingerprint,
        )

    @r.get("/risk-workspace", response_model=RiskWorkspaceResponse)
    async def get_risk_workspace() -> RiskWorkspaceResponse:
        """Return richer drawdown, exposure, and concentration diagnostics."""
        state = dependencies.get_state()
        portfolio_snapshot = await snapshot.get_portfolio()
        equity_series = await performance.get_equity_curve_series("all")
        equity_curve = _cash_flow_adjusted_equity_points_from_series(
            state,
            equity_series,
        )
        if (
            not _equity_series_matches_valuation(
                equity_series,
                portfolio_snapshot.valuation_snapshot_id,
            )
            and portfolio_snapshot.total_equity is not None
        ):
            equity_curve = [
                EquityPoint(
                    timestamp=portfolio_snapshot.valuation_as_of
                    or get_shanghai_now().isoformat(),
                    equity=portfolio_snapshot.total_equity,
                )
            ]
        elif not equity_curve:
            equity_curve = await performance.get_equity_curve()
        return build_risk_workspace(portfolio_snapshot, equity_curve)

    return r


__all__ = ["create_router"]
