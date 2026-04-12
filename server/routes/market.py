"""Market routes — /api/market/*"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter

from core.types import AssetClass, BarFrequency, Symbol
from server.models import KlineBar, MarketQuote, WatchlistItem

logger = logging.getLogger(__name__)

_DEFAULT_END_DATE = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

_ASSET_CLASS_MAP = {
    "stock": AssetClass.STOCK,
    "etf": AssetClass.FUND,
    "fund": AssetClass.FUND,
    "gold": AssetClass.GOLD,
    "bond": AssetClass.BOND,
}


def create_router() -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    @r.get("/watchlist", response_model=list[WatchlistItem])
    async def get_watchlist() -> list[WatchlistItem]:
        """获取配置的关注列表 + 最新报价。"""
        from server.app import get_app_state

        state = get_app_state()
        config = state.config
        scheduler = state.scheduler
        items: list[WatchlistItem] = []
        for asset_cfg in config.assets:
            sym = asset_cfg["symbol"]
            ac = asset_cfg["asset_class"]
            items.append(WatchlistItem(symbol=sym, asset_class=ac))

        if scheduler and scheduler.is_running:
            for item in items:
                quote = scheduler.latest_quotes.get(item.symbol)
                if quote:
                    item.name = f"{item.symbol}"

        return items

    @r.get("/quote/{symbol}", response_model=MarketQuote)
    async def get_quote(symbol: str) -> MarketQuote:
        """获取单标的报价。"""
        from server.app import get_app_state

        state = get_app_state()
        scheduler = state.scheduler

        if scheduler and scheduler.is_running:
            q = scheduler.latest_quotes.get(symbol)
            if q:
                return MarketQuote(symbol=symbol, **q)

        try:
            from data.manager import build_sources

            sources = build_sources(
                data_source=config.data_source,
                tushare_token=config.tushare_token,
            )
            source = sources.get(config.data_source, sources["akshare"])
            ac = AssetClass.STOCK
            config = state.config
            for asset_cfg in config.assets:
                if asset_cfg["symbol"] == symbol:
                    ac = _ASSET_CLASS_MAP.get(
                        asset_cfg["asset_class"], AssetClass.STOCK
                    )
                    break
            snapshot = source.fetch_latest(Symbol(symbol), ac)
            if snapshot:
                return MarketQuote(
                    symbol=symbol,
                    price=snapshot["price"],
                    volume=snapshot.get("volume"),
                    timestamp=snapshot.get("timestamp"),
                    asset_class=ac.value,
                )
        except Exception:
            logger.exception("Failed to fetch quote for %s", symbol)

        return MarketQuote(symbol=symbol, price=0)

    @r.get("/kline/{symbol}", response_model=list[KlineBar])
    async def get_kline(
        symbol: str,
        start: str = "2025-01-02",
        end: str = _DEFAULT_END_DATE,
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
            handler = dm.get_bars(
                Symbol(symbol),
                datetime.strptime(start, "%Y-%m-%d"),
                datetime.strptime(end, "%Y-%m-%d"),
                BarFrequency.DAILY,
                ac,
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
            logger.exception("Failed to fetch kline for %s", symbol)
            return []

    return r
