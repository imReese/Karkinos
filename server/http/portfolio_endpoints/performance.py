"""Portfolio performance HTTP endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from server.contracts.http.ledger_models import (
    ActivityItem,
    EquityPoint,
    EquitySeriesPoint,
)


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _append_current_equity_series_point = dependency(
        "_append_current_equity_series_point"
    )
    _bind_current_equity_valuation = dependency("_bind_current_equity_valuation")
    _bind_equity_series_valuation = dependency("_bind_equity_series_valuation")
    _build_activity_items = dependency("_build_activity_items")
    _build_intraday_equity_curve_series = dependency(
        "_build_intraday_equity_curve_series"
    )
    _collect_latest_quotes = dependency("_collect_latest_quotes")
    _current_equity_series_point = dependency("_current_equity_series_point")
    _current_valuation_snapshot = dependency("_current_valuation_snapshot")
    _daily_equity_series_for_range = dependency("_daily_equity_series_for_range")
    _daily_equity_series_from_ledger_history = dependency(
        "_daily_equity_series_from_ledger_history"
    )
    _flat_intraday_equity_series_from_current = dependency(
        "_flat_intraday_equity_series_from_current"
    )
    _has_rows = dependency("_has_rows")
    _hydrate_missing_position_quotes = dependency("_hydrate_missing_position_quotes")
    _parse_quote_timestamp = dependency("_parse_quote_timestamp")
    _quotes_from_valuation_snapshot = dependency("_quotes_from_valuation_snapshot")
    _resolve_projection_sources = dependency("_resolve_projection_sources")
    _series_point_from_intraday = dependency("_series_point_from_intraday")
    _should_fetch_intraday_equity_curve = dependency(
        "_should_fetch_intraday_equity_curve"
    )
    _synthetic_intraday_equity_series_from_current_quotes = dependency(
        "_synthetic_intraday_equity_series_from_current_quotes"
    )
    asyncio = dependency("asyncio")
    build_equity_curve_from_db = dependency("build_equity_curve_from_db")
    build_equity_series_from_db = dependency("build_equity_series_from_db")
    get_shanghai_now = dependency("get_shanghai_now")
    logger = dependency("logger")

    @r.get("/equity-curve", response_model=list[EquityPoint])
    async def get_equity_curve() -> list[EquityPoint]:
        """获取权益曲线。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
        portfolio = scheduler.portfolio if scheduler else None

        if portfolio is None:
            if state.db is None:
                return []

            legacy_cash_flows = (
                state.db.get_cash_flows_sync(limit=1, offset=0)
                if hasattr(state.db, "get_cash_flows_sync")
                else []
            )
            legacy_trades = (
                state.db.get_trades_sync(limit=1, offset=0)
                if hasattr(state.db, "get_trades_sync")
                else []
            )
            ledger_entries = (
                state.db.get_ledger_entries_sync(limit=1, offset=0)
                if hasattr(state.db, "get_ledger_entries_sync")
                else []
            )
            if (
                _has_rows(legacy_cash_flows) or _has_rows(legacy_trades)
            ) or not _has_rows(ledger_entries):
                return []

            points = build_equity_curve_from_db(
                state.db,
                initial_cash=state.config.initial_cash,
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
        from server.dependencies import get_app_state

        state = get_app_state()
        valuation_snapshot = _current_valuation_snapshot(state)
        latest_quotes = _quotes_from_valuation_snapshot(valuation_snapshot)
        selected_range = str(range).lower()
        if selected_range == "1d":
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
                intraday_points = await asyncio.wait_for(
                    asyncio.to_thread(
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
            initial_cash=state.config.initial_cash,
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

    @r.get("/activity", response_model=list[ActivityItem])
    async def get_activity(limit: int = 10) -> list[ActivityItem]:
        """获取首页最近活动流。"""
        from server.dependencies import get_app_state

        state = get_app_state()
        trades = await state.db.get_trades(limit=limit, offset=0)
        flows = await state.db.get_cash_flows(limit=limit, offset=0)
        return _build_activity_items(trades, flows)[:limit]

    endpoints["get_equity_curve"] = get_equity_curve
    endpoints["get_equity_curve_series"] = get_equity_curve_series
    return r
