"""Asset configuration, fund confirmation, and allocation projections."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, time, timedelta

from server.models import AllocationGroup, AllocationItem

_FUND_SUBSCRIPTION_CUTOFF = time(15, 0)
_ASSET_CLASS_LABELS = {
    "stock": "股票",
    "fund": "基金",
    "etf": "ETF",
    "gold": "黄金",
    "bond": "债券",
    "cash": "现金",
}


def normalize_asset_class(value: str | None) -> str:
    if not value:
        return "other"
    normalized = str(value).strip().lower()
    if normalized in {"stock", "fund", "etf", "gold", "bond", "cash"}:
        return normalized
    return "other"


def ensure_asset_config(
    state,
    *,
    symbol: str,
    asset_class: str,
    display_name: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    existing_display_name = None
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        try:
            existing_watchlist = next(
                (
                    asset
                    for asset in list_watchlist() or []
                    if str(asset.get("symbol") or "").strip().lower()
                    == symbol.strip().lower()
                ),
                None,
            )
        except Exception:
            existing_watchlist = None
        if existing_watchlist is not None:
            existing_display_name = (
                str(existing_watchlist.get("display_name") or "").strip() or None
            )

    upsert_watchlist = getattr(db, "upsert_watchlist_asset_sync", None)
    if callable(upsert_watchlist) and existing_display_name is None:
        upsert_watchlist(
            symbol=symbol,
            asset_class=asset_class,
            display_name=display_name or symbol,
            source="trade",
        )

    existing_metadata = None
    get_metadata = getattr(db, "get_instrument_metadata_sync", None)
    if callable(get_metadata):
        try:
            existing_metadata = get_metadata(symbol, asset_class)
            if existing_metadata is None:
                existing_metadata = get_metadata(symbol)
        except Exception:
            existing_metadata = None
    upsert_metadata = getattr(db, "upsert_instrument_metadata_sync", None)
    if callable(upsert_metadata) and existing_metadata is None:
        upsert_metadata(
            symbol=symbol,
            asset_type=asset_class,
            display_name=display_name or existing_display_name or symbol,
            provider_symbol=symbol,
            source="trade",
        )


def resolve_fund_buy_fill(
    state,
    *,
    symbol: str,
    timestamp: str,
    gross_amount: float,
    commission: float,
) -> dict:
    from core.types import AssetClass, BarFrequency, Symbol
    from data.manager import build_sources

    submitted_at = datetime.fromisoformat(timestamp)
    target_date = submitted_at.date()
    if submitted_at.time() >= _FUND_SUBSCRIPTION_CUTOFF:
        target_date += timedelta(days=1)

    sources = build_sources(
        data_source=getattr(state.config, "data_source", "akshare"),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    akshare = sources["akshare"]
    symbol_obj = Symbol(symbol.strip())
    display_name = (
        akshare._resolve_open_end_fund_name(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_name")
        else str(symbol_obj)
    ) or str(symbol_obj)
    canonical_symbol = (
        akshare._resolve_open_end_fund_code(symbol_obj)
        if hasattr(akshare, "_resolve_open_end_fund_code")
        else str(symbol_obj)
    ) or str(symbol_obj)

    start = datetime.combine(submitted_at.date() - timedelta(days=1), time.min)
    end = datetime.combine(submitted_at.date() + timedelta(days=10), time.max)
    bars = akshare.fetch_bars(
        Symbol(canonical_symbol),
        start=start,
        end=end,
        frequency=BarFrequency.DAILY,
        asset_class=AssetClass.FUND,
    )
    if bars.empty:
        raise ValueError("No fund NAV history available from AKShare")

    eligible = bars[bars["timestamp"].dt.date >= target_date].sort_values("timestamp")
    latest_available = bars["timestamp"].max().date()
    if eligible.empty:
        raise LookupError(
            f"Fund NAV for target trade date {target_date.isoformat()} is not published yet "
            f"(latest available {latest_available.isoformat()})."
        )

    confirmed = eligible.iloc[0]
    confirmed_trade_date = confirmed["timestamp"].date().isoformat()
    confirmed_nav = float(confirmed["close"])
    net_amount = gross_amount - commission
    if net_amount <= 0:
        raise ValueError("Net subscription amount must be positive")
    quantity = net_amount / confirmed_nav
    return {
        "symbol": canonical_symbol,
        "display_name": display_name,
        "price": confirmed_nav,
        "quantity": quantity,
        "confirmed_trade_date": confirmed_trade_date,
        "gross_amount": gross_amount,
        "target_trade_date": target_date.isoformat(),
    }


def confirm_pending_fund_orders(state) -> int:
    """Try to convert published pending fund subscriptions into normal trades."""
    if state.db is None or not hasattr(state.db, "get_pending_fund_orders_sync"):
        return 0

    confirmed_count = 0
    for order in state.db.get_pending_fund_orders_sync(status="pending"):
        try:
            resolved = resolve_fund_buy_fill(
                state,
                symbol=order["symbol"],
                timestamp=order["submitted_at"],
                gross_amount=float(order["amount"]),
                commission=float(order.get("commission") or 0.0),
            )
        except (LookupError, ValueError):
            continue

        note_parts = [
            order.get("note") or "",
            f"Auto-confirmed pending fund subscription: gross_amount={resolved['gross_amount']:.2f}",
            f"confirmed_trade_date={resolved['confirmed_trade_date']}",
            f"confirmed_nav={resolved['price']:.6f}",
        ]
        trade_id = state.db.add_trade_sync(
            timestamp=order["submitted_at"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
        )
        state.db.insert_ledger_entry_sync(
            entry_type="trade_buy",
            timestamp=order["submitted_at"],
            amount=resolved["quantity"] * resolved["price"],
            symbol=resolved["symbol"],
            direction="buy",
            quantity=resolved["quantity"],
            price=resolved["price"],
            commission=float(order.get("commission") or 0.0),
            asset_class="fund",
            note=" | ".join(part for part in note_parts if part),
            source="portfolio_trade",
            source_ref=f"trade:{trade_id}",
        )
        state.db.mark_pending_fund_order_confirmed_sync(
            order_id=int(order["id"]),
            trade_id=trade_id,
            confirmed_nav=resolved["price"],
            confirmed_quantity=resolved["quantity"],
            confirmed_trade_date=resolved["confirmed_trade_date"],
        )
        ensure_asset_config(
            state,
            symbol=resolved["symbol"],
            asset_class="fund",
            display_name=resolved["display_name"],
        )
        confirmed_count += 1
    return confirmed_count


def build_grouped_allocation(
    allocation: list[AllocationItem], total_equity: float
) -> list[AllocationGroup]:
    """按 asset_class 聚合 allocation 列表。"""
    groups: dict[str, list[AllocationItem]] = defaultdict(list)
    for item in allocation:
        groups[item.asset_class].append(item)

    result = []
    for ac, items in groups.items():
        group_value = sum(i.value for i in items)
        result.append(
            AllocationGroup(
                asset_class=ac,
                name=_ASSET_CLASS_LABELS.get(ac, ac),
                value=group_value,
                weight=group_value / total_equity if total_equity > 0 else 0,
                items=items,
            )
        )
    # 现金排第一，其余按市值降序
    result.sort(key=lambda g: (g.asset_class != "cash", -g.value))
    return result


def parse_fee_breakdown(value) -> dict | None:
    if not value:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
