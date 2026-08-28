"""Portfolio performance HTTP endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter

from server.contracts.http.ledger_models import (
    ActivityItem,
    EquityPoint,
    EquitySeriesPoint,
)
from server.http.portfolio_endpoints.dependencies import (
    PortfolioPerformanceDependencies,
    PortfolioPerformanceOperations,
)


@dataclass(frozen=True, slots=True)
class PortfolioPerformanceEndpoints:
    router: APIRouter
    operations: PortfolioPerformanceOperations


def create_router(
    dependencies: PortfolioPerformanceDependencies,
) -> PortfolioPerformanceEndpoints:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    _append_current_equity_series_point = (
        dependencies.append_current_equity_series_point
    )
    _bind_current_equity_valuation = dependencies.bind_current_equity_valuation
    _bind_equity_series_valuation = dependencies.bind_equity_series_valuation
    _build_activity_items = dependencies.build_activity_items
    _build_intraday_equity_curve_series = (
        dependencies.build_intraday_equity_curve_series
    )
    _collect_latest_quotes = dependencies.collect_latest_quotes
    _current_equity_series_point = dependencies.current_equity_series_point
    _current_valuation_snapshot = dependencies.current_valuation_snapshot
    _daily_equity_series_for_range = dependencies.daily_equity_series_for_range
    _daily_equity_series_from_ledger_history = (
        dependencies.daily_equity_series_from_ledger_history
    )
    _flat_intraday_equity_series_from_current = (
        dependencies.flat_intraday_equity_series_from_current
    )
    _has_rows = dependencies.has_rows
    _hydrate_missing_position_quotes = dependencies.hydrate_missing_position_quotes
    _parse_quote_timestamp = dependencies.parse_quote_timestamp
    _quotes_from_valuation_snapshot = dependencies.quotes_from_valuation_snapshot
    _resolve_projection_sources = dependencies.resolve_projection_sources
    _series_point_from_intraday = dependencies.series_point_from_intraday
    _should_fetch_intraday_equity_curve = (
        dependencies.should_fetch_intraday_equity_curve
    )
    _synthetic_intraday_equity_series_from_current_quotes = (
        dependencies.synthetic_intraday_equity_series_from_current_quotes
    )
    build_equity_curve_from_db = dependencies.build_equity_curve_from_db
    build_equity_series_from_db = dependencies.build_equity_series_from_db
    get_shanghai_now = dependencies.get_shanghai_now
    async_runtime = dependencies.async_runtime
    logger = dependencies.logger

    def _build_historical_equity_curve_series(
        state,
        selected_range: str,
    ) -> list[EquitySeriesPoint]:
        """Build the persisted historical curve in one worker-thread stage."""

        valuation_snapshot = _current_valuation_snapshot(state)
        latest_quotes = _quotes_from_valuation_snapshot(valuation_snapshot)
        if state.db is None or not hasattr(state.db, "get_ledger_entries_sync"):
            return []

        sample_entries = state.db.get_ledger_entries_sync(limit=1, offset=0)
        if not _has_rows(sample_entries):
            return []

        portfolio, instruments = _resolve_projection_sources(
            state,
            latest_quotes=latest_quotes,
        )
        portfolio, instruments, _ = _hydrate_missing_position_quotes(
            state,
            portfolio,
            instruments,
        )
        current_point = _current_equity_series_point(
            state,
            portfolio,
            instruments,
            latest_quotes,
        )
        current_point = _bind_current_equity_valuation(
            current_point,
            valuation_snapshot,
        )
        daily_points = _daily_equity_series_from_ledger_history(
            state,
            selected_range=selected_range,
            current_point=current_point,
        )
        if daily_points:
            return _append_current_equity_series_point(daily_points, current_point)

        points = build_equity_series_from_db(
            state.db,
            initial_cash=0,
            latest_quotes=latest_quotes,
        )
        series_points = [
            EquitySeriesPoint(
                timestamp=str(point["timestamp"].isoformat()),
                total=float(point["total"]),
                stocks=float(point["stocks"]),
                funds=float(point["funds"]),
                others=float(point["others"]),
                cash=float(point["cash"]),
                unrealized_pnl=None,
                quote_status="live",
            )
            for point in points
        ]
        return _daily_equity_series_for_range(
            _append_current_equity_series_point(
                series_points,
                current_point,
            ),
            selected_range,
        )

    @r.get("/equity-curve", response_model=list[EquityPoint])
    async def get_equity_curve() -> list[EquityPoint]:
        """获取权益曲线。"""
        state = dependencies.get_state()
        scheduler = state.scheduler
        portfolio = scheduler.portfolio if scheduler else None

        if portfolio is None:
            if state.db is None:
                return []

            ledger_entries = (
                state.db.get_ledger_entries_sync(limit=1, offset=0)
                if hasattr(state.db, "get_ledger_entries_sync")
                else []
            )
            if not _has_rows(ledger_entries):
                return []

            points = build_equity_curve_from_db(
                state.db,
                initial_cash=0,
                latest_quotes=_collect_latest_quotes(state),
            )
            return [
                EquityPoint(timestamp=ts.isoformat(), equity=float(eq))
                for ts, eq in points
            ]

        legacy_equity_curve = getattr(portfolio, "equity_curve", [])
        return [
            EquityPoint(timestamp=ts.isoformat(), equity=float(eq))
            for ts, eq in legacy_equity_curve
        ]

    @r.get("/equity-curve/series", response_model=list[EquitySeriesPoint])
    async def get_equity_curve_series(range: str = "1m") -> list[EquitySeriesPoint]:
        """获取按资产类别拆分的权益曲线。"""
        state = dependencies.get_state()
        selected_range = str(range).lower()
        if selected_range == "1d":
            valuation_snapshot = _current_valuation_snapshot(state)
            latest_quotes = _quotes_from_valuation_snapshot(valuation_snapshot)
            portfolio, instruments = _resolve_projection_sources(
                state,
                latest_quotes=latest_quotes,
            )
            portfolio, instruments, _ = _hydrate_missing_position_quotes(
                state,
                portfolio,
                instruments,
            )
            if portfolio is None:
                return []

            current_point = _current_equity_series_point(
                state,
                portfolio,
                instruments,
                latest_quotes,
            )
            current_point = _bind_current_equity_valuation(
                current_point,
                valuation_snapshot,
            )
            quote_status = (
                "live" if current_point is None else current_point.quote_status
            )
            valuation_time = (
                _parse_quote_timestamp(valuation_snapshot.get("as_of"))
                or get_shanghai_now()
            )
            if not _should_fetch_intraday_equity_curve(valuation_time):
                return _bind_equity_series_valuation(
                    _flat_intraday_equity_series_from_current(current_point),
                    valuation_snapshot,
                )

            timeout_seconds = float(
                getattr(state.config, "intraday_curve_timeout_seconds", 4.0) or 4.0
            )
            try:
                intraday_points = await async_runtime.wait_for(
                    async_runtime.to_thread(
                        _build_intraday_equity_curve_series,
                        state,
                        portfolio,
                        instruments,
                        latest_quotes,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "Timed out building intraday equity curve after %.2fs",
                    timeout_seconds,
                )
                return _bind_equity_series_valuation(
                    _synthetic_intraday_equity_series_from_current_quotes(
                        state,
                        portfolio,
                        instruments,
                        current_point,
                        latest_quotes,
                    ),
                    valuation_snapshot,
                )
            except Exception:
                logger.warning("Failed to build intraday equity curve", exc_info=True)
                return _bind_equity_series_valuation(
                    _synthetic_intraday_equity_series_from_current_quotes(
                        state,
                        portfolio,
                        instruments,
                        current_point,
                        latest_quotes,
                    ),
                    valuation_snapshot,
                )

            return _bind_equity_series_valuation(
                [
                    _series_point_from_intraday(
                        point,
                        quote_status=quote_status,
                        missing_price_symbols=(
                            []
                            if current_point is None
                            else current_point.missing_price_symbols
                        ),
                    )
                    for point in intraday_points
                ],
                valuation_snapshot,
            )

        return await async_runtime.to_thread(
            _build_historical_equity_curve_series,
            state,
            selected_range,
        )

    @r.get("/activity", response_model=list[ActivityItem])
    async def get_activity(limit: int = 10) -> list[ActivityItem]:
        """获取首页最近活动流。"""
        state = dependencies.get_state()
        trades = await state.db.get_trades(limit=limit, offset=0)
        flows = await state.db.get_cash_flows(limit=limit, offset=0)
        return _build_activity_items(trades, flows)[:limit]

    return PortfolioPerformanceEndpoints(
        router=r,
        operations=PortfolioPerformanceOperations(
            get_equity_curve=get_equity_curve,
            get_equity_curve_series=get_equity_curve_series,
        ),
    )


__all__ = ["PortfolioPerformanceEndpoints", "create_router"]
