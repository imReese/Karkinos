"""Market watchlist HTTP endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.types import AssetClass, BarFrequency, Symbol
from server.contracts.http.market_models import (
    KlineBar,
    MarketQuote,
    WatchlistCreateRequest,
    WatchlistItem,
)


def create_router(facade: Any, endpoints: dict[str, Any]) -> APIRouter:
    r = APIRouter(prefix="/api/market", tags=["market"])

    def dependency(name: str):
        value = getattr(facade, name)
        if callable(value) and not isinstance(value, type):
            return lambda *args, **kwargs: getattr(facade, name)(*args, **kwargs)
        return value

    _ASSET_CLASS_MAP = dependency("_ASSET_CLASS_MAP")
    _DEFAULT_END_DATE = dependency("_DEFAULT_END_DATE")
    _extract_runtime_portfolio = dependency("_extract_runtime_portfolio")
    _merged_watchlist_assets = dependency("_merged_watchlist_assets")
    _position_for_symbol = dependency("_position_for_symbol")
    datetime = dependency("datetime")
    logger = dependency("logger")
    _read_market_bars = dependency("_read_market_bars")
    timedelta = dependency("timedelta")

    @r.get("/watchlist", response_model=list[WatchlistItem])
    async def get_watchlist() -> list[WatchlistItem]:
        """获取配置的关注列表，并附带持仓与快照信息。"""
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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
        from server.dependencies import get_app_state

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
        from server.bootstrap import resolve_data_dir

        def _load_bars() -> list[KlineBar]:
            frequency = {
                "1m": BarFrequency.MIN_1,
                "5m": BarFrequency.MIN_5,
                "1d": BarFrequency.DAILY,
            }.get(interval, BarFrequency.DAILY)
            start_at = datetime.strptime(start, "%Y-%m-%d")
            end_exclusive = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            store_path = Path(resolve_data_dir()) / "meta.db"
            rows = _read_market_bars(
                store_path,
                symbol=str(Symbol(symbol)),
                frequency=frequency.value,
                start_at=start_at,
                end_exclusive=end_exclusive,
            )
            return [KlineBar(**row) for row in rows]

        try:
            return _load_bars()
        except Exception:
            logger.warning("Failed to fetch kline for %s", symbol, exc_info=True)
            return []

    endpoints["get_watchlist"] = get_watchlist
    return r
