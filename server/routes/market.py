"""Market routes — /api/market/*"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from core.types import AssetClass, BarFrequency, Symbol
from server.models import (
    KlineBar,
    MarketDataHealthResponse,
    MarketHealthQuote,
    MarketQuote,
    ResearchNoteCreate,
    ResearchNoteListResponse,
    ResearchNoteResponse,
    ResearchNoteUpdate,
    ResearchBoardItem,
    ResearchBoardResponse,
    WatchlistCreateRequest,
    WatchlistItem,
)
from server.bootstrap import resolve_config_path
from server.services.asset_metadata import resolve_asset_metadata
from server.services.market_hours import is_cn_trading_session
from server.services.data_health import build_data_health
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

logger = logging.getLogger(__name__)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_QUOTE_REFRESH_ATTEMPTS: dict[tuple[str, str], datetime] = {}
_QUOTE_REFRESH_ERRORS: dict[tuple[str, str], str | None] = {}
_MANUAL_REFRESH_TIMEOUT_SECONDS = 8.0
_SH_TZ = ZoneInfo("Asia/Shanghai")

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


class QuoteRefreshRequest(BaseModel):
    symbols: list[str] | None = None
    force: bool = False


class QuoteRefreshSymbolResult(BaseModel):
    symbol: str
    status: str
    quote_timestamp: str | None = None
    quote_source: str | None = None
    quote_age_seconds: int | None = None
    error: str | None = None
    reason: str | None = None
    last_refresh_attempt: str | None = None
    last_refresh_error: str | None = None


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
    timestamp = _parse_quote_timestamp(None if quote is None else quote.get("timestamp"))
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
    source = quote.get("source") or quote.get("provider")
    if source:
        return str(source)
    configured = getattr(state.config, "data_source", None)
    return str(configured) if configured else None


def _stale_reason(
    state,
    quote: dict | None,
    *,
    market_open: bool,
    refresh_policy: str,
    now: datetime | None = None,
) -> str | None:
    if not quote or quote.get("price") in {None, ""}:
        return "quote_missing"

    timestamp = _parse_quote_timestamp(quote.get("timestamp"))
    if timestamp is None:
        return "quote_timestamp_missing"

    if _resolve_quote_status(state, quote) != "stale":
        return None

    if refresh_policy == "cache_only":
        return "market_closed_cache_only" if not market_open else "refresh_policy_cache_only"

    age = _quote_age_seconds(quote, now=now)
    ttl_seconds = max(int(getattr(state.config, "live_poll_interval", 60) or 60), 15) * 3
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
    return {
        "quote_status": _resolve_quote_status(state, quote),
        "quote_source": _quote_source(state, quote),
        "quote_age_seconds": _quote_age_seconds(quote, now=now),
        "stale_reason": _stale_reason(
            state,
            quote,
            market_open=market_open,
            refresh_policy=refresh_policy,
            now=now,
        ),
        "last_refresh_attempt": _latest_refresh_attempt(symbol, asset_class),
        "last_refresh_error": _latest_refresh_error(symbol, asset_class),
    }


def _find_asset_config(assets: list[dict[str, str]], symbol: str) -> dict[str, str] | None:
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
    if source_health in {"stale", "partial"}:
        return "refresh_quotes_or_check_source"
    return None


def _normalize_asset_class(asset_class: AssetClass | str | None) -> str:
    if isinstance(asset_class, AssetClass):
        return asset_class.value
    if isinstance(asset_class, str):
        return asset_class
    return AssetClass.STOCK.value


def _extract_runtime_portfolio(state):
    scheduler = state.scheduler
    portfolio = getattr(scheduler, "portfolio", None) if scheduler else None
    instruments = getattr(scheduler, "instruments", {}) if scheduler else {}
    latest_quotes: dict[str, dict] = {}
    if scheduler and getattr(scheduler, "latest_quotes", None):
        latest_quotes.update(scheduler.latest_quotes)
    if state.db is not None and hasattr(state.db, "get_latest_quotes_sync"):
        for row in state.db.get_latest_quotes_sync():
            latest_quotes.setdefault(row["symbol"], row)

    if (
        portfolio is None
        and state.db is not None
        and hasattr(state.db, "get_trades_sync")
        and hasattr(state.db, "get_cash_flows_sync")
    ):
        rebuilt = rebuild_portfolio_from_ledger(
            state.config,
            state.db,
            latest_quotes=latest_quotes,
        )
        portfolio = rebuilt.portfolio
        instruments = rebuilt.instruments

    positions = getattr(portfolio, "positions", {}) if portfolio else {}
    return portfolio, positions, instruments, latest_quotes


def _position_for_symbol(positions, symbol: str):
    return positions.get(Symbol(symbol)) or positions.get(symbol)


def _merged_watchlist_assets(state) -> list[dict[str, str]]:
    _, positions, instruments, latest_quotes = _extract_runtime_portfolio(state)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    for asset_cfg in state.config.assets:
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
    if holding_symbols:
        return holding_symbols
    return _normalize_refresh_symbols(
        [asset_cfg["symbol"] for asset_cfg in _merged_watchlist_assets(state)]
    )


def _latest_cached_quote(state, symbol: str) -> dict | None:
    scheduler = state.scheduler
    if scheduler and getattr(scheduler, "latest_quotes", None):
        quote = scheduler.latest_quotes.get(symbol)
        if quote:
            return quote

    if state.db is not None and hasattr(state.db, "get_latest_quotes_sync"):
        for row in state.db.get_latest_quotes_sync():
            if row.get("symbol") == symbol:
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


def _resolve_quote_status(state, quote: dict | None) -> str:
    try:
        from server.routes.portfolio import _quote_status

        return _quote_status(state, quote)
    except Exception:
        logger.warning("Failed to resolve quote status", exc_info=True)
        return "live" if quote and quote.get("timestamp") else "stale"


def _persist_config(config) -> None:
    data = {
        "host": config.host,
        "port": config.port,
        "live_auto_start": config.live_auto_start,
        "initial_cash": str(config.initial_cash),
        "start_date": config.start_date,
        "end_date": config.end_date,
        "assets": config.assets,
        "strategy": config.strategy,
        "short_period": config.short_period,
        "long_period": config.long_period,
        "data_source": config.data_source,
        "tushare_token": config.tushare_token,
        "notification": config.notification,
        "live_poll_interval": config.live_poll_interval,
    }
    resolve_config_path().write_text(json.dumps(data, indent=2, ensure_ascii=False))


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


def _fetch_latest_snapshot(state, symbol: str, asset_class: AssetClass) -> dict | None:
    from data.manager import build_sources

    data_source = getattr(state.config, "data_source", "akshare")
    tushare_token = getattr(state.config, "tushare_token", "")
    sources = build_sources(
        data_source=data_source,
        tushare_token=tushare_token,
    )
    preferred = sources.get(data_source, sources["akshare"])
    source_chain = [preferred]
    if asset_class == AssetClass.FUND and data_source != "akshare":
        akshare = sources.get("akshare")
        if akshare is not None and akshare is not preferred:
            source_chain.append(akshare)

    snapshot = None
    selected_source_name = data_source
    for source in source_chain:
        snapshot = source.fetch_latest(Symbol(symbol), asset_class)
        if snapshot:
            if source is not preferred:
                selected_source_name = "akshare"
            break
    if not snapshot:
        return None
    payload = {
        "symbol": symbol,
        "asset_class": asset_class.value,
        "price": snapshot["price"],
        "volume": snapshot.get("volume"),
        "timestamp": snapshot.get("timestamp"),
        "source": selected_source_name,
    }
    display_name = snapshot.get("display_name") or snapshot.get("name")
    if display_name:
        payload["display_name"] = str(display_name)
        payload["name"] = str(display_name)
    if state.db is not None and payload["timestamp"]:
        state.db.save_quote_snapshot_sync(
            symbol=symbol,
            asset_class=payload["asset_class"],
            price=float(payload["price"]),
            volume=None if payload["volume"] is None else float(payload["volume"]),
            timestamp=str(payload["timestamp"]),
        )
        previous_close = snapshot.get("previous_close")
        previous_close_date = snapshot.get("previous_close_date")
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
        payload["previous_close"] = previous_close
        payload["previous_close_date"] = previous_close_date
    return payload


async def _refresh_one_quote(
    state,
    symbol: str,
    asset_class: AssetClass,
    timeout_seconds: float | None = None,
) -> QuoteRefreshSymbolResult:
    timeout = (
        _MANUAL_REFRESH_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    key = (symbol, asset_class.value)
    attempted_at = datetime.now()
    _QUOTE_REFRESH_ATTEMPTS[key] = attempted_at
    _QUOTE_REFRESH_ERRORS[key] = None
    market_open = is_cn_trading_session()
    refresh_policy = "live" if market_open else "cache_only"
    try:
        snapshot = await asyncio.wait_for(
            asyncio.to_thread(_fetch_latest_snapshot, state, symbol, asset_class),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        cached_quote = _latest_cached_quote(state, symbol)
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
            status="failed",
            quote_timestamp=None if cached_quote is None else cached_quote.get("timestamp"),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error="provider_timeout",
            reason="行情源刷新超时，已保留缓存行情",
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error="provider_timeout",
        )
    except Exception as exc:
        cached_quote = _latest_cached_quote(state, symbol)
        logger.warning("Manual quote refresh failed for %s", symbol, exc_info=True)
        error_message = str(exc)
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
            status="failed",
            quote_timestamp=None if cached_quote is None else cached_quote.get("timestamp"),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason="行情源刷新失败，已保留缓存行情",
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
        )

    if not snapshot:
        cached_quote = _latest_cached_quote(state, symbol)
        error_message = None if cached_quote else "quote_unavailable"
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
            status="stale" if cached_quote else "failed",
            quote_timestamp=None if cached_quote is None else cached_quote.get("timestamp"),
            quote_source=metadata["quote_source"],
            quote_age_seconds=metadata["quote_age_seconds"],
            error=error_message,
            reason="行情源没有返回新报价，当前仍基于缓存行情",
            last_refresh_attempt=attempted_at.isoformat(),
            last_refresh_error=error_message,
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
        status="refreshed" if quote_status == "live" else "stale",
        quote_timestamp=snapshot.get("timestamp"),
        quote_source=metadata["quote_source"],
        quote_age_seconds=metadata["quote_age_seconds"],
        reason=None if quote_status == "live" else "行情源返回的报价仍为缓存行情",
        last_refresh_attempt=attempted_at.isoformat(),
        last_refresh_error=None,
    )


async def _refresh_quote_snapshot(state, symbol: str, asset_class: AssetClass) -> None:
    try:
        await asyncio.to_thread(_fetch_latest_snapshot, state, symbol, asset_class)
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
                    market_value=None if position is None else float(position.market_value),
                    unrealized_pnl=None
                    if position is None
                    else float(position.unrealized_pnl),
                    realized_pnl=None if position is None else float(position.realized_pnl),
                    last_snapshot_at=None if quote is None else quote.get("timestamp"),
                )
            )

        return items

    @r.post("/watchlist", response_model=list[WatchlistItem])
    async def add_watchlist_item(request: WatchlistCreateRequest) -> list[WatchlistItem]:
        """新增关注标的并写入配置。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        symbol = request.symbol.strip()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        if any(asset["symbol"].lower() == symbol.lower() for asset in config.assets):
            raise HTTPException(status_code=409, detail="symbol already exists")

        config.assets.append(
            {
                "symbol": symbol,
                "asset_class": request.asset_class,
                "display_name": symbol,
            }
        )
        _persist_config(config)
        return await get_watchlist()

    @r.delete("/watchlist/{symbol}", response_model=list[WatchlistItem])
    async def remove_watchlist_item(symbol: str) -> list[WatchlistItem]:
        """移除关注标的并写入配置。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        original_len = len(config.assets)
        config.assets = [
            asset for asset in config.assets if asset["symbol"].lower() != symbol.lower()
        ]
        if len(config.assets) == original_len:
            raise HTTPException(status_code=404, detail="symbol not found")

        _persist_config(config)
        return await get_watchlist()

    @r.get("/quote/{symbol}", response_model=MarketQuote)
    async def get_quote(symbol: str, background_tasks: BackgroundTasks) -> MarketQuote:
        """本地优先获取报价，并异步刷新快照。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler
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

        if scheduler and scheduler.is_running:
            q = scheduler.latest_quotes.get(symbol)
            if q:
                _maybe_schedule_quote_refresh(
                    state, background_tasks, symbol, asset_class
                )
                return MarketQuote(symbol=symbol, **q)

        if state.db is not None:
            cached = await state.db.get_latest_quote(symbol)
            if cached:
                _maybe_schedule_quote_refresh(
                    state, background_tasks, symbol, asset_class
                )
                return MarketQuote(**cached)

        if not is_cn_trading_session():
            return MarketQuote(symbol=symbol, price=0, asset_class=asset_class.value)

        try:
            snapshot = await asyncio.to_thread(
                _fetch_latest_snapshot, state, symbol, asset_class
            )
            if snapshot:
                return MarketQuote(**snapshot)
        except Exception:
            logger.warning("Failed to fetch quote for %s", symbol, exc_info=True)

        return MarketQuote(symbol=symbol, price=0, asset_class=asset_class.value)

    @r.get("/kline/{symbol}", response_model=list[KlineBar])
    async def get_kline(
        symbol: str,
        start: str = "2025-01-02",
        end: str = _DEFAULT_END_DATE,
        interval: str = "1d",
    ) -> list[KlineBar]:
        """获取历史 K 线数据。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config

        ac = AssetClass.STOCK
        for asset_cfg in config.assets:
            if asset_cfg["symbol"] == symbol:
                ac = _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
                break

        try:
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
                allow_remote_refresh=is_cn_trading_session(),
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
        except Exception:
            logger.warning("Failed to fetch kline for %s", symbol, exc_info=True)
            return []

    @r.get("/data-health")
    async def get_data_health() -> MarketDataHealthResponse:
        """获取数据缓存与快照健康度概览。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler

        watchlist = [
            (asset_cfg["symbol"], asset_cfg["asset_class"])
            for asset_cfg in _merged_watchlist_assets(state)
        ]

        latest_quotes: dict[str, dict] = {}
        if scheduler and getattr(scheduler, "latest_quotes", None):
            latest_quotes.update(scheduler.latest_quotes)

        if state.db is not None:
            for row in state.db.get_latest_quotes_sync():
                latest_quotes.setdefault(row["symbol"], row)

        payload = build_data_health(
            watchlist=watchlist,
            latest_quotes=latest_quotes,
            bar_coverage={},
        )
        market_open = is_cn_trading_session()
        refresh_policy = (
            "live"
            if market_open
            else "cache_only"
        )
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
        cache_age_seconds = None
        if quote_timestamps:
            cache_age_seconds = max(
                int((now - max(quote_timestamps)).total_seconds()), 0
            )
        stale_symbols = [
            item.symbol
            for item in health_quotes
            if item.quote_status != "live"
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
            (item.last_refresh_error for item in health_quotes if item.last_refresh_error),
            None,
        )
        provider_name = _configured_provider_name(state)
        provider_requires_token = _provider_requires_token(provider_name)
        provider_configured = _provider_configured(state, provider_name)
        provider_supports_funds = _provider_supports_funds(provider_name)
        source_health = (
            "unknown"
            if not health_quotes
            else "live"
            if not stale_symbols
            else "stale"
            if len(stale_symbols) == len(health_quotes)
            else "partial"
        )
        provider_status = (
            "error"
            if latest_refresh_error and not any(item.quote_status == "live" for item in health_quotes)
            else source_health
        )
        has_funds = any(
            asset_class in {"fund", "etf"} for _, asset_class in watchlist
        )
        next_action = _provider_next_action(
            provider_configured=provider_configured,
            provider_supports_funds=provider_supports_funds,
            has_funds=has_funds,
            latest_refresh_error=latest_refresh_error,
            source_health=source_health,
        )
        return MarketDataHealthResponse(
            quotes=health_quotes,
            market_open=market_open,
            refresh_policy=refresh_policy,
            provider_status=provider_status,
            provider_name=provider_name,
            provider_configured=provider_configured,
            provider_requires_token=provider_requires_token,
            provider_supports_funds=provider_supports_funds,
            provider_last_error=latest_refresh_error,
            provider_timeout_seconds=_MANUAL_REFRESH_TIMEOUT_SECONDS,
            next_action=next_action,
            source_health=source_health,
            cache_age_seconds=cache_age_seconds,
            latest_quote_timestamp=latest_quote_timestamp,
            last_refresh_attempt=latest_refresh_attempt,
            last_refresh_error=latest_refresh_error,
            stale_symbols_count=len(stale_symbols),
            stale_symbols_sample=stale_symbols[:5],
        )

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

        if not requested_symbols:
            completed_at_dt = datetime.now()
            return QuoteRefreshResponse(
                requested_symbols=[],
                refresh_policy=refresh_policy,
                market_open=market_open,
                started_at=started_at,
                completed_at=completed_at_dt.isoformat(),
                duration_ms=int(
                    (completed_at_dt - started_at_dt).total_seconds() * 1000
                ),
                quote_status="error",
                last_refresh_attempt=started_at,
                last_refresh_error="no_refresh_symbols",
                message="没有可刷新的行情标的",
            )

        watchlist_assets = _merged_watchlist_assets(state)
        asset_class_by_symbol = {
            asset_cfg["symbol"]: _ASSET_CLASS_MAP.get(
                asset_cfg["asset_class"], AssetClass.STOCK
            )
            for asset_cfg in watchlist_assets
        }

        results = await asyncio.gather(
            *[
                _refresh_one_quote(
                    state,
                    symbol,
                    asset_class_by_symbol.get(symbol, AssetClass.STOCK),
                )
                for symbol in requested_symbols
            ]
        )

        refreshed = [result for result in results if result.status == "refreshed"]
        failed = [result for result in results if result.status == "failed"]
        skipped = [
            result
            for result in results
            if result.status not in {"refreshed", "failed"}
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
            (result.last_refresh_error or result.error for result in results if result.error),
            None,
        )
        return QuoteRefreshResponse(
            requested_symbols=requested_symbols,
            refreshed=refreshed,
            failed=failed,
            skipped=skipped,
            refresh_policy=refresh_policy,
            market_open=market_open,
            started_at=started_at,
            completed_at=completed_at_dt.isoformat(),
            duration_ms=int((completed_at_dt - started_at_dt).total_seconds() * 1000),
            quote_status=quote_status,
            last_refresh_attempt=started_at,
            last_refresh_error=last_refresh_error,
            message=message,
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

        latest_quotes = {
            item.symbol: item for item in health.quotes
        }

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
                price=latest_quotes.get(item.symbol).price
                if latest_quotes.get(item.symbol)
                else None,
                volume=None,
                research_count=int(note_stats.get(item.symbol, {}).get("count", 0)),
                last_research_at=str(note_stats.get(item.symbol, {}).get("latest", "")) or None,
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
