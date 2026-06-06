"""DataSource — 数据源抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from core.types import AssetClass, BarFrequency, Symbol


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


@dataclass(frozen=True)
class ProviderQuote:
    """Normalized latest quote emitted by concrete market data providers."""

    symbol: str
    asset_class: AssetClass
    provider_name: str
    provider_symbol: str
    price: float
    timestamp: str
    volume: float | None = None
    turnover: float | None = None
    quote_source: str | None = None
    display_name: str | None = None
    previous_close: float | None = None
    previous_close_date: str | None = None
    change: float | None = None
    change_percent: float | None = None
    day_change_value: float | None = None
    day_change_pct: float | None = None
    exchange: str | None = None
    market: str | None = None
    metadata: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """Return the dict-compatible quote payload used by routes and scheduler."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "provider_name": self.provider_name,
            "provider_symbol": self.provider_symbol,
            "source": self.provider_name,
            "price": self.price,
            "volume": self.volume,
            "timestamp": self.timestamp,
        }
        optional: dict[str, Any] = {
            "turnover": self.turnover,
            "quote_source": self.quote_source,
            "display_name": self.display_name,
            "previous_close": self.previous_close,
            "previous_close_date": self.previous_close_date,
            "change": self.change,
            "change_percent": self.change_percent,
            "day_change_value": self.day_change_value,
            "day_change_pct": self.day_change_pct,
            "exchange": self.exchange,
            "market": self.market,
            "metadata": self.metadata,
        }
        payload.update(
            {
                key: value
                for key, value in optional.items()
                if value is not None and value != ""
            }
        )
        return payload


def normalize_provider_quote(
    symbol: Symbol,
    asset_class: AssetClass,
    payload: dict[str, Any] | ProviderQuote | None,
    *,
    provider_name: str,
    provider_symbol: str | None = None,
) -> ProviderQuote | None:
    """Normalize a provider-specific quote dict into the shared quote schema."""
    if payload is None:
        return None
    if isinstance(payload, ProviderQuote):
        return payload

    price = _optional_float(payload.get("price"))
    if price is None:
        return None

    symbol_value = str(payload.get("symbol") or symbol)
    provider_value = str(
        payload.get("provider_name")
        or payload.get("provider")
        or payload.get("source")
        or provider_name
    )
    provider_symbol_value = str(
        payload.get("provider_symbol") or provider_symbol or symbol_value
    )
    display_name = _optional_str(
        payload.get("display_name") or payload.get("name") or payload.get("asset_name")
    )
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        metadata = {"value": metadata}

    return ProviderQuote(
        symbol=symbol_value,
        asset_class=asset_class,
        provider_name=provider_value,
        provider_symbol=provider_symbol_value,
        price=price,
        timestamp=str(payload.get("timestamp") or ""),
        volume=_optional_float(payload.get("volume")),
        turnover=_optional_float(payload.get("turnover")),
        quote_source=_optional_str(payload.get("quote_source")),
        display_name=display_name,
        previous_close=_optional_float(payload.get("previous_close")),
        previous_close_date=_optional_str(payload.get("previous_close_date")),
        change=_optional_float(payload.get("change")),
        change_percent=_optional_float(payload.get("change_percent")),
        day_change_value=_optional_float(payload.get("day_change_value")),
        day_change_pct=_optional_float(payload.get("day_change_pct")),
        exchange=_optional_str(payload.get("exchange")),
        market=_optional_str(payload.get("market")),
        metadata=metadata,
    )


class DataSource(ABC):
    """数据源抽象基类。

    定义统一接口，AKShare/Tushare 等具体适配器实现此接口。
    """

    @abstractmethod
    def fetch_bars(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
        frequency: BarFrequency = BarFrequency.DAILY,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> pd.DataFrame:
        """获取 K 线数据，返回 DataFrame。

        列名约定：open, high, low, close, volume, amount, timestamp
        asset_class 决定调用哪个底层 API（股票/ETF/黄金/债券）。
        """

    @abstractmethod
    def fetch_ticks(
        self,
        symbol: Symbol,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """获取逐笔数据。"""

    @abstractmethod
    def list_symbols(self) -> list[Symbol]:
        """列出可用的标的代码。"""

    def fetch_latest(
        self,
        symbol: Symbol,
        asset_class: AssetClass = AssetClass.STOCK,
    ) -> dict | None:
        """获取最新行情快照（实时模式用）。

        返回 ProviderQuote.to_payload() 兼容格式，至少包含:
        {"symbol", "asset_class", "provider_name", "provider_symbol",
        "price", "volume", "timestamp", "source"}。
        默认返回 None，子类按需覆盖。
        """
        return None
