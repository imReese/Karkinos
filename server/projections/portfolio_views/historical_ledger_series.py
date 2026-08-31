"""Canonical daily equity history reconstructed from immutable ledger facts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from server.ledger.models import LedgerEntry
from server.models import EquitySeriesPoint
from server.projections.portfolio_application import (
    collect_latest_quotes as _collect_latest_quotes,
)
from server.projections.portfolio_application import (
    normalize_asset_class_value as _normalize_asset_class_value,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.service import build_portfolio_projection
from server.services.position_presence import is_economically_zero_quantity

_CN_AFTERNOON_CLOSE = time(15, 0)
_SH_TZ = ZoneInfo("Asia/Shanghai")
_EQUITY_SERIES_RANGE_DAYS = {
    "5d": 5,
    "1m": 31,
    "6m": 183,
    "1y": 366,
}


def load_ledger_entries_for_equity_series(
    db,
    batch_size: int = 500,
) -> list[LedgerEntry]:
    entries: list[LedgerEntry] = []
    offset = 0
    while True:
        rows = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not rows:
            break
        entries.extend(LedgerEntry.from_row(row) for row in rows)
        if len(rows) < batch_size:
            break
        offset += batch_size
    return sorted(entries, key=lambda entry: (entry.timestamp, entry.id or 0))


def ledger_entry_timestamp(entry: LedgerEntry) -> datetime | None:
    try:
        timestamp = datetime.fromisoformat(entry.timestamp)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=_SH_TZ)
    return timestamp.astimezone(_SH_TZ)


def equity_series_bucket(asset_class: str | None) -> str | None:
    normalized = _normalize_asset_class_value(asset_class)
    if normalized == "stock":
        return "stocks"
    if normalized in {"fund", "etf"}:
        return "funds"
    if normalized in {"bond", "gold"}:
        return "others"
    return None


def historical_quote_for_equity_day(
    state,
    *,
    symbol: str,
    asset_class: str,
    trade_date: date,
    latest_quotes: dict[str, dict],
    is_current_day: bool,
) -> dict | None:
    next_date = (trade_date + timedelta(days=1)).isoformat()
    db = state.db
    if db is not None and hasattr(db, "get_latest_market_bar_before_date_sync"):
        market_bar = db.get_latest_market_bar_before_date_sync(symbol, next_date)
        if market_bar:
            return {
                "symbol": symbol,
                "asset_class": market_bar.get("asset_class") or asset_class,
                "price": market_bar.get("price", market_bar.get("close")),
                "timestamp": market_bar.get("timestamp")
                or market_bar.get("trade_date")
                or trade_date.isoformat(),
                "quote_status": "confirmed",
                "source": market_bar.get("source") or "market_bars",
                "open": market_bar.get("open"),
                "high": market_bar.get("high"),
                "low": market_bar.get("low"),
                "close": market_bar.get("close"),
            }

    if db is not None and hasattr(db, "get_latest_daily_close_before_sync"):
        daily_close = db.get_latest_daily_close_before_sync(symbol, next_date)
        if daily_close:
            return {
                "symbol": symbol,
                "asset_class": daily_close.get("asset_class") or asset_class,
                "price": daily_close["close_price"],
                "timestamp": daily_close.get("trade_date"),
                "quote_status": "confirmed",
                "source": daily_close.get("source"),
            }

    if db is not None and hasattr(db, "get_latest_quote_before_date_sync"):
        quote = db.get_latest_quote_before_date_sync(symbol, next_date)
        if quote:
            return quote

    if is_current_day:
        return latest_quotes.get(symbol)
    return None


def quote_valuation_date(quote: dict | None) -> date | None:
    if not quote:
        return None
    for key in ("trade_date", "timestamp", "quote_timestamp"):
        value = quote.get(key)
        parsed = _parse_quote_timestamp(value)
        if parsed is not None:
            return parsed.date()
        if isinstance(value, str) and value.strip():
            try:
                return date.fromisoformat(value.strip().split("T")[0].split(" ")[0])
            except ValueError:
                continue
    return None


def build_daily_equity_series_from_ledger_history(
    state,
    *,
    selected_range: str,
    current_point: EquitySeriesPoint | None,
    now: datetime,
) -> list[EquitySeriesPoint]:
    if (
        selected_range == "1d"
        or state.db is None
        or not hasattr(state.db, "get_ledger_entries_sync")
    ):
        return []

    entries = load_ledger_entries_for_equity_series(state.db)
    dated_entries = [
        (timestamp, entry)
        for entry in entries
        if (timestamp := ledger_entry_timestamp(entry)) is not None
    ]
    if not dated_entries:
        return []

    latest_timestamp = (
        _parse_quote_timestamp(current_point.timestamp)
        if current_point is not None
        else None
    ) or now
    latest_timestamp = latest_timestamp.astimezone(_SH_TZ)
    range_days = _EQUITY_SERIES_RANGE_DAYS.get(selected_range)
    first_entry_date = dated_entries[0][0].date()
    start_date = (
        first_entry_date
        if range_days is None
        else (latest_timestamp - timedelta(days=range_days)).date()
    )
    end_date = latest_timestamp.date()
    if start_date > end_date:
        return []

    latest_quotes = _collect_latest_quotes(state)
    active_entries: list[LedgerEntry] = []
    entry_index = 0
    asset_classes: dict[str, str] = {}
    points: list[EquitySeriesPoint] = []
    current_date = start_date

    while current_date <= end_date:
        day_end = datetime.combine(current_date, time(23, 59, 59), tzinfo=_SH_TZ)
        while (
            entry_index < len(dated_entries)
            and dated_entries[entry_index][0] <= day_end
        ):
            _, entry = dated_entries[entry_index]
            active_entries.append(entry)
            if entry.symbol:
                asset_classes[str(entry.symbol)] = _normalize_asset_class_value(
                    entry.asset_class
                )
            entry_index += 1

        should_emit_day = current_date == start_date or current_date.weekday() < 5
        if active_entries and should_emit_day:
            position_projection = build_portfolio_projection(
                active_entries,
                initial_cash=0,
                latest_quotes={},
            )
            active_symbols = {
                str(symbol)
                for symbol, position in position_projection.positions.items()
                if not is_economically_zero_quantity(position.quantity)
            }
            historical_quotes: dict[str, dict] = {}
            missing_price_symbols: list[str] = []
            stale_terminal_symbols: list[str] = []
            for symbol in sorted(active_symbols):
                asset_class = asset_classes.get(symbol, "stock")
                quote = historical_quote_for_equity_day(
                    state,
                    symbol=symbol,
                    asset_class=asset_class,
                    trade_date=current_date,
                    latest_quotes=latest_quotes,
                    is_current_day=current_date == end_date,
                )
                if quote is not None:
                    quote_date = quote_valuation_date(quote)
                    if current_date == end_date and quote_date != current_date:
                        stale_terminal_symbols.append(symbol)
                        continue
                    historical_quotes[symbol] = quote
                else:
                    missing_price_symbols.append(symbol)

            if current_date == end_date and stale_terminal_symbols:
                current_date += timedelta(days=1)
                continue

            projection = build_portfolio_projection(
                active_entries,
                initial_cash=0,
                latest_quotes=historical_quotes,
            )
            buckets = {"stocks": 0.0, "funds": 0.0, "others": 0.0}
            unrealized_pnl = 0.0
            for symbol, position in projection.positions.items():
                bucket = equity_series_bucket(asset_classes.get(symbol))
                if bucket is None:
                    continue
                market_value = float(position.market_value)
                buckets[bucket] += market_value
                unrealized_pnl += float(position.unrealized_pnl)

            timestamp = datetime.combine(
                current_date,
                _CN_AFTERNOON_CLOSE,
                tzinfo=_SH_TZ,
            )
            points.append(
                EquitySeriesPoint(
                    timestamp=timestamp.isoformat(),
                    total=float(projection.cash)
                    + buckets["stocks"]
                    + buckets["funds"]
                    + buckets["others"],
                    stocks=buckets["stocks"],
                    funds=buckets["funds"],
                    others=buckets["others"],
                    cash=float(projection.cash),
                    unrealized_pnl=unrealized_pnl,
                    quote_status="missing" if missing_price_symbols else "live",
                    missing_price_symbols=sorted(set(missing_price_symbols)),
                )
            )

        current_date += timedelta(days=1)

    return points


__all__ = (
    "build_daily_equity_series_from_ledger_history",
    "equity_series_bucket",
    "historical_quote_for_equity_day",
    "ledger_entry_timestamp",
    "load_ledger_entries_for_equity_series",
    "quote_valuation_date",
)
