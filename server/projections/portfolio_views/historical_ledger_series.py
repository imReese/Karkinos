"""Canonical daily equity history reconstructed from immutable ledger facts."""

from __future__ import annotations

import json
from calendar import monthrange
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from core.types import InstrumentKey
from data.market_data import (
    PUBLISHED_FUND_NAV_QUOTE_SOURCES,
    PUBLISHED_FUND_NAV_STATUSES,
    is_fund_estimate_quote_source,
)
from server.contracts.quote_ingestion import (
    fund_nav_pricing_date,
    historical_observation_rank,
    historical_observation_status,
    historical_observation_within_as_of,
)
from server.ledger.models import LedgerEntry
from server.models import EquitySeriesPoint
from server.projections.ledger_correction_read import restated_ledger_rows
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
    is_authoritative_historical_fund_close_source,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.projections.service import PortfolioReplayAccumulator
from server.services.market.calendar import validate_verified_market_calendar

_CN_AFTERNOON_CLOSE = time(15, 0)
_SH_TZ = ZoneInfo("Asia/Shanghai")
_EQUITY_SERIES_RANGE_DAYS = {
    "5d": 5,
}


def equity_series_range_start_date(end_date: date, selected_range: str) -> date | None:
    if selected_range == "all":
        return None
    if selected_range == "ytd":
        return date(end_date.year, 1, 1)
    calendar_months = {"1m": 1, "6m": 6, "1y": 12}.get(selected_range)
    if calendar_months is not None:
        target_index = end_date.year * 12 + (end_date.month - 1) - calendar_months
        target_year, target_month_index = divmod(target_index, 12)
        target_month = target_month_index + 1
        target_day = min(end_date.day, monthrange(target_year, target_month)[1])
        return date(target_year, target_month, target_day)
    range_days = _EQUITY_SERIES_RANGE_DAYS.get(selected_range)
    return end_date - timedelta(days=range_days) if range_days is not None else None


def _verified_trading_days(
    db,
    *,
    start_date: date,
    end_date: date,
) -> dict[date, bool]:
    reader = getattr(db, "get_market_calendar_snapshot_sync", None)
    if not callable(reader):
        return {}

    resolved: dict[date, bool] = {}
    for year in range(start_date.year, end_date.year + 1):
        try:
            raw = reader(exchange="SSE", year=year)
        except Exception:
            continue
        row = None if raw is None else dict(raw)
        validation = validate_verified_market_calendar(row)
        if row is None or not validation.verified:
            continue
        days = row.get("days")
        if not isinstance(days, list):
            try:
                days = json.loads(str(row.get("days_json") or "[]"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        for item in days:
            if not isinstance(item, dict):
                continue
            value = str(item.get("date") or "")
            try:
                current = date.fromisoformat(value)
            except ValueError:
                continue
            if start_date <= current <= end_date and isinstance(
                item.get("is_trading_day"), bool
            ):
                resolved[current] = bool(item["is_trading_day"])
    return resolved


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
    entries = [LedgerEntry.from_row(row) for row in restated_ledger_rows(rows)]
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
    as_of: datetime | str | None = None,
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
            as_of=as_of,
        )

    db = state.db
    instrument_type = _historical_instrument_type(asset_class)
    if db is not None and callable(
        getattr(db, "get_historical_price_matrix_sync", None)
    ):
        day_iso = trade_date.isoformat()
        key = InstrumentKey.from_values(symbol, instrument_type)
        kwargs: dict[str, Any] = {
            "instrument_keys": [key],
            "start_date": day_iso,
            "end_date": day_iso,
        }
        if as_of is not None:
            kwargs["as_of"] = as_of
        raw_matrix = db.get_historical_price_matrix_sync(**kwargs)
        keyed_rows = (
            raw_matrix.get(key)
            or raw_matrix.get(symbol)
            or raw_matrix.get((key.symbol, key.instrument_type.value))
            or []
        )
        matched = _matrix_quote_for_equity_day(
            {symbol: list(keyed_rows)},
            symbol=symbol,
            asset_class=asset_class,
            trade_date=trade_date,
            is_current_day=is_current_day,
            as_of=as_of,
        )
        if matched is not None:
            return matched
        if is_current_day:
            current_quote = latest_quotes.get(symbol)
            if current_quote is not None:
                return _select_candidate_for_equity_day(
                    [current_quote],
                    asset_class=asset_class,
                    trade_date=trade_date,
                    as_of=as_of,
                )
        return None

    next_date = (trade_date + timedelta(days=1)).isoformat()
    candidates: list[dict] = []
    if db is not None and hasattr(db, "get_latest_market_bar_before_date_sync"):
        market_bar = db.get_latest_market_bar_before_date_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if market_bar:
            candidates.append(
                {
                    **market_bar,
                    "symbol": symbol,
                    "instrument_type": market_bar.get("instrument_type")
                    or instrument_type,
                    "asset_class": market_bar.get("asset_class") or asset_class,
                    "price": market_bar.get("price", market_bar.get("close")),
                    "timestamp": market_bar.get("timestamp")
                    or market_bar.get("trade_date"),
                    "source": market_bar.get("source") or "market_bars",
                    "kind": "bar",
                }
            )

    if db is not None and hasattr(db, "get_latest_daily_close_before_sync"):
        daily_close = db.get_latest_daily_close_before_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if daily_close:
            candidates.append(
                {
                    **daily_close,
                    "symbol": symbol,
                    "instrument_type": daily_close.get("instrument_type")
                    or instrument_type,
                    "asset_class": daily_close.get("asset_class") or asset_class,
                    "price": daily_close["close_price"],
                    "timestamp": daily_close.get("trade_date"),
                    "source": daily_close.get("source"),
                    "kind": "close",
                }
            )

    if db is not None and hasattr(db, "get_latest_quote_before_date_sync"):
        quote = db.get_latest_quote_before_date_sync(
            symbol,
            next_date,
            instrument_type=instrument_type,
        )
        if quote:
            candidates.append({**quote, "kind": quote.get("kind") or "quote"})

    if is_current_day:
        current_quote = latest_quotes.get(symbol)
        if current_quote:
            candidates.append(
                {**current_quote, "kind": current_quote.get("kind") or "quote"}
            )

    return _select_candidate_for_equity_day(
        candidates,
        asset_class=asset_class,
        trade_date=trade_date,
        as_of=as_of,
    )


def quote_valuation_date(
    quote: dict | None,
    *,
    prefer_nav_date: bool = True,
) -> date | None:
    if not quote:
        return None
    inst_type = _historical_instrument_type(
        quote.get("instrument_type")
        or quote.get("asset_type")
        or quote.get("asset_class")
        or "stock"
    )
    raw_nav_date = quote.get("nav_date")
    if (
        prefer_nav_date
        and inst_type == "open_end_fund"
        and raw_nav_date not in {None, ""}
    ):
        resolved = fund_nav_pricing_date(raw_nav_date, None)
        return date.fromisoformat(resolved) if resolved else None
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
    trade_date: date | None = None,
) -> dict:
    normalized_asset_class = (
        str(quote.get("asset_class") or asset_class or "").strip().lower()
    )
    source = str(quote.get("source") or quote.get("quote_source") or "").strip()
    kind = str(quote.get("kind") or "").strip().lower()
    observed_status = historical_observation_status(quote)
    quote_status = observed_status
    is_fund = normalized_asset_class in {"fund", "open_end_fund"}
    if is_fund and is_fund_estimate_quote_source(source):
        quote_status = "confirmed_nav_missing"
    elif (
        is_fund and trade_date is not None and quote_valuation_date(quote) != trade_date
    ):
        quote_status = "stale"
    projected = {
        **quote,
        "asset_class": quote.get("asset_class") or asset_class,
        "quote_status": quote_status,
    }
    if kind == "bar" and not projected.get("valuation_price_source"):
        projected["valuation_price_source"] = "market_bar_close"
    elif (
        kind == "close"
        and observed_status in PUBLISHED_FUND_NAV_STATUSES
        and is_authoritative_historical_fund_close_source(source)
        and not projected.get("valuation_price_source")
    ):
        projected["valuation_price_source"] = "daily_close"
    elif (
        is_fund
        and kind == "quote"
        and source.lower() in PUBLISHED_FUND_NAV_QUOTE_SOURCES
        and observed_status in PUBLISHED_FUND_NAV_STATUSES
    ):
        projected.setdefault("quote_source", source)
    return projected


def _select_candidate_for_equity_day(
    rows: Sequence[dict],
    *,
    asset_class: str,
    trade_date: date,
    as_of: datetime | str | None = None,
) -> dict | None:
    expected_instrument_type = _historical_instrument_type(asset_class)
    eligible = [
        dict(row)
        for row in rows
        if (row_date := quote_valuation_date(row)) is not None
        and row_date == trade_date
        and _historical_instrument_type(
            row.get("instrument_type")
            or row.get("asset_type")
            or row.get("asset_class")
            or asset_class
        )
        == expected_instrument_type
        and historical_observation_within_as_of(row, as_of)
    ]
    if not eligible:
        return None
    quote = max(eligible, key=historical_observation_rank)
    return _historical_quote_with_status(
        quote, asset_class=asset_class, trade_date=trade_date
    )


def _matrix_quote_for_equity_day(
    matrix: dict[str, list[dict]],
    *,
    symbol: str,
    asset_class: str,
    trade_date: date,
    is_current_day: bool,
    as_of: datetime | str | None = None,
) -> dict | None:
    del is_current_day
    return _select_candidate_for_equity_day(
        matrix.get(symbol, []),
        asset_class=asset_class,
        trade_date=trade_date,
        as_of=as_of,
    )


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
    as_of: datetime | str | None = None,
) -> list[EquitySeriesPoint]:
    """Replay current history from the canonical identity-bound cached inputs."""
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
            (
                LedgerEntry.from_row(row)
                for row in restated_ledger_rows(
                    [dict(row) for row in read_snapshot.ledger_rows]
                )
            ),
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
    first_entry_date = dated_entries[0][0].date()
    requested_start_date = equity_series_range_start_date(
        latest_timestamp.date(), selected_range
    )
    start_date = requested_start_date or first_entry_date
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
        if callable(matrix_reader):
            matrix_kwargs: dict[str, Any] = {
                "symbols": candidate_symbols,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if as_of is not None:
                matrix_kwargs["as_of"] = as_of
            price_matrix = matrix_reader(**matrix_kwargs)
        else:
            price_matrix = None
    latest_quotes = _collect_latest_quotes(state) if price_matrix is None else {}
    replay = PortfolioReplayAccumulator(initial_cash=0)
    entry_index = 0
    asset_classes: dict[str, str] = {}
    points: list[EquitySeriesPoint] = []
    trading_days = _verified_trading_days(
        state.db,
        start_date=start_date,
        end_date=end_date,
    )
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

        calendar_state = trading_days.get(current_date)
        is_trading_day = (
            calendar_state if calendar_state is not None else current_date.weekday() < 5
        )
        should_emit_day = current_date == start_date or is_trading_day
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
                        as_of=as_of,
                    )
                    if price_matrix is not None
                    else historical_quote_for_equity_day(
                        state,
                        symbol=symbol,
                        asset_class=asset_class,
                        trade_date=current_date,
                        latest_quotes=latest_quotes,
                        is_current_day=current_date == end_date,
                        as_of=as_of,
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
                    valuation_policy="karkinos.historical_replay.v2",
                    valuation_status=(
                        "reconstructed"
                        if valuation.total is not None and not missing_price_symbols
                        else "missing"
                    ),
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
