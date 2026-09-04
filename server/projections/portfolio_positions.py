"""Ledger-backed position and daily-performance projections."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from core.types import InstrumentType
from server.models import AccountOverview, PortfolioSnapshot
from server.projections.portfolio_assets import (
    normalize_asset_class,
    parse_fee_breakdown,
)
from server.projections.portfolio_quotes import (
    collect_latest_quotes,
    has_position_ledger_entries,
    normalize_asset_class_value,
    refresh_policy,
)
from server.projections.portfolio_read_snapshot_persistence import (
    portfolio_read_snapshot_for_state,
)
from server.projections.quote_status import (
    parse_quote_timestamp as _parse_quote_timestamp,
)
from server.services.daily_performance import (
    build_position_daily_context,
    mark_position_daily,
)
from server.services.market_hours import get_shanghai_now
from server.services.portfolio_ledger import (
    rebuild_portfolio_from_entries,
    rebuild_portfolio_from_ledger,
)

_SH_TZ = ZoneInfo("Asia/Shanghai")


def has_rows(rows: list[dict]) -> bool:
    """Compatibility predicate for read-only portfolio consumers."""

    return bool(rows)


def resolve_live_holding_baseline(
    state,
    symbol: str,
    latest_quote: dict | None,
    *,
    instrument_type: object,
    as_of: datetime | None = None,
) -> tuple[float | None, str | None, str]:
    try:
        normalized_instrument_type = InstrumentType.from_persisted(
            instrument_type
        ).value
    except ValueError:
        return None, None, "instrument_identity_unavailable"
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    trade_date = (
        latest_timestamp.date().isoformat()
        if latest_timestamp is not None
        else (as_of or get_shanghai_now()).astimezone(_SH_TZ).date().isoformat()
    )

    if latest_quote:
        previous_close = latest_quote.get("previous_close")
        previous_close_date = latest_quote.get("previous_close_date")
        if previous_close not in {None, 0, ""}:
            return (
                float(previous_close),
                None if previous_close_date in {None, ""} else str(previous_close_date),
                str(latest_quote.get("previous_close_source") or "previous_close"),
            )

        if "valuation_baseline_status" in latest_quote:
            return None, None, "snapshot_baseline_unavailable"

    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        candidates = [
            dict(row)
            for row in read_snapshot.price_matrix_rows
            if str(row.get("symbol") or "").strip() == symbol
            and str(row.get("trade_date") or "") < trade_date
            and row.get("price") not in {None, ""}
        ]
        if candidates:
            baseline = max(
                candidates,
                key=lambda row: (
                    str(row.get("trade_date") or ""),
                    str(row.get("timestamp") or ""),
                ),
            )
            source = str(baseline.get("source") or "snapshot_price_matrix")
            if source == "market_bars":
                source = "market_bar_close"
            elif source == "daily_close_snapshots":
                source = "daily_close"
            elif source == "quote_snapshots":
                source = "fallback_close"
            return (
                float(baseline["price"]),
                str(baseline.get("trade_date") or "") or None,
                source,
            )
        return None, None, "snapshot_baseline_unavailable"

    if state.db is not None and hasattr(
        state.db, "get_latest_market_bar_before_date_sync"
    ):
        market_bar = state.db.get_latest_market_bar_before_date_sync(
            symbol,
            trade_date,
            instrument_type=normalized_instrument_type,
        )
        if market_bar:
            return (
                float(market_bar.get("close", market_bar.get("price"))),
                market_bar.get("trade_date")
                or str(market_bar.get("timestamp", "")).split("T")[0],
                "market_bar_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_daily_close_before_sync"):
        daily_close = state.db.get_latest_daily_close_before_sync(
            symbol,
            trade_date,
            instrument_type=normalized_instrument_type,
        )
        if daily_close:
            return (
                float(daily_close["close_price"]),
                daily_close.get("trade_date"),
                "daily_close",
            )

    if state.db is not None and hasattr(state.db, "get_latest_quote_before_date_sync"):
        fallback_quote = state.db.get_latest_quote_before_date_sync(
            symbol,
            trade_date,
            instrument_type=normalized_instrument_type,
        )
        if fallback_quote:
            return (
                float(fallback_quote["price"]),
                fallback_quote.get("timestamp"),
                "fallback_close",
            )

    return None, None, "unavailable"


def ledger_entry_shanghai_date(entry: dict) -> date | None:
    timestamp = entry.get("timestamp")
    if timestamp in {None, ""}:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ).date()


def read_daily_ledger_entries(state, *, batch_size: int = 500) -> list[dict]:
    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        return [dict(row) for row in read_snapshot.ledger_rows]
    db = state.db
    if db is None or not hasattr(db, "get_ledger_entries_sync"):
        return []

    entries: list[dict] = []
    offset = 0
    while True:
        batch = db.get_ledger_entries_sync(limit=batch_size, offset=offset)
        if not batch:
            break
        entries.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size
    return entries


def same_day_buy_lots(
    state,
    *,
    symbol: str,
    trade_day: date,
    ledger_entries: list[dict] | None = None,
) -> list[dict[str, float | datetime]]:
    lots: list[dict[str, float | datetime]] = []
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    for entry in resolved_entries:
        if (
            str(entry.get("symbol") or "") != symbol
            or str(entry.get("entry_type") or "").lower() != "trade_buy"
            or ledger_entry_shanghai_date(entry) != trade_day
        ):
            continue
        quantity = entry.get("quantity")
        price = entry.get("price")
        if quantity in {None, ""} or price in {None, ""}:
            continue
        quantity_value = float(quantity)
        if quantity_value <= 0:
            continue
        timestamp = _parse_quote_timestamp(entry.get("timestamp"))
        if timestamp is None:
            continue
        trade_cost = quantity_value * float(price)
        trade_cost += ledger_entry_trade_total_fee(entry)
        lots.append(
            {
                "timestamp": timestamp.astimezone(_SH_TZ),
                "quantity": quantity_value,
                "price": float(price),
                "total_cost": trade_cost,
                "avg_cost": trade_cost / quantity_value,
            }
        )

    return sorted(lots, key=lambda lot: lot["timestamp"])


def ledger_entry_trade_total_fee(entry: dict) -> float:
    breakdown = (
        parse_fee_breakdown(
            entry.get("fee_breakdown_json") or entry.get("fee_breakdown")
        )
        or {}
    )
    total_fee = breakdown.get("total_fee")
    if total_fee not in {None, ""}:
        return abs(float(total_fee))

    commission = breakdown.get("commission")
    total = abs(
        float(commission)
        if commission not in {None, ""}
        else float(entry.get("commission") or 0.0)
    )
    for aliases in (
        ("subscription_fee",),
        ("redemption_fee",),
        ("stamp_tax", "tax"),
        ("transfer_fee",),
        ("other_fees",),
        ("surcharge_fee",),
        ("exchange_clearing_fee",),
    ):
        for key in aliases:
            value = breakdown.get(key)
            if value not in {None, ""}:
                total += abs(float(value))
                break
    return total


def same_day_sell_lots(
    state,
    *,
    symbol: str,
    trade_day: date,
    ledger_entries: list[dict] | None = None,
) -> list[dict[str, float | datetime]]:
    lots: list[dict[str, float | datetime]] = []
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    for entry in resolved_entries:
        if (
            str(entry.get("symbol") or "") != symbol
            or str(entry.get("entry_type") or "").lower() != "trade_sell"
            or ledger_entry_shanghai_date(entry) != trade_day
        ):
            continue
        quantity = entry.get("quantity")
        price = entry.get("price")
        if quantity in {None, ""} or price in {None, ""}:
            continue
        quantity_value = float(quantity)
        if quantity_value <= 0:
            continue
        timestamp = _parse_quote_timestamp(entry.get("timestamp"))
        if timestamp is None:
            continue
        net_cash_impact = entry.get("net_cash_impact")
        net_proceeds = (
            float(net_cash_impact)
            if net_cash_impact not in {None, ""}
            else quantity_value * float(price) - ledger_entry_trade_total_fee(entry)
        )
        lots.append(
            {
                "timestamp": timestamp.astimezone(_SH_TZ),
                "quantity": quantity_value,
                "price": float(price),
                "net_proceeds": net_proceeds,
            }
        )

    return sorted(lots, key=lambda lot: lot["timestamp"])


def resolve_position_today_change(
    state,
    *,
    symbol: str,
    quantity: float,
    avg_cost: float,
    latest_quote: dict | None,
    latest_price_value: float | None,
    instrument_type: object,
    ledger_entries: list[dict] | None = None,
    now: datetime | None = None,
) -> tuple[float | None, float | None, float | None, str | None, str]:
    baseline_price, baseline_timestamp, baseline_source = resolve_live_holding_baseline(
        state,
        symbol,
        latest_quote,
        instrument_type=instrument_type,
        as_of=now,
    )
    latest_timestamp = _parse_quote_timestamp(
        None if latest_quote is None else latest_quote.get("timestamp")
    )
    resolved_entries = (
        read_daily_ledger_entries(state) if ledger_entries is None else ledger_entries
    )
    shanghai_today = (now or get_shanghai_now()).astimezone(_SH_TZ).date()
    has_today_trade = any(
        str(entry.get("symbol") or "") == symbol
        and str(entry.get("entry_type") or "").lower() in {"trade_buy", "trade_sell"}
        and ledger_entry_shanghai_date(entry) == shanghai_today
        for entry in resolved_entries
    )
    trade_day = (
        shanghai_today
        if has_today_trade or latest_timestamp is None
        else latest_timestamp.date()
    )
    buy_lots = same_day_buy_lots(
        state,
        symbol=symbol,
        trade_day=trade_day,
        ledger_entries=resolved_entries,
    )
    sell_lots = same_day_sell_lots(
        state,
        symbol=symbol,
        trade_day=trade_day,
        ledger_entries=resolved_entries,
    )
    context = build_position_daily_context(
        quantity=quantity,
        previous_close=baseline_price,
        same_day_buy_lots=buy_lots,
        same_day_sell_lots=sell_lots,
    )
    if (context.lots or context.sell_lots) and context.status == "complete":
        baseline_price = context.baseline_price
        baseline_timestamp = trade_day.isoformat()
        baseline_source = context.source
    elif context.status != "complete":
        baseline_source = context.source

    mark = mark_position_daily(context, price=latest_price_value)
    if mark.status != "complete":
        return (
            None,
            None,
            baseline_price,
            baseline_timestamp,
            mark.source,
        )

    return (
        mark.today_change,
        mark.today_change_pct,
        baseline_price,
        baseline_timestamp,
        baseline_source,
    )


def resolve_projection_sources(
    state,
    *,
    latest_quotes: dict[str, dict] | None = None,
) -> tuple[object | None, dict]:
    scheduler = state.scheduler
    portfolio = scheduler.portfolio if scheduler else None
    instruments = scheduler.instruments if scheduler else {}

    if state.db is None:
        return portfolio, instruments

    latest_quotes = (
        collect_latest_quotes(state) if latest_quotes is None else latest_quotes
    )
    read_snapshot = portfolio_read_snapshot_for_state(state)
    if read_snapshot is not None:
        rebuilt = rebuild_portfolio_from_entries(
            state.config,
            read_snapshot.ledger_rows,
            latest_quotes=latest_quotes,
        )
        return rebuilt.portfolio, rebuilt.instruments
    if hasattr(state.db, "get_ledger_entries_sync"):
        rebuilt = rebuild_portfolio_from_ledger(
            state.config,
            state.db,
            latest_quotes=latest_quotes,
        )
        return rebuilt.portfolio, rebuilt.instruments

    if portfolio is not None:
        return portfolio, instruments

    return None, {}


def snapshot_quote_status(snapshot: PortfolioSnapshot) -> str:
    if any(position.quote_status == "missing" for position in snapshot.positions):
        return "missing"
    if any(position.quote_status == "stale" for position in snapshot.positions):
        return "stale"
    return "live"


def snapshot_quote_age_seconds(snapshot: PortfolioSnapshot) -> int | None:
    ages = [
        position.quote_age_seconds
        for position in snapshot.positions
        if position.quote_age_seconds is not None
    ]
    return max(ages) if ages else None


def snapshot_stale_reason(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_status == "stale" and position.stale_reason:
            return position.stale_reason
        if position.quote_status == "missing" and position.stale_reason:
            return position.stale_reason
    return None


def snapshot_quote_source(snapshot: PortfolioSnapshot) -> str | None:
    for position in snapshot.positions:
        if position.quote_source:
            return position.quote_source
    return None


def snapshot_uses_persistent_cache(snapshot: PortfolioSnapshot) -> bool:
    return any(position.using_persistent_cache for position in snapshot.positions)


def with_overview_quote_metadata(
    overview: AccountOverview,
    snapshot: PortfolioSnapshot,
    *,
    now: datetime | None = None,
) -> AccountOverview:
    resolved_now = now or get_shanghai_now()
    return overview.model_copy(
        update={
            "valuation_timestamp": resolved_now.isoformat(),
            "quote_status": snapshot_quote_status(snapshot),
            "quote_age_seconds": snapshot_quote_age_seconds(snapshot),
            "quote_source": snapshot_quote_source(snapshot),
            "stale_reason": snapshot_stale_reason(snapshot),
            "refresh_policy": refresh_policy(resolved_now),
            "using_persistent_cache": snapshot_uses_persistent_cache(snapshot),
        }
    )
