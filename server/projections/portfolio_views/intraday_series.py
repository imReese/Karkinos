"""Canonical portfolio intraday series projections."""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.types import Symbol
from server.models import (
    EquitySeriesPoint,
)
from server.projections.portfolio_application import (
    collect_latest_quotes as _collect_latest_quotes,
)
from server.projections.portfolio_application import (
    ledger_entry_shanghai_date as _ledger_entry_shanghai_date,
)
from server.projections.portfolio_application import (
    normalize_asset_class_value as _normalize_asset_class_value,
)
from server.projections.portfolio_application import (
    position_quote_presentation as _position_quote_presentation,
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
    merge_equity_series_quote_status,
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

logger = logging.getLogger(__name__)

_CN_MORNING_OPEN = time(9, 30)

_CN_MORNING_CLOSE = time(11, 30)

_CN_AFTERNOON_OPEN = time(13, 0)

_CN_AFTERNOON_CLOSE = time(15, 0)

_INTRADAY_STEP_MINUTES = 5

_SH_TZ = ZoneInfo("Asia/Shanghai")


def combine_session_time(trade_day, session_time: time, tzinfo) -> datetime:
    return datetime.combine(trade_day, session_time, tzinfo=tzinfo)


def floor_session_timestamp(timestamp: datetime, step_minutes: int) -> datetime:
    return timestamp.replace(
        minute=timestamp.minute - (timestamp.minute % step_minutes),
        second=0,
        microsecond=0,
    )


def build_cn_session_ticks(
    trade_day,
    tzinfo,
    *,
    full_session: bool = False,
    now: datetime | None = None,
) -> list[datetime]:
    morning_open = combine_session_time(trade_day, _CN_MORNING_OPEN, tzinfo)
    morning_close = combine_session_time(trade_day, _CN_MORNING_CLOSE, tzinfo)
    afternoon_open = combine_session_time(trade_day, _CN_AFTERNOON_OPEN, tzinfo)
    afternoon_close = combine_session_time(trade_day, _CN_AFTERNOON_CLOSE, tzinfo)
    if full_session:
        effective_end = afternoon_close
    else:
        if now is None:
            current = get_shanghai_now()
        elif now.tzinfo is None:
            current = now.replace(tzinfo=tzinfo)
        else:
            current = now.astimezone(tzinfo)
        effective_end = min(
            floor_session_timestamp(current, _INTRADAY_STEP_MINUTES),
            afternoon_close,
        )
    if effective_end <= morning_open:
        return [morning_open]

    ticks: list[datetime] = []
    for start, end in (
        (morning_open, morning_close),
        (afternoon_open, afternoon_close),
    ):
        if effective_end < start:
            continue
        segment_end = end if full_session else min(end, effective_end)
        current = start
        while current <= segment_end:
            ticks.append(current)
            current += timedelta(minutes=_INTRADAY_STEP_MINUTES)

    return ticks or [morning_open]


def normalize_intraday_timestamp(timestamp, tzinfo) -> datetime | None:
    if timestamp is None:
        return None
    if hasattr(timestamp, "to_pydatetime"):
        timestamp = timestamp.to_pydatetime()
    elif isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=tzinfo)
    return timestamp.astimezone(tzinfo)


def load_local_intraday_quote_points(
    db,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    get_snapshots = getattr(db, "get_recent_quote_snapshots_sync", None)
    if not callable(get_snapshots):
        return []

    try:
        snapshots = get_snapshots(symbol, limit=1000)
    except Exception:
        logger.warning(
            "Failed to load local intraday quote snapshots for %s",
            symbol,
            exc_info=True,
        )
        return []

    points: list[tuple[datetime, float]] = []
    for snapshot in snapshots:
        quote_status = str(snapshot.get("quote_status") or "").strip().lower()
        if quote_status in {"missing", "error"}:
            continue
        timestamp = normalize_intraday_timestamp(
            snapshot.get("timestamp"),
            start.tzinfo,
        )
        price = snapshot.get("price")
        if timestamp is None or price in {None, ""}:
            continue
        if timestamp.date() != start.date() or timestamp < start or timestamp > end:
            continue
        points.append((timestamp, float(price)))

    points.sort(key=lambda item: item[0])
    return points


def load_intraday_price_points(
    *,
    db,
    symbol: str,
    start: datetime,
    end: datetime,
    latest_quote: dict | None,
) -> tuple[list[tuple[datetime, float]], bool]:
    points: list[tuple[datetime, float]] = []
    local_points = load_local_intraday_quote_points(
        db,
        symbol=symbol,
        start=start,
        end=end,
    )
    points.extend(local_points)

    latest_price = latest_quote.get("price") if latest_quote else None
    latest_timestamp = normalize_intraday_timestamp(
        latest_quote.get("timestamp") if latest_quote else None,
        start.tzinfo,
    )
    if (
        latest_price not in {None, ""}
        and latest_timestamp is not None
        and latest_timestamp.date() == start.date()
        and start <= latest_timestamp <= end
    ):
        points.append((latest_timestamp, float(latest_price)))

    points.sort(key=lambda item: item[0])
    deduped: list[tuple[datetime, float]] = []
    for timestamp, close in points:
        if deduped and deduped[-1][0] == timestamp:
            deduped[-1] = (timestamp, close)
            continue
        deduped.append((timestamp, close))
    return deduped, bool(local_points)


def build_intraday_equity_curve_series(
    state,
    portfolio,
    instruments: dict,
    latest_quotes: dict[str, dict],
) -> list[dict]:
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
    session_now = (
        get_shanghai_now()
        if has_today_trade
        else max(quote_timestamps, default=get_shanghai_now())
    ).astimezone(_SH_TZ)
    tzinfo = session_now.tzinfo
    trade_day = session_now.date()
    session_start = combine_session_time(trade_day, _CN_MORNING_OPEN, tzinfo)
    session_close = combine_session_time(trade_day, _CN_AFTERNOON_CLOSE, tzinfo)
    live_ticks = build_cn_session_ticks(trade_day, tzinfo, now=session_now)
    full_session_ticks = build_cn_session_ticks(trade_day, tzinfo, full_session=True)
    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    holdings: list[dict] = []
    has_intraday_prices = False

    for sym, position in positions.items():
        quantity = float(getattr(position, "quantity", 0.0) or 0.0)
        symbol = str(sym)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        latest_quote = latest_quotes.get(symbol, {})
        asset_class = _normalize_asset_class_value(
            latest_quote.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        baseline_price, _, _ = _resolve_live_holding_baseline(
            state,
            symbol,
            latest_quote if latest_quote else None,
        )
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

        price_points, has_source_intraday_prices = load_intraday_price_points(
            db=state.db,
            symbol=symbol,
            start=session_start,
            end=session_close,
            latest_quote=latest_quote if latest_quote else None,
        )
        has_intraday_prices = has_intraday_prices or has_source_intraday_prices
        holdings.append(
            {
                "asset_class": asset_class,
                "quantity": quantity,
                "avg_cost": float(getattr(position, "avg_cost", 0.0) or 0.0),
                "daily_context": daily_context,
                "same_day_buy_lots": same_day_buy_lots,
                "same_day_sell_lots": same_day_sell_lots,
                "price_points": price_points,
            }
        )

    sparse_quote_ticks = {session_start}
    trade_ticks = set()
    observation_ticks = set()
    for holding in holdings:
        for lot in holding["same_day_buy_lots"]:
            lot_timestamp = lot["timestamp"]
            if isinstance(lot_timestamp, datetime):
                if session_start <= lot_timestamp <= session_close:
                    trade_ticks.add(lot_timestamp)
                    sparse_quote_ticks.add(lot_timestamp)
        for lot in holding["same_day_sell_lots"]:
            lot_timestamp = lot["timestamp"]
            if isinstance(lot_timestamp, datetime):
                if session_start <= lot_timestamp <= session_close:
                    trade_ticks.add(lot_timestamp)
                    sparse_quote_ticks.add(lot_timestamp)
        if not has_intraday_prices:
            for point_timestamp, _ in holding["price_points"]:
                if session_start <= point_timestamp <= session_close:
                    sparse_quote_ticks.add(point_timestamp)
        for point_timestamp, _ in holding["price_points"]:
            if session_start <= point_timestamp <= session_close:
                observation_ticks.add(point_timestamp)
    if has_intraday_prices:
        ticks = sorted(set(live_ticks) | trade_ticks | observation_ticks)
    elif len(sparse_quote_ticks) > 1:
        ticks = sorted(sparse_quote_ticks)
    else:
        ticks = full_session_ticks
    current_cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    series: list[dict] = []

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
        cash = current_cash + pending_trade_cost - pending_sell_proceeds
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

        total = cash + stocks_value + funds_value + others_value
        total_daily_change = (
            stocks_daily_change + funds_daily_change + others_daily_change
        )
        series.append(
            {
                "timestamp": tick,
                "total": total,
                "stocks": stocks_value,
                "funds": funds_value,
                "others": others_value,
                "cash": cash,
                "unrealized_pnl": unrealized_pnl,
                "total_daily_change": total_daily_change,
                "stocks_daily_change": stocks_daily_change,
                "funds_daily_change": funds_daily_change,
                "others_daily_change": others_daily_change,
            }
        )

    if series:
        return series

    return [
        {
            "timestamp": tick,
            "total": cash,
            "stocks": 0.0,
            "funds": 0.0,
            "others": 0.0,
            "cash": cash,
            "unrealized_pnl": 0.0,
            "total_daily_change": 0.0,
            "stocks_daily_change": 0.0,
            "funds_daily_change": 0.0,
            "others_daily_change": 0.0,
        }
        for tick in full_session_ticks
    ]


def current_equity_series_point(
    state,
    portfolio,
    instruments: dict,
    latest_quotes: dict[str, dict] | None = None,
) -> EquitySeriesPoint | None:
    if portfolio is None:
        return None

    latest_quotes = (
        _collect_latest_quotes(state) if latest_quotes is None else latest_quotes
    )

    cash = float(getattr(portfolio, "cash", 0.0) or 0.0)
    buckets = {"stocks": 0.0, "funds": 0.0, "others": 0.0}
    unrealized_pnl = 0.0
    quote_status = "live"
    missing_price_symbols: set[str] = set()

    for sym, position in getattr(portfolio, "positions", {}).items():
        if is_economically_zero_quantity(getattr(position, "quantity", None)):
            continue
        symbol = str(sym)
        quote = latest_quotes.get(symbol)
        asset_class = _normalize_asset_class_value(
            (quote or {}).get("asset_class")
            or getattr(
                getattr(
                    (instruments or {}).get(Symbol(symbol))
                    or (instruments or {}).get(symbol),
                    "asset_class",
                    None,
                ),
                "value",
                None,
            )
        )
        bucket = "others"
        if asset_class == "stock":
            bucket = "stocks"
        elif asset_class in {"fund", "etf"}:
            bucket = "funds"

        market_value = float(getattr(position, "market_value", 0.0) or 0.0)
        buckets[bucket] += market_value
        unrealized_pnl += float(getattr(position, "unrealized_pnl", 0.0) or 0.0)
        position_quote_status, position_stale_reason = _position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=asset_class,
            quote=quote,
        )
        if position_stale_reason == "confirmed_fund_nav_missing_estimate_only":
            position_quote_status = "confirmed_nav_missing"
        if is_missing_equity_quote_status(position_quote_status):
            missing_price_symbols.add(symbol)
        quote_status = merge_equity_series_quote_status(
            quote_status,
            position_quote_status,
        )

    quote_dependent_values_available = not is_missing_equity_quote_status(quote_status)
    effective_timestamps = [
        timestamp
        for quote in latest_quotes.values()
        if (timestamp := _quote_market_timestamp(quote)) is not None
    ]
    effective_timestamp = max(effective_timestamps, default=get_shanghai_now())
    return EquitySeriesPoint(
        timestamp=effective_timestamp.astimezone(_SH_TZ).isoformat(),
        total=(
            cash + buckets["stocks"] + buckets["funds"] + buckets["others"]
            if quote_dependent_values_available
            else None
        ),
        stocks=buckets["stocks"] if quote_dependent_values_available else None,
        funds=buckets["funds"] if quote_dependent_values_available else None,
        others=buckets["others"] if quote_dependent_values_available else None,
        cash=cash,
        unrealized_pnl=unrealized_pnl if quote_dependent_values_available else None,
        quote_status=quote_status,
        missing_price_symbols=sorted(missing_price_symbols),
    )


def append_current_equity_series_point(
    points: list[EquitySeriesPoint],
    current: EquitySeriesPoint | None,
) -> list[EquitySeriesPoint]:
    if current is None:
        return points
    if not points:
        return [current]

    last_timestamp = _parse_quote_timestamp(points[-1].timestamp)
    current_timestamp = _parse_quote_timestamp(current.timestamp)
    if last_timestamp is None or current_timestamp is None:
        return points + [current]
    if current_timestamp.date() == last_timestamp.date():
        return [*points[:-1], current]
    if current_timestamp < last_timestamp:
        return points
    if current_timestamp == last_timestamp:
        return [*points[:-1], current]
    return [*points, current]


__all__ = (
    "append_current_equity_series_point",
    "build_cn_session_ticks",
    "build_intraday_equity_curve_series",
    "combine_session_time",
    "current_equity_series_point",
    "floor_session_timestamp",
    "load_intraday_price_points",
    "load_local_intraday_quote_points",
    "normalize_intraday_timestamp",
)
