"""AKShare 多资产数据适配器。"""

from __future__ import annotations

import logging
from functools import lru_cache
from datetime import datetime

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource

logger = logging.getLogger(__name__)

# 资产类别 → (日线函数名, 列名映射, 是否有成交量)
_HIST_CONFIG: dict[AssetClass, tuple[str, dict, bool]] = {
    AssetClass.STOCK: (
        "stock_zh_a_hist",
        {
            "日期": "timestamp",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        },
        True,
    ),
    AssetClass.FUND: (
        "fund_etf_hist_em",
        {
            "日期": "timestamp",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        },
        True,
    ),
    AssetClass.GOLD: (
        "spot_hist_sge",
        {
            "date": "timestamp",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
        },
        False,
    ),
    AssetClass.BOND: (
        "bond_zh_hs_daily",
        {
            "date": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
        },
        False,
    ),
}


class AKShareSource(DataSource):
    """AKShare 多资产数据源适配器。

    根据 asset_class 调用不同的 AKShare 函数，统一列名映射。
    """

    _MAX_RETRIES = 3
    _RETRY_DELAY = 2  # seconds

    @staticmethod
    @lru_cache(maxsize=1)
    def _open_end_fund_name_map() -> dict[str, str]:
        import akshare as ak

        df = ak.fund_name_em()
        mapping: dict[str, str] = {}
        if "基金简称" not in df.columns or "基金代码" not in df.columns:
            return mapping
        for _, row in df.iterrows():
            name = str(row["基金简称"]).strip()
            code = str(row["基金代码"]).strip()
            if name and code:
                mapping[name] = code
        return mapping

    def _resolve_open_end_fund_code(self, symbol: Symbol) -> str | None:
        symbol_str = str(symbol).strip()
        if symbol_str[:1].isdigit():
            return symbol_str
        return self._open_end_fund_name_map().get(symbol_str)

    def _call_with_retry(self, func, **kwargs):
        """带重试的 AKShare API 调用。"""
        import time

        last_error = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return func(**kwargs)
            except Exception as e:
                last_error = e
                if attempt < self._MAX_RETRIES - 1:
                    logger.warning(
                        "AKShare 调用失败 (第%d次), %ds 后重试: %s",
                        attempt + 1,
                        self._RETRY_DELAY,
                        e,
                    )
                    time.sleep(self._RETRY_DELAY)
        raise last_error

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        import akshare as ak

        # 分钟线 — 仅支持 A股/ETF
        if frequency in (BarFrequency.MIN_1, BarFrequency.MIN_5):
            return self._fetch_minute_bars(
                ak, symbol, start, end, frequency, asset_class
            )

        if frequency != BarFrequency.DAILY:
            raise NotImplementedError(
                f"AKShare does not support frequency: {frequency}"
            )

        config = _HIST_CONFIG.get(asset_class)
        if config is None:
            raise NotImplementedError(
                f"AKShare does not support asset class: {asset_class}"
            )

        func_name, col_map, has_volume = config
        func = getattr(ak, func_name)

        # A股/ETF 支持日期范围参数；黄金/债券需全量拉取后过滤
        if asset_class in (AssetClass.STOCK, AssetClass.FUND):
            if asset_class == AssetClass.FUND and not str(symbol)[:1].isdigit():
                fund_code = self._resolve_open_end_fund_code(symbol)
                if not fund_code:
                    return pd.DataFrame(
                        columns=["timestamp", "open", "high", "low", "close", "volume", "amount"]
                    )
                df = self._call_with_retry(
                    ak.fund_open_fund_info_em,
                    symbol=fund_code,
                    indicator="单位净值走势",
                )
                if df.empty:
                    return pd.DataFrame(
                        columns=["timestamp", "open", "high", "low", "close", "volume", "amount"]
                    )
                df = df.rename(
                    columns={
                        "净值日期": "timestamp",
                        "单位净值": "close",
                    }
                )
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df["open"] = pd.to_numeric(df["close"], errors="coerce")
                df["high"] = pd.to_numeric(df["close"], errors="coerce")
                df["low"] = pd.to_numeric(df["close"], errors="coerce")
                df["volume"] = 0.0
                df["amount"] = 0.0
            else:
                df = self._call_with_retry(
                    func,
                    symbol=str(symbol),
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
        else:
            # 黄金/债券：全量拉取
            df = self._call_with_retry(func, symbol=str(symbol))

        if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(df.columns):
            df = self._normalize_bars(df, col_map, has_volume)

        # 按日期范围过滤
        if "timestamp" in df.columns and len(df) > 0:
            df = df[
                (df["timestamp"] >= pd.Timestamp(start))
                & (df["timestamp"] <= pd.Timestamp(end))
            ]

        return df.reset_index(drop=True)

    def _fetch_minute_bars(
        self,
        ak,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency,
        asset_class: AssetClass,
    ) -> pd.DataFrame:
        """获取分钟线数据（仅 A股/ETF）。"""
        if asset_class == AssetClass.STOCK:
            func = ak.stock_zh_a_hist_min_em
        elif asset_class == AssetClass.FUND:
            func = ak.fund_etf_hist_min_em
        else:
            raise NotImplementedError(f"Minute bars not supported for {asset_class}")

        period = "1" if frequency == BarFrequency.MIN_1 else "5"
        df = self._call_with_retry(func, symbol=str(symbol), period=period)

        col_map = {
            "时间": "timestamp",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
        }
        df = self._normalize_bars(df, col_map, has_volume=True)

        if "timestamp" in df.columns and len(df) > 0:
            df = df[
                (df["timestamp"] >= pd.Timestamp(start))
                & (df["timestamp"] <= pd.Timestamp(end))
            ]

        return df.reset_index(drop=True)

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        raise NotImplementedError("AKShare tick data not supported")

    def list_symbols(self) -> list[Symbol]:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        return [Symbol(str(code)) for code in df["代码"].tolist()]

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        """获取最新行情快照。"""
        import akshare as ak

        try:
            if asset_class == AssetClass.STOCK:
                df = self._call_with_retry(ak.stock_zh_a_spot_em)
                row = df[df["代码"] == str(symbol)]
                if row.empty:
                    return None
                row = row.iloc[0]
                return {
                    "price": float(row["最新价"]),
                    "volume": float(row["成交额"]) if "成交额" in row else None,
                    "timestamp": str(row.get("时间", "")),
                }

            elif asset_class == AssetClass.FUND:
                if str(symbol)[:1].isdigit():
                    df = self._call_with_retry(ak.fund_etf_spot_em)
                    row = df[df["代码"] == str(symbol)]
                    if row.empty:
                        return None
                    row = row.iloc[0]
                    return {
                        "price": float(row["最新价"]),
                        "volume": float(row["成交额"]) if "成交额" in row else None,
                        "timestamp": str(row.get("时间", "")),
                    }

                fund_code = self._resolve_open_end_fund_code(symbol)
                if not fund_code:
                    return None
                df = self._call_with_retry(ak.fund_open_fund_daily_em)
                row = df[
                    (df["基金代码"].astype(str) == fund_code)
                    | (df["基金简称"].astype(str).str.strip() == str(symbol).strip())
                ]
                if row.empty:
                    return None
                row = row.iloc[0]
                nav_column = next(
                    (
                        column
                        for column in row.index
                        if str(column).endswith("-单位净值")
                    ),
                    None,
                )
                if nav_column is None:
                    return None
                price = pd.to_numeric(row[nav_column], errors="coerce")
                if pd.isna(price):
                    return None
                trade_day = str(nav_column).replace("-单位净值", "")
                return {
                    "price": float(price),
                    "volume": None,
                    "timestamp": trade_day,
                }

            elif asset_class == AssetClass.GOLD:
                df = self._call_with_retry(ak.spot_quotations_sge, symbol=str(symbol))
                if df.empty:
                    return None
                row = df.iloc[0]
                return {
                    "price": (
                        float(row["最新价"]) if "最新价" in row else float(row.iloc[0])
                    ),
                    "volume": None,
                    "timestamp": str(row.get("时间", "")),
                }

            elif asset_class == AssetClass.BOND:
                df = self._call_with_retry(ak.bond_zh_hs_spot)
                row = df[df["代码"] == str(symbol)]
                if row.empty:
                    return None
                row = row.iloc[0]
                return {
                    "price": (
                        float(row["最新价"]) if "最新价" in row else float(row.iloc[0])
                    ),
                    "volume": None,
                    "timestamp": str(row.get("时间", "")),
                }

        except Exception:
            logger.exception("fetch_latest failed for %s (%s)", symbol, asset_class)
            return None

        return None

    @staticmethod
    def _normalize_bars(
        df: pd.DataFrame,
        col_map: dict,
        has_volume: bool = True,
    ) -> pd.DataFrame:
        """将 AKShare 返回的列名映射到统一格式。"""
        # 只映射存在的列
        existing = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing)

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        if not has_volume:
            df["volume"] = 0
            df["amount"] = 0

        # 确保关键列存在且为 float
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df
