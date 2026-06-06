"""AKShare 多资产数据适配器。"""

from __future__ import annotations

import json
import re
import logging
import os
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

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
_CHINA_MARKET_TZ = timezone(timedelta(hours=8))
_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


def _looks_like_open_end_fund_code(value: str) -> bool:
    return value.isdigit() and len(value) == 6 and value.startswith("0")


def _row_float(row, *columns: str) -> float | None:
    for column in columns:
        if column not in row.index:
            continue
        value = pd.to_numeric(row.get(column), errors="coerce")
        if not pd.isna(value):
            return float(value)
    return None


def _previous_weekday(value: date) -> date:
    previous = value - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def _date_from_epoch_ms(value) -> str | None:
    if value in {None, ""}:
        return None
    try:
        return (
            datetime.fromtimestamp(float(value) / 1000, tz=_CHINA_MARKET_TZ)
            .date()
            .isoformat()
        )
    except (TypeError, ValueError):
        return None


def _dict_float(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
            return symbol_str if _looks_like_open_end_fund_code(symbol_str) else None
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
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
            )
        df = self._call_with_retry(
            ak.fund_open_fund_info_em,
            symbol=fund_code,
            indicator="单位净值走势",
        )
        if df.empty:
            return pd.DataFrame(
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                ]
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

        if _looks_like_open_end_fund_code(str(symbol).strip()):
            for loader in (
                self._fetch_open_end_fund_latest_from_estimate,
                self._fetch_open_end_fund_latest_from_page,
            ):
                try:
                    snapshot = loader(fund_code)
                except Exception:
                    logger.warning(
                        "AKShare single fund fallback failed for %s",
                        fund_code,
                        exc_info=True,
                    )
                    continue
                if snapshot is not None:
                    return snapshot

        canonical_name = None
        if not _looks_like_open_end_fund_code(str(symbol).strip()):
            canonical_name = self._resolve_open_end_fund_name(symbol)
        try:
            df = self._call_with_retry(ak.fund_open_fund_daily_em)
        except Exception:
            logger.warning(
                "AKShare open-end fund daily table failed for %s; falling back to single fund page",
                fund_code,
                exc_info=True,
            )
            return self._fetch_open_end_fund_latest_from_page(fund_code)
        row = df[df["基金代码"].astype(str) == fund_code]
        if row.empty and canonical_name:
            row = df[df["基金简称"].astype(str).str.strip() == canonical_name]
        if row.empty:
            return self._fetch_open_end_fund_latest_from_page(fund_code)

        row = row.iloc[0]
        if not canonical_name and "基金简称" in row.index:
            name_value = str(row["基金简称"]).strip()
            canonical_name = name_value or None
        nav_columns = sorted(
            (str(column) for column in row.index if str(column).endswith("-单位净值")),
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

    def _fetch_open_end_fund_latest_from_estimate(self, fund_code: str) -> dict | None:
        import requests

        url = f"http://fundgz.1234567.com.cn/js/{fund_code}.js"
        with _provider_network_env():
            response = requests.get(url, timeout=3)
        response.raise_for_status()
        match = re.search(r"jsonpgz\((\{.*\})\);?", response.text, flags=re.S)
        if match is None:
            return None

        payload = json.loads(match.group(1))
        price = _dict_float(payload, "gsz") or _dict_float(payload, "dwjz")
        if price is None:
            return None

        previous_close = _dict_float(payload, "dwjz")
        result = {
            "price": price,
            "volume": None,
            "timestamp": str(payload.get("gztime") or payload.get("jzrq") or ""),
            "source": "akshare",
            "quote_source": "eastmoney_fund_estimate",
        }
        display_name = str(payload.get("name") or "").strip()
        if display_name:
            result["name"] = display_name
            result["display_name"] = display_name
        if previous_close is not None:
            result["previous_close"] = previous_close
            result["previous_close_date"] = str(payload.get("jzrq") or "")
            result["day_change_value"] = price - previous_close
        growth_rate = _dict_float(payload, "gszzl")
        if growth_rate is not None:
            result["day_change_pct"] = growth_rate / 100
        return result

    def _fetch_open_end_fund_latest_from_page(self, fund_code: str) -> dict | None:
        import requests

        url = f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
        with _provider_network_env():
            response = requests.get(url, timeout=3)
        response.raise_for_status()
        text = response.text

        name_match = re.search(r'fS_name\s*=\s*"([^"]+)"', text)
        trend_match = re.search(
            r"Data_netWorthTrend\s*=\s*(\[.*?\]);",
            text,
            flags=re.S,
        )
        if trend_match is None:
            return None

        trend = json.loads(trend_match.group(1))
        if not trend:
            return None
        latest = trend[-1]
        previous = trend[-2] if len(trend) > 1 else {}
        price = _dict_float(latest, "y")
        if price is None:
            return None

        payload = {
            "price": price,
            "volume": None,
            "timestamp": _date_from_epoch_ms(latest.get("x")),
            "source": "akshare",
            "quote_source": "eastmoney_fund_page",
        }
        if name_match:
            display_name = name_match.group(1).strip()
            if display_name:
                payload["name"] = display_name
                payload["display_name"] = display_name

        previous_close = _dict_float(previous, "y")
        if previous_close is not None:
            payload["previous_close"] = previous_close
            payload["previous_close_date"] = _date_from_epoch_ms(previous.get("x"))
            payload["day_change_value"] = price - previous_close
        growth_rate = _dict_float(latest, "equityReturn")
        if growth_rate is not None:
            payload["day_change_pct"] = growth_rate / 100
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
            if asset_class == AssetClass.FUND and self._resolve_open_end_fund_code(
                symbol
            ):
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

        if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(
            df.columns
        ):
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
                previous_close = _row_float(row, "昨收", "昨收价", "昨日收盘")
                change = _row_float(row, "涨跌额")
                change_percent = _row_float(row, "涨跌幅")
                if previous_close is not None:
                    payload["previous_close"] = previous_close
                    payload["previous_close_date"] = _previous_weekday(
                        datetime.now().date()
                    ).isoformat()
                if change is not None:
                    payload["change"] = change
                if change_percent is not None:
                    payload["change_percent"] = change_percent / 100
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
