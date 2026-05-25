"""DataManager — 数据管线编排：查缓存 → 受控补缺 → 返回 DataHandler。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
from core.types import AssetClass, BarFrequency, Symbol
from data.handler import DataHandler
from data.source import DataSource
from data.store import DataStore
from domain.instrument import (
    Instrument,
    make_bond,
    make_etf,
    make_gold_spot,
    make_open_end_fund,
    make_stock,
)

logger = logging.getLogger(__name__)

_EMPTY_BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def build_sources(
    data_source: str = "akshare", tushare_token: str = ""
) -> dict[str, DataSource]:
    """集中构建数据源字典，消除四处重复代码。"""
    from data.providers.akshare_source import AKShareSource
    from data.providers.tushare_source import TushareSource

    sources: dict[str, DataSource] = {"akshare": AKShareSource()}
    if tushare_token:
        sources["tushare"] = TushareSource(token=tushare_token)
    return sources


# 资产类别 → 标的名称模板
_ASSET_NAMES: dict[AssetClass, str] = {
    AssetClass.STOCK: "A股",
    AssetClass.FUND: "ETF",
    AssetClass.GOLD: "黄金",
    AssetClass.BOND: "债券",
}


class DataManager:
    """数据管线编排。

    串联 DataSource → DataStore → DataHandler，
    支持多数据源切换、Parquet 缓存和增量更新。
    """

    def __init__(
        self,
        sources: dict[str, DataSource],
        store: DataStore | None = None,
        default_source: str = "akshare",
    ) -> None:
        self.sources = sources
        self.store = store
        self.default_source = default_source

    def get_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
        source_name: str | None = None,
        allow_remote_refresh: bool = True,
        refresh_ttl_seconds: int | None = None,
        degrade_to_cache: bool = False,
    ) -> DataHandler:
        """获取 K 线数据，支持本地优先和受控增量补缺。"""
        if self.store is not None:
            cached = self.store.load_bars(symbol, frequency)
            if cached is not None and len(cached) > 0 and "timestamp" in cached.columns:
                ts_min = cached["timestamp"].min()
                ts_max = cached["timestamp"].max()
                cached_slice = self._slice_cached(cached, start, end)

                if ts_min <= pd.Timestamp(start) and ts_max >= pd.Timestamp(end):
                    logger.info("缓存命中: %s (%s)", symbol, frequency.value)
                    return DataHandler(
                        cached_slice,
                        symbol,
                        frequency,
                        asset_class,
                    )

                if not allow_remote_refresh or not self._should_refresh_remote(
                    symbol,
                    frequency,
                    end,
                    refresh_ttl_seconds,
                ):
                    logger.info(
                        "使用本地缓存，跳过远端补缺: %s (%s)",
                        symbol,
                        frequency.value,
                    )
                    return DataHandler(
                        cached_slice,
                        symbol,
                        frequency,
                        asset_class,
                    )

                gaps = self._compute_gaps(ts_min, ts_max, start, end)
                if gaps:
                    source = self._get_source(source_name)
                    for gap_start, gap_end in gaps:
                        try:
                            logger.info(
                                "增量拉取: %s (%s) %s ~ %s",
                                symbol,
                                asset_class.value,
                                gap_start.date(),
                                gap_end.date(),
                            )
                            df = source.fetch_bars(
                                symbol,
                                gap_start,
                                gap_end,
                                frequency,
                                asset_class,
                            )
                            if not df.empty:
                                self.store.append_bars(symbol, frequency, df)
                        except Exception:
                            logger.warning(
                                "增量拉取失败，回退使用本地缓存: %s %s~%s",
                                symbol,
                                gap_start.date(),
                                gap_end.date(),
                                exc_info=True,
                            )
                    cached = self.store.load_bars(symbol, frequency)
                    if cached is not None and len(cached) > 0:
                        return DataHandler(
                            self._slice_cached(cached, start, end),
                            symbol,
                            frequency,
                            asset_class,
                        )

                return DataHandler(
                    cached_slice,
                    symbol,
                    frequency,
                    asset_class,
                )

        if not allow_remote_refresh:
            logger.info("远端刷新已禁用，返回空缓存结果: %s (%s)", symbol, frequency.value)
            return DataHandler(
                self._empty_bars(),
                symbol,
                frequency,
                asset_class,
            )

        source = self._get_source(source_name)
        logger.info(
            "拉取数据: %s (%s) from %s",
            symbol,
            asset_class.value,
            source_name or self.default_source,
        )
        try:
            df = source.fetch_bars(symbol, start, end, frequency, asset_class)
        except Exception:
            logger.warning(
                "远端拉取失败，%s (%s) 回退为空结果",
                symbol,
                frequency.value,
                exc_info=True,
            )
            if degrade_to_cache:
                return DataHandler(
                    self._empty_bars(),
                    symbol,
                    frequency,
                    asset_class,
                )
            raise

        if df.empty:
            raise ValueError(
                f"未获取到数据: {symbol} ({asset_class.value}) {start}~{end}"
            )

        if self.store is not None:
            self.store.save_bars(symbol, frequency, df)

        return DataHandler(df, symbol, frequency, asset_class)

    @staticmethod
    def _empty_bars() -> pd.DataFrame:
        return pd.DataFrame(columns=_EMPTY_BAR_COLUMNS)

    @staticmethod
    def _slice_cached(
        cached: pd.DataFrame,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if cached.empty or "timestamp" not in cached.columns:
            return cached.reset_index(drop=True)
        mask = (cached["timestamp"] >= pd.Timestamp(start)) & (
            cached["timestamp"] <= pd.Timestamp(end)
        )
        return cached.loc[mask].reset_index(drop=True)

    @staticmethod
    def _targets_recent_range(end: datetime, frequency: BarFrequency) -> bool:
        now = datetime.now()
        if frequency in (BarFrequency.MIN_1, BarFrequency.MIN_5):
            return end.date() >= now.date()
        return end.date() >= (now - timedelta(days=1)).date()

    def _should_refresh_remote(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        end: datetime,
        refresh_ttl_seconds: int | None,
    ) -> bool:
        if not self._targets_recent_range(end, frequency):
            return False
        if refresh_ttl_seconds is None or self.store is None:
            return True

        meta = self.store.get_meta(symbol, frequency)
        if meta is None or not meta.get("last_updated"):
            return True

        last_updated = datetime.fromisoformat(str(meta["last_updated"]))
        return (datetime.now() - last_updated).total_seconds() >= refresh_ttl_seconds

    @staticmethod
    def _compute_gaps(
        cached_min: "pd.Timestamp",
        cached_max: "pd.Timestamp",
        requested_start: datetime,
        requested_end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """计算缓存未覆盖的缺失区间。"""
        import pandas as pd

        gaps = []
        # 头部缺失
        if pd.Timestamp(requested_start) < cached_min:
            gaps.append((requested_start, cached_min.to_pydatetime()))
        # 尾部缺失
        if pd.Timestamp(requested_end) > cached_max:
            gaps.append((cached_max.to_pydatetime(), requested_end))
        return gaps

    def _get_source(self, source_name: str | None = None) -> DataSource:
        """获取数据源。"""
        name = source_name or self.default_source
        source = self.sources.get(name)
        if source is None:
            raise ValueError(f"数据源 '{name}' 未注册")
        return source

    @staticmethod
    def get_instrument(symbol: Symbol, asset_class: AssetClass) -> Instrument:
        """根据 symbol + asset_class 自动创建 Instrument。"""
        sym_str = str(symbol)
        name = f"{sym_str} {_ASSET_NAMES.get(asset_class, '')}"

        if asset_class == AssetClass.STOCK:
            return make_stock(sym_str, name)
        elif asset_class == AssetClass.FUND:
            if not sym_str.isascii() or not sym_str[:1].isdigit():
                return make_open_end_fund(sym_str, sym_str)
            return make_etf(sym_str, name)
        elif asset_class == AssetClass.GOLD:
            return make_gold_spot(symbol=sym_str, name=name)
        elif asset_class == AssetClass.BOND:
            return make_bond(sym_str, name)
        else:
            raise ValueError(f"不支持的资产类别: {asset_class}")
