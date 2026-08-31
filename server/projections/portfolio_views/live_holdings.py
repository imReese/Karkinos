"""Canonical portfolio live holdings projections."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from core.types import Symbol
from server.models import (
    LiveHoldingGroupResponse,
    LiveHoldingItemResponse,
    LiveHoldingsResponse,
)
from server.projections.portfolio_application import (
    current_valuation_snapshot as _current_valuation_snapshot,
)
from server.projections.portfolio_application import (
    hydrate_missing_position_quotes as _hydrate_missing_position_quotes,
)
from server.projections.portfolio_application import (
    ledger_entry_shanghai_date as _ledger_entry_shanghai_date,
)
from server.projections.portfolio_application import (
    normalize_asset_class as _normalize_asset_class,
)
from server.projections.portfolio_application import (
    position_quote_presentation as _position_quote_presentation,
)
from server.projections.portfolio_application import (
    quote_age_seconds as _quote_age_seconds,
)
from server.projections.portfolio_application import quote_source as _quote_source
from server.projections.portfolio_application import (
    quotes_from_valuation_snapshot as _quotes_from_valuation_snapshot,
)
from server.projections.portfolio_application import (
    read_daily_ledger_entries as _read_daily_ledger_entries,
)
from server.projections.portfolio_application import refresh_policy as _refresh_policy
from server.projections.portfolio_application import (
    resolve_position_today_change as _resolve_position_today_change,
)
from server.projections.portfolio_application import (
    resolve_projection_sources as _resolve_projection_sources,
)
from server.projections.portfolio_application import (
    using_persistent_cache as _using_persistent_cache,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.asset_metadata import resolve_asset_metadata
from server.services.market_hours import get_shanghai_now, is_cn_trading_session
from server.services.position_presence import (
    is_economically_zero_quantity,
)
from server.services.valuation_snapshot import (
    valuation_identity_fields,
)

_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def session_closed_market_bar_price(
    state,
    *,
    symbol: str,
    latest_quote: dict | None,
) -> tuple[float | None, str | None]:
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_day = (
        latest_timestamp.date()
        if latest_timestamp is not None
        else get_shanghai_now().date()
    )
    now = get_shanghai_now()
    if trade_day != now.date() or is_cn_trading_session(now):
        return None, None
    if state.db is None or not hasattr(state.db, "get_market_bar_on_date_sync"):
        return None, None
    market_bar = state.db.get_market_bar_on_date_sync(symbol, trade_day.isoformat())
    if not market_bar:
        return None, None
    close = market_bar.get("close", market_bar.get("price"))
    if close in {None, ""}:
        return None, None
    return (
        float(close),
        market_bar.get("trade_date")
        or str(market_bar.get("timestamp", "")).split("T")[0],
    )


def resolve_live_holding_latest_price(
    state,
    *,
    symbol: str,
    latest_quote: dict | None,
    latest_price_value: float | None,
) -> float | None:
    _ = state, symbol, latest_quote
    return latest_price_value


def get_recent_quote_snapshots(state, symbol: str, limit: int = 2) -> list[dict]:
    if state.db is None or not hasattr(state.db, "get_recent_quote_snapshots_sync"):
        return []
    rows = state.db.get_recent_quote_snapshots_sync(symbol, limit=limit)
    return rows if isinstance(rows, list) else []


def has_same_day_sell(
    state,
    *,
    symbol: str,
    trade_day: date,
    ledger_entries: list[dict] | None = None,
) -> bool:
    resolved_entries = (
        _read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    return any(
        str(entry.get("symbol") or "") == symbol
        and str(entry.get("entry_type") or "").lower() == "trade_sell"
        and _ledger_entry_shanghai_date(entry) == trade_day
        for entry in resolved_entries
    )


def build_live_holdings_response(
    state,
    valuation_snapshot: dict | None = None,
    *,
    now: datetime | None = None,
) -> LiveHoldingsResponse:
    resolved_now = now or get_shanghai_now()
    valuation_snapshot = valuation_snapshot or _current_valuation_snapshot(state)
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
        return LiveHoldingsResponse(
            groups=[], **valuation_identity_fields(valuation_snapshot)
        )

    groups: dict[str, list[LiveHoldingItemResponse]] = defaultdict(list)
    daily_ledger_entries = _read_daily_ledger_entries(state)

    for sym, pos in portfolio.positions.items():
        quantity = float(pos.quantity)
        if is_economically_zero_quantity(quantity):
            continue

        symbol = str(sym)
        instrument = instruments.get(Symbol(symbol)) if instruments else None
        latest_quote = latest_quotes.get(symbol, {})
        asset_class = _normalize_asset_class(
            latest_quote.get("asset_class")
            or getattr(getattr(instrument, "asset_class", None), "value", None)
        )
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=latest_quote,
            fallback_name=getattr(instrument, "name", symbol),
        )
        latest_price = latest_quote.get("price")
        latest_price_value = (
            float(latest_price) if latest_price not in {None, ""} else None
        )
        latest_price_value = resolve_live_holding_latest_price(
            state,
            symbol=symbol,
            latest_quote=latest_quote if latest_quote else None,
            latest_price_value=latest_price_value,
        )
        (
            today_change,
            today_change_pct,
            baseline_price,
            baseline_timestamp,
            baseline_source,
        ) = _resolve_position_today_change(
            state,
            symbol=symbol,
            quantity=quantity,
            avg_cost=float(pos.avg_cost),
            latest_quote=latest_quote if latest_quote else None,
            latest_price_value=latest_price_value,
            ledger_entries=daily_ledger_entries,
            now=resolved_now,
        )
        avg_cost = float(pos.avg_cost)
        market_value = (
            quantity * latest_price_value
            if latest_price_value is not None
            else float(pos.market_value)
        )
        cost_basis = quantity * avg_cost
        since_buy_pnl = market_value - cost_basis
        since_buy_pnl_pct = None if cost_basis == 0 else since_buy_pnl / cost_basis
        quote_status, stale_reason = _position_quote_presentation(
            state,
            symbol=symbol,
            asset_class=metadata.asset_class,
            quote=latest_quote,
            now=resolved_now,
        )

        groups[metadata.asset_class].append(
            LiveHoldingItemResponse(
                symbol=symbol,
                name=metadata.display_name,
                display_name=metadata.display_name,
                asset_class=metadata.asset_class,
                quantity=quantity,
                avg_cost=avg_cost,
                market_value=market_value,
                latest_price=latest_price_value,
                quote_timestamp=latest_quote.get("timestamp"),
                since_buy_pnl=since_buy_pnl,
                since_buy_pnl_pct=since_buy_pnl_pct,
                today_change=today_change,
                today_change_pct=today_change_pct,
                baseline_price=baseline_price,
                baseline_timestamp=baseline_timestamp,
                baseline_source=baseline_source,
                quote_status=quote_status,
                quote_source=_quote_source(state, latest_quote),
                quote_age_seconds=_quote_age_seconds(latest_quote, now=resolved_now),
                stale_reason=stale_reason,
                refresh_policy=_refresh_policy(resolved_now),
                using_persistent_cache=_using_persistent_cache(latest_quote),
                nav_date=latest_quote.get("nav_date"),
            )
        )

    response_groups: list[LiveHoldingGroupResponse] = []
    for asset_class, items in groups.items():
        items.sort(key=lambda item: item.market_value, reverse=True)
        today_change_complete = all(item.today_change is not None for item in items)
        response_groups.append(
            LiveHoldingGroupResponse(
                asset_class=asset_class,
                label=_ASSET_CLASS_LABELS.get(asset_class, asset_class.upper()),
                total_market_value=sum(item.market_value for item in items),
                total_today_change=(
                    sum(float(item.today_change) for item in items)
                    if today_change_complete
                    else None
                ),
                total_since_buy_pnl=sum(item.since_buy_pnl for item in items),
                items=items,
            )
        )

    response_groups.sort(key=lambda group: -group.total_market_value)
    return LiveHoldingsResponse(
        groups=response_groups,
        **valuation_identity_fields(valuation_snapshot),
    )


__all__ = (
    "build_live_holdings_response",
    "get_recent_quote_snapshots",
    "has_same_day_sell",
    "resolve_live_holding_latest_price",
    "session_closed_market_bar_price",
)
