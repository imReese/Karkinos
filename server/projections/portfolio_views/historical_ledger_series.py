"""Canonical daily equity history reconstructed from immutable ledger facts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from data.market_data import is_fund_estimate_quote_source
from server.ledger.models import LedgerEntry
from server.models import EquitySeriesPoint
from server.projections.portfolio_application import (
    collect_latest_quotes as _collect_latest_quotes,
)
from server.projections.portfolio_application import (
    normalize_asset_class_value as _normalize_asset_class_value,
)
from server.projections.portfolio_read_snapshot_persistence import (
    portfolio_read_snapshot_for_state,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.service import PortfolioReplayAccumulator

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
    snapshot_reader = getattr(db, "get_all_ledger_entries_sync", None)
    if callable(snapshot_reader):
        rows = list(snapshot_reader() or [])
    else:
        reader = getattr(db, "get_ledger_entries_sync", None)
        if not callable(reader):
            return []
        rows = list(reader(limit=batch_size, offset=0) or [])
        if len(rows) >= batch_size:
            raise RuntimeError(
                "historical equity requires a single-statement ledger snapshot reader"
            )
    entries = [LedgerEntry.from_row(dict(row)) for row in rows]
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
    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        matrix: dict[str, list[dict]] = {symbol: []}
        for raw_row in read_snapshot.price_matrix_rows:
            row = dict(raw_row)
            if str(row.get("symbol") or "").strip() == symbol:
                matrix[symbol].append(row)
        return _matrix_quote_for_equity_day(
            matrix,
            symbol=symbol,
            asset_class=asset_class,
            trade_date=trade_date,
            is_current_day=is_current_day,
        )

    next_date = (trade_date + timedelta(days=1)).isoformat()
    instrument_type = _historical_instrument_type(asset_class)
    db = state.db
    if db is not None and hasattr(db, "get_latest_market_bar_before_date_sync"):
        market_bar = db.get_latest_market_bar_before_date_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if market_bar and quote_valuation_date(market_bar) == trade_date:
            return _historical_quote_with_status(
                {
                    "symbol": symbol,
                    "asset_class": market_bar.get("asset_class") or asset_class,
                    "price": market_bar.get("price", market_bar.get("close")),
                    "timestamp": market_bar.get("timestamp")
                    or market_bar.get("trade_date"),
                    "source": market_bar.get("source") or "market_bars",
                    "open": market_bar.get("open"),
                    "high": market_bar.get("high"),
                    "low": market_bar.get("low"),
                    "close": market_bar.get("close"),
                },
                asset_class=asset_class,
            )

    if db is not None and hasattr(db, "get_latest_daily_close_before_sync"):
        daily_close = db.get_latest_daily_close_before_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if daily_close and quote_valuation_date(daily_close) == trade_date:
            return _historical_quote_with_status(
                {
                    "symbol": symbol,
                    "asset_class": daily_close.get("asset_class") or asset_class,
                    "price": daily_close["close_price"],
                    "timestamp": daily_close.get("trade_date"),
                    "source": daily_close.get("source"),
                },
                asset_class=asset_class,
            )

    if db is not None and hasattr(db, "get_latest_quote_before_date_sync"):
        quote = db.get_latest_quote_before_date_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if quote and quote_valuation_date(quote) == trade_date:
            return _historical_quote_with_status(quote, asset_class=asset_class)

    if is_current_day:
        quote = latest_quotes.get(symbol)
        if quote_valuation_date(quote) == trade_date:
            return _historical_quote_with_status(quote, asset_class=asset_class)
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


def _historical_quote_with_status(
    quote: dict,
    *,
    asset_class: str,
) -> dict:
    normalized_asset_class = (
        str(quote.get("asset_class") or asset_class or "").strip().lower()
    )
    source = str(quote.get("source") or quote.get("quote_source") or "")
    quote_status = str(quote.get("quote_status") or "confirmed").strip().lower()
    if normalized_asset_class in {"fund", "open_end_fund"} and (
        is_fund_estimate_quote_source(source)
    ):
        quote_status = "confirmed_nav_missing"
    return {
        **quote,
        "asset_class": quote.get("asset_class") or asset_class,
        "quote_status": quote_status,
    }


def _matrix_quote_for_equity_day(
    matrix: dict[str, list[dict]],
    *,
    symbol: str,
    asset_class: str,
    trade_date: date,
    is_current_day: bool,
) -> dict | None:
    del is_current_day
    expected_instrument_type = _historical_instrument_type(asset_class)
    eligible = [
        row
        for row in matrix.get(symbol, [])
        if (row_date := quote_valuation_date(row)) is not None
        and row_date == trade_date
        and _historical_instrument_type(
            row.get("instrument_type")
            or row.get("asset_type")
            or row.get("asset_class")
        )
        == expected_instrument_type
    ]
    if not eligible:
        return None
    quote = max(
        eligible,
        key=lambda row: (
            quote_valuation_date(row) or date.min,
            str(row.get("timestamp") or ""),
        ),
    )
    return _historical_quote_with_status(quote, asset_class=asset_class)


def _historical_instrument_type(value: object) -> str:
    normalized = str(value or "stock").strip().lower().replace("-", "_")
    if normalized in {"fund", "openend_fund"}:
        return "open_end_fund"
    return normalized


def _aggregate_quote_status(
    quotes: dict[str, dict],
    missing_price_symbols: list[str],
) -> str:
    statuses = {
        str((quotes.get(symbol) or {}).get("quote_status") or "missing").strip().lower()
        for symbol in missing_price_symbols
    }
    if statuses & {"missing", "error"}:
        return "missing"
    if statuses & {
        "confirmed_nav_missing",
        "confirmed_fund_nav_missing_estimate_only",
    }:
        return "confirmed_nav_missing"
    if "estimated" in statuses:
        return "estimated"
    return "missing"


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
        or not (
            hasattr(state.db, "get_all_ledger_entries_sync")
            or hasattr(state.db, "get_ledger_entries_sync")
        )
    ):
        return []

    read_snapshot = portfolio_read_snapshot_for_state(state)
    entries = (
        sorted(
            (LedgerEntry.from_row(dict(row)) for row in read_snapshot.ledger_rows),
            key=lambda entry: (entry.timestamp, entry.id or 0),
        )
        if read_snapshot is not None
        else load_ledger_entries_for_equity_series(state.db)
    )
    dated_entries = [
        (timestamp, entry)
        for entry in entries
        if (timestamp := ledger_entry_timestamp(entry)) is not None
    ]
    if not dated_entries:
        return []
    dated_entries.sort(key=lambda item: (item[0], item[1].id or 0))

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

    candidate_symbols = sorted(
        {
            str(entry.symbol).strip()
            for _, entry in dated_entries
            if entry.symbol and str(entry.symbol).strip()
        }
    )
    if read_snapshot is not None:
        price_matrix: dict[str, list[dict]] | None = {
            symbol: [] for symbol in candidate_symbols
        }
        for raw_row in read_snapshot.price_matrix_rows:
            row = dict(raw_row)
            symbol = str(row.get("symbol") or "").strip()
            if symbol in price_matrix:
                price_matrix[symbol].append(row)
    else:
        matrix_reader = getattr(state.db, "get_historical_price_matrix_sync", None)
        price_matrix = (
            matrix_reader(
                symbols=candidate_symbols,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            if callable(matrix_reader)
            else None
        )
    latest_quotes = _collect_latest_quotes(state) if price_matrix is None else {}
    replay = PortfolioReplayAccumulator(initial_cash=0)
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
            replay.apply(entry)
            if entry.symbol:
                asset_classes[str(entry.symbol)] = (
                    str(entry.asset_class).strip().lower()
                )
            entry_index += 1

        should_emit_day = current_date == start_date or current_date.weekday() < 5
        if replay.applied_entry_count and should_emit_day:
            historical_quotes: dict[str, dict] = {}
            for symbol in replay.active_symbols:
                asset_class = asset_classes[symbol]
                quote = (
                    _matrix_quote_for_equity_day(
                        price_matrix,
                        symbol=symbol,
                        asset_class=asset_class,
                        trade_date=current_date,
                        is_current_day=current_date == end_date,
                    )
                    if price_matrix is not None
                    else historical_quote_for_equity_day(
                        state,
                        symbol=symbol,
                        asset_class=asset_class,
                        trade_date=current_date,
                        latest_quotes=latest_quotes,
                        is_current_day=current_date == end_date,
                    )
                )
                if quote is not None:
                    historical_quotes[symbol] = quote

            valuation = replay.value(historical_quotes)
            missing_price_symbols = list(valuation.missing_price_symbols)
            quote_status = (
                _aggregate_quote_status(historical_quotes, missing_price_symbols)
                if missing_price_symbols
                else "live"
            )

            timestamp = datetime.combine(
                current_date,
                _CN_AFTERNOON_CLOSE,
                tzinfo=_SH_TZ,
            )
            points.append(
                EquitySeriesPoint(
                    timestamp=timestamp.isoformat(),
                    total=None if valuation.total is None else float(valuation.total),
                    stocks=(
                        None if valuation.stocks is None else float(valuation.stocks)
                    ),
                    funds=None if valuation.funds is None else float(valuation.funds),
                    others=(
                        None if valuation.others is None else float(valuation.others)
                    ),
                    cash=float(valuation.cash),
                    unrealized_pnl=(
                        None
                        if valuation.unrealized_pnl is None
                        else float(valuation.unrealized_pnl)
                    ),
                    quote_status=quote_status,
                    missing_price_symbols=missing_price_symbols,
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
