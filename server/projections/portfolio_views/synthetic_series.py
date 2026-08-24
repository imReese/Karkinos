"""Canonical portfolio synthetic series projections."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.types import Symbol
from server.models import (
    EquitySeriesPoint,
)
from server.projections.portfolio_application import (
    ledger_entry_shanghai_date as _ledger_entry_shanghai_date,
)
from server.projections.portfolio_application import (
    normalize_asset_class_value as _normalize_asset_class_value,
)
from server.projections.portfolio_application import (
    quote_market_timestamp as _quote_market_timestamp,
)
from server.projections.portfolio_application import (
    read_daily_ledger_entries as _read_daily_ledger_entries,
)
from server.projections.portfolio_application import (
    resolve_live_holding_baseline as _resolve_live_holding_baseline,
)
from server.projections.portfolio_application import (
    same_day_buy_lots as _same_day_buy_lots,
)
from server.projections.portfolio_application import (
    same_day_sell_lots as _same_day_sell_lots,
)
from server.projections.portfolio_views.explainability import (
    is_missing_equity_quote_status,
)
from server.projections.portfolio_views.intraday_series import (
    build_cn_session_ticks,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.daily_performance import (
    build_position_daily_context,
    mark_position_daily,
    price_at_tick,
)
from server.services.market_hours import get_shanghai_now
from server.services.position_presence import (
    is_economically_zero_quantity,
)

_SH_TZ = ZoneInfo("Asia/Shanghai")


def synthetic_intraday_equity_series_from_current_quotes(
    state,
    portfolio,
    instruments: dict,
    current: EquitySeriesPoint | None,
    latest_quotes: dict[str, dict],
) -> list[EquitySeriesPoint]:
    if portfolio is None:
        return []

    daily_ledger_entries = _read_daily_ledger_entries(state)
    shanghai_today = get_shanghai_now().date()
    has_today_trade = any(
        str(entry.get("entry_type") or "").lower() in {"trade_buy", "trade_sell"}
        and _ledger_entry_shanghai_date(entry) == shanghai_today
        for entry in daily_ledger_entries
    )
    quote_timestamps = [
        timestamp
        for quote in latest_quotes.values()
        if (timestamp := _quote_market_timestamp(quote)) is not None
    ]
    now = (
        get_shanghai_now()
        if has_today_trade
        else max(quote_timestamps, default=get_shanghai_now())
    ).astimezone(_SH_TZ)
    trade_day = now.date()
    session_ticks = build_cn_session_ticks(
        trade_day, now.tzinfo or _SH_TZ, full_session=True
    )
    if not session_ticks:
        return [] if current is None else [current]
    session_start = session_ticks[0]
    session_close = session_ticks[-1]

    cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    holdings: list[dict] = []
    sparse_quote_ticks = {session_start}

    for sym, position in getattr(portfolio, "positions", {}).items():
        quantity = float(getattr(position, "quantity", 0.0) or 0.0)
        symbol = str(sym)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        latest_quote = latest_quotes.get(symbol, {})
        asset_class = _normalize_asset_class_value(
            latest_quote.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        latest_price = latest_quote.get("price")
        latest_price_value = (
            float(latest_price) if latest_price not in {None, ""} else None
        )
        baseline_price, _, _ = _resolve_live_holding_baseline(
            state,
            symbol,
            latest_quote if latest_quote else None,
        )
        quote_timestamp = _parse_quote_timestamp(latest_quote.get("timestamp"))
        same_day_buy_lots = _same_day_buy_lots(
            state,
            symbol=symbol,
            trade_day=trade_day,
            ledger_entries=daily_ledger_entries,
        )
        same_day_sell_lots = _same_day_sell_lots(
            state,
            symbol=symbol,
            trade_day=trade_day,
            ledger_entries=daily_ledger_entries,
        )
        if (
            is_economically_zero_quantity(quantity)
            and not same_day_buy_lots
            and not same_day_sell_lots
        ):
            continue
        daily_context = build_position_daily_context(
            quantity=quantity,
            previous_close=baseline_price,
            same_day_buy_lots=same_day_buy_lots,
            same_day_sell_lots=same_day_sell_lots,
        )
        if (
            latest_price_value is not None
            and quote_timestamp is not None
            and session_start <= quote_timestamp <= session_close
        ):
            sparse_quote_ticks.add(quote_timestamp)
        for sell_lot in same_day_sell_lots:
            sell_timestamp = sell_lot["timestamp"]
            if (
                isinstance(sell_timestamp, datetime)
                and session_start <= sell_timestamp <= session_close
            ):
                sparse_quote_ticks.add(sell_timestamp)

        holdings.append(
            {
                "asset_class": asset_class,
                "quantity": quantity,
                "avg_cost": float(getattr(position, "avg_cost", 0.0) or 0.0),
                "daily_context": daily_context,
                "same_day_buy_lots": same_day_buy_lots,
                "same_day_sell_lots": same_day_sell_lots,
                "price_points": (
                    [(quote_timestamp, latest_price_value)]
                    if latest_price_value is not None and quote_timestamp is not None
                    else []
                ),
            }
        )

    quote_status = "live" if current is None else current.quote_status
    ticks = sorted(sparse_quote_ticks) if len(sparse_quote_ticks) > 1 else session_ticks
    points: list[EquitySeriesPoint] = []
    for tick in ticks:
        pending_trade_cost = sum(
            float(lot["total_cost"])
            for holding in holdings
            for lot in holding["same_day_buy_lots"]
            if isinstance(lot["timestamp"], datetime) and lot["timestamp"] > tick
        )
        pending_sell_proceeds = sum(
            float(lot["net_proceeds"])
            for holding in holdings
            for lot in holding["same_day_sell_lots"]
            if isinstance(lot["timestamp"], datetime) and lot["timestamp"] > tick
        )
        tick_cash = cash + pending_trade_cost - pending_sell_proceeds
        stocks_value = 0.0
        funds_value = 0.0
        others_value = 0.0
        unrealized_pnl = 0.0
        stocks_daily_change = 0.0
        funds_daily_change = 0.0
        others_daily_change = 0.0
        for holding in holdings:
            daily_context = holding["daily_context"]
            price = price_at_tick(
                daily_context,
                tick=tick,
                quote_points=holding["price_points"],
            )
            mark = mark_position_daily(daily_context, price=price, at=tick)
            if mark.current_value is None or mark.today_change is None:
                continue
            position_value = mark.current_value
            cost_basis = mark.active_quantity * holding["avg_cost"]
            unrealized_pnl += position_value - cost_basis
            daily_change = mark.today_change

            if holding["asset_class"] == "stock":
                stocks_value += position_value
                stocks_daily_change += daily_change
            elif holding["asset_class"] in {"fund", "etf"}:
                funds_value += position_value
                funds_daily_change += daily_change
            else:
                others_value += position_value
                others_daily_change += daily_change

        total_daily_change = (
            stocks_daily_change + funds_daily_change + others_daily_change
        )
        points.append(
            EquitySeriesPoint(
                timestamp=tick.isoformat(),
                total=tick_cash + stocks_value + funds_value + others_value,
                stocks=stocks_value,
                funds=funds_value,
                others=others_value,
                cash=tick_cash,
                unrealized_pnl=unrealized_pnl,
                total_daily_change=total_daily_change,
                stocks_daily_change=stocks_daily_change,
                funds_daily_change=funds_daily_change,
                others_daily_change=others_daily_change,
                quote_status=quote_status,
            )
        )

    return points


def should_fetch_intraday_equity_curve(now: datetime) -> bool:
    return now.astimezone(_SH_TZ).weekday() < 5


def series_point_from_intraday(
    point: dict,
    quote_status: str = "live",
    missing_price_symbols: list[str] | None = None,
) -> EquitySeriesPoint:
    if is_missing_equity_quote_status(quote_status):
        return EquitySeriesPoint(
            timestamp=str(point["timestamp"].isoformat()),
            total=None,
            stocks=None,
            funds=None,
            others=None,
            cash=float(point["cash"]),
            unrealized_pnl=None,
            total_daily_change=None,
            stocks_daily_change=None,
            funds_daily_change=None,
            others_daily_change=None,
            quote_status=quote_status,
            missing_price_symbols=sorted(set(missing_price_symbols or [])),
        )

    return EquitySeriesPoint(
        timestamp=str(point["timestamp"].isoformat()),
        total=float(point["total"]),
        stocks=float(point["stocks"]),
        funds=float(point["funds"]),
        others=float(point["others"]),
        cash=float(point["cash"]),
        unrealized_pnl=float(point["unrealized_pnl"]),
        total_daily_change=(
            None
            if point.get("total_daily_change") is None
            else float(point["total_daily_change"])
        ),
        stocks_daily_change=(
            None
            if point.get("stocks_daily_change") is None
            else float(point["stocks_daily_change"])
        ),
        funds_daily_change=(
            None
            if point.get("funds_daily_change") is None
            else float(point["funds_daily_change"])
        ),
        others_daily_change=(
            None
            if point.get("others_daily_change") is None
            else float(point["others_daily_change"])
        ),
        quote_status=quote_status,
        missing_price_symbols=sorted(set(missing_price_symbols or [])),
    )


__all__ = (
    "series_point_from_intraday",
    "should_fetch_intraday_equity_curve",
    "synthetic_intraday_equity_series_from_current_quotes",
)
