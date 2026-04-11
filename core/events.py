"""MyQuant 事件类型定义（frozen dataclass）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from core.types import AssetClass, BarFrequency, OrderSide, OrderType, Symbol


@dataclass(frozen=True)
class Event:
    """事件基类。"""

    timestamp: datetime


@dataclass(frozen=True)
class MarketEvent(Event):
    """K 线行情事件。"""

    symbol: Symbol
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    frequency: BarFrequency = BarFrequency.DAILY
    asset_class: AssetClass | None = None


@dataclass(frozen=True)
class SignalEvent(Event):
    """策略信号事件 —— 目标权重。"""

    strategy_id: str
    symbol: Symbol
    target_weight: Decimal  # 0.0 ~ 1.0
    price: Decimal | None = None  # 参考价格


@dataclass(frozen=True)
class OrderEvent(Event):
    """委托单事件。"""

    order_id: str
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None  # limit/stop 订单需要


@dataclass(frozen=True)
class FillEvent(Event):
    """成交回报事件。"""

    fill_id: str
    order_id: str
    symbol: Symbol
    side: OrderSide
    fill_price: Decimal
    fill_quantity: Decimal
    commission: Decimal
    slippage: Decimal


@dataclass(frozen=True)
class RiskAlertEvent(Event):
    """风控告警事件。"""

    alert_id: str
    rule_name: str
    severity: str  # "warning" / "critical"
    message: str
    symbol: Symbol | None = None
    order_id: str | None = None
