"""Market watchlist HTTP endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from server.contracts.http.market_models import (
    KlineBar,
    MarketQuote,
    WatchlistCreateRequest,
    WatchlistItem,
)
from server.http.market_endpoints.dependencies import WatchlistEndpointDependencies

WatchlistLoader = Callable[[], Awaitable[list[WatchlistItem]]]


def _resolve_instrument_type(
    assets: list[dict[str, object]],
    *,
    symbol: str,
    explicit: str | None,
) -> InstrumentType | None:
    if explicit is not None:
        try:
            return InstrumentType.from_persisted(explicit)
        except ValueError:
            return None
    identities: set[InstrumentType] = set()
    for asset in assets:
        if str(asset.get("symbol") or "").strip() != symbol:
            continue
        try:
            identities.add(
                InstrumentType.from_persisted(
                    asset.get("instrument_type") or asset.get("asset_class")
                )
            )
        except ValueError:
            return None
    return next(iter(identities)) if len(identities) == 1 else None


def create_router(
    dependencies: WatchlistEndpointDependencies,
) -> tuple[APIRouter, WatchlistLoader]:
    r = APIRouter(prefix="/api/market", tags=["market"])
    _ASSET_CLASS_MAP = dependencies.asset_class_map
    _DEFAULT_END_DATE = dependencies.default_end_date
    _extract_runtime_portfolio = dependencies.extract_runtime_portfolio
    _merged_watchlist_assets = dependencies.merged_watchlist_assets
    _position_for_symbol = dependencies.position_for_symbol
    _read_market_bars = dependencies.read_market_bars

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
                    instrument_type=asset_cfg.get("instrument_type"),
                    identity_provenance=asset_cfg.get("identity_provenance"),
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
        try:
            instrument_type = InstrumentType.from_persisted(
                request.instrument_type or request.asset_class
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="instrument_type is required and must be supported",
            ) from exc
        compatible_asset_classes = {
            InstrumentType.STOCK: {"stock"},
            InstrumentType.ETF: {"etf", "fund"},
            InstrumentType.OPEN_END_FUND: {"open_end_fund", "fund"},
            InstrumentType.GOLD: {"gold"},
            InstrumentType.BOND: {"bond"},
            InstrumentType.INDEX: {"index"},
        }
        normalized_asset_class = request.asset_class.strip().lower().replace("-", "_")
        if normalized_asset_class not in compatible_asset_classes[instrument_type]:
            raise HTTPException(
                status_code=400,
                detail="asset_class conflicts with instrument_type",
            )
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
            instrument_type=instrument_type.value,
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
        instrument_type: str | None = None,
    ) -> MarketQuote:
        """只读取持久化报价事实；行情刷新必须走显式命令接口。"""
        del background_tasks
        from server.dependencies import get_app_state

        state = get_app_state()
        assets = _merged_watchlist_assets(state)
        resolved_type = _resolve_instrument_type(
            assets,
            symbol=symbol,
            explicit=instrument_type,
        )
        if resolved_type is None:
            raise HTTPException(
                status_code=422,
                detail="instrument identity is missing or ambiguous",
            )
        asset_class = (
            AssetClass.FUND
            if resolved_type in {InstrumentType.ETF, InstrumentType.OPEN_END_FUND}
            else _ASSET_CLASS_MAP.get(resolved_type.value, AssetClass.STOCK)
        )

        if state.db is not None:
            cached = await state.db.get_latest_quote(
                symbol,
                instrument_type=resolved_type.value,
            )
            if cached:
                return MarketQuote(**cached)

        return MarketQuote(symbol=symbol, price=0, asset_class=asset_class.value)

    @r.get("/kline/{symbol}", response_model=list[KlineBar])
    async def get_kline(
        symbol: str,
        start: str = "2025-01-02",
        end: str = _DEFAULT_END_DATE,
        interval: str = "1d",
        instrument_type: str | None = None,
    ) -> list[KlineBar]:
        """只读取已持久化历史 K 线；远端同步必须走 bars/backfill。"""
        from server.bootstrap import resolve_data_dir
        from server.dependencies import get_app_state

        resolved_type = _resolve_instrument_type(
            _merged_watchlist_assets(get_app_state()),
            symbol=symbol,
            explicit=instrument_type,
        )
        if resolved_type is None:
            return []

        def _load_bars() -> list[KlineBar]:
            frequency = {
                "1m": BarFrequency.MIN_1,
                "5m": BarFrequency.MIN_5,
                "1d": BarFrequency.DAILY,
            }.get(interval, BarFrequency.DAILY)
            start_at = dependencies.datetime_provider().strptime(start, "%Y-%m-%d")
            end_exclusive = dependencies.datetime_provider().strptime(
                end, "%Y-%m-%d"
            ) + dependencies.timedelta_provider()(days=1)
            store_path = Path(resolve_data_dir()) / "meta.db"
            rows = _read_market_bars(
                store_path,
                symbol=str(Symbol(symbol)),
                instrument_type=resolved_type.value,
                frequency=frequency.value,
                start_at=start_at,
                end_exclusive=end_exclusive,
            )
            return [KlineBar(**row) for row in rows]

        try:
            return _load_bars()
        except Exception:
            dependencies.logger_provider().warning(
                "Failed to fetch kline for %s", symbol, exc_info=True
            )
            return []

    return r, get_watchlist
