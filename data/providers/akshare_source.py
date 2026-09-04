"""AKShare 多资产数据适配器。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.providers.akshare_open_end_funds import OpenEndFundMixin
from data.providers.akshare_support import CHINA_MARKET_TZ as _CHINA_MARKET_TZ
from data.providers.akshare_support import previous_weekday as _previous_weekday
from data.providers.akshare_support import provider_network_env as _provider_network_env
from data.providers.akshare_support import row_float as _row_float
from data.source import DataSource, normalize_provider_quote

logger = logging.getLogger(__name__)


def _clean_stock_master_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    return normalized or None


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
    AssetClass.INDEX: (
        "index_zh_a_hist",
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
}


class AKShareSource(OpenEndFundMixin, DataSource):
    """AKShare 多资产数据源适配器。

    根据 asset_class 调用不同的 AKShare 函数，统一列名映射。
    """

    _MAX_RETRIES = 3
    _RETRY_DELAY = 2  # seconds

    @staticmethod
    def _stock_bid_ask_payload(
        frame: pd.DataFrame,
        *,
        observed_at: datetime,
    ) -> dict | None:
        """Normalize AKShare's single-stock quote response.

        ``stock_zh_a_spot_em`` downloads the complete A-share market and is not
        suitable for one request per watched symbol.  The single-stock endpoint
        has no exchange timestamp, so the client observation time is explicit in
        both the quote timestamp and metadata instead of being presented as a
        provider-supplied timestamp.
        """

        if (
            frame is None
            or frame.empty
            or not {"item", "value"}.issubset(frame.columns)
        ):
            return None
        values = pd.Series(
            {
                str(row["item"]): row["value"]
                for _, row in frame[["item", "value"]].iterrows()
            }
        )
        price = _row_float(values, "最新")
        if price is None or price <= 0:
            return None
        total_lots = _row_float(values, "总手")
        previous_close = _row_float(values, "昨收")
        change = _row_float(values, "涨跌")
        change_percent = _row_float(values, "涨幅")
        payload: dict[str, object] = {
            "price": price,
            "volume": None if total_lots is None else total_lots * 100,
            "turnover": _row_float(values, "金额"),
            "timestamp": observed_at.isoformat(timespec="seconds"),
            "quote_source": "akshare_stock_bid_ask",
            "metadata": {
                "timestamp_source": "client_observed_at",
                "provider_timestamp_available": False,
            },
        }
        if previous_close is not None:
            payload["previous_close"] = previous_close
            # This endpoint identifies the value as yesterday's close but does
            # not identify the owning trading session. A weekday guess is not
            # authoritative across exchange holidays, so leave the date
            # unclaimed until calendar-backed evidence can bind it.
        if change is not None:
            payload["change"] = change
        if change_percent is not None:
            payload["change_percent"] = change_percent / 100
        return payload

    def supports_bars(
        self,
        asset_class: AssetClass = AssetClass.STOCK,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> bool:
        if frequency == BarFrequency.DAILY:
            return asset_class in _HIST_CONFIG
        if frequency in (BarFrequency.MIN_1, BarFrequency.MIN_5):
            return asset_class in (AssetClass.STOCK, AssetClass.FUND)
        return False

    def _call_with_retry(
        self,
        func,
        *,
        retry_delay_seconds: float | None = None,
        **kwargs,
    ):
        """带重试的 AKShare API 调用。"""
        import time

        retry_delay = (
            self._RETRY_DELAY
            if retry_delay_seconds is None
            else max(float(retry_delay_seconds), 0.0)
        )
        last_error = None
        for attempt in range(self._MAX_RETRIES):
            try:
                with _provider_network_env():
                    return func(**kwargs)
            except Exception as e:
                last_error = e
                if attempt < self._MAX_RETRIES - 1:
                    logger.warning(
                        "AKShare 调用失败 (第%d次), %.3fs 后重试: %s",
                        attempt + 1,
                        retry_delay,
                        e,
                    )
                    if retry_delay:
                        time.sleep(retry_delay)
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

        # A股/ETF/指数支持日期范围参数；黄金/债券需全量拉取后过滤
        if asset_class in (AssetClass.STOCK, AssetClass.FUND, AssetClass.INDEX):
            if asset_class == AssetClass.FUND and self._resolve_open_end_fund_code(
                symbol
            ):
                df = self._fetch_open_end_fund_bars(symbol, start, end)
            elif asset_class == AssetClass.INDEX:
                df = self._call_with_retry(
                    func,
                    symbol=str(symbol),
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                )
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
        return [
            Symbol(str(item["symbol"])) for item in self.list_symbol_metadata() or []
        ]

    def list_symbol_metadata(self) -> list[dict[str, object]]:
        """Return codes and names from the same AKShare stock-master response."""
        import akshare as ak

        with _provider_network_env():
            df = ak.stock_zh_a_spot_em()
        rows: list[dict[str, object]] = []
        for _, row in df.iterrows():
            symbol = _clean_stock_master_text(row.get("代码"))
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "asset_class": AssetClass.STOCK.value,
                    "display_name": _clean_stock_master_text(row.get("名称")),
                    "provider_symbol": symbol,
                    "provider_name": "akshare",
                    "market": "cn",
                    "source": "stock_master",
                }
            )
        return rows

    @staticmethod
    def _latest_completed_index_daily_row(
        ak,
        symbol: Symbol,
        *,
        display_name: str | None,
        now: datetime | None = None,
    ):
        current = now or datetime.now(_CHINA_MARKET_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=_CHINA_MARKET_TZ)
        completed_date = current.date()
        if (current.hour, current.minute) < (15, 0):
            completed_date -= timedelta(days=1)
        provider_symbol = (
            f"sz{symbol}" if str(symbol).startswith("399") else f"sh{symbol}"
        )
        start_date = (completed_date - timedelta(days=14)).strftime("%Y%m%d")
        end_date = completed_date.strftime("%Y%m%d")
        with _provider_network_env():
            daily = ak.stock_zh_index_daily_tx(
                symbol=provider_symbol,
                start_date=start_date,
                end_date=end_date,
            )
        if daily.empty or not {"date", "close"}.issubset(daily.columns):
            return None
        rows = daily.copy()
        rows["date"] = pd.to_datetime(rows["date"], errors="coerce").dt.date
        rows = rows[rows["date"] <= completed_date].sort_values("date")
        if rows.empty:
            return None
        latest = rows.iloc[-1]
        previous = rows.iloc[-2] if len(rows) > 1 else None
        latest_close = float(latest["close"])
        previous_close = None if previous is None else float(previous["close"])
        payload = {
            "代码": provider_symbol,
            "名称": display_name,
            "最新价": latest_close,
            "成交额": _row_float(latest, "amount", "volume"),
            "时间": datetime.combine(
                latest["date"],
                datetime.min.time().replace(hour=15),
                tzinfo=_CHINA_MARKET_TZ,
            ).isoformat(),
        }
        if previous_close is not None:
            change = latest_close - previous_close
            payload.update(
                {
                    "昨收": previous_close,
                    "涨跌额": change,
                    "涨跌幅": (
                        0.0 if previous_close == 0 else change / previous_close * 100
                    ),
                }
            )
        return pd.Series(payload)

    @classmethod
    def _fetch_index_latest_row(cls, ak, symbol: Symbol):
        """Return one index row from bounded, vendor-diverse AKShare feeds."""
        symbol_text = str(symbol)
        provider_symbol = (
            f"sz{symbol_text}" if symbol_text.startswith("399") else f"sh{symbol_text}"
        )
        provisional_sina_row = None
        try:
            with _provider_network_env():
                sina = ak.stock_zh_index_spot_sina()
            rows = sina[sina["代码"].astype(str) == provider_symbol]
            if not rows.empty:
                provisional_sina_row = rows.iloc[0]
                daily_row = cls._latest_completed_index_daily_row(
                    ak,
                    symbol,
                    display_name=(
                        str(provisional_sina_row.get("名称") or "").strip() or None
                    ),
                )
                if daily_row is not None:
                    return daily_row, "akshare_index_daily_tx"
        except Exception as exc:
            logger.warning(
                "AKShare Sina index evidence failed for %s; trying Eastmoney: %s",
                symbol_text,
                exc,
            )

        index_series = (
            "深证系列指数" if symbol_text.startswith("399") else "上证系列指数"
        )
        try:
            with _provider_network_env():
                eastmoney = ak.stock_zh_index_spot_em(symbol=index_series)
            rows = eastmoney[eastmoney["代码"].astype(str) == symbol_text]
            if not rows.empty:
                return rows.iloc[0], "akshare_index_spot_em"
        except Exception as exc:
            logger.warning(
                "AKShare Eastmoney index spot failed for %s: %s",
                symbol_text,
                exc,
            )
        if provisional_sina_row is not None:
            return provisional_sina_row, "akshare_index_spot_sina"
        return None

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        """获取最新行情快照。"""
        import akshare as ak

        try:
            if asset_class == AssetClass.STOCK:
                frame = self._call_with_retry(
                    ak.stock_bid_ask_em,
                    symbol=str(symbol),
                    retry_delay_seconds=0,
                )
                observed_at = datetime.now(_CHINA_MARKET_TZ)
                payload = self._stock_bid_ask_payload(
                    frame,
                    observed_at=observed_at,
                )
                if payload is None:
                    return None
                return self._normalize_latest_quote(symbol, asset_class, payload)

            elif asset_class == AssetClass.FUND:
                if open_end_snapshot := self._fetch_open_end_fund_latest(symbol):
                    return self._normalize_latest_quote(
                        symbol,
                        asset_class,
                        open_end_snapshot,
                        provider_symbol=self._resolve_open_end_fund_code(symbol),
                    )

                df = self._call_with_retry(ak.fund_etf_spot_em)
                row = df[df["代码"] == str(symbol)]
                if row.empty:
                    return None
                row = row.iloc[0]
                payload = {
                    "price": float(row["最新价"]),
                    "volume": float(row["成交额"]) if "成交额" in row else None,
                    "timestamp": str(row.get("时间", "")),
                    "quote_source": "akshare_fund_etf_spot",
                }
                if "名称" in row and str(row["名称"]).strip():
                    payload["name"] = str(row["名称"]).strip()
                    payload["display_name"] = str(row["名称"]).strip()
                return self._normalize_latest_quote(symbol, asset_class, payload)

            elif asset_class == AssetClass.GOLD:
                df = self._call_with_retry(ak.spot_quotations_sge, symbol=str(symbol))
                if df.empty:
                    return None
                row = df.iloc[0]
                return self._normalize_latest_quote(
                    symbol,
                    asset_class,
                    {
                        "price": (
                            float(row["最新价"])
                            if "最新价" in row
                            else float(row.iloc[0])
                        ),
                        "volume": None,
                        "timestamp": str(row.get("时间", "")),
                        "quote_source": "akshare_sge_spot",
                    },
                )

            elif asset_class == AssetClass.BOND:
                df = self._call_with_retry(ak.bond_zh_hs_spot)
                row = df[df["代码"] == str(symbol)]
                if row.empty:
                    return None
                row = row.iloc[0]
                return self._normalize_latest_quote(
                    symbol,
                    asset_class,
                    {
                        "price": (
                            float(row["最新价"])
                            if "最新价" in row
                            else float(row.iloc[0])
                        ),
                        "volume": None,
                        "timestamp": str(row.get("时间", "")),
                        "quote_source": "akshare_bond_spot",
                    },
                )

            elif asset_class == AssetClass.INDEX:
                index_result = self._fetch_index_latest_row(ak, symbol)
                if index_result is None:
                    return None
                row, quote_source = index_result
                payload = {
                    "price": float(row["最新价"]),
                    "volume": _row_float(row, "成交额", "成交量"),
                    "timestamp": str(row.get("时间", "")),
                    "quote_source": quote_source,
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
                return self._normalize_latest_quote(symbol, asset_class, payload)

        except Exception:
            logger.exception("fetch_latest failed for %s (%s)", symbol, asset_class)
            return None

        return None

    @staticmethod
    def _normalize_latest_quote(
        symbol: Symbol,
        asset_class: AssetClass,
        payload: dict | None,
        provider_symbol: str | None = None,
    ) -> dict | None:
        quote = normalize_provider_quote(
            symbol,
            asset_class,
            payload,
            provider_name="akshare",
            provider_symbol=provider_symbol or str(symbol),
        )
        return None if quote is None else quote.to_payload()

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
