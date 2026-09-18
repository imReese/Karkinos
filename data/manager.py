"""DataManager — 数据管线编排：查缓存 → 受控补缺 → 返回 DataHandler。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.handler import DataHandler
from data.provider_registry import build_provider_registry
from data.source import DataSource
from data.source_policy import (
    CN_RESEARCH_V1,
    MarketDataUseCase,
    MarketSourcePolicy,
    legacy_preferred_provider_policy,
    resolve_market_source_policy,
    source_policy_for_config,
)
from data.store import DataStore
from domain.instrument import (
    Instrument,
    make_bond,
    make_etf,
    make_gold_spot,
    make_index,
    make_open_end_fund,
    make_stock,
)

logger = logging.getLogger(__name__)

_EMPTY_BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def build_sources(
    data_source: str | None = None,
    tushare_token: str = "",
    *,
    source_policy: MarketSourcePolicy | str | None = None,
) -> dict[str, DataSource]:
    """Build legacy DataSource adapters in policy order."""
    if source_policy is None:
        policy = (
            legacy_preferred_provider_policy(data_source)
            if data_source
            else CN_RESEARCH_V1
        )
    elif isinstance(source_policy, MarketSourcePolicy):
        policy = source_policy
    else:
        policy = resolve_market_source_policy(str(source_policy))

    ordered: list[str] = []
    for _, route in policy.routes:
        for name in route.candidates:
            if name not in ordered:
                ordered.append(name)
    return build_provider_registry(
        tushare_token=tushare_token,
        include_tdx=False,
    ).legacy_sources(tuple(ordered))


def build_sources_for_config(config: object) -> dict[str, DataSource]:
    return build_sources(
        tushare_token=str(getattr(config, "tushare_token", "") or ""),
        source_policy=source_policy_for_config(config),
    )


# 资产类别 → 标的名称模板
_ASSET_NAMES: dict[AssetClass, str] = {
    AssetClass.STOCK: "A股",
    AssetClass.FUND: "ETF",
    AssetClass.GOLD: "黄金",
    AssetClass.BOND: "债券",
    AssetClass.INDEX: "指数",
}

_ASSET_INSTRUMENT_TYPES: dict[AssetClass, InstrumentType] = {
    AssetClass.STOCK: InstrumentType.STOCK,
    AssetClass.GOLD: InstrumentType.GOLD,
    AssetClass.BOND: InstrumentType.BOND,
    AssetClass.INDEX: InstrumentType.INDEX,
}


def _bar_instrument_type(
    asset_class: AssetClass,
    *,
    instrument_type: InstrumentType | None,
) -> InstrumentType:
    """Require the ETF/open-end distinction before cache access or writes."""

    if instrument_type is not None:
        if instrument_type is InstrumentType.UNKNOWN:
            raise ValueError("authoritative instrument type is unresolved")
        expected = _ASSET_INSTRUMENT_TYPES.get(asset_class)
        if expected is not None and instrument_type is not expected:
            raise ValueError("instrument_type conflicts with asset_class")
        if asset_class is AssetClass.FUND and instrument_type not in {
            InstrumentType.ETF,
            InstrumentType.OPEN_END_FUND,
        }:
            raise ValueError("fund bar identity must be ETF or open-end fund")
        return instrument_type
    resolved = _ASSET_INSTRUMENT_TYPES.get(asset_class)
    if resolved is None:
        raise ValueError(
            "AssetClass.FUND is ambiguous; instrument_type must distinguish "
            "ETF from open-end fund"
        )
    return resolved


def _bar_use_case(
    asset_class: AssetClass,
    frequency: BarFrequency,
) -> MarketDataUseCase:
    if asset_class is AssetClass.INDEX:
        return MarketDataUseCase.INDEX_BARS
    if asset_class is AssetClass.GOLD:
        return MarketDataUseCase.GOLD_BARS
    if asset_class is AssetClass.BOND:
        return MarketDataUseCase.BOND_BARS
    if frequency in {BarFrequency.MIN_1, BarFrequency.MIN_5}:
        return MarketDataUseCase.REALTIME_QUOTES
    return MarketDataUseCase.DAILY_BARS


class DataManager:
    """数据管线编排。

    串联 DataSource → DataStore → DataHandler，
    支持多数据源切换、Parquet 缓存和增量更新。
    """

    def __init__(
        self,
        sources: dict[str, DataSource],
        store: DataStore | None = None,
        default_source: str | None = None,
        *,
        source_policy: MarketSourcePolicy | None = None,
    ) -> None:
        self.sources = sources
        self.store = store
        self._explicit_default_source = default_source
        self.source_policy = (
            source_policy
            if source_policy is not None
            else (
                legacy_preferred_provider_policy(default_source)
                if default_source
                else CN_RESEARCH_V1
            )
        )
        self.default_source = (
            default_source
            or self.source_policy.route(MarketDataUseCase.REALTIME_QUOTES).candidates[0]
        )

    def get_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
        instrument_type: InstrumentType | None = None,
        source_name: str | None = None,
        allow_remote_refresh: bool = True,
        refresh_ttl_seconds: int | None = None,
        degrade_to_cache: bool = False,
    ) -> DataHandler:
        """获取 K 线数据，支持本地优先和受控增量补缺。"""
        resolved_instrument_type = _bar_instrument_type(
            asset_class,
            instrument_type=instrument_type,
        )
        if self.store is not None:
            cached = self.store.load_bars(
                symbol,
                frequency,
                instrument_type=resolved_instrument_type,
            )
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
                        resolved_instrument_type,
                    )

                if not allow_remote_refresh or not self._should_refresh_remote(
                    symbol,
                    frequency,
                    end,
                    refresh_ttl_seconds,
                    instrument_type=resolved_instrument_type,
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
                        resolved_instrument_type,
                    )

                gaps = self._compute_gaps(ts_min, ts_max, start, end)
                if gaps:
                    for gap_start, gap_end in gaps:
                        try:
                            logger.info(
                                "增量拉取: %s (%s) %s ~ %s",
                                symbol,
                                asset_class.value,
                                gap_start.date(),
                                gap_end.date(),
                            )
                            df = self._fetch_bars_remote(
                                symbol,
                                gap_start,
                                gap_end,
                                frequency,
                                asset_class,
                                source_name=source_name,
                            )
                            if not df.empty:
                                self.store.append_bars(
                                    symbol,
                                    frequency,
                                    df,
                                    instrument_type=resolved_instrument_type,
                                )
                        except Exception:
                            logger.warning(
                                "增量拉取失败，回退使用本地缓存: %s %s~%s",
                                symbol,
                                gap_start.date(),
                                gap_end.date(),
                                exc_info=True,
                            )
                    cached = self.store.load_bars(
                        symbol,
                        frequency,
                        instrument_type=resolved_instrument_type,
                    )
                    if cached is not None and len(cached) > 0:
                        return DataHandler(
                            self._slice_cached(cached, start, end),
                            symbol,
                            frequency,
                            asset_class,
                            resolved_instrument_type,
                        )

                return DataHandler(
                    cached_slice,
                    symbol,
                    frequency,
                    asset_class,
                    resolved_instrument_type,
                )

        if not allow_remote_refresh:
            logger.info(
                "远端刷新已禁用，返回空缓存结果: %s (%s)", symbol, frequency.value
            )
            return DataHandler(
                self._empty_bars(),
                symbol,
                frequency,
                asset_class,
                resolved_instrument_type,
            )

        logger.info(
            "拉取数据: %s (%s) from %s",
            symbol,
            asset_class.value,
            source_name
            or self.source_policy.route(
                _bar_use_case(asset_class, frequency)
            ).candidates[0],
        )
        try:
            df = self._fetch_bars_remote(
                symbol,
                start,
                end,
                frequency,
                asset_class,
                source_name=source_name,
            )
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
                    resolved_instrument_type,
                )
            raise

        if df.empty:
            raise ValueError(
                f"未获取到数据: {symbol} ({asset_class.value}) {start}~{end}"
            )

        if self.store is not None:
            self.store.save_bars(
                symbol,
                frequency,
                df,
                instrument_type=resolved_instrument_type,
            )

        return DataHandler(
            df,
            symbol,
            frequency,
            asset_class,
            resolved_instrument_type,
        )

    def _source_candidates(
        self,
        *,
        asset_class: AssetClass,
        frequency: BarFrequency,
        source_name: str | None = None,
    ) -> list[tuple[str, DataSource]]:
        if source_name is not None:
            return [(source_name, self._get_source(source_name))]
        route_names = self.source_policy.route(
            _bar_use_case(asset_class, frequency)
        ).candidates
        names = list(route_names)
        explicit = self._explicit_default_source
        if explicit and explicit in self.sources and explicit not in names:
            names.insert(0, explicit)
        return [
            (name, source)
            for name in names
            if (source := self.sources.get(name)) is not None
        ]

    def _fetch_bars_remote(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency,
        asset_class: AssetClass,
        *,
        source_name: str | None = None,
    ) -> pd.DataFrame:
        errors: list[Exception] = []
        empty_sources: list[str] = []
        unsupported_sources: list[str] = []
        for candidate_name, source in self._source_candidates(
            asset_class=asset_class,
            frequency=frequency,
            source_name=source_name,
        ):
            supports_bars = getattr(source, "supports_bars", None)
            if callable(supports_bars) and not supports_bars(
                asset_class=asset_class, frequency=frequency
            ):
                unsupported_sources.append(candidate_name)
                logger.info(
                    "跳过不支持的远端数据源: %s %s (%s, %s)",
                    candidate_name,
                    symbol,
                    asset_class.value,
                    frequency.value,
                )
                continue
            try:
                df = source.fetch_bars(symbol, start, end, frequency, asset_class)
            except Exception as exc:
                errors.append(exc)
                logger.warning(
                    "远端数据源失败: %s %s (%s) %s~%s",
                    candidate_name,
                    symbol,
                    asset_class.value,
                    start.date(),
                    end.date(),
                    exc_info=True,
                )
                continue
            if df is not None and not df.empty:
                df = df.copy()
                df.attrs["provider_name"] = candidate_name
                df.attrs["data_source"] = candidate_name
                requested_source = (
                    source_name
                    or self._explicit_default_source
                    or self.source_policy.route(
                        _bar_use_case(asset_class, frequency)
                    ).candidates[0]
                )
                if candidate_name != requested_source:
                    logger.info(
                        "远端数据源 fallback 成功: %s -> %s for %s (%s)",
                        requested_source,
                        candidate_name,
                        symbol,
                        asset_class.value,
                    )
                return df
            empty_sources.append(candidate_name)

        if errors:
            raise errors[-1]
        raise ValueError(
            f"未获取到数据: {symbol} ({asset_class.value}) {start}~{end}; "
            f"unsupported_sources={unsupported_sources}; empty_sources={empty_sources}"
        )

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
        *,
        instrument_type: InstrumentType,
    ) -> bool:
        if not self._targets_recent_range(end, frequency):
            return False
        if refresh_ttl_seconds is None or self.store is None:
            return True

        meta = self.store.get_meta(
            symbol,
            frequency,
            instrument_type=instrument_type,
        )
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
        """Legacy broad-class adapter; authoritative callers must pass a type.

        ``AssetClass.FUND`` cannot distinguish an exchange-traded ETF from an
        open-end fund.  The historical symbol heuristic remains only for old
        backtest adapters; live and persisted-fact paths use
        :meth:`get_instrument_by_type`.
        """
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
        elif asset_class == AssetClass.INDEX:
            return make_index(sym_str, name)
        else:
            raise ValueError(f"不支持的资产类别: {asset_class}")

    @staticmethod
    def get_instrument_by_type(
        symbol: Symbol,
        instrument_type: InstrumentType,
        *,
        name: str | None = None,
    ) -> Instrument:
        """Build an instrument from an unambiguous canonical identity.

        Authoritative valuation and research paths must use this method instead
        of guessing an ETF/open-end-fund distinction from a symbol.
        """

        sym_str = str(symbol).strip()
        if not sym_str:
            raise ValueError("instrument symbol is required")
        display_name = name or sym_str
        if instrument_type is InstrumentType.STOCK:
            return make_stock(sym_str, display_name)
        if instrument_type is InstrumentType.ETF:
            return make_etf(sym_str, display_name)
        if instrument_type is InstrumentType.OPEN_END_FUND:
            return make_open_end_fund(sym_str, display_name)
        if instrument_type is InstrumentType.GOLD:
            return make_gold_spot(symbol=sym_str, name=display_name)
        if instrument_type is InstrumentType.BOND:
            return make_bond(sym_str, display_name)
        if instrument_type is InstrumentType.INDEX:
            return make_index(sym_str, display_name)
        raise ValueError(
            f"authoritative instrument type is unresolved: {instrument_type.value}"
        )
