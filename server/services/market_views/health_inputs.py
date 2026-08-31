"""Canonical market health inputs projections."""

from __future__ import annotations

import json

from core.types import AssetClass, Symbol
from server.models import (
    MarketCalendarSnapshotResponse,
    MarketHealthQuote,
)
from server.services.asset_metadata import (
    resolve_asset_metadata,
)
from server.services.market_indices import (
    default_market_index_assets,
)
from server.services.market_refresh import optional_float as _optional_float
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}


def adapt_latest_quote_for_health(row: dict) -> dict:
    quote = dict(row)
    if quote.get("asset_class") in {None, ""} and quote.get("asset_type") not in {
        None,
        "",
    }:
        quote["asset_class"] = quote.get("asset_type")
    if quote.get("timestamp") in {None, ""} and quote.get("quote_timestamp") not in {
        None,
        "",
    }:
        quote["timestamp"] = quote.get("quote_timestamp")
    return quote


def find_asset_config(
    assets: list[dict[str, str]], symbol: str
) -> dict[str, str] | None:
    for asset_cfg in assets:
        if asset_cfg["symbol"] == symbol:
            return asset_cfg
    return None


def resolve_asset_class(symbol: str, assets: list[dict[str, str]]) -> AssetClass:
    if asset_cfg := find_asset_config(assets, symbol):
        return _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
    return AssetClass.STOCK


def resolve_asset_display_name(assets: list[dict[str, str]], symbol: str) -> str:
    if asset_cfg := find_asset_config(assets, symbol):
        return str(asset_cfg.get("display_name") or asset_cfg["symbol"])
    return symbol


def configured_provider_name(state) -> str:
    return str(getattr(state.config, "data_source", "unknown") or "unknown")


def provider_requires_token(provider_name: str) -> bool:
    return provider_name == "tushare"


def provider_configured(state, provider_name: str) -> bool:
    if provider_requires_token(provider_name):
        return bool(getattr(state.config, "tushare_token", ""))
    return provider_name in {"akshare", "tushare"}


def provider_supports_funds(provider_name: str) -> bool | None:
    if provider_name == "akshare":
        return True
    if provider_name == "tushare":
        return False
    return None


def provider_next_action(
    *,
    provider_configured: bool,
    provider_supports_funds: bool | None,
    has_funds: bool,
    latest_refresh_error: str | None,
    source_health: str,
) -> str | None:
    if not provider_configured:
        return "configure_data_source_token"
    if has_funds and provider_supports_funds is False:
        return "switch_to_fund_supported_provider"
    if latest_refresh_error == "provider_timeout":
        return "check_provider_network_or_use_cache"
    if latest_refresh_error:
        return "check_data_source_settings"
    if source_health in {
        "cache",
        "confirmed_nav_missing",
        "estimated",
        "missing",
        "partial",
        "stale",
    }:
        return "refresh_quotes_or_check_source"
    return None


def json_array(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def market_calendar_snapshot_response(
    row: dict | None,
    *,
    exchange: str,
    year: int,
) -> MarketCalendarSnapshotResponse:
    if row is None:
        return MarketCalendarSnapshotResponse(
            exchange=exchange.upper(),
            year=int(year),
            provider="none",
            status="missing",
            source_fingerprint=None,
            limitations=[
                "market_calendar_snapshot_missing",
                "Run explicit market calendar sync before using holiday labels.",
            ],
        )
    return MarketCalendarSnapshotResponse(
        schema_version=str(row.get("schema_version") or "karkinos.market_calendar.v1"),
        exchange=str(row.get("exchange") or exchange).upper(),
        year=int(row.get("year") or year),
        provider=str(row.get("provider") or "unknown"),
        status=str(row.get("status") or "available"),
        trading_day_count=int(row.get("trading_day_count") or 0),
        closed_day_count=int(row.get("closed_day_count") or 0),
        source_fingerprint=row.get("source_fingerprint"),
        official_verification_status=str(
            row.get("official_verification_status") or "unverified"
        ),
        official_source_url=row.get("official_source_url"),
        verification_source_fingerprint=row.get("verification_source_fingerprint"),
        official_source_fingerprint=row.get("official_source_fingerprint"),
        official_verified_at=row.get("official_verified_at"),
        official_verified_by=row.get("official_verified_by"),
        limitations=json_array(row.get("limitations_json")),
        days=json_array(row.get("days_json")),
        updated_at=row.get("updated_at"),
    )


def aggregate_market_data_health_status(
    health_quotes: list[MarketHealthQuote],
) -> str:
    if not health_quotes:
        return "unknown"
    statuses = {item.quote_status for item in health_quotes}
    if statuses == {"live"}:
        return "live"
    for status in (
        "missing",
        "confirmed_nav_missing",
        "estimated",
        "stale",
        "cache",
    ):
        if statuses == {status}:
            return status
    return "partial"


def has_live_fund_quotes(health_quotes: list[MarketHealthQuote]) -> bool:
    fund_quotes = [
        item for item in health_quotes if item.asset_class in {"fund", "etf"}
    ]
    return bool(fund_quotes) and all(
        item.quote_status == "live" and item.price is not None for item in fund_quotes
    )


def normalize_asset_class(asset_class: AssetClass | str | None) -> str:
    if isinstance(asset_class, AssetClass):
        return asset_class.value
    if isinstance(asset_class, str):
        return asset_class
    return AssetClass.STOCK.value


def extract_runtime_portfolio(state):
    scheduler = getattr(state, "scheduler", None)
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
    instruments = getattr(scheduler, "instruments", {}) if scheduler else {}
    latest_quotes: dict[str, dict] = {}
    db = getattr(state, "db", None)
    persistent_reader_available = db is not None and (
        hasattr(db, "get_latest_quotes_sync") or hasattr(db, "list_latest_quotes_sync")
    )
    if db is not None and hasattr(db, "list_latest_quotes_sync"):
        for row in db.list_latest_quotes_sync():
            latest_quotes[str(row["symbol"])] = row
    if db is not None and hasattr(db, "get_latest_quotes_sync"):
        for row in db.get_latest_quotes_sync():
            latest_quotes.setdefault(str(row["symbol"]), row)
    if (
        not persistent_reader_available
        and scheduler
        and getattr(scheduler, "latest_quotes", None)
    ):
        for symbol, quote in scheduler.latest_quotes.items():
            latest_quotes[str(symbol)] = quote

    if (
        db is not None
        and hasattr(db, "get_ledger_entries_sync")
        and hasattr(state.config, "initial_cash")
    ):
        rebuilt = rebuild_portfolio_from_ledger(
            state.config,
            db,
            latest_quotes=latest_quotes,
        )
        portfolio = rebuilt.portfolio
        instruments = rebuilt.instruments

    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    return portfolio, positions, instruments, latest_quotes


def position_for_symbol(positions, symbol: str):
    return positions.get(Symbol(symbol)) or positions.get(symbol)


def ledger_position_assets(state) -> list[dict[str, str]]:
    db = getattr(state, "db", None)
    get_entries = getattr(db, "get_ledger_entries_sync", None)
    if not callable(get_entries):
        return []

    quantities: dict[str, float] = {}
    asset_classes: dict[str, str] = {}
    offset = 0
    batch_size = 500
    while True:
        rows = get_entries(limit=batch_size, offset=offset)
        if not rows:
            break
        for row in rows:
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            quantity = _optional_float(row.get("quantity")) or 0.0
            if quantity == 0:
                continue
            entry_type = str(row.get("entry_type") or "").strip().lower()
            direction = str(row.get("direction") or "").strip().lower()
            if entry_type in {"trade_sell", "sell"} or direction == "sell":
                quantity = -abs(quantity)
            elif entry_type in {"trade_buy", "buy", "trade"} or direction == "buy":
                quantity = abs(quantity)
            else:
                continue
            quantities[symbol] = quantities.get(symbol, 0.0) + quantity
            asset_classes[symbol] = normalize_asset_class(
                row.get("asset_class") or AssetClass.STOCK.value
            )
        if len(rows) < batch_size:
            break
        offset += batch_size

    assets: list[dict[str, str]] = []
    for symbol, quantity in quantities.items():
        if quantity <= 0:
            continue
        asset_class = asset_classes.get(symbol, AssetClass.STOCK.value)
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            fallback_name=symbol,
        )
        assets.append(
            {
                "symbol": symbol,
                "asset_class": metadata.asset_class,
                "display_name": metadata.display_name,
            }
        )
    return assets


def merged_watchlist_assets(state) -> list[dict[str, str]]:
    _, positions, instruments, latest_quotes = extract_runtime_portfolio(state)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    persisted_assets = list_watchlist() if callable(list_watchlist) else []
    config_assets = []
    if not persisted_assets:
        config_assets = getattr(state.config, "assets", []) or []

    for asset_cfg in persisted_assets:
        symbol = str(asset_cfg.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=str(asset_cfg.get("asset_class") or "stock"),
            fallback_name=str(asset_cfg.get("display_name") or symbol),
        )
        merged.append(
            {
                "symbol": symbol,
                "asset_class": metadata.asset_class,
                "display_name": metadata.display_name,
            }
        )
        seen.add(symbol)

    for asset_cfg in config_assets:
        symbol = str(
            asset_cfg.get("provider_symbol")
            or asset_cfg.get("provider_code")
            or asset_cfg.get("code")
            or asset_cfg["symbol"]
        )
        if symbol in seen:
            continue
        merged.append(
            {
                "symbol": symbol,
                "asset_class": asset_cfg["asset_class"],
                "display_name": asset_cfg.get("display_name")
                or asset_cfg.get("symbol", symbol),
            }
        )
        seen.add(symbol)

    for raw_symbol in positions:
        symbol = str(raw_symbol)
        if symbol in seen:
            continue
        instrument = instruments.get(Symbol(symbol))
        asset_class = normalize_asset_class(
            getattr(instrument, "asset_class", None)
            or latest_quotes.get(symbol, {}).get("asset_class")
            or AssetClass.STOCK.value
        )
        metadata = resolve_asset_metadata(
            state,
            symbol,
            asset_class=asset_class,
            quote=latest_quotes.get(symbol),
            fallback_name=getattr(instrument, "name", None) or symbol,
        )
        merged.append(
            {
                "symbol": symbol,
                "asset_class": metadata.asset_class,
                "display_name": metadata.display_name,
            }
        )
        seen.add(symbol)

    for asset_cfg in ledger_position_assets(state):
        symbol = asset_cfg["symbol"]
        if symbol in seen:
            continue
        merged.append(asset_cfg)
        seen.add(symbol)

    return merged


def with_default_market_indices(
    assets: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = list(assets)
    seen = {asset["symbol"] for asset in merged}
    for asset_cfg in default_market_index_assets():
        symbol = asset_cfg["symbol"]
        if symbol in seen:
            continue
        merged.append(asset_cfg)
        seen.add(symbol)
    return merged


def normalize_refresh_symbols(symbols: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol).strip()
        if not symbol or symbol in seen:
            continue
        normalized.append(symbol)
        seen.add(symbol)
    return normalized


def default_refresh_symbols(state) -> list[str]:
    _, positions, _, _ = extract_runtime_portfolio(state)
    holding_symbols = normalize_refresh_symbols(
        [str(raw_symbol) for raw_symbol in positions]
    )
    persisted_watchlist_symbols: list[str] = []
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        persisted_watchlist_symbols = normalize_refresh_symbols(
            [str(asset.get("symbol") or "") for asset in list_watchlist()]
        )
    index_symbols = normalize_refresh_symbols(
        [asset_cfg["symbol"] for asset_cfg in default_market_index_assets()]
    )
    return normalize_refresh_symbols(
        [*holding_symbols, *persisted_watchlist_symbols, *index_symbols]
    )


__all__ = (
    "adapt_latest_quote_for_health",
    "aggregate_market_data_health_status",
    "configured_provider_name",
    "default_refresh_symbols",
    "extract_runtime_portfolio",
    "find_asset_config",
    "has_live_fund_quotes",
    "json_array",
    "ledger_position_assets",
    "market_calendar_snapshot_response",
    "merged_watchlist_assets",
    "normalize_asset_class",
    "normalize_refresh_symbols",
    "position_for_symbol",
    "provider_configured",
    "provider_next_action",
    "provider_requires_token",
    "provider_supports_funds",
    "resolve_asset_class",
    "resolve_asset_display_name",
    "with_default_market_indices",
)
