"""Tencent market data provider for realtime quotes and daily bars."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from core.types import AssetClass, BarFrequency, InstrumentType, Symbol
from data.market.contracts import (
    DailyBarCapability,
    DailyBarRequest,
    MarketDataProviderDescriptor,
    ProviderDailyBarBatch,
)
from data.providers.akshare_tencent_daily import (
    AkshareTencentDailyBarProvider,
    _AkshareTencentClient,
)
from data.source import DataSource, ProviderQuote

logger = logging.getLogger(__name__)

_CHINA_MARKET_TZ = ZoneInfo("Asia/Shanghai")

TENCENT_DAILY_BAR_ADAPTER_VERSION = "karkinos.tencent.daily_bar.v1"
TENCENT_DAILY_BAR_PAYLOAD_FORMAT = "tencent.stock_zh_a_hist_tx.dataframe.v1"
TENCENT_DAILY_BAR_DESCRIPTOR = MarketDataProviderDescriptor(
    provider="tencent",
    upstream_group="tencent",
    adapter_version=TENCENT_DAILY_BAR_ADAPTER_VERSION,
    daily_bar_capabilities=(
        DailyBarCapability(
            endpoint="stock_zh_a_hist_tx",
            instrument_types=(InstrumentType.STOCK, InstrumentType.ETF),
            price_basis="unadjusted",
        ),
    ),
)


def resolve_tencent_market_prefix(symbol: Symbol | str, asset_class: AssetClass) -> str:
    """Resolve Tencent quote prefix ('sh', 'sz', 'bj') for a given symbol."""
    sym = str(symbol).strip()
    if asset_class == AssetClass.INDEX:
        if sym.startswith(("399",)):
            return "sz"
        return "sh"

    if sym.startswith(("4", "8", "920")):
        return "bj"
    if sym.startswith(("6", "9", "5", "7")):
        return "sh"
    if sym.startswith(("0", "3", "1", "2")):
        return "sz"
    return "sh"


def fetch_tencent_realtime_quote(
    symbol: Symbol | str,
    asset_class: AssetClass = AssetClass.STOCK,
    *,
    timeout_seconds: float = 3.0,
) -> dict[str, Any] | None:
    """Fetch realtime quote directly from Tencent official quote endpoint (qt.gtimg.cn).

    High-availability, ultra-low latency (<50ms), zero authentication required.
    """
    sym = str(symbol).strip()
    if not sym:
        return None

    prefix = resolve_tencent_market_prefix(sym, asset_class)
    tencent_code = f"{prefix}{sym}"
    url = f"http://qt.gtimg.cn/q={tencent_code}"

    try:
        resp = requests.get(url, timeout=max(float(timeout_seconds), 0.1))
        resp.encoding = "gbk"
        text = resp.text.strip()
        if "~" not in text:
            return None
        parts = text.split("~")
        if len(parts) <= 32:
            return None

        price = float(parts[3])
        if price <= 0:
            return None

        name = str(parts[1]).strip() or None
        prev_close = float(parts[4]) if parts[4] else None
        lots = float(parts[6]) if parts[6] else None
        time_str = parts[30]
        if len(time_str) == 14:
            try:
                dt = datetime.strptime(time_str, "%Y%m%d%H%M%S").replace(
                    tzinfo=_CHINA_MARKET_TZ
                )
            except ValueError:
                dt = datetime.now(_CHINA_MARKET_TZ)
        else:
            dt = datetime.now(_CHINA_MARKET_TZ)

        change = float(parts[31]) if parts[31] else None
        pct = float(parts[32]) / 100.0 if parts[32] else None
        amount = (
            float(parts[57]) * 10000.0
            if len(parts) > 57 and parts[57]
            else (float(parts[37]) * 10000.0 if len(parts) > 37 and parts[37] else None)
        )

        volume = None
        if lots is not None:
            volume = lots if asset_class == AssetClass.INDEX else lots * 100.0

        quote = ProviderQuote(
            symbol=sym,
            asset_class=asset_class,
            provider_name="tencent",
            provider_symbol=tencent_code,
            price=price,
            timestamp=dt.isoformat(timespec="seconds"),
            volume=volume,
            turnover=amount,
            quote_source="tencent_realtime_quote",
            display_name=name,
            previous_close=prev_close,
            change=change,
            change_percent=pct,
        )
        return quote.to_payload()
    except Exception:
        logger.warning(
            "Tencent realtime quote fetch failed for %s (%s)",
            sym,
            asset_class.value,
            exc_info=True,
        )
        return None


class TencentDailyBarProvider(AkshareTencentDailyBarProvider):
    """Fetch raw/unadjusted SSE/SZSE stock and ETF daily bars with provider='tencent'."""

    @property
    def descriptor(self) -> MarketDataProviderDescriptor:
        return TENCENT_DAILY_BAR_DESCRIPTOR

    def fetch_daily_bars(self, request: DailyBarRequest) -> ProviderDailyBarBatch:
        batch = super().fetch_daily_bars(request)
        return ProviderDailyBarBatch(
            provider="tencent",
            adapter_version=TENCENT_DAILY_BAR_ADAPTER_VERSION,
            payload_format=TENCENT_DAILY_BAR_PAYLOAD_FORMAT,
            started_at=batch.started_at,
            completed_at=batch.completed_at,
            raw_payload=batch.raw_payload,
            rows=batch.rows,
        )


class TencentSource(DataSource):
    """Tencent market data adapter providing realtime quotes and daily bars."""

    def __init__(
        self,
        client: _AkshareTencentClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._daily_provider = TencentDailyBarProvider(client=client, clock=clock)

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict[str, Any] | None:
        """Fetch latest realtime quote from Tencent."""
        return fetch_tencent_realtime_quote(symbol, asset_class=asset_class)

    def supports_bars(
        self,
        asset_class: AssetClass = AssetClass.STOCK,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> bool:
        """Tencent supports Daily bars for Stock and ETF."""
        if frequency == BarFrequency.DAILY:
            return asset_class in (AssetClass.STOCK, AssetClass.FUND)
        return False

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        """Fetch bars using Tencent hist API via AKShare client."""
        if not self.supports_bars(asset_class, frequency):
            raise NotImplementedError(
                f"TencentSource does not support {frequency} bars for {asset_class}"
            )
        import akshare as ak

        prefix = resolve_tencent_market_prefix(symbol, asset_class)
        tencent_code = f"{prefix}{str(symbol).strip()}"
        df = ak.stock_zh_a_hist_tx(
            symbol=tencent_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
        if df is None or df.empty:
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
        col_map = {
            "date": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }
        df = df.rename(columns=col_map)
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(
            _CHINA_MARKET_TZ
        )
        return df.reset_index(drop=True)

    def fetch_ticks(
        self,
        symbol: Symbol,
        date: datetime,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        """TencentSource does not expose tick-level data."""
        raise NotImplementedError("TencentSource does not support tick-level data")

    def list_symbols(self) -> list[Symbol]:
        """TencentSource does not expose a local symbol directory."""
        return []
