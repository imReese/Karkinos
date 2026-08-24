"""Persisted portfolio and market-evidence projection for Decision."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

from server.services.decision_contracts import (
    TRUSTED_DATA_STATUSES,
    action_trade_date,
    float_or_zero,
    parse_action_timestamp,
)


def decision_portfolio_context(state: Any) -> dict[str, Any]:
    """Resolve Decision facts from the same persisted snapshot as Portfolio."""

    db = getattr(state, "db", None)
    persistent_facts_available = db is not None and any(
        callable(getattr(db, name, None))
        for name in (
            "list_latest_quotes_sync",
            "get_latest_quotes_sync",
            "list_quote_snapshots_sync",
            "get_ledger_entries_sync",
        )
    )
    if persistent_facts_available:
        from server.projections.portfolio_application import (
            current_valuation_snapshot,
            quotes_from_valuation_snapshot,
            resolve_projection_sources,
        )
        from server.services.valuation_snapshot import build_current_valuation_snapshot

        snapshot = (
            current_valuation_snapshot(state)
            if callable(getattr(db, "save_valuation_snapshot_sync", None))
            else build_current_valuation_snapshot(db, persist=False)
        )
        quotes = quotes_from_valuation_snapshot(snapshot)
        scheduler = getattr(state, "scheduler", None)
        projection_scheduler = (
            SimpleNamespace(
                portfolio=getattr(scheduler, "portfolio", None),
                instruments=getattr(scheduler, "instruments", {}),
            )
            if scheduler is not None
            else None
        )
        projection_state = SimpleNamespace(
            db=db,
            scheduler=projection_scheduler,
            config=getattr(
                state,
                "config",
                SimpleNamespace(initial_cash=0, assets=[]),
            ),
        )
        portfolio, instruments = resolve_projection_sources(
            projection_state,
            latest_quotes=quotes,
        )
        return {
            "portfolio": portfolio,
            "instruments": instruments,
            "quotes": quotes,
            "valuation_snapshot": snapshot,
            "authority": "persisted_valuation_snapshot",
        }

    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
    return {
        "portfolio": portfolio,
        "instruments": getattr(scheduler, "instruments", {}) if scheduler else {},
        "quotes": collect_decision_quotes(state),
        "valuation_snapshot": None,
        "authority": "legacy_runtime_fallback",
    }


def decision_date_from_context(context: dict[str, Any]) -> str:
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("trade_date"):
        return str(snapshot["trade_date"])
    timestamps = [
        parse_action_timestamp(quote.get("quote_timestamp") or quote.get("timestamp"))
        for quote in (context.get("quotes") or {}).values()
        if isinstance(quote, dict)
    ]
    parsed = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(parsed).date().isoformat() if parsed else date.today().isoformat()


def action_filter_date(context: dict[str, Any]) -> str | None:
    if context.get("authority") != "persisted_valuation_snapshot":
        return None
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict) and snapshot.get("status") == "missing":
        return None
    return decision_date_from_context(context)


def response_decision_date(
    context: dict[str, Any],
    actions: list[dict[str, Any]],
) -> str:
    snapshot = context.get("valuation_snapshot")
    if (
        context.get("authority") == "persisted_valuation_snapshot"
        and isinstance(snapshot, dict)
        and snapshot.get("status") != "missing"
    ):
        return decision_date_from_context(context)
    action_dates = [
        trade_date
        for action in actions
        for trade_date in [action_trade_date(action)]
        if trade_date is not None
    ]
    return max(action_dates) if action_dates else decision_date_from_context(context)


def journal_by_signal_id(db: Any) -> dict[int, dict[str, Any]]:
    reader = getattr(db, "list_signal_journal_sync", None)
    if not callable(reader):
        return {}
    rows = reader(limit=50, offset=0)
    indexed: dict[int, dict[str, Any]] = {}
    for row in rows:
        signal = row.get("signal") or {}
        signal_id = signal.get("id")
        if signal_id is None:
            continue
        indexed[int(signal_id)] = row
    return indexed


def portfolio_state_summary(
    state: Any,
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = portfolio_context or decision_portfolio_context(state)
    portfolio = context.get("portfolio")
    if portfolio is None:
        return {
            "status": "missing",
            "cash": 0.0,
            "position_count": 0,
            "symbols": [],
            "total_market_value": 0.0,
            "total_equity": 0.0,
        }
    positions = getattr(portfolio, "positions", {}) or {}
    position_items = positions.items() if isinstance(positions, dict) else []
    symbols: list[str] = []
    total_market_value = 0.0
    for symbol, position in position_items:
        symbols.append(str(symbol))
        total_market_value += position_market_value(position)
    cash = float_or_zero(getattr(portfolio, "cash", 0.0))
    total_equity = portfolio_total_equity(portfolio, cash, total_market_value)
    result = {
        "status": "available",
        "cash": cash,
        "position_count": len(symbols),
        "symbols": symbols,
        "total_market_value": total_market_value,
        "total_equity": total_equity,
    }
    snapshot = context.get("valuation_snapshot")
    if isinstance(snapshot, dict):
        from server.services.valuation_snapshot import valuation_identity_fields

        result.update(valuation_identity_fields(snapshot))
    result["fact_authority"] = context.get("authority")
    return result


def portfolio_total_equity(
    portfolio: Any,
    cash: float,
    total_market_value: float,
) -> float:
    total_equity = getattr(portfolio, "total_equity", None)
    if callable(total_equity):
        try:
            return float_or_zero(total_equity())
        except TypeError:
            pass
    if total_equity is not None and not callable(total_equity):
        return float_or_zero(total_equity)
    return cash + total_market_value


def position_market_value(position: Any) -> float:
    market_value = getattr(position, "market_value", None)
    if callable(market_value):
        try:
            return float_or_zero(market_value())
        except TypeError:
            return 0.0
    if market_value is not None:
        return float_or_zero(market_value)
    quantity = float_or_zero(
        getattr(position, "quantity", getattr(position, "shares", 0.0))
    )
    price = float_or_zero(
        getattr(
            position,
            "current_price",
            getattr(position, "last_price", getattr(position, "price", 0.0)),
        )
    )
    return quantity * price


def market_data_summary(
    state: Any,
    actions: list[dict[str, Any]],
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = portfolio_context or decision_portfolio_context(state)
    symbols = decision_symbols(state, actions, portfolio_context=context)
    quotes = dict(context.get("quotes") or {})
    relevant_quotes = {symbol: quotes[symbol] for symbol in symbols if symbol in quotes}
    statuses = [
        str(quote.get("quote_status") or quote.get("provider_status") or "live")
        for quote in relevant_quotes.values()
    ]
    live_count = sum(1 for status in statuses if status == "live")
    confirmed_count = sum(1 for status in statuses if status == "confirmed")
    trusted_count = sum(1 for status in statuses if status in TRUSTED_DATA_STATUSES)
    stale_count = sum(1 for status in statuses if status not in TRUSTED_DATA_STATUSES)
    missing_symbols = [symbol for symbol in symbols if symbol not in quotes]
    latest_timestamp = latest_quote_timestamp(relevant_quotes.values())
    if not symbols:
        source_health = "unknown"
    elif missing_symbols and not relevant_quotes:
        source_health = "missing"
    elif missing_symbols or stale_count:
        source_health = "partial" if trusted_count else "stale"
    else:
        source_health = "live" if live_count == len(statuses) else "confirmed"
    return {
        "source_health": source_health,
        "quote_count": len(relevant_quotes),
        "live_quote_count": live_count,
        "confirmed_quote_count": confirmed_count,
        "trusted_quote_count": trusted_count,
        "stale_quote_count": stale_count,
        "missing_symbols": missing_symbols,
        "latest_quote_timestamp": latest_timestamp,
        "has_persistent_cache": has_persistent_quote_cache(state),
    }


def decision_symbols(
    state: Any,
    actions: list[dict[str, Any]],
    *,
    portfolio_context: dict[str, Any] | None = None,
) -> list[str]:
    symbols: list[str] = []
    for action in actions:
        append_unique_symbol(symbols, action.get("symbol"))
    scheduler = getattr(state, "scheduler", None)
    for item in getattr(scheduler, "watchlist", []) or []:
        symbol = item[0] if isinstance(item, (list, tuple)) and item else item
        append_unique_symbol(symbols, symbol)
    context = portfolio_context or decision_portfolio_context(state)
    portfolio = context.get("portfolio")
    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    if isinstance(positions, dict):
        for symbol in positions:
            append_unique_symbol(symbols, symbol)
    config = getattr(state, "config", None)
    for asset in getattr(config, "assets", []) or []:
        if isinstance(asset, dict):
            append_unique_symbol(symbols, asset.get("symbol"))
    return symbols


def append_unique_symbol(symbols: list[str], symbol: Any) -> None:
    if symbol is None:
        return
    value = str(symbol)
    if value and value not in symbols:
        symbols.append(value)


def collect_decision_quotes(state: Any) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    db = getattr(state, "db", None)
    persistent_reader_available = db is not None and any(
        callable(getattr(db, name, None))
        for name in ("list_latest_quotes_sync", "get_latest_quotes_sync")
    )
    for reader_name in ("list_latest_quotes_sync", "get_latest_quotes_sync"):
        reader = getattr(db, reader_name, None)
        if not callable(reader):
            continue
        for row in reader() or []:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol")
            if symbol is None:
                continue
            quotes[str(symbol)] = normalize_quote(symbol, row)
    if persistent_reader_available:
        return quotes
    scheduler = getattr(state, "scheduler", None)
    for symbol, quote in (getattr(scheduler, "latest_quotes", {}) or {}).items():
        if isinstance(quote, dict):
            quotes[str(symbol)] = normalize_quote(symbol, quote)
    return quotes


def normalize_quote(symbol: Any, quote: dict[str, Any]) -> dict[str, Any]:
    return {
        **quote,
        "symbol": str(quote.get("symbol") or symbol),
        "asset_class": quote.get("asset_class") or quote.get("asset_type"),
        "quote_status": quote.get("quote_status") or quote.get("provider_status"),
        "quote_timestamp": quote.get("quote_timestamp") or quote.get("timestamp"),
    }


def latest_quote_timestamp(quotes: Any) -> str | None:
    timestamps = [
        parsed
        for quote in quotes
        for timestamp in [quote.get("quote_timestamp") or quote.get("timestamp")]
        for parsed in [parse_action_timestamp(timestamp)]
        if parsed is not None
    ]
    return max(timestamps).isoformat() if timestamps else None


def has_persistent_quote_cache(state: Any) -> bool:
    db = getattr(state, "db", None)
    if db is None:
        return False
    for reader_name in ("list_latest_quotes_sync", "get_latest_quotes_sync"):
        reader = getattr(db, reader_name, None)
        if not callable(reader):
            continue
        rows = reader() or []
        if rows:
            return True
    return False
