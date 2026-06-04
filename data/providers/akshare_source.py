"""AKShare 多资产数据适配器。"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
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

_OPEN_END_FUND_NOISE = ("发起式", "发起", "A类", "C类", "（", "）", "(", ")", " ")
_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


def _provider_uses_proxy() -> bool:
    value = os.environ.get("KARKINOS_PROVIDER_USE_PROXY", "")
    return value.lower() in {"1", "true", "yes", "on"}


@contextmanager
def _provider_network_env():
    """Keep provider calls from inheriting broken local proxy settings by default."""
    if _provider_uses_proxy():
        yield
        return

    original = {key: os.environ.get(key) for key in _PROXY_ENV_KEYS}
    for key in _PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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

        with _provider_network_env():
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

    @staticmethod
    def _normalize_open_end_fund_name(name: str) -> str:
        normalized = str(name).strip()
        for token in _OPEN_END_FUND_NOISE:
            normalized = normalized.replace(token, "")
        return normalized

    @classmethod
    def _open_end_fund_alias_map(cls) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for name, code in cls._open_end_fund_name_map().items():
            aliases.setdefault(name, code)
            normalized = cls._normalize_open_end_fund_name(name)
            if normalized:
                aliases.setdefault(normalized, code)
        return aliases

    def _resolve_open_end_fund_name(self, symbol: Symbol) -> str | None:
        symbol_str = str(symbol).strip()
        name_map = self._open_end_fund_name_map()
        if symbol_str in name_map:
            return symbol_str
        fund_code = self._resolve_open_end_fund_code(symbol)
        if not fund_code:
            return None
        for name, code in name_map.items():
            if code == fund_code:
                return name
        return None

    def _resolve_open_end_fund_code(self, symbol: Symbol) -> str | None:
        symbol_str = str(symbol).strip()
        if symbol_str[:1].isdigit():
            if symbol_str in set(self._open_end_fund_name_map().values()):
                return symbol_str
            return None
        if code := self._open_end_fund_name_map().get(symbol_str):
            return code
        normalized = self._normalize_open_end_fund_name(symbol_str)
        if not normalized:
            return None
        return self._open_end_fund_alias_map().get(normalized)

    def _fetch_open_end_fund_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        import akshare as ak

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
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["open"] = df["close"]
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0.0
        df["amount"] = 0.0
        return df[
            (df["timestamp"] >= pd.Timestamp(start))
            & (df["timestamp"] <= pd.Timestamp(end))
        ].reset_index(drop=True)

    def _fetch_open_end_fund_latest(self, symbol: Symbol) -> dict | None:
        import akshare as ak

        fund_code = self._resolve_open_end_fund_code(symbol)
        if not fund_code:
            return None

        canonical_name = self._resolve_open_end_fund_name(symbol)
        df = self._call_with_retry(ak.fund_open_fund_daily_em)
        row = df[df["基金代码"].astype(str) == fund_code]
        if row.empty and canonical_name:
            row = df[df["基金简称"].astype(str).str.strip() == canonical_name]
        if row.empty:
            return None

        row = row.iloc[0]
        nav_columns = sorted(
            (
                str(column)
                for column in row.index
                if str(column).endswith("-单位净值")
            ),
            reverse=True,
        )
        if not nav_columns:
            return None
        nav_column = nav_columns[0]
        price = pd.to_numeric(row[nav_column], errors="coerce")
        if pd.isna(price):
            return None
        trade_day = str(nav_column).replace("-单位净值", "")
        payload = {
            "price": float(price),
            "volume": None,
            "timestamp": trade_day,
        }
        if canonical_name:
            payload["name"] = canonical_name
            payload["display_name"] = canonical_name
        if len(nav_columns) > 1:
            previous_nav_column = nav_columns[1]
            previous_close = pd.to_numeric(row[previous_nav_column], errors="coerce")
            if not pd.isna(previous_close):
                payload["previous_close"] = float(previous_close)
                payload["previous_close_date"] = str(previous_nav_column).replace(
                    "-单位净值", ""
                )
        growth_rate = pd.to_numeric(row.get("日增长率"), errors="coerce")
        growth_value = pd.to_numeric(row.get("日增长值"), errors="coerce")
        if not pd.isna(growth_rate):
            payload["day_change_pct"] = float(growth_rate) / 100
        if not pd.isna(growth_value):
            payload["day_change_value"] = float(growth_value)
        return payload

    def _call_with_retry(self, func, **kwargs):
        """带重试的 AKShare API 调用。"""
        import time

        last_error = None
        for attempt in range(self._MAX_RETRIES):
            try:
                with _provider_network_env():
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
            if asset_class == AssetClass.FUND and self._resolve_open_end_fund_code(symbol):
                df = self._fetch_open_end_fund_bars(symbol, start, end)
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

        with _provider_network_env():
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
                payload = {
                    "price": float(row["最新价"]),
                    "volume": float(row["成交额"]) if "成交额" in row else None,
                    "timestamp": str(row.get("时间", "")),
                }
                if "名称" in row and str(row["名称"]).strip():
                    payload["name"] = str(row["名称"]).strip()
                    payload["display_name"] = str(row["名称"]).strip()
                return payload

            elif asset_class == AssetClass.FUND:
                if open_end_snapshot := self._fetch_open_end_fund_latest(symbol):
                    return open_end_snapshot

                df = self._call_with_retry(ak.fund_etf_spot_em)
                row = df[df["代码"] == str(symbol)]
                if row.empty:
                    return None
                row = row.iloc[0]
                payload = {
                    "price": float(row["最新价"]),
                    "volume": float(row["成交额"]) if "成交额" in row else None,
                    "timestamp": str(row.get("时间", "")),
                }
                if "名称" in row and str(row["名称"]).strip():
                    payload["name"] = str(row["名称"]).strip()
                    payload["display_name"] = str(row["名称"]).strip()
                return payload

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
