"""Portfolio analysis HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from server.contracts.http.ledger_models import EquityPoint
from server.contracts.http.portfolio_models import (
    ExplainabilityResponse,
    RiskWorkspaceResponse,
)


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _build_equity_bridge = dependency("_build_equity_bridge")
    _build_position_drivers = dependency("_build_position_drivers")
    _build_recent_drivers = dependency("_build_recent_drivers")
    _build_timeline = dependency("_build_timeline")
    _cash_flow_adjusted_equity_points_from_series = dependency(
        "_cash_flow_adjusted_equity_points_from_series"
    )
    _collect_latest_quote_timestamps = dependency("_collect_latest_quote_timestamps")
    _dedupe_equity_series_points_by_date = dependency(
        "_dedupe_equity_series_points_by_date"
    )
    _equity_points_from_series = dependency("_equity_points_from_series")
    _equity_series_components_by_date = dependency("_equity_series_components_by_date")
    _equity_series_matches_valuation = dependency("_equity_series_matches_valuation")
    _equity_series_metadata_by_date = dependency("_equity_series_metadata_by_date")
    _trim_intraday_terminal_series_point = dependency(
        "_trim_intraday_terminal_series_point"
    )
    _trim_non_trading_terminal_series_point = dependency(
        "_trim_non_trading_terminal_series_point"
    )
    build_account_state_projection = dependency("build_account_state_projection")
    build_risk_summary = dependency("build_risk_summary")
    build_risk_workspace = dependency("build_risk_workspace")
    get_shanghai_now = dependency("get_shanghai_now")

    def get_portfolio(*args, **kwargs):
        return endpoints["get_portfolio"](*args, **kwargs)

    def get_equity_curve(*args, **kwargs):
        return endpoints["get_equity_curve"](*args, **kwargs)

    def get_equity_curve_series(*args, **kwargs):
        return endpoints["get_equity_curve_series"](*args, **kwargs)

    @r.get("/explainability", response_model=ExplainabilityResponse)
    async def get_explainability(
        limit: int = 50,
        from_date: str | None = None,
        to_date: str | None = None,
        event_kind: str | None = None,
    ) -> ExplainabilityResponse:
        """Return traceable drivers for equity, PnL, and current positions."""
        from server.dependencies import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        summary = build_account_state_projection(
            snapshot,
            build_risk_summary(snapshot, _collect_latest_quote_timestamps(state)),
        ).summary
        equity_curve: list[EquityPoint] = []
        equity_valuation_consistent = True
        valuation_status_by_date: dict[str, str] = {}
        missing_price_symbols_by_date: dict[str, list[str]] = {}
        component_values_by_date: dict[str, dict[str, float]] = {}
        if state.db is not None and (
            hasattr(state.db, "get_latest_daily_close_before_sync")
            or hasattr(state.db, "get_latest_quote_before_date_sync")
        ):
            equity_series = await get_equity_curve_series("all")
            equity_valuation_consistent = _equity_series_matches_valuation(
                equity_series,
                snapshot.valuation_snapshot_id,
            )
            equity_series = _trim_non_trading_terminal_series_point(equity_series)
            equity_series = _trim_intraday_terminal_series_point(equity_series)
            equity_series = _dedupe_equity_series_points_by_date(equity_series)
            equity_curve = _equity_points_from_series(equity_series)
            component_values_by_date = _equity_series_components_by_date(equity_series)
            (
                valuation_status_by_date,
                missing_price_symbols_by_date,
            ) = _equity_series_metadata_by_date(equity_series)
        if equity_valuation_consistent and not equity_curve:
            equity_curve = await get_equity_curve()

        entries = []
        if state.db is not None and hasattr(state.db, "get_ledger_entries_sync"):
            entries = state.db.get_ledger_entries_sync(limit=limit, offset=0)

        return ExplainabilityResponse(
            equity_bridge=_build_equity_bridge(snapshot, summary),
            recent_drivers=_build_recent_drivers(state, entries),
            positions=_build_position_drivers(snapshot, entries),
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
            valuation_snapshot_id=snapshot.valuation_snapshot_id,
            valuation_as_of=snapshot.valuation_as_of,
            valuation_trade_date=snapshot.valuation_trade_date,
            valuation_policy=snapshot.valuation_policy,
            valuation_status=(
                snapshot.valuation_status if equity_valuation_consistent else "missing"
            ),
            ledger_cutoff_id=snapshot.ledger_cutoff_id,
            ledger_fingerprint=snapshot.ledger_fingerprint,
            quote_set_fingerprint=snapshot.quote_set_fingerprint,
        )

    @r.get("/risk-workspace", response_model=RiskWorkspaceResponse)
    async def get_risk_workspace() -> RiskWorkspaceResponse:
        """Return richer drawdown, exposure, and concentration diagnostics."""
        from server.dependencies import get_app_state

        state = get_app_state()
        snapshot = await get_portfolio()
        equity_series = await get_equity_curve_series("all")
        equity_curve = _cash_flow_adjusted_equity_points_from_series(
            state,
            equity_series,
        )
        if not _equity_series_matches_valuation(
            equity_series,
            snapshot.valuation_snapshot_id,
        ):
            equity_curve = [
                EquityPoint(
                    timestamp=snapshot.valuation_as_of
                    or get_shanghai_now().isoformat(),
                    equity=snapshot.total_equity,
                )
            ]
        elif not equity_curve:
            equity_curve = await get_equity_curve()
        return build_risk_workspace(snapshot, equity_curve)

    return r
