"""Unified market history and facts synchronization service.

Provides complete, multi-asset market data synchronization:
- Exchange Trading Calendar (SSE / SZSE via AkShare / official verification)
- Benchmark Indices (OHLCV daily bars + real-time quotes via TDX)
- ETFs (OHLCV daily bars + real-time quotes via TDX)
- Open-End Funds (NAV history + latest NAV via AkShare / EastMoney)
- Stocks (OHLCV daily bars + real-time quotes via TDX, preserving receipt integrity)
- Latest quote snapshots and daily close snapshots
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.market_calendar import build_market_calendar_provider
from data.providers.akshare import AKShareSource
from data.providers.tdx import TdxSource
from data.store import DataStore
from server.persistence.market_calendar import MarketCalendarRepository
from server.projections.quote_status import parse_quote_timestamp
from server.runtime_paths import resolve_data_dir
from server.services.fund_nav_sync import is_confirmed_fund_nav_quote

logger = logging.getLogger(__name__)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

DEFAULT_BENCHMARK_INDICES: tuple[tuple[str, str], ...] = (
    ("000001", "上证指数"),
    ("399001", "深证成指"),
    ("399006", "创业板指"),
    ("000300", "沪深300"),
    ("000905", "中证500"),
    ("000016", "上证50"),
    ("000688", "科创50"),
    ("000852", "中证1000"),
)

DEFAULT_ETFS: tuple[tuple[str, str], ...] = (
    ("510300", "沪深300ETF"),
    ("159915", "创业板ETF"),
    ("510500", "中证500ETF"),
    ("518880", "黄金ETF"),
    ("511010", "国债ETF"),
    ("512890", "红利低波ETF"),
    ("513100", "纳指ETF"),
    ("513500", "标普500ETF"),
    ("159949", "创业板50ETF"),
    ("588000", "科创50ETF"),
)

DEFAULT_OPEN_END_FUNDS: tuple[tuple[str, str], ...] = (
    ("018125", "永赢先进制造智选混合C"),
    ("012710", "华夏核心成长混合C"),
    ("026539", "融通科技臻选混合C"),
)

DEFAULT_WATCHLIST_STOCKS: tuple[tuple[str, str], ...] = (
    ("601985", "中国核电"),
    ("002594", "比亚迪"),
    ("600172", "黄河旋风"),
    ("603659", "璞泰来"),
    ("600066", "宇通客车"),
)


@dataclass(frozen=True, slots=True)
class SyncTarget:
    symbol: str
    asset_class: AssetClass
    instrument_type: InstrumentType
    display_name: str


@dataclass(slots=True)
class MarketSyncItem:
    symbol: str
    asset_class: str
    instrument_type: str
    bars_count: int
    status: str  # "updated", "cached", "failed", "skipped"
    error: str | None = None


@dataclass(slots=True)
class MarketSyncSummary:
    status: str  # "success", "partial", "failed"
    started_at: str
    completed_at: str
    duration_seconds: float
    calendar_years: list[int] = field(default_factory=list)
    total_targets: int = 0
    successful_targets: int = 0
    failed_targets: int = 0
    quotes_updated: int = 0
    items: list[MarketSyncItem] = field(default_factory=list)


@dataclass(slots=True)
class MarketSyncRequest:
    universe: str = "core"  # "core", "indices", "etfs", "funds", "stocks", "all"
    symbols: list[str] | None = None
    asset_class: str | None = None
    instrument_type: str | None = None
    start_date: str = "2020-01-01"
    end_date: str | None = None
    skip_calendar: bool = False
    skip_quotes: bool = False
    force: bool = False


def _daily_close_trade_date(
    target: SyncTarget,
    snapshot: dict[str, Any],
    *,
    captured_at: datetime,
) -> str | None:
    observed_at = parse_quote_timestamp(
        snapshot.get("quote_timestamp") or snapshot.get("timestamp")
    )
    if observed_at is None or observed_at > captured_at:
        return None
    if target.instrument_type is InstrumentType.OPEN_END_FUND:
        nav_date = str(snapshot.get("nav_date") or "").strip()
        try:
            nav_day = date.fromisoformat(nav_date)
        except ValueError:
            return None
        if nav_day > observed_at.date():
            return None
        return (
            nav_date
            if is_confirmed_fund_nav_quote(snapshot, target_date=nav_date)
            else None
        )
    if (
        observed_at.time() < time(15)
        or str(snapshot.get("quote_status") or "live").strip().lower()
        not in {"live", "confirmed", "fresh", "healthy"}
        or str(snapshot.get("provider_status") or "live").strip().lower() != "live"
        or snapshot.get("stale_reason") not in {None, ""}
    ):
        return None
    return observed_at.date().isoformat()


class MarketSyncService:
    """Unified engine for syncing all market facts and historical series."""

    def __init__(
        self,
        *,
        data_dir: Path | str | None = None,
        db: Any = None,
        config: Any = None,
        data_store: DataStore | None = None,
        tdx_source: TdxSource | None = None,
        ak_source: AKShareSource | None = None,
    ) -> None:
        self._data_dir = Path(data_dir or resolve_data_dir())
        self._db = db
        self._config = config
        self._data_store = data_store or DataStore(self._data_dir)
        self._tdx = tdx_source or TdxSource()
        self._ak = ak_source or AKShareSource()
        self._last_summary: MarketSyncSummary | None = None

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def data_store(self) -> DataStore:
        return self._data_store

    def get_last_summary(self) -> MarketSyncSummary | None:
        return self._last_summary

    def resolve_targets(self, request: MarketSyncRequest) -> list[SyncTarget]:
        """Resolve concrete sync targets from request scope and database."""
        if request.symbols:
            targets: list[SyncTarget] = []
            for raw_sym in request.symbols:
                sym_code = raw_sym.strip()
                if not sym_code:
                    continue
                inst_type = self._detect_instrument_type(
                    sym_code,
                    asset_class_str=request.asset_class,
                    instrument_type_str=request.instrument_type,
                )
                ac = self._instrument_type_to_asset_class(inst_type)
                targets.append(
                    SyncTarget(
                        symbol=sym_code,
                        asset_class=ac,
                        instrument_type=inst_type,
                        display_name=sym_code,
                    )
                )
            return targets

        scope = request.universe.lower().strip()
        targets: list[SyncTarget] = []
        sync_all = scope in ("core", "all")

        # 1. Benchmark Indices
        if sync_all or scope == "indices":
            for sym, name in DEFAULT_BENCHMARK_INDICES:
                targets.append(
                    SyncTarget(
                        symbol=sym,
                        asset_class=AssetClass.INDEX,
                        instrument_type=InstrumentType.INDEX,
                        display_name=name,
                    )
                )

        # 2. ETFs
        if sync_all or scope == "etfs":
            for sym, name in DEFAULT_ETFS:
                targets.append(
                    SyncTarget(
                        symbol=sym,
                        asset_class=AssetClass.FUND,
                        instrument_type=InstrumentType.ETF,
                        display_name=name,
                    )
                )

        # 3. Open-End Funds
        if sync_all or scope == "funds":
            discovered_funds: dict[str, str] = {s: n for s, n in DEFAULT_OPEN_END_FUNDS}
            if self._db and hasattr(self._db, "list_watchlist_assets_sync"):
                try:
                    for asset in self._db.list_watchlist_assets_sync():
                        if (
                            str(asset.get("asset_class") or "") == "fund"
                            or str(asset.get("instrument_type") or "")
                            == "open_end_fund"
                        ):
                            s = str(asset.get("symbol") or "").strip()
                            if s and not s.startswith(("51", "15", "56", "58")):
                                discovered_funds[s] = str(
                                    asset.get("display_name") or s
                                )
                except Exception:
                    logger.debug(
                        "Could not read watchlist funds from db", exc_info=True
                    )
            for sym, name in discovered_funds.items():
                targets.append(
                    SyncTarget(
                        symbol=sym,
                        asset_class=AssetClass.FUND,
                        instrument_type=InstrumentType.OPEN_END_FUND,
                        display_name=name,
                    )
                )

        # 4. Stocks (Watchlist / Core)
        if sync_all or scope == "stocks":
            discovered_stocks: dict[str, str] = {
                s: n for s, n in DEFAULT_WATCHLIST_STOCKS
            }
            if self._db and hasattr(self._db, "list_watchlist_assets_sync"):
                try:
                    for asset in self._db.list_watchlist_assets_sync():
                        ac = str(asset.get("asset_class") or "")
                        it = str(asset.get("instrument_type") or "")
                        if ac == "stock" or it == "stock":
                            s = str(asset.get("symbol") or "").strip()
                            if s:
                                discovered_stocks[s] = str(
                                    asset.get("display_name") or s
                                )
                except Exception:
                    logger.debug(
                        "Could not read watchlist stocks from db", exc_info=True
                    )
            for sym, name in discovered_stocks.items():
                targets.append(
                    SyncTarget(
                        symbol=sym,
                        asset_class=AssetClass.STOCK,
                        instrument_type=InstrumentType.STOCK,
                        display_name=name,
                    )
                )

        # Deduplicate targets by (symbol, instrument_type)
        deduped: list[SyncTarget] = []
        seen: set[tuple[str, InstrumentType]] = set()
        for t in targets:
            key = (t.symbol, t.instrument_type)
            if key not in seen:
                seen.add(key)
                deduped.append(t)
        return deduped

    def sync_calendar(
        self, start_year: int, end_year: int, *, force: bool = False
    ) -> list[int]:
        """Synchronize exchange trading calendar snapshots into local storage."""
        app_db = self._data_dir / "app.db"
        repo = MarketCalendarRepository(str(app_db))
        provider = build_market_calendar_provider("akshare")
        synced_years: list[int] = []

        for year in range(start_year, end_year + 1):
            if not force:
                existing = repo.get_snapshot(exchange="SSE", year=year)
                if existing is not None:
                    continue
            try:
                snap = provider.fetch_snapshot(exchange="SSE", year=year)
                repo.upsert_snapshot(snap)
                synced_years.append(year)
                logger.info(
                    "Saved calendar %d: %d trading days, %d closed days",
                    year,
                    snap.trading_day_count,
                    snap.closed_day_count,
                )
            except Exception:
                logger.warning(
                    "Failed to fetch calendar for year %d", year, exc_info=True
                )
        return synced_years

    def sync_target_bars(
        self,
        target: SyncTarget,
        start: datetime,
        end: datetime,
        *,
        force: bool = False,
    ) -> MarketSyncItem:
        """Fetch and persist historical bars for one target under its exact identity."""
        sym = Symbol(target.symbol)
        try:
            if target.instrument_type is InstrumentType.INDEX:
                df = self._tdx.fetch_bars(
                    sym,
                    start=start,
                    end=end,
                    frequency=BarFrequency.DAILY,
                    asset_class=AssetClass.INDEX,
                )
                if df.empty:
                    return MarketSyncItem(
                        symbol=target.symbol,
                        asset_class=target.asset_class.value,
                        instrument_type=target.instrument_type.value,
                        bars_count=0,
                        status="skipped",
                        error="no_bars_returned",
                    )
                self._data_store.save_bars(
                    sym,
                    BarFrequency.DAILY,
                    df,
                    instrument_type=InstrumentType.INDEX,
                    provider_name="tdx",
                    data_source="tdx",
                )
                return MarketSyncItem(
                    symbol=target.symbol,
                    asset_class=target.asset_class.value,
                    instrument_type=target.instrument_type.value,
                    bars_count=len(df),
                    status="updated",
                )

            elif target.instrument_type is InstrumentType.ETF:
                df = self._tdx.fetch_bars(
                    sym,
                    start=start,
                    end=end,
                    frequency=BarFrequency.DAILY,
                    asset_class=AssetClass.FUND,
                )
                if df.empty:
                    return MarketSyncItem(
                        symbol=target.symbol,
                        asset_class=target.asset_class.value,
                        instrument_type=target.instrument_type.value,
                        bars_count=0,
                        status="skipped",
                        error="no_bars_returned",
                    )
                self._data_store.save_bars(
                    sym,
                    BarFrequency.DAILY,
                    df,
                    instrument_type=InstrumentType.ETF,
                    provider_name="tdx",
                    data_source="tdx",
                )
                return MarketSyncItem(
                    symbol=target.symbol,
                    asset_class=target.asset_class.value,
                    instrument_type=target.instrument_type.value,
                    bars_count=len(df),
                    status="updated",
                )

            elif target.instrument_type is InstrumentType.OPEN_END_FUND:
                df = self._ak.fetch_bars(
                    sym,
                    start=start,
                    end=end,
                    frequency=BarFrequency.DAILY,
                    asset_class=AssetClass.FUND,
                )
                if df.empty:
                    return MarketSyncItem(
                        symbol=target.symbol,
                        asset_class=target.asset_class.value,
                        instrument_type=target.instrument_type.value,
                        bars_count=0,
                        status="skipped",
                        error="no_bars_returned",
                    )
                self._data_store.save_bars(
                    sym,
                    BarFrequency.DAILY,
                    df,
                    instrument_type=InstrumentType.OPEN_END_FUND,
                    provider_name="akshare",
                    data_source="akshare",
                )
                return MarketSyncItem(
                    symbol=target.symbol,
                    asset_class=target.asset_class.value,
                    instrument_type=target.instrument_type.value,
                    bars_count=len(df),
                    status="updated",
                )

            else:
                # Stock: merge with existing receipt-bound bars to avoid mutation conflicts
                df_remote = self._tdx.fetch_bars(
                    sym,
                    start=start,
                    end=end,
                    frequency=BarFrequency.DAILY,
                    asset_class=AssetClass.STOCK,
                )
                if df_remote.empty:
                    return MarketSyncItem(
                        symbol=target.symbol,
                        asset_class=target.asset_class.value,
                        instrument_type=target.instrument_type.value,
                        bars_count=0,
                        status="skipped",
                        error="no_bars_returned",
                    )

                df_merged = self._merge_stock_bars_safely(sym, df_remote)
                self._data_store.save_bars(
                    sym,
                    BarFrequency.DAILY,
                    df_merged,
                    instrument_type=InstrumentType.STOCK,
                    provider_name="tdx",
                    data_source="tdx",
                )
                return MarketSyncItem(
                    symbol=target.symbol,
                    asset_class=target.asset_class.value,
                    instrument_type=target.instrument_type.value,
                    bars_count=len(df_merged),
                    status="updated",
                )

        except Exception as exc:
            logger.warning(
                "Sync failed for %s (%s): %s",
                target.symbol,
                target.instrument_type.value,
                exc,
                exc_info=True,
            )
            return MarketSyncItem(
                symbol=target.symbol,
                asset_class=target.asset_class.value,
                instrument_type=target.instrument_type.value,
                bars_count=0,
                status="failed",
                error=str(exc),
            )

    def _get_db(self) -> Any:
        if self._db is not None:
            return self._db
        app_db = self._data_dir / "app.db"
        if app_db.exists():
            from server.db import AppDatabase

            self._db = AppDatabase(app_db)
        return self._db

    def _merge_stock_bars_safely(
        self, symbol: Symbol, df_remote: pd.DataFrame
    ) -> pd.DataFrame:
        """Merge remote bars while strictly preserving existing observations."""
        existing_df = self._data_store.load_bars(
            symbol,
            BarFrequency.DAILY,
            instrument_type=InstrumentType.STOCK,
        )
        if existing_df is None or existing_df.empty:
            return df_remote

        existing_copy = existing_df.copy()
        existing_copy["_date"] = pd.to_datetime(existing_copy["timestamp"]).dt.strftime(
            "%Y-%m-%d"
        )
        existing_dates = set(existing_copy["_date"])

        remote_copy = df_remote.copy()
        remote_copy["_date"] = pd.to_datetime(remote_copy["timestamp"]).dt.strftime(
            "%Y-%m-%d"
        )

        new_bars = remote_copy[~remote_copy["_date"].isin(existing_dates)]
        if new_bars.empty:
            return existing_df.sort_values("timestamp").reset_index(drop=True)

        cols = [
            c
            for c in ["timestamp", "open", "high", "low", "close", "volume", "amount"]
            if c in existing_df.columns
        ]
        combined = pd.concat([existing_df[cols], new_bars[cols]], ignore_index=True)
        combined["timestamp"] = pd.to_datetime(combined["timestamp"])
        return combined.sort_values("timestamp").reset_index(drop=True)

    def sync_latest_quotes(self, targets: list[SyncTarget]) -> int:
        """Update atomic latest quotes and daily close snapshots."""
        db = self._get_db()
        captured_at = datetime.now(timezone.utc)
        now_iso = captured_at.isoformat()
        updated_count = 0

        for target in targets:
            sym = Symbol(target.symbol)
            try:
                if target.instrument_type is InstrumentType.OPEN_END_FUND:
                    q = self._ak.fetch_latest(sym, asset_class=AssetClass.FUND)
                else:
                    q = self._tdx.fetch_latest(sym, asset_class=target.asset_class)

                if not q or q.get("price") is None:
                    continue

                price = float(q["price"])
                prev_close = float(q.get("previous_close") or price)
                change = float(q.get("change") or round(price - prev_close, 4))
                change_pct = float(
                    q.get("change_percent")
                    or (round(change / prev_close, 6) if prev_close else 0.0)
                )
                vol = float(q.get("volume") or 0.0)
                turnover = float(q.get("turnover") or 0.0)
                quote_ts = q.get("quote_timestamp") or q.get("timestamp") or now_iso
                nav_date = q.get("nav_date")
                provider_name = str(q.get("provider_name") or "tdx")
                quote_source = str(q.get("quote_source") or f"{provider_name}_realtime")

                if db is not None:
                    db.upsert_latest_quote_sync(
                        symbol=target.symbol,
                        asset_type=target.instrument_type.value,
                        price=price,
                        previous_close=prev_close,
                        change=change,
                        change_percent=change_pct,
                        volume=vol,
                        turnover=turnover,
                        quote_timestamp=str(quote_ts),
                        quote_source=quote_source,
                        provider_name=provider_name,
                        captured_at=now_iso,
                        nav_date=nav_date,
                    )
                    close_date = _daily_close_trade_date(
                        target, q, captured_at=captured_at
                    )
                    if close_date is not None:
                        db.save_daily_close_snapshot_sync(
                            symbol=target.symbol,
                            asset_class=target.instrument_type.value,
                            trade_date=close_date,
                            close_price=price,
                            source=provider_name,
                        )
                    updated_count += 1
            except Exception:
                logger.warning(
                    "Quote snapshot update failed for %s", target.symbol, exc_info=True
                )

        return updated_count

    def sync(self, request: MarketSyncRequest | None = None) -> MarketSyncSummary:
        """Execute complete synchronization according to request specification."""
        req = request or MarketSyncRequest()
        start_time = datetime.now()
        started_at_iso = start_time.isoformat()

        start_date = datetime.strptime(req.start_date, "%Y-%m-%d").replace(
            tzinfo=_SHANGHAI
        )
        end_date = (
            datetime.strptime(req.end_date, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=_SHANGHAI
            )
            if req.end_date
            else datetime.now(_SHANGHAI).replace(hour=23, minute=59, second=59)
        )

        calendar_years: list[int] = []
        if not req.skip_calendar:
            calendar_years = self.sync_calendar(
                start_date.year, end_date.year, force=req.force
            )

        targets = self.resolve_targets(req)
        items: list[MarketSyncItem] = []
        for target in targets:
            item = self.sync_target_bars(target, start_date, end_date, force=req.force)
            items.append(item)

        quotes_updated = 0
        if not req.skip_quotes and targets:
            quotes_updated = self.sync_latest_quotes(targets)

        end_time = datetime.now()
        completed_at_iso = end_time.isoformat()
        duration = (end_time - start_time).total_seconds()

        successful = sum(1 for it in items if it.status in ("updated", "cached"))
        failed = sum(1 for it in items if it.status == "failed")
        overall_status = (
            "success" if failed == 0 else ("partial" if successful > 0 else "failed")
        )

        summary = MarketSyncSummary(
            status=overall_status,
            started_at=started_at_iso,
            completed_at=completed_at_iso,
            duration_seconds=round(duration, 3),
            calendar_years=calendar_years,
            total_targets=len(targets),
            successful_targets=successful,
            failed_targets=failed,
            quotes_updated=quotes_updated,
            items=items,
        )
        self._last_summary = summary
        return summary

    def sync_post_close(self, trade_date: str | None = None) -> MarketSyncSummary:
        """Routine post-close reconciliation helper for the background scheduler."""
        today = trade_date or datetime.now(_SHANGHAI).strftime("%Y-%m-%d")
        # Ensure calendar for this year exists, sync core universe bars & quotes for recent 60 days
        start_day = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=60)
        ).strftime("%Y-%m-%d")
        req = MarketSyncRequest(
            universe="core",
            start_date=start_day,
            end_date=today,
            skip_calendar=False,
            skip_quotes=False,
        )
        return self.sync(req)

    @staticmethod
    def _detect_instrument_type(
        symbol: str,
        asset_class_str: str | None = None,
        instrument_type_str: str | None = None,
    ) -> InstrumentType:
        if instrument_type_str:
            return InstrumentType.from_persisted(instrument_type_str)
        if asset_class_str:
            ac = str(asset_class_str).lower().strip()
            if ac == "index":
                return InstrumentType.INDEX
            if ac == "fund":
                if symbol.startswith(("51", "15", "56", "58")):
                    return InstrumentType.ETF
                return InstrumentType.OPEN_END_FUND
            if ac == "stock":
                return InstrumentType.STOCK

        if symbol in {
            "000001",
            "399001",
            "399006",
            "000300",
            "000905",
            "000016",
            "000688",
            "000852",
        }:
            return InstrumentType.INDEX
        if symbol.startswith(("51", "15", "56", "58")):
            return InstrumentType.ETF
        if symbol.startswith(("01", "02", "16")):
            return InstrumentType.OPEN_END_FUND
        return InstrumentType.STOCK

    @staticmethod
    def _instrument_type_to_asset_class(inst_type: InstrumentType) -> AssetClass:
        if inst_type is InstrumentType.INDEX:
            return AssetClass.INDEX
        if inst_type in (InstrumentType.ETF, InstrumentType.OPEN_END_FUND):
            return AssetClass.FUND
        return AssetClass.STOCK


_GLOBAL_SERVICE: MarketSyncService | None = None


def get_market_sync_service(
    *,
    data_dir: Path | str | None = None,
    db: Any = None,
    config: Any = None,
) -> MarketSyncService:
    global _GLOBAL_SERVICE
    if _GLOBAL_SERVICE is None:
        _GLOBAL_SERVICE = MarketSyncService(data_dir=data_dir, db=db, config=config)
    return _GLOBAL_SERVICE
