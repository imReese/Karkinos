"""Market routes — /api/market/*"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.types import AssetClass, BarFrequency, Symbol
from server.models import KlineBar, MarketQuote, WatchlistCreateRequest, WatchlistItem
from server.bootstrap import resolve_config_path
from server.services.market_hours import is_cn_trading_session
from server.services.data_health import build_data_health
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

logger = logging.getLogger(__name__)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
_QUOTE_REFRESH_ATTEMPTS: dict[tuple[str, str], datetime] = {}

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


def _resolve_asset_class(symbol: str, assets: list[dict[str, str]]) -> AssetClass:
    for asset_cfg in assets:
        if asset_cfg["symbol"] == symbol:
            return _ASSET_CLASS_MAP.get(asset_cfg["asset_class"], AssetClass.STOCK)
    return AssetClass.STOCK


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
        symbol = asset_cfg["symbol"]
        if symbol in seen:
            continue
        merged.append(
            {
                "symbol": symbol,
                "asset_class": asset_cfg["asset_class"],
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
        merged.append({"symbol": symbol, "asset_class": asset_class})
        seen.add(symbol)

    return merged


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


def _fetch_latest_snapshot(state, symbol: str, asset_class: AssetClass) -> dict | None:
    from data.manager import build_sources

    sources = build_sources(
        data_source=state.config.data_source,
        tushare_token=state.config.tushare_token,
    )
    source = sources.get(state.config.data_source, sources["akshare"])
    snapshot = source.fetch_latest(Symbol(symbol), asset_class)
    if not snapshot:
        return None
    payload = {
        "symbol": symbol,
        "asset_class": asset_class.value,
        "price": snapshot["price"],
        "volume": snapshot.get("volume"),
        "timestamp": snapshot.get("timestamp"),
    }
    if state.db is not None and payload["timestamp"]:
        state.db.save_quote_snapshot_sync(
            symbol=symbol,
            asset_class=payload["asset_class"],
            price=float(payload["price"]),
            volume=None if payload["volume"] is None else float(payload["volume"]),
            timestamp=str(payload["timestamp"]),
        )
    return payload


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
                    name=sym,
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

        config.assets.append({"symbol": symbol, "asset_class": request.asset_class})
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
    async def get_data_health() -> dict:
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
        payload["market_open"] = is_cn_trading_session()
        payload["refresh_policy"] = (
            "live"
            if payload["market_open"]
            else "cache_only"
        )
        return payload

    return r
