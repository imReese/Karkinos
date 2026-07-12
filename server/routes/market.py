"""Market routes — /api/market/*"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import date, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from core.types import AssetClass, BarFrequency, Symbol
from data.market_calendar import build_market_calendar_provider
from server.models import (
    KlineBar,
    MarketCalendarSnapshotResponse,
    MarketCalendarSyncRequest,
    MarketCalendarVerificationRequest,
    MarketDataHealthResponse,
    MarketHealthQuote,
    MarketQuote,
    QuoteFetchRunResponse,
    ResearchBoardItem,
    ResearchBoardResponse,
    ResearchNoteCreate,
    ResearchNoteListResponse,
    ResearchNoteResponse,
    ResearchNoteUpdate,
    WatchlistCreateRequest,
    WatchlistItem,
)
from server.services.asset_metadata import (
    metadata_configured_count,
    resolve_asset_metadata,
)
from server.services.data_health import build_data_health
from server.services.market_hours import is_cn_trading_session
from server.services.market_indices import (
    default_market_index_assets,
    market_index_display_name,
)
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger
from server.services.valuation_snapshot import build_current_valuation_snapshot

logger = logging.getLogger(__name__)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_QUOTE_REFRESH_ATTEMPTS: dict[tuple[str, str], datetime] = {}
_QUOTE_REFRESH_ERRORS: dict[tuple[str, str], str | None] = {}
_MANUAL_REFRESH_TIMEOUT_SECONDS = 8.0
_PROVIDER_REFRESH_TIMEOUT_SECONDS = 3.0
_KLINE_FETCH_TIMEOUT_SECONDS = 3.0
_BAR_BACKFILL_TIMEOUT_SECONDS = 60.0
_BLOCKING_FETCH_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="market-fetch",
)
_SH_TZ = ZoneInfo("Asia/Shanghai")

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
    "index": AssetClass.INDEX,
}
_TUSHARE_FUND_NAV_PERMISSION_DENIED = "tushare_fund_nav_permission_denied"


class QuoteRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


class QuoteRefreshSymbolResult(BaseModel):
    symbol: str
    asset_class: str
    status: str
    quote_timestamp: str | None = None
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    error: str | None = None
    reason: str | None = None
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    using_persistent_cache: bool = False


class QuoteRefreshResponse(BaseModel):
    requested_symbols: list[str]
    refreshed: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    failed: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    skipped: list[QuoteRefreshSymbolResult] = Field(default_factory=list)
    refresh_policy: str
    market_open: bool
    started_at: str
    completed_at: str
    duration_ms: int
    quote_status: str
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None
    message: str
    real_data_available: bool = False
    has_persistent_cache: bool = False


class InstrumentMetadataBackfillRequest(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


class InstrumentMetadataBackfillItem(BaseModel):
    symbol: str
    asset_class: str
    status: str
    display_name: str | None = None
    provider: str | None = None
    error: str | None = None


class InstrumentMetadataBackfillResponse(BaseModel):
    provider: str
    requested_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    items: list[InstrumentMetadataBackfillItem] = Field(default_factory=list)


class MarketBarsBackfillRequest(BaseModel):
    symbols: list[str] | None = None
    asset_class: str | None = None
    start: str | None = None
    end: str | None = None
    interval: str = "1d"
    force: bool = False


class MarketBarsBackfillItem(BaseModel):
    symbol: str
    asset_class: str
    status: str
    row_count: int = 0
    stored_start: str | None = None
    stored_end: str | None = None
    error: str | None = None


class MarketBarsBackfillResponse(BaseModel):
    provider: str
    interval: str
    start: str
    end: str
    requested_count: int
    updated_count: int
    cached_count: int
    failed_count: int
    items: list[MarketBarsBackfillItem] = Field(default_factory=list)


def _shanghai_now() -> datetime:
    return datetime.now(_SH_TZ)


def _parse_quote_timestamp(timestamp: object) -> datetime | None:
    if isinstance(timestamp, datetime):
        parsed = timestamp
    elif isinstance(timestamp, str) and timestamp.strip():
        value = timestamp.strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(f"{value}T00:00:00")
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_SH_TZ)
    return parsed.astimezone(_SH_TZ)


def _quote_age_seconds(quote: dict | None, now: datetime | None = None) -> int | None:
    timestamp = _parse_quote_timestamp(
        None if quote is None else quote.get("timestamp")
    )
    if timestamp is None:
        return None
    current = now or _shanghai_now()
    return max(int((current - timestamp).total_seconds()), 0)


def _latest_refresh_attempt(symbol: str, asset_class: str) -> str | None:
    attempt = _QUOTE_REFRESH_ATTEMPTS.get((symbol, asset_class))
    return None if attempt is None else attempt.isoformat()


def _latest_refresh_error(symbol: str, asset_class: str) -> str | None:
    return _QUOTE_REFRESH_ERRORS.get((symbol, asset_class))


def _quote_source(state, quote: dict | None) -> str | None:
    if not quote:
        return None
    source = (
        quote.get("quote_source")
        or quote.get("source")
        or quote.get("provider_name")
        or quote.get("provider")
    )
    if source:
        return str(source)
    configured = getattr(state.config, "data_source", None)
    if configured:
        return str(configured)
    return None


def _is_real_persistent_quote(quote: dict | None) -> bool:
    return bool(quote and quote.get("price") not in {None, ""})


def _adapt_latest_quote_for_health(row: dict) -> dict:
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


def _mark_persistent_cache_quote(
    quote: dict | None, *, stale_reason: str = "source_unavailable"
) -> dict | None:
    if quote is None:
        return None
    marked = dict(quote)
    marked["quote_status"] = "stale"
    marked["stale_reason"] = stale_reason
    marked["provider_status"] = "error"
    marked["using_persistent_cache"] = True
    marked["persistent_cache_status"] = "available"
    return marked


def _provider_error_code(exc: Exception) -> str | None:
    message = str(exc)
    normalized = message.lower()
    if "fund_nav" in normalized and (
        "访问权限" in message
        or "没有接口" in message
        or "permission" in normalized
        or "access" in normalized
    ):
        return _TUSHARE_FUND_NAV_PERMISSION_DENIED
    return None


def _provider_error_reason(error_code: str, *, using_cache: bool) -> str:
    if error_code == _TUSHARE_FUND_NAV_PERMISSION_DENIED:
        return (
            "TuShare fund_nav 权限不足，继续使用本地基金缓存"
            if using_cache
            else "TuShare fund_nav 权限不足，请使用 Eastmoney 基金估算源或提升 TuShare 权限"
        )
    return (
        "行情源刷新失败，继续使用本地缓存"
        if using_cache
        else "行情源刷新失败，暂无真实行情数据"
    )


def _stale_reason(
    state,
    quote: dict | None,
    *,
    market_open: bool,
    refresh_policy: str,
    now: datetime | None = None,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return (
            str(quote.get("stale_reason"))
            if quote and quote.get("stale_reason")
            else "no_real_data_available"
        )

    timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return "quote_timestamp_missing"

    if _resolve_quote_status(state, quote) != "stale":
        return None

    if refresh_policy == "cache_only":
        return (
            "market_closed_cache_only"
            if not market_open
            else "refresh_policy_cache_only"
        )

    age = _quote_age_seconds(quote, now=now)
    ttl_seconds = (
        max(int(getattr(state.config, "live_poll_interval", 60) or 60), 15) * 3
    )
    if age is not None and age > ttl_seconds:
        return "quote_older_than_expected_session"

    return "quote_older_than_expected_session"


def _quote_metadata(
    state,
    symbol: str,
    asset_class: str,
    quote: dict | None,
    *,
    market_open: bool,
    refresh_policy: str,
    now: datetime | None = None,
) -> dict:
    metadata = resolve_asset_metadata(
        state,
        symbol,
        asset_class=asset_class,
        quote=quote,
        fallback_name=symbol,
    )
    display_name = (
        (
            str(quote.get("display_name") or quote.get("name") or "").strip()
            if quote
            else ""
        )
        or market_index_display_name(symbol)
        or metadata.display_name
    )
    daily_change = (
        None
        if quote is None
        else _optional_float(
            quote.get("daily_change")
            or quote.get("day_change_value")
            or quote.get("change")
        )
    )
    daily_change_pct = (
        None
        if quote is None
        else _optional_float(
            quote.get("daily_change_pct")
            or quote.get("day_change_pct")
            or quote.get("change_pct")
            or quote.get("change_percent")
            or quote.get("pct_chg")
        )
    )
    quote_status = (
        "missing"
        if not quote or quote.get("price") in {None, ""}
        else _resolve_quote_status(state, quote)
    )
    stale_reason = (
        str(quote.get("stale_reason"))
        if quote and quote.get("stale_reason")
        else _stale_reason(
            state,
            quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
            now=now,
        )
    )
    return {
        "name": display_name,
        "display_name": display_name,
        "daily_change": daily_change,
        "daily_change_pct": daily_change_pct,
        "change": daily_change,
        "change_pct": daily_change_pct,
        "pct_chg": daily_change_pct,
        "quote_status": quote_status,
        "quote_source": _quote_source(state, quote),
        "quote_age_seconds": _quote_age_seconds(quote, now=now),
        "stale_reason": stale_reason,
        "last_refresh_attempt": _latest_refresh_attempt(symbol, asset_class),
        "last_refresh_error": _latest_refresh_error(symbol, asset_class),
        "using_persistent_cache": bool(
            quote
            and (
                quote.get("using_persistent_cache")
                or quote.get("captured_reason") == "persistent_cache"
            )
        ),
        "nav_date": None if quote is None else quote.get("nav_date"),
    }


def _find_asset_config(
    assets: list[dict[str, str]], symbol: str
) -> dict[str, str] | None:
    for asset_cfg in assets:
        if asset_cfg["symbol"] == symbol:
            return asset_cfg
    return None


def _resolve_asset_class(symbol: str, assets: list[dict[str, str]]) -> AssetClass:
    if asset_cfg := _find_asset_config(assets, symbol):
        return _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
    return AssetClass.STOCK


def _resolve_asset_display_name(assets: list[dict[str, str]], symbol: str) -> str:
    if asset_cfg := _find_asset_config(assets, symbol):
        return str(asset_cfg.get("display_name") or asset_cfg["symbol"])
    return symbol


def _configured_provider_name(state) -> str:
    return str(getattr(state.config, "data_source", "unknown") or "unknown")


def _provider_requires_token(provider_name: str) -> bool:
    return provider_name == "tushare"


def _provider_configured(state, provider_name: str) -> bool:
    if _provider_requires_token(provider_name):
        return bool(getattr(state.config, "tushare_token", ""))
    return provider_name in {"akshare", "tushare"}


def _provider_supports_funds(provider_name: str) -> bool | None:
    if provider_name == "akshare":
        return True
    if provider_name == "tushare":
        return False
    return None


def _provider_next_action(
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


def _json_array(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _market_calendar_snapshot_response(
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
        official_verified_at=row.get("official_verified_at"),
        official_verified_by=row.get("official_verified_by"),
        limitations=_json_array(row.get("limitations_json")),
        days=_json_array(row.get("days_json")),
        updated_at=row.get("updated_at"),
    )


def _aggregate_market_data_health_status(
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


def _has_live_fund_quotes(health_quotes: list[MarketHealthQuote]) -> bool:
    fund_quotes = [
        item for item in health_quotes if item.asset_class in {"fund", "etf"}
    ]
    return bool(fund_quotes) and all(
        item.quote_status == "live" and item.price is not None for item in fund_quotes
    )


def _normalize_asset_class(asset_class: AssetClass | str | None) -> str:
    if isinstance(asset_class, AssetClass):
        return asset_class.value
    if isinstance(asset_class, str):
        return asset_class
    return AssetClass.STOCK.value


def _extract_runtime_portfolio(state):
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
        and hasattr(db, "get_trades_sync")
        and hasattr(db, "get_cash_flows_sync")
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


def _position_for_symbol(positions, symbol: str):
    return positions.get(Symbol(symbol)) or positions.get(symbol)


def _ledger_position_assets(state) -> list[dict[str, str]]:
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
            asset_classes[symbol] = _normalize_asset_class(
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


def _merged_watchlist_assets(state) -> list[dict[str, str]]:
    _, positions, instruments, latest_quotes = _extract_runtime_portfolio(state)
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
        asset_class = _normalize_asset_class(
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

    for asset_cfg in _ledger_position_assets(state):
        symbol = asset_cfg["symbol"]
        if symbol in seen:
            continue
        merged.append(asset_cfg)
        seen.add(symbol)

    return merged


def _with_default_market_indices(
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


def _normalize_refresh_symbols(symbols: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols or []:
        symbol = str(raw_symbol).strip()
        if not symbol or symbol in seen:
            continue
        normalized.append(symbol)
        seen.add(symbol)
    return normalized


def _default_refresh_symbols(state) -> list[str]:
    _, positions, _, _ = _extract_runtime_portfolio(state)
    holding_symbols = _normalize_refresh_symbols(
        [str(raw_symbol) for raw_symbol in positions]
    )
    persisted_watchlist_symbols: list[str] = []
    db = getattr(state, "db", None)
    list_watchlist = getattr(db, "list_watchlist_assets_sync", None)
    if callable(list_watchlist):
        persisted_watchlist_symbols = _normalize_refresh_symbols(
            [str(asset.get("symbol") or "") for asset in list_watchlist()]
        )
    index_symbols = _normalize_refresh_symbols(
        [asset_cfg["symbol"] for asset_cfg in default_market_index_assets()]
    )
    return _normalize_refresh_symbols(
        [*holding_symbols, *persisted_watchlist_symbols, *index_symbols]
    )


def _quote_fetch_run_asset_type(
    requested_symbols: list[str],
    asset_class_by_symbol: dict[str, AssetClass],
) -> str | None:
    asset_types = {
        asset_class_by_symbol.get(symbol, AssetClass.STOCK).value
        for symbol in requested_symbols
    }
    if not asset_types:
        return None
    if len(asset_types) == 1:
        return next(iter(asset_types))
    return "mixed"


def _create_manual_quote_fetch_run(
    state,
    *,
    run_id: str,
    started_at: str,
    requested_symbols: list[str],
    asset_type: str | None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "create_quote_fetch_run"):
        return
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at=started_at,
        trigger="manual_refresh",
        provider=_configured_provider_name(state),
        asset_type=asset_type,
        symbol_count=len(requested_symbols),
        status="running",
        metadata={
            "requested_symbols": requested_symbols,
        },
    )


def _manual_quote_fetch_run_status(
    *,
    quote_status: str,
    success_count: int,
    failure_count: int,
    cache_hit_count: int,
) -> str:
    if quote_status == "live":
        return "success"
    if cache_hit_count > 0 and success_count == 0:
        return "cache_only"
    if success_count > 0 or cache_hit_count > 0:
        return "partial_success"
    if failure_count > 0:
        return "failed"
    return "failed"


def _manual_quote_fetch_provider_status(
    state,
    *,
    quote_status: str,
    last_refresh_error: str | None,
) -> str:
    if last_refresh_error:
        return "failed"
    if quote_status == "live":
        return "live"
    if quote_status == "partial":
        return "partial"
    if quote_status == "stale":
        return "cache"
    return "failed"


def _finish_manual_quote_fetch_run(
    state,
    *,
    run_id: str,
    finished_at: str,
    requested_symbols: list[str],
    refreshed: list[QuoteRefreshSymbolResult],
    failed: list[QuoteRefreshSymbolResult],
    skipped: list[QuoteRefreshSymbolResult],
    quote_status: str,
    refresh_policy: str,
    market_open: bool,
    last_refresh_error: str | None,
    valuation_snapshot_id: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "finish_quote_fetch_run"):
        return
    success_count = len(refreshed)
    failure_count = len(failed)
    cache_hit_count = sum(
        1 for result in [*refreshed, *failed, *skipped] if result.using_persistent_cache
    )
    status = _manual_quote_fetch_run_status(
        quote_status=quote_status,
        success_count=success_count,
        failure_count=failure_count,
        cache_hit_count=cache_hit_count,
    )
    metadata = {
        "provider": _configured_provider_name(state),
        "provider_status": _manual_quote_fetch_provider_status(
            state,
            quote_status=quote_status,
            last_refresh_error=last_refresh_error,
        ),
        "quote_status": quote_status,
        "refresh_policy": refresh_policy,
        "market_open": market_open,
        "using_persistent_cache": cache_hit_count > 0,
        "requested_symbols": requested_symbols,
        "refreshed_symbols": [result.symbol for result in refreshed],
        "failed_symbols": [result.symbol for result in failed],
        "skipped_symbols": [result.symbol for result in skipped],
        "valuation_snapshot_id": valuation_snapshot_id,
    }
    db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at=finished_at,
        status=status,
        success_count=success_count,
        failure_count=failure_count,
        cache_hit_count=cache_hit_count,
        error_message=last_refresh_error,
        metadata=metadata,
    )


def _quote_fetch_run_metadata(row: dict) -> dict | None:
    metadata_json = row.get("metadata_json")
    if not metadata_json:
        return None
    try:
        parsed = json.loads(str(metadata_json))
    except (TypeError, ValueError):
        return {
            "raw_metadata": str(metadata_json),
            "parse_error": "invalid_json",
        }
    if isinstance(parsed, dict):
        return parsed
    return {
        "raw_metadata": str(metadata_json),
        "parse_error": "metadata_not_object",
    }


def _quote_fetch_run_response(row: dict) -> QuoteFetchRunResponse:
    return QuoteFetchRunResponse(
        run_id=str(row["run_id"]),
        trigger=str(row["trigger"]),
        provider=row.get("provider"),
        asset_type=row.get("asset_type"),
        status=str(row["status"]),
        started_at=str(row["started_at"]),
        finished_at=row.get("finished_at"),
        symbol_count=int(row.get("symbol_count") or 0),
        success_count=int(row.get("success_count") or 0),
        failure_count=int(row.get("failure_count") or 0),
        cache_hit_count=int(row.get("cache_hit_count") or 0),
        error_message=row.get("error_message"),
        metadata=_quote_fetch_run_metadata(row),
    )


def _metadata_name_is_useful(row: dict | None, symbol: str) -> bool:
    if not row:
        return False
    display_name = str(row.get("display_name") or "").strip()
    return bool(
        display_name and display_name != symbol and display_name != f"{symbol} A股"
    )


def _instrument_metadata_targets(
    state,
    requested_symbols: list[str] | None = None,
) -> list[dict[str, str]]:
    by_symbol: dict[str, dict[str, str]] = {}
    for asset_cfg in _merged_watchlist_assets(state):
        symbol = str(asset_cfg.get("symbol") or "").strip()
        if not symbol:
            continue
        by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "asset_class": _normalize_asset_class(asset_cfg.get("asset_class")),
            },
        )

    symbols = _normalize_refresh_symbols(requested_symbols)
    if symbols:
        return [
            by_symbol.get(
                symbol,
                {
                    "symbol": symbol,
                    "asset_class": AssetClass.STOCK.value,
                },
            )
            for symbol in symbols
        ]
    return list(by_symbol.values())


def _provider_asset_class(asset_class: str) -> AssetClass:
    return _ASSET_CLASS_MAP.get(asset_class, AssetClass.STOCK)


def _bar_frequency(interval: str) -> BarFrequency:
    frequency = {
        "1m": BarFrequency.MIN_1,
        "5m": BarFrequency.MIN_5,
        "1d": BarFrequency.DAILY,
    }.get(interval)
    if frequency is None:
        raise HTTPException(
            status_code=422, detail="interval must be one of 1d, 1m, 5m"
        )
    return frequency


def _parse_backfill_date(
    value: str | None, *, field_name: str, default: date
) -> datetime:
    raw = value or default.isoformat()
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must use YYYY-MM-DD",
        ) from exc


def _market_bar_backfill_range(
    state, request: MarketBarsBackfillRequest
) -> tuple[datetime, datetime]:
    config_start = getattr(state.config, "start_date", None)
    default_start = date.today() - timedelta(days=365)
    if config_start:
        try:
            default_start = date.fromisoformat(str(config_start))
        except ValueError:
            pass
    start = _parse_backfill_date(
        request.start, field_name="start", default=default_start
    )
    end = _parse_backfill_date(
        request.end,
        field_name="end",
        default=_shanghai_now().date(),
    )
    if start > end:
        raise HTTPException(
            status_code=422, detail="start must be before or equal to end"
        )
    return start, end


def _market_bar_backfill_targets(
    state,
    request: MarketBarsBackfillRequest,
) -> list[dict[str, str]]:
    targets = _instrument_metadata_targets(state, request.symbols)
    if request.asset_class:
        asset_class = _normalize_asset_class(request.asset_class)
        targets = [{**target, "asset_class": asset_class} for target in targets]
    return targets


def _meta_covers_range(meta: dict | None, start: datetime, end: datetime) -> bool:
    if not meta or not meta.get("start_date") or not meta.get("end_date"):
        return False
    try:
        meta_start = datetime.fromisoformat(str(meta["start_date"]))
        meta_end = datetime.fromisoformat(str(meta["end_date"]))
    except ValueError:
        return False
    return meta_start <= start and meta_end >= end


async def _backfill_market_bars(
    state,
    request: MarketBarsBackfillRequest,
) -> MarketBarsBackfillResponse:
    from data.manager import DataManager, build_sources
    from data.store import DataStore

    provider_name = str(getattr(state.config, "data_source", "akshare") or "akshare")
    frequency = _bar_frequency(request.interval)
    start, end = _market_bar_backfill_range(state, request)
    targets = _market_bar_backfill_targets(state, request)
    store = DataStore()
    manager = DataManager(
        sources=build_sources(
            data_source=provider_name,
            tushare_token=getattr(state.config, "tushare_token", ""),
        ),
        store=store,
        default_source=provider_name,
    )

    def _run_backfill() -> list[MarketBarsBackfillItem]:
        items: list[MarketBarsBackfillItem] = []
        for target in targets:
            symbol = target["symbol"]
            asset_class = _normalize_asset_class(target.get("asset_class"))
            provider_asset_class = _provider_asset_class(asset_class)
            before = store.get_meta(Symbol(symbol), frequency)
            cached_before = _meta_covers_range(before, start, end)
            try:
                handler = manager.get_bars(
                    Symbol(symbol),
                    start,
                    end,
                    frequency,
                    provider_asset_class,
                    allow_remote_refresh=True,
                    refresh_ttl_seconds=0 if request.force else None,
                    degrade_to_cache=False,
                )
                after = store.get_meta(Symbol(symbol), frequency)
                status = "cached" if cached_before and not request.force else "updated"
                items.append(
                    MarketBarsBackfillItem(
                        symbol=symbol,
                        asset_class=asset_class,
                        status=status,
                        row_count=int(getattr(handler, "total_bars", 0)),
                        stored_start=None if after is None else after.get("start_date"),
                        stored_end=None if after is None else after.get("end_date"),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Historical bar backfill failed for %s",
                    symbol,
                    exc_info=True,
                )
                items.append(
                    MarketBarsBackfillItem(
                        symbol=symbol,
                        asset_class=asset_class,
                        status="failed",
                        error=str(exc),
                    )
                )
        return items

    items = await asyncio.wait_for(
        _run_blocking_fetch(_run_backfill),
        timeout=_BAR_BACKFILL_TIMEOUT_SECONDS,
    )
    return MarketBarsBackfillResponse(
        provider=provider_name,
        interval=frequency.value,
        start=start.date().isoformat(),
        end=end.date().isoformat(),
        requested_count=len(targets),
        updated_count=sum(1 for item in items if item.status == "updated"),
        cached_count=sum(1 for item in items if item.status == "cached"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        items=items,
    )


def _extract_provider_display_name(payload: dict | None) -> str | None:
    if not payload:
        return None
    display_name = str(
        payload.get("display_name")
        or payload.get("name")
        or payload.get("asset_name")
        or ""
    ).strip()
    return display_name or None


async def _backfill_instrument_metadata(
    state,
    request: InstrumentMetadataBackfillRequest,
) -> InstrumentMetadataBackfillResponse:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_instrument_metadata_sync"):
        raise HTTPException(
            status_code=503, detail="instrument metadata database is unavailable"
        )

    from data.manager import build_sources

    provider_name = "akshare"
    sources = build_sources(
        data_source=getattr(state.config, "data_source", provider_name),
        tushare_token=getattr(state.config, "tushare_token", ""),
    )
    source = sources.get(provider_name)
    if source is None or not hasattr(source, "fetch_latest"):
        raise HTTPException(status_code=503, detail="akshare source is unavailable")

    items: list[InstrumentMetadataBackfillItem] = []
    timeout = float(
        getattr(state.config, "metadata_backfill_timeout_seconds", 8.0) or 8.0
    )

    for target in _instrument_metadata_targets(state, request.symbols):
        symbol = target["symbol"]
        asset_class = target["asset_class"]
        existing = (
            db.get_instrument_metadata_sync(symbol, asset_class)
            if hasattr(db, "get_instrument_metadata_sync")
            else None
        )
        if _metadata_name_is_useful(existing, symbol) and not request.force:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="skipped",
                    display_name=existing.get("display_name"),
                    provider=existing.get("provider_name") or existing.get("provider"),
                )
            )
            continue

        try:
            payload = await asyncio.wait_for(
                _run_blocking_fetch(
                    source.fetch_latest,
                    Symbol(symbol),
                    _provider_asset_class(asset_class),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error="provider_timeout",
                )
            )
            continue
        except Exception as exc:
            logger.warning(
                "Instrument metadata backfill failed for %s", symbol, exc_info=True
            )
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error=str(exc),
                )
            )
            continue

        display_name = _extract_provider_display_name(payload)
        if not display_name:
            items.append(
                InstrumentMetadataBackfillItem(
                    symbol=symbol,
                    asset_class=asset_class,
                    status="failed",
                    provider=provider_name,
                    error="metadata_not_available",
                )
            )
            continue

        fetched_at = datetime.now().isoformat()
        db.upsert_instrument_metadata_sync(
            symbol=symbol,
            asset_type=asset_class,
            display_name=display_name,
            provider_symbol=str(payload.get("provider_symbol") or symbol),
            exchange=payload.get("exchange"),
            market=payload.get("market"),
            provider_name=provider_name,
            source="backfill",
            fetched_at=fetched_at,
            metadata={
                "quote_timestamp": payload.get("timestamp"),
                "quote_source": payload.get("quote_source")
                or payload.get("source")
                or provider_name,
                "payload_keys": sorted(str(key) for key in payload.keys()),
            },
        )
        items.append(
            InstrumentMetadataBackfillItem(
                symbol=symbol,
                asset_class=asset_class,
                status="updated",
                display_name=display_name,
                provider=provider_name,
            )
        )

    return InstrumentMetadataBackfillResponse(
        provider=provider_name,
        requested_count=len(items),
        updated_count=sum(1 for item in items if item.status == "updated"),
        skipped_count=sum(1 for item in items if item.status == "skipped"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        items=items,
    )


def _latest_persistent_real_quote(state, symbol: str) -> dict | None:
    if state.db is None or not hasattr(state.db, "get_latest_quotes_sync"):
        return None
    for row in state.db.get_latest_quotes_sync():
        if row.get("symbol") == symbol and _is_real_persistent_quote(row):
            return row
    return None


def _store_runtime_quote(state, symbol: str, quote: dict) -> None:
    scheduler = state.scheduler
    if scheduler is None:
        return
    if hasattr(scheduler, "_latest_quotes"):
        scheduler._latest_quotes[symbol] = quote
        return
    latest_quotes = getattr(scheduler, "latest_quotes", None)
    if isinstance(latest_quotes, dict):
        latest_quotes[symbol] = quote


def _optional_float(value) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


async def _run_blocking_fetch(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _BLOCKING_FETCH_EXECUTOR,
        partial(func, *args),
    )


def _upsert_instrument_metadata_from_quote(
    state,
    *,
    symbol: str,
    asset_type: str,
    snapshot: dict,
    provider_name: str | None,
    fetched_at: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_instrument_metadata_sync"):
        return
    display_name = str(
        snapshot.get("display_name")
        or snapshot.get("name")
        or snapshot.get("asset_name")
        or ""
    ).strip()
    if not display_name:
        return
    try:
        db.upsert_instrument_metadata_sync(
            symbol=symbol,
            asset_type=asset_type,
            display_name=display_name,
            provider_symbol=snapshot.get("provider_symbol") or symbol,
            exchange=snapshot.get("exchange"),
            market=snapshot.get("market"),
            provider_name=provider_name,
            source="quote",
            fetched_at=fetched_at,
            metadata={
                "source": snapshot.get("source"),
                "quote_source": snapshot.get("quote_source"),
            },
        )
    except Exception:
        logger.warning(
            "Failed to upsert instrument metadata for %s", symbol, exc_info=True
        )


def _upsert_latest_quote_snapshot(
    state,
    *,
    symbol: str,
    asset_type: str,
    snapshot: dict,
    quote_source: str | None,
    provider_name: str | None,
    provider_status: str | None,
    quote_status: str,
    captured_reason: str,
    nav_date: str | None = None,
    fetch_run_id: str | None = None,
) -> None:
    db = getattr(state, "db", None)
    if db is None or not hasattr(db, "upsert_latest_quote_sync"):
        return
    timestamp = snapshot.get("timestamp")
    if not timestamp:
        return
    try:
        db.upsert_latest_quote_sync(
            symbol=symbol,
            asset_type=asset_type,
            price=float(snapshot["price"]),
            previous_close=_optional_float(snapshot.get("previous_close")),
            change=_optional_float(snapshot.get("change")),
            change_percent=_optional_float(
                snapshot.get("change_percent") or snapshot.get("pct_chg")
            ),
            volume=_optional_float(snapshot.get("volume")),
            turnover=_optional_float(
                snapshot.get("turnover") or snapshot.get("amount")
            ),
            quote_timestamp=str(timestamp),
            quote_source=quote_source,
            provider_name=provider_name,
            provider_status=provider_status,
            quote_status=quote_status,
            stale_reason=snapshot.get("stale_reason"),
            captured_at=datetime.now().isoformat(),
            captured_reason=captured_reason,
            nav_date=nav_date,
            fetch_run_id=fetch_run_id,
            metadata={
                "source": snapshot.get("source"),
                "display_name": snapshot.get("display_name") or snapshot.get("name"),
            },
        )
        _upsert_instrument_metadata_from_quote(
            state,
            symbol=symbol,
            asset_type=asset_type,
            snapshot=snapshot,
            provider_name=provider_name,
            fetched_at=str(timestamp),
        )
    except Exception:
        logger.warning("Failed to upsert latest quote for %s", symbol, exc_info=True)


def _resolve_quote_status(state, quote: dict | None) -> str:
    try:
        from server.routes.portfolio import _quote_status

        return _quote_status(state, quote)
    except Exception:
        logger.warning("Failed to resolve quote status", exc_info=True)
        return "live" if quote and quote.get("timestamp") else "stale"


def _build_research_note_stats(rows: list[dict]) -> dict[str, dict[str, int | str]]:
    stats: dict[str, dict[str, int | str]] = {}
    for row in rows:
        symbol = row["symbol"]
        current = stats.setdefault(symbol, {"count": 0, "latest": ""})
        current["count"] = int(current["count"]) + 1
        updated_at = row.get("updated_at") or ""
        if updated_at and updated_at > str(current["latest"]):
            current["latest"] = updated_at
    return stats


def _load_latest_snapshot_from_provider(
    state, symbol: str, asset_class: AssetClass
) -> dict | None:
    from data.manager import build_sources

    data_source = getattr(state.config, "data_source", "akshare")
    tushare_token = getattr(state.config, "tushare_token", "")
    sources = build_sources(
        data_source=data_source,
        tushare_token=tushare_token,
    )
    preferred = sources.get(data_source, sources["akshare"])
    source_chain = [(data_source if data_source in sources else "akshare", preferred)]
    if data_source != "akshare":
        akshare = sources.get("akshare")
        if akshare is not None and akshare is not preferred:
            source_chain.append(("akshare", akshare))

    snapshot = None
    selected_source_name = data_source
    last_error: Exception | None = None
    fallback_reason_code: str | None = None
    saw_provider_response = False
    primary_source_name = source_chain[0][0]
    for source_name, source in source_chain:
        try:
            snapshot = _fetch_provider_latest_with_timeout(
                source,
                symbol,
                asset_class,
                timeout_seconds=_PROVIDER_REFRESH_TIMEOUT_SECONDS,
            )
            saw_provider_response = True
        except Exception as exc:
            logger.warning(
                "Latest quote provider failed: %s %s (%s)",
                source_name,
                symbol,
                asset_class.value,
                exc_info=True,
            )
            last_error = exc
            if source_name == primary_source_name:
                fallback_reason_code = _provider_error_code(exc)
            snapshot = None
        if snapshot:
            selected_source_name = source_name
            break
    if not snapshot:
        if last_error is not None and not saw_provider_response:
            raise last_error
        return None
    payload = {
        "symbol": symbol,
        "asset_class": asset_class.value,
        "price": snapshot["price"],
        "volume": snapshot.get("volume"),
        "timestamp": snapshot.get("timestamp"),
        "source": snapshot.get("source") or selected_source_name,
        "quote_source": snapshot.get("quote_source")
        or snapshot.get("source")
        or selected_source_name,
        "provider_name": snapshot.get("provider_name") or selected_source_name,
        "provider_symbol": snapshot.get("provider_symbol") or symbol,
        "exchange": snapshot.get("exchange"),
        "market": snapshot.get("market"),
        "quote_status": "live",
        "provider_status": (
            "fallback" if selected_source_name != primary_source_name else "live"
        ),
        "stale_reason": fallback_reason_code,
        "nav_date": snapshot.get("nav_date")
        or (snapshot.get("timestamp") if asset_class == AssetClass.FUND else None),
    }
    display_name = snapshot.get("display_name") or snapshot.get("name")
    if display_name:
        payload["display_name"] = str(display_name)
        payload["name"] = str(display_name)
    previous_close = snapshot.get("previous_close")
    previous_close_date = snapshot.get("previous_close_date")
    change = snapshot.get("change") or snapshot.get("day_change_value")
    change_percent = (
        snapshot.get("change_percent")
        or snapshot.get("pct_chg")
        or snapshot.get("day_change_pct")
    )
    payload["previous_close"] = previous_close
    payload["previous_close_date"] = previous_close_date
    payload["change"] = change
    payload["change_percent"] = change_percent
    return payload


def _fetch_provider_latest_with_timeout(
    source,
    symbol: str,
    asset_class: AssetClass,
    *,
    timeout_seconds: float,
) -> dict | None:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quote-provider")
    future = executor.submit(source.fetch_latest, Symbol(symbol), asset_class)
    try:
        return future.result(timeout=max(float(timeout_seconds), 0.001))
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(
            f"provider fetch_latest timed out after {timeout_seconds:.1f}s"
        ) from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _persist_latest_snapshot(
    state,
    symbol: str,
    payload: dict,
    *,
    fetch_run_id: str | None = None,
) -> None:
    if (
        state.db is not None
        and hasattr(state.db, "save_quote_snapshot_sync")
        and payload.get("timestamp")
    ):
        captured_reason = "manual_or_route_refresh"
        state.db.save_quote_snapshot_sync(
            symbol=symbol,
            asset_class=payload["asset_class"],
            price=float(payload["price"]),
            volume=None if payload["volume"] is None else float(payload["volume"]),
            timestamp=str(payload["timestamp"]),
            quote_source=payload["quote_source"],
            provider_name=payload["provider_name"],
            quote_status=payload["quote_status"],
            provider_status=payload["provider_status"],
            captured_reason=captured_reason,
            nav_date=payload.get("nav_date"),
            fetch_run_id=fetch_run_id,
        )
        snapshot_metadata = dict(payload)
        _upsert_latest_quote_snapshot(
            state,
            symbol=symbol,
            asset_type=payload["asset_class"],
            snapshot=snapshot_metadata,
            quote_source=payload["quote_source"],
            provider_name=payload["provider_name"],
            provider_status=payload["provider_status"],
            quote_status=payload["quote_status"],
            captured_reason=captured_reason,
            nav_date=payload.get("nav_date"),
            fetch_run_id=fetch_run_id,
        )
        previous_close = payload.get("previous_close")
        previous_close_date = payload.get("previous_close_date")
        if (
            previous_close not in {None, ""}
            and previous_close_date not in {None, ""}
            and hasattr(state.db, "save_daily_close_snapshot_sync")
        ):
            state.db.save_daily_close_snapshot_sync(
                symbol=symbol,
                asset_class=payload["asset_class"],
                trade_date=str(previous_close_date),
                close_price=float(previous_close),
                source="reported_previous_close",
            )


def _fetch_latest_snapshot(state, symbol: str, asset_class: AssetClass) -> dict | None:
    payload = _load_latest_snapshot_from_provider(state, symbol, asset_class)
    if payload:
        _persist_latest_snapshot(state, symbol, payload)
    return payload


async def _refresh_one_quote(
    state,
    symbol: str,
    asset_class: AssetClass,
    timeout_seconds: float | None = None,
    fetch_run_id: str | None = None,
) -> QuoteRefreshSymbolResult:
    timeout = (
        _MANUAL_REFRESH_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )
    key = (symbol, asset_class.value)
    attempted_at = datetime.now()
    _QUOTE_REFRESH_ATTEMPTS[key] = attempted_at
    _QUOTE_REFRESH_ERRORS[key] = None
    market_open = is_cn_trading_session()
    refresh_policy = "live" if market_open else "cache_only"
    try:
        snapshot = await asyncio.wait_for(
            _run_blocking_fetch(
                _load_latest_snapshot_from_provider,
                state,
                symbol,
                asset_class,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        cached_quote = _latest_persistent_real_quote(state, symbol)
        cached_quote = _mark_persistent_cache_quote(
            cached_quote, stale_reason="provider_timeout"
        )
        _QUOTE_REFRESH_ERRORS[key] = "provider_timeout"
        metadata = _quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error="provider_timeout",
            reason=(
                "行情源刷新超时，继续使用本地缓存"
                if cached_quote
                else "行情源刷新超时，暂无真实行情数据"
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error="provider_timeout",
            using_persistent_cache=bool(cached_quote),
        )
    except Exception as exc:
        cached_quote = _latest_persistent_real_quote(state, symbol)
        logger.warning("Manual quote refresh failed for %s", symbol, exc_info=True)
        error_code = _provider_error_code(exc)
        error_message = error_code or str(exc)
        _QUOTE_REFRESH_ERRORS[key] = error_message
        cached_quote = _mark_persistent_cache_quote(
            cached_quote, stale_reason=error_code or "provider_unavailable"
        )
        metadata = _quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason=_provider_error_reason(
                error_message,
                using_cache=bool(cached_quote),
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(cached_quote),
        )

    if not snapshot:
        cached_quote = _latest_persistent_real_quote(state, symbol)
        cached_quote = _mark_persistent_cache_quote(
            cached_quote, stale_reason="source_unavailable"
        )
        error_message = None if cached_quote else "no_real_data_available"
        _QUOTE_REFRESH_ERRORS[key] = error_message
        metadata = _quote_metadata(
            state,
            symbol,
            asset_class.value,
            cached_quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
        )
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="stale" if cached_quote else "failed",
            quote_timestamp=(
                None if cached_quote is None else cached_quote.get("timestamp")
            ),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason=(
                "行情源没有返回新报价，继续使用本地缓存"
                if cached_quote
                else "暂无真实行情数据，请配置数据源或执行首次同步"
            ),
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(cached_quote),
        )

    try:
        _persist_latest_snapshot(
            state,
            symbol,
            snapshot,
            fetch_run_id=fetch_run_id,
        )
    except Exception:
        logger.exception("Failed to persist refreshed quote for %s", symbol)
        error_message = "quote_persistence_failed"
        _QUOTE_REFRESH_ERRORS[key] = error_message
        return QuoteRefreshSymbolResult(
            symbol=symbol,
            asset_class=asset_class.value,
            status="failed",
            quote_timestamp=snapshot.get("timestamp"),
            quote_source=snapshot.get("quote_source"),
            error=error_message,
            reason="行情已获取但未完整落库，拒绝发布为可用行情",
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
            using_persistent_cache=bool(_latest_persistent_real_quote(state, symbol)),
        )
    _store_runtime_quote(state, symbol, snapshot)
    quote_status = _resolve_quote_status(state, snapshot)
    metadata = _quote_metadata(
        state,
        symbol,
        asset_class.value,
        snapshot,
        market_open=market_open,
        refresh_policy=refresh_policy,
    )
    return QuoteRefreshSymbolResult(
        symbol=symbol,
        asset_class=asset_class.value,
        status="refreshed" if quote_status == "live" else "stale",
        quote_timestamp=snapshot.get("timestamp"),
        quote_source=metadata["quote_source"],
        quote_age_seconds=metadata["quote_age_seconds"],
        reason=None if quote_status == "live" else "行情源返回的报价仍为缓存行情",
        last_refresh_attempt=attempted_at.isoformat(),
        last_refresh_error=None,
        using_persistent_cache=False,
    )


async def _refresh_quote_snapshot(state, symbol: str, asset_class: AssetClass) -> None:
    try:
        snapshot = await _run_blocking_fetch(
            _load_latest_snapshot_from_provider,
            state,
            symbol,
            asset_class,
        )
        if snapshot:
            _persist_latest_snapshot(state, symbol, snapshot)
    except Exception:
        logger.warning("Async quote refresh failed for %s", symbol, exc_info=True)


def _quote_refresh_due(state, symbol: str, asset_class: AssetClass) -> bool:
    if not is_cn_trading_session():
        return False

    ttl = max(int(getattr(state.config, "live_poll_interval", 60) or 60), 15)
    key = (symbol, asset_class.value)
    now = datetime.now()
    last_attempt = _QUOTE_REFRESH_ATTEMPTS.get(key)
    if last_attempt is not None and (now - last_attempt).total_seconds() < ttl:
        return False
    _QUOTE_REFRESH_ATTEMPTS[key] = now
    return True


def _maybe_schedule_quote_refresh(
    state,
    background_tasks: BackgroundTasks,
    symbol: str,
    asset_class: AssetClass,
) -> None:
    if _quote_refresh_due(state, symbol, asset_class):
        background_tasks.add_task(_refresh_quote_snapshot, state, symbol, asset_class)


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.get("/calendar", response_model=MarketCalendarSnapshotResponse)
    async def get_market_calendar(
        exchange: str = "SSE",
        year: int = 2026,
    ) -> MarketCalendarSnapshotResponse:
        """Read the stored exchange calendar snapshot without network access."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        getter = getattr(db, "get_market_calendar_snapshot_sync", None)
        if not callable(getter):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        row = getter(exchange=exchange, year=year)
        return _market_calendar_snapshot_response(row, exchange=exchange, year=year)

    @r.post("/calendar/sync", response_model=MarketCalendarSnapshotResponse)
    async def sync_market_calendar(
        request: MarketCalendarSyncRequest,
    ) -> MarketCalendarSnapshotResponse:
        """Synchronize a provider calendar snapshot into local storage."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        upsert = getattr(db, "upsert_market_calendar_snapshot_sync", None)
        if not callable(upsert):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        provider_name = str(
            request.provider
            or getattr(state.config, "data_source", "akshare")
            or "akshare"
        ).lower()
        try:
            provider = build_market_calendar_provider(
                provider_name,
                tushare_token=getattr(state.config, "tushare_token", ""),
            )
            snapshot = provider.fetch_snapshot(
                exchange=request.exchange.upper(),
                year=request.year,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"market calendar provider failed: {exc}",
            ) from exc

        row = upsert(snapshot)
        return _market_calendar_snapshot_response(
            row,
            exchange=request.exchange,
            year=request.year,
        )

    @r.put("/calendar/verification", response_model=MarketCalendarSnapshotResponse)
    async def update_market_calendar_verification(
        request: MarketCalendarVerificationRequest,
    ) -> MarketCalendarSnapshotResponse:
        """Record manual official-notice verification for a stored snapshot."""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        updater = getattr(db, "update_market_calendar_verification_sync", None)
        if not callable(updater):
            raise HTTPException(
                status_code=503, detail="market calendar storage unavailable"
            )
        row = updater(
            exchange=request.exchange,
            year=request.year,
            verification_status=request.verification_status,
            official_source_url=request.official_source_url,
            verified_by=request.verified_by,
            review_notes=request.review_notes,
            day_labels=request.day_labels,
        )
        if row is None:
            raise HTTPException(
                status_code=404, detail="market calendar snapshot not found"
            )
        return _market_calendar_snapshot_response(
            row,
            exchange=request.exchange,
            year=request.year,
        )

    @r.get("/watchlist", response_model=list[WatchlistItem])
    async def get_watchlist() -> list[WatchlistItem]:
        """获取配置的关注列表，并附带持仓与快照信息。"""
        from server.app import get_app_state

        state = get_app_state()
        _, positions, _, latest_quotes = _extract_runtime_portfolio(state)

        items: list[WatchlistItem] = []
        for asset_cfg in _merged_watchlist_assets(state):
            sym = asset_cfg["symbol"]
            ac = asset_cfg["asset_class"]
            position = _position_for_symbol(positions, sym)
            quote = latest_quotes.get(sym)
            items.append(
                WatchlistItem(
                    symbol=sym,
                    asset_class=ac,
                    name=str(asset_cfg.get("display_name") or sym),
                    is_holding=position is not None,
                    quantity=None if position is None else float(position.quantity),
                    avg_cost=None if position is None else float(position.avg_cost),
                    market_value=(
                        None if position is None else float(position.market_value)
                    ),
                    unrealized_pnl=(
                        None if position is None else float(position.unrealized_pnl)
                    ),
                    realized_pnl=(
                        None if position is None else float(position.realized_pnl)
                    ),
                    last_snapshot_at=None if quote is None else quote.get("timestamp"),
                )
            )

        return items

    @r.post("/watchlist", response_model=list[WatchlistItem])
    async def add_watchlist_item(
        request: WatchlistCreateRequest,
    ) -> list[WatchlistItem]:
        """新增关注标的并写入持久数据库。"""
        from server.app import get_app_state

        state = get_app_state()
        symbol = request.symbol.strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        if any(
            asset["symbol"].lower() == symbol.lower()
            for asset in _merged_watchlist_assets(state)
        ):
            raise HTTPException(status_code=409, detail="symbol already exists")

        db = getattr(state, "db", None)
        upsert_watchlist = getattr(db, "upsert_watchlist_asset_sync", None)
        if not callable(upsert_watchlist):
            raise HTTPException(status_code=503, detail="watchlist storage unavailable")
        upsert_watchlist(
            symbol=symbol,
            asset_class=request.asset_class,
            display_name=symbol,
            source="manual",
        )
        return await get_watchlist()

    @r.delete("/watchlist/{symbol}", response_model=list[WatchlistItem])
    async def remove_watchlist_item(symbol: str) -> list[WatchlistItem]:
        """从持久数据库移除关注标的。"""
        from server.app import get_app_state

        state = get_app_state()
        db = getattr(state, "db", None)
        delete_watchlist = getattr(db, "delete_watchlist_asset_sync", None)
        if not callable(delete_watchlist):
            raise HTTPException(status_code=503, detail="watchlist storage unavailable")
        if not delete_watchlist(symbol):
            raise HTTPException(status_code=404, detail="symbol not found")

        return await get_watchlist()

    @r.get("/quote/{symbol}", response_model=MarketQuote)
    async def get_quote(
        symbol: str,
        background_tasks: BackgroundTasks,
    ) -> MarketQuote:
        """只读取持久化报价事实；行情刷新必须走显式命令接口。"""
        del background_tasks
        from server.app import get_app_state

        state = get_app_state()
        asset_class = _ASSET_CLASS_MAP.get(
            next(
                (
                    asset["asset_class"]
                    for asset in _merged_watchlist_assets(state)
                    if asset["symbol"] == symbol
                ),
                AssetClass.STOCK.value,
            ),
            AssetClass.STOCK,
        )

        if state.db is not None:
            cached = await state.db.get_latest_quote(symbol)
            if cached:
                return MarketQuote(**cached)

        return MarketQuote(symbol=symbol, price=0, asset_class=asset_class.value)

    @r.get("/kline/{symbol}", response_model=list[KlineBar])
    async def get_kline(
        symbol: str,
        start: str = "2025-01-02",
        end: str = _DEFAULT_END_DATE,
        interval: str = "1d",
    ) -> list[KlineBar]:
        """只读取已持久化历史 K 线；远端同步必须走 bars/backfill。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        ac = AssetClass.STOCK
        for asset_cfg in _merged_watchlist_assets(state):
            if asset_cfg["symbol"] == symbol:
                ac = _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
                break

        def _load_bars() -> list[KlineBar]:
            from data.manager import DataManager, build_sources
            from data.store import DataStore

            store = None
            try:
                store = DataStore()
            except Exception:
                pass

            dm = DataManager(
                sources=build_sources(
                    data_source=config.data_source,
                    tushare_token=config.tushare_token,
                ),
                store=store,
                default_source=config.data_source,
            )
            frequency = {
                "1m": BarFrequency.MIN_1,
                "5m": BarFrequency.MIN_5,
                "1d": BarFrequency.DAILY,
            }.get(interval, BarFrequency.DAILY)
            handler = dm.get_bars(
                Symbol(symbol),
                datetime.strptime(start, "%Y-%m-%d"),
                datetime.strptime(end, "%Y-%m-%d"),
                frequency,
                ac,
                allow_remote_refresh=False,
                refresh_ttl_seconds=max(int(config.live_poll_interval or 60), 15),
                degrade_to_cache=True,
            )
            bars: list[KlineBar] = []
            for event in handler:
                bars.append(
                    KlineBar(
                        timestamp=event.timestamp.isoformat(),
                        open=float(event.open),
                        high=float(event.high),
                        low=float(event.low),
                        close=float(event.close),
                        volume=float(event.volume),
                    )
                )
            return bars

        try:
            return await asyncio.wait_for(
                _run_blocking_fetch(_load_bars),
                timeout=_KLINE_FETCH_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out fetching kline for %s", symbol)
            return []
        except Exception:
            logger.warning("Failed to fetch kline for %s", symbol, exc_info=True)
            return []

    @r.get("/data-health")
    async def get_data_health() -> MarketDataHealthResponse:
        """获取数据缓存与快照健康度概览。"""
        from server.app import get_app_state

        state = get_app_state()
        market_health_assets = _with_default_market_indices(
            _merged_watchlist_assets(state)
        )
        watchlist = [
            (asset_cfg["symbol"], asset_cfg["asset_class"])
            for asset_cfg in market_health_assets
        ]

        latest_quotes: dict[str, dict] = {}
        persistent_quotes: dict[str, dict] = {}
        persistent_reader_available = state.db is not None and (
            hasattr(state.db, "list_latest_quotes_sync")
            or hasattr(state.db, "get_latest_quotes_sync")
        )
        scheduler = state.scheduler
        if (
            not persistent_reader_available
            and scheduler
            and getattr(scheduler, "latest_quotes", None)
        ):
            latest_quotes.update(
                {
                    str(symbol): quote
                    for symbol, quote in scheduler.latest_quotes.items()
                }
            )
        if state.db is not None:
            if hasattr(state.db, "list_latest_quotes_sync"):
                for row in state.db.list_latest_quotes_sync():
                    quote = _adapt_latest_quote_for_health(row)
                    if _is_real_persistent_quote(quote):
                        persistent_quotes[quote["symbol"]] = quote
                    latest_quotes[quote["symbol"]] = quote
            if hasattr(state.db, "get_latest_quotes_sync"):
                for row in state.db.get_latest_quotes_sync():
                    quote = _adapt_latest_quote_for_health(row)
                    if _is_real_persistent_quote(quote):
                        persistent_quotes.setdefault(quote["symbol"], quote)
                    latest_quotes.setdefault(quote["symbol"], quote)

        payload = build_data_health(
            watchlist=watchlist,
            latest_quotes=latest_quotes,
            bar_coverage={},
        )
        market_open = is_cn_trading_session()
        refresh_policy = "live" if market_open else "cache_only"
        now = _shanghai_now()
        health_quotes: list[MarketHealthQuote] = []
        for item in payload["quotes"]:
            symbol = item["symbol"]
            asset_class = item["asset_class"]
            quote = latest_quotes.get(symbol)
            metadata = _quote_metadata(
                state,
                symbol,
                asset_class,
                quote,
                market_open=market_open,
                refresh_policy=refresh_policy,
                now=now,
            )
            health_quotes.append(
                MarketHealthQuote(
                    symbol=symbol,
                    asset_class=asset_class,
                    timestamp=item["timestamp"],
                    price=item["price"],
                    **metadata,
                )
            )

        quote_timestamps = [
            _parse_quote_timestamp(item.timestamp) for item in health_quotes
        ]
        quote_timestamps = [item for item in quote_timestamps if item is not None]
        latest_quote_timestamp = (
            max(quote_timestamps).isoformat() if quote_timestamps else None
        )
        persistent_timestamps = [
            _parse_quote_timestamp(item.get("timestamp"))
            for item in persistent_quotes.values()
        ]
        persistent_timestamps = [
            item for item in persistent_timestamps if item is not None
        ]
        latest_persistent_quote_timestamp = (
            max(persistent_timestamps).isoformat() if persistent_timestamps else None
        )
        cache_age_seconds = None
        if quote_timestamps:
            cache_age_seconds = max(
                int((now - max(quote_timestamps)).total_seconds()), 0
            )
        account_health_quotes = [
            item for item in health_quotes if item.asset_class != AssetClass.INDEX.value
        ]
        status_health_quotes = account_health_quotes or health_quotes
        stale_symbols = [
            item.symbol for item in status_health_quotes if item.quote_status != "live"
        ]
        latest_attempts = [
            _parse_quote_timestamp(item.last_refresh_attempt)
            for item in health_quotes
            if item.last_refresh_attempt
        ]
        latest_attempts = [item for item in latest_attempts if item is not None]
        latest_refresh_attempt = (
            max(latest_attempts).isoformat() if latest_attempts else None
        )
        latest_refresh_error = next(
            (
                item.last_refresh_error
                for item in health_quotes
                if item.last_refresh_error
            ),
            None,
        )
        provider_name = _configured_provider_name(state)
        provider_requires_token = _provider_requires_token(provider_name)
        provider_configured = _provider_configured(state, provider_name)
        provider_supports_funds = _provider_supports_funds(provider_name)
        source_health = _aggregate_market_data_health_status(status_health_quotes)
        provider_status = (
            "error"
            if latest_refresh_error
            and not any(item.quote_status == "live" for item in status_health_quotes)
            else source_health
        )
        has_funds = any(asset_class in {"fund", "etf"} for _, asset_class in watchlist)
        effective_provider_supports_funds = (
            True
            if has_funds and _has_live_fund_quotes(health_quotes)
            else provider_supports_funds
        )
        has_persistent_cache = bool(persistent_quotes)
        real_data_available = has_persistent_cache
        persistent_cache_status = "available" if has_persistent_cache else "missing"
        next_action = _provider_next_action(
            provider_configured=provider_configured,
            provider_supports_funds=effective_provider_supports_funds,
            has_funds=has_funds,
            latest_refresh_error=latest_refresh_error,
            source_health=source_health,
        )
        if latest_refresh_error and has_persistent_cache:
            next_action = "use_cached_data"
        elif latest_refresh_error and not has_persistent_cache:
            next_action = "run_first_sync"
        return MarketDataHealthResponse(
            quotes=health_quotes,
            market_open=market_open,
            refresh_policy=refresh_policy,
            provider_status=provider_status,
            provider_name=provider_name,
            provider_configured=provider_configured,
            provider_requires_token=provider_requires_token,
            provider_supports_funds=effective_provider_supports_funds,
            provider_last_error=latest_refresh_error,
            provider_timeout_seconds=_MANUAL_REFRESH_TIMEOUT_SECONDS,
            next_action=next_action,
            metadata_configured_count=metadata_configured_count(state),
            source_health=source_health,
            cache_age_seconds=cache_age_seconds,
            latest_quote_timestamp=latest_quote_timestamp,
            last_refresh_attempt=latest_refresh_attempt,
            last_refresh_error=latest_refresh_error,
            stale_symbols_count=len(stale_symbols),
            stale_symbols_sample=stale_symbols[:5],
            real_data_available=real_data_available,
            has_persistent_cache=has_persistent_cache,
            latest_persistent_quote_timestamp=latest_persistent_quote_timestamp,
            persistent_cache_status=persistent_cache_status,
        )

    @r.get("/quote-fetch-runs", response_model=list[QuoteFetchRunResponse])
    async def get_quote_fetch_runs(
        limit: int = 20,
        trigger: str | None = None,
        status: str | None = None,
        provider: str | None = None,
    ) -> list[QuoteFetchRunResponse]:
        """List recent quote fetch audit runs for backend diagnostics."""
        from server.app import get_app_state

        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be at least 1")
        if limit > 100:
            raise HTTPException(status_code=422, detail="limit must be at most 100")

        state = get_app_state()
        db = getattr(state, "db", None)
        if db is None or not hasattr(db, "list_quote_fetch_runs"):
            return []
        rows = db.list_quote_fetch_runs(
            limit=limit,
            trigger=trigger,
            status=status,
            provider=provider,
        )
        return [_quote_fetch_run_response(row) for row in rows]

    @r.post(
        "/instrument-metadata/backfill",
        response_model=InstrumentMetadataBackfillResponse,
    )
    async def backfill_instrument_metadata(
        request: InstrumentMetadataBackfillRequest,
    ) -> InstrumentMetadataBackfillResponse:
        """Backfill local instrument names from AKShare into the database."""
        from server.app import get_app_state

        state = get_app_state()
        return await _backfill_instrument_metadata(state, request)

    @r.post("/bars/backfill", response_model=MarketBarsBackfillResponse)
    async def backfill_market_bars(
        request: MarketBarsBackfillRequest,
    ) -> MarketBarsBackfillResponse:
        """Backfill historical OHLCV bars into the authoritative local store."""
        from server.app import get_app_state

        state = get_app_state()
        return await _backfill_market_bars(state, request)

    @r.post("/quotes/refresh", response_model=QuoteRefreshResponse)
    async def refresh_quotes(request: QuoteRefreshRequest) -> QuoteRefreshResponse:
        """手动刷新行情快照，逐标的返回刷新结果。"""
        from server.app import get_app_state

        state = get_app_state()
        started_at_dt = datetime.now()
        started_at = started_at_dt.isoformat()
        market_open = is_cn_trading_session()
        refresh_policy = "live" if market_open else "cache_only"

        requested_symbols = _normalize_refresh_symbols(request.symbols)
        if not requested_symbols:
            requested_symbols = _default_refresh_symbols(state)
        run_id = f"manual_refresh:{started_at_dt.isoformat()}:{uuid.uuid4().hex}"

        if not requested_symbols:
            completed_at_dt = datetime.now()
            completed_at = completed_at_dt.isoformat()
            _create_manual_quote_fetch_run(
                state,
                run_id=run_id,
                started_at=started_at,
                requested_symbols=[],
                asset_type=None,
            )
            _finish_manual_quote_fetch_run(
                state,
                run_id=run_id,
                finished_at=completed_at,
                requested_symbols=[],
                refreshed=[],
                failed=[],
                skipped=[],
                quote_status="error",
                refresh_policy=refresh_policy,
                market_open=market_open,
                last_refresh_error="no_refresh_symbols",
                valuation_snapshot_id=None,
            )
            return QuoteRefreshResponse(
                requested_symbols=[],
                refresh_policy=refresh_policy,
                market_open=market_open,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=int(
                    (completed_at_dt - started_at_dt).total_seconds() * 1000
                ),
                quote_status="error",
                last_refresh_attempt=started_at,
                last_refresh_error="no_refresh_symbols",
                message="没有可刷新的行情标的",
            )

        watchlist_assets = _with_default_market_indices(_merged_watchlist_assets(state))
        asset_class_by_symbol = {
            asset_cfg["symbol"]: _ASSET_CLASS_MAP.get(
                asset_cfg["asset_class"], AssetClass.STOCK
            )
            for asset_cfg in watchlist_assets
        }
        _create_manual_quote_fetch_run(
            state,
            run_id=run_id,
            started_at=started_at,
            requested_symbols=requested_symbols,
            asset_type=_quote_fetch_run_asset_type(
                requested_symbols,
                asset_class_by_symbol,
            ),
        )

        results = await asyncio.gather(
            *[
                _refresh_one_quote(
                    state,
                    symbol,
                    asset_class_by_symbol.get(symbol, AssetClass.STOCK),
                    fetch_run_id=run_id,
                )
                for symbol in requested_symbols
            ]
        )

        refreshed = [result for result in results if result.status == "refreshed"]
        failed = [result for result in results if result.status == "failed"]
        skipped = [
            result for result in results if result.status not in {"refreshed", "failed"}
        ]

        if refreshed and not failed and not skipped:
            quote_status = "live"
            message = "行情刷新完成"
        elif refreshed:
            quote_status = "partial"
            message = "部分行情刷新完成"
        elif failed and not skipped:
            quote_status = "error"
            message = "行情刷新失败"
        else:
            quote_status = "stale"
            message = "行情源返回缓存行情"

        completed_at_dt = datetime.now()
        last_refresh_error = next(
            (
                result.last_refresh_error or result.error
                for result in results
                if result.error
            ),
            None,
        )
        has_persistent_cache = any(result.using_persistent_cache for result in results)
        completed_at = completed_at_dt.isoformat()
        try:
            valuation_snapshot = build_current_valuation_snapshot(
                getattr(state, "db", None),
                persist=True,
            )
        except Exception as exc:
            logger.exception("Failed to create valuation snapshot after manual refresh")
            db = getattr(state, "db", None)
            if db is not None and hasattr(db, "finish_quote_fetch_run"):
                db.finish_quote_fetch_run(
                    run_id=run_id,
                    finished_at=completed_at,
                    status="failed",
                    success_count=len(refreshed),
                    failure_count=max(len(failed), 1),
                    cache_hit_count=sum(
                        1 for result in results if result.using_persistent_cache
                    ),
                    error_message="valuation_snapshot_persistence_failed",
                    metadata={
                        "requested_symbols": requested_symbols,
                        "error": str(exc),
                        "facts_persisted_but_not_published": True,
                    },
                )
            raise HTTPException(
                status_code=503,
                detail="行情已落库但估值快照生成失败，本批次未发布",
            ) from exc
        _finish_manual_quote_fetch_run(
            state,
            run_id=run_id,
            finished_at=completed_at,
            requested_symbols=requested_symbols,
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            quote_status=quote_status,
            refresh_policy=refresh_policy,
            market_open=market_open,
            last_refresh_error=last_refresh_error,
            valuation_snapshot_id=str(valuation_snapshot["snapshot_id"]),
        )
        return QuoteRefreshResponse(
            requested_symbols=requested_symbols,
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            refresh_policy=refresh_policy,
            market_open=market_open,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=int((completed_at_dt - started_at_dt).total_seconds() * 1000),
            quote_status=quote_status,
            last_refresh_attempt=started_at,
            last_refresh_error=last_refresh_error,
            message=message,
            real_data_available=bool(refreshed) or has_persistent_cache,
            has_persistent_cache=has_persistent_cache,
        )

    @r.get("/research-board", response_model=ResearchBoardResponse)
    async def get_research_board() -> ResearchBoardResponse:
        """聚合 watchlist、最新报价与数据健康，供研究工作台消费。"""
        from server.app import get_app_state

        state = get_app_state()
        watchlist = await get_watchlist()
        health = await get_data_health()
        note_stats = (
            _build_research_note_stats(
                state.db.get_research_notes_sync(limit=500, offset=0)
            )
            if state.db is not None and hasattr(state.db, "get_research_notes_sync")
            else {}
        )

        latest_quotes = {item.symbol: item for item in health.quotes}

        items = [
            ResearchBoardItem(
                symbol=item.symbol,
                asset_class=item.asset_class,
                name=item.name,
                is_holding=item.is_holding,
                quantity=item.quantity,
                avg_cost=item.avg_cost,
                market_value=item.market_value,
                unrealized_pnl=item.unrealized_pnl,
                realized_pnl=item.realized_pnl,
                last_snapshot_at=item.last_snapshot_at,
                price=(
                    latest_quotes.get(item.symbol).price
                    if latest_quotes.get(item.symbol)
                    else None
                ),
                volume=None,
                research_count=int(note_stats.get(item.symbol, {}).get("count", 0)),
                last_research_at=str(note_stats.get(item.symbol, {}).get("latest", ""))
                or None,
            )
            for item in watchlist
        ]

        return ResearchBoardResponse(items=items, health=health)

    @r.get("/research-notes", response_model=ResearchNoteListResponse)
    async def get_research_notes(
        symbol: str | None = None,
        entry_kind: str | None = None,
        priority: str | None = None,
        event_date_from: str | None = None,
        event_date_to: str | None = None,
        limit: int = 100,
    ) -> ResearchNoteListResponse:
        """列出研究记录，支持按 symbol 过滤。"""
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "get_research_notes"):
            return ResearchNoteListResponse(items=[])

        rows = await state.db.get_research_notes(
            symbol=symbol,
            entry_kind=entry_kind,
            priority=priority,
            event_date_from=event_date_from,
            event_date_to=event_date_to,
            limit=limit,
            offset=0,
        )
        return ResearchNoteListResponse(
            items=[ResearchNoteResponse(**row) for row in rows]
        )

    @r.post("/research-notes", response_model=ResearchNoteResponse)
    async def create_research_note(body: ResearchNoteCreate) -> ResearchNoteResponse:
        """新增研究记录，支持 note / thesis / catalyst。"""
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "add_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        symbol = body.symbol.strip()
        title = body.title.strip()
        content = body.content.strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        if not content:
            raise HTTPException(status_code=400, detail="content is required")

        note_id = await state.db.add_research_note(
            symbol=symbol,
            asset_class=body.asset_class,
            entry_kind=body.entry_kind,
            title=title,
            content=content,
            priority=body.priority,
            event_date=body.event_date,
        )
        rows = await state.db.get_research_notes(limit=1, offset=0)
        note = next((row for row in rows if row["id"] == note_id), None)
        if note is None:
            raise HTTPException(status_code=500, detail="failed to fetch created note")
        return ResearchNoteResponse(**note)

    @r.put("/research-notes/{note_id}", response_model=ResearchNoteResponse)
    async def update_research_note(
        note_id: int, body: ResearchNoteUpdate
    ) -> ResearchNoteResponse:
        """更新研究记录内容与分类。"""
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "update_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        title = body.title.strip()
        content = body.content.strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        if not content:
            raise HTTPException(status_code=400, detail="content is required")

        updated = await state.db.update_research_note(
            note_id=note_id,
            entry_kind=body.entry_kind,
            title=title,
            content=content,
            priority=body.priority,
            event_date=body.event_date,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="note not found")

        rows = await state.db.get_research_notes(limit=200, offset=0)
        note = next((row for row in rows if row["id"] == note_id), None)
        if note is None:
            raise HTTPException(status_code=500, detail="failed to fetch updated note")
        return ResearchNoteResponse(**note)

    @r.delete("/research-notes/{note_id}")
    async def delete_research_note(note_id: int) -> dict[str, str]:
        """删除研究记录。"""
        from server.app import get_app_state

        state = get_app_state()
        if state.db is None or not hasattr(state.db, "delete_research_note"):
            raise HTTPException(status_code=503, detail="research storage unavailable")

        deleted = await state.db.delete_research_note(note_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="note not found")
        return {"status": "ok"}

    return r
