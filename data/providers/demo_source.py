"""Deterministic local market data source for development and demos."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol
from data.source import DataSource

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _seed(symbol: Symbol, asset_class: AssetClass) -> int:
    raw = f"{symbol}:{asset_class.value}".encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:12], 16)


def _base_price(symbol: Symbol, asset_class: AssetClass) -> float:
    seed = _seed(symbol, asset_class)
    if asset_class == AssetClass.FUND:
        return round(0.8 + (seed % 2400) / 1000, 4)
    if asset_class == AssetClass.GOLD:
        return round(400 + (seed % 16000) / 100, 2)
    if asset_class == AssetClass.BOND:
        return round(90 + (seed % 2500) / 100, 3)
    return round(8 + (seed % 32000) / 100, 2)


def _demo_price(symbol: Symbol, asset_class: AssetClass, timestamp: datetime) -> float:
    seed = _seed(symbol, asset_class)
    base = _base_price(symbol, asset_class)
    wave = math.sin((timestamp.toordinal() + seed % 31) / 5) * 0.018
    intraday = ((timestamp.hour * 60 + timestamp.minute + seed % 97) % 240) / 24000
    return round(max(base * (1 + wave + intraday), 0.0001), 4)


class DemoSource(DataSource):
    """Offline quote provider that is explicitly marked as demo data."""

    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        freq = {
            BarFrequency.DAILY: "D",
            BarFrequency.MIN_1: "1min",
            BarFrequency.MIN_5: "5min",
        }.get(frequency, "D")
        timestamps = pd.date_range(start=start, end=end, freq=freq)
        if timestamps.empty:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        rows = []
        previous_close = _base_price(symbol, asset_class)
        for idx, timestamp in enumerate(timestamps):
            ts = timestamp.to_pydatetime()
            close = _demo_price(symbol, asset_class, ts)
            open_price = previous_close if idx else close * 0.998
            high = max(open_price, close) * 1.004
            low = min(open_price, close) * 0.996
            volume = float(10_000 + (_seed(symbol, asset_class) % 5000) + idx * 13)
            rows.append(
                {
                    "timestamp": pd.Timestamp(ts),
                    "open": round(open_price, 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "volume": volume,
                }
            )
            previous_close = close
        return pd.DataFrame(rows)

    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        return pd.DataFrame(columns=["timestamp", "price", "volume"])

    def list_symbols(self) -> list[Symbol]:
        return []

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        now = datetime.now(_SH_TZ).replace(microsecond=0)
        price = _demo_price(symbol, asset_class, now)
        previous_close_ts = now.replace(hour=15, minute=0, second=0)
        if previous_close_ts >= now:
            previous_close_ts = previous_close_ts - timedelta(days=1)
        previous_close = _demo_price(symbol, asset_class, previous_close_ts)
        return {
            "price": price,
            "volume": float(100_000 + (_seed(symbol, asset_class) % 50_000)),
            "timestamp": now.isoformat(),
            "previous_close": previous_close,
            "previous_close_date": previous_close_ts.date().isoformat(),
            "source": "demo",
            "quote_source": "demo",
        }
