"""Open-end-fund workflows for the AKShare data adapter."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from functools import lru_cache

import pandas as pd

from core.types import AssetClass, Symbol
from data.providers.akshare_support import CHINA_MARKET_TZ as _CHINA_MARKET_TZ
from data.providers.akshare_support import OPEN_END_FUND_NOISE as _OPEN_END_FUND_NOISE
from data.providers.akshare_support import date_from_epoch_ms as _date_from_epoch_ms
from data.providers.akshare_support import dict_float as _dict_float
from data.providers.akshare_support import (
    looks_like_open_end_fund_code as _looks_like_open_end_fund_code,
)
from data.providers.akshare_support import provider_network_env as _provider_network_env

logger = logging.getLogger("data.providers.akshare_source")


class OpenEndFundMixin:
    """Resolve and fetch exchange-unlisted open-end fund NAV evidence."""

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

        url = (
            "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/"
            "FdFundService.getEstimateNetworthPic"
        )
        with _provider_network_env():
            response = requests.get(url, params={"symbol": fund_code}, timeout=3)
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return None
        status = result.get("status")
        if not isinstance(status, dict) or status.get("code") != 0:
            return None

        data = result.get("data")
        if not isinstance(data, dict):
            return None
        raw_points = data.get("networth")
        if not isinstance(raw_points, list):
            return None

        session_close = None
        time_ranges = data.get("time_range")
        if isinstance(time_ranges, list):
            session_ends = [
                str(period[-1]).strip()
                for period in time_ranges
                if isinstance(period, list) and period and str(period[-1]).strip()
            ]
            if session_ends:
                session_close = max(session_ends)

        estimates: list[tuple[datetime, dict]] = []
        for point in raw_points:
            if not isinstance(point, dict):
                continue
            estimate_date = str(point.get("pre_date") or "").strip()
            estimate_time = str(point.get("min_time") or "").strip()
            if not estimate_date or not estimate_time:
                continue
            if session_close and estimate_time[:5] > session_close[:5]:
                continue
            try:
                estimate_timestamp = datetime.fromisoformat(
                    f"{estimate_date}T{estimate_time}"
                ).replace(tzinfo=_CHINA_MARKET_TZ)
            except ValueError:
                continue
            if _dict_float(point, "pre_nav") is None:
                continue
            estimates.append((estimate_timestamp, point))
        if not estimates:
            return None

        estimate_timestamp, latest = max(estimates, key=lambda item: item[0])
        price = _dict_float(latest, "pre_nav")
        if price is None:
            return None
        previous_close = _dict_float(data, "worth")
        previous_close_date = str(data.get("worth_date") or "").strip()
        if len(previous_close_date) == 8 and previous_close_date.isdigit():
            previous_close_date = (
                f"{previous_close_date[:4]}-{previous_close_date[4:6]}-"
                f"{previous_close_date[6:]}"
            )

        snapshot = {
            "price": price,
            "volume": None,
            "timestamp": estimate_timestamp.isoformat(),
            "source": "sina",
            "provider_name": "sina",
            "quote_source": "sina_fund_estimate",
            "metadata": {
                "estimate_model": "pre_nav",
                "session_close": session_close,
            },
        }
        if previous_close is not None:
            snapshot["previous_close"] = previous_close
            snapshot["day_change_value"] = price - previous_close
        if previous_close_date:
            snapshot["previous_close_date"] = previous_close_date
            snapshot["nav_date"] = previous_close_date
        growth_rate = _dict_float(latest, "nav_pct")
        if growth_rate is not None:
            snapshot["day_change_pct"] = growth_rate / 100
        return snapshot

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

    def fetch_confirmed_fund_nav(self, symbol: Symbol) -> dict | None:
        """Fetch the latest published open-end fund NAV, never an estimate."""
        fund_code = self._resolve_open_end_fund_code(symbol)
        if not fund_code:
            return None

        snapshot = self._fetch_open_end_fund_latest_from_page(fund_code)
        if snapshot is None:
            return None

        nav_date = str(snapshot.get("timestamp") or "").strip()
        try:
            published_date = datetime.fromisoformat(
                nav_date.replace("Z", "+00:00")
            ).date()
        except ValueError:
            return None
        snapshot["timestamp"] = datetime.combine(
            published_date,
            datetime.min.time().replace(hour=15),
            tzinfo=_CHINA_MARKET_TZ,
        ).isoformat()
        snapshot["nav_date"] = published_date.isoformat()
        snapshot["source"] = "akshare"
        snapshot["quote_source"] = "eastmoney_fund_page"

        normalized = self._normalize_latest_quote(
            symbol,
            AssetClass.FUND,
            snapshot,
            provider_symbol=fund_code,
        )
        if normalized is not None:
            normalized["nav_date"] = published_date.isoformat()
        return normalized
