"""Karkinos 事件类型定义（frozen dataclass）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

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
class OrderIntentEvent(Event):
    """交易意图事件。

    由 Portfolio 根据 SignalEvent 生成，表达“想交易什么”。
    该事件不能直接进入执行层，必须先经过风控闸门转换为 OrderEvent。
    """

    intent_id: str
    strategy_id: str
    symbol: Symbol
    side: OrderSide
    target_weight: Decimal
    quantity: Decimal
    reference_price: Decimal
    asset_class: AssetClass | None = None
    source_signal_id: str | None = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskDecisionEvent(Event):
    """风控决策事件，用于审计和实时推送。"""

    decision_id: str
    intent_id: str
    passed: bool
    symbol: Symbol
    side: OrderSide
    reasons: list[str]
    resulting_order_id: str | None = None
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderEvent(Event):
    """委托单事件。

    兼容旧构造方式：新增字段均有默认值。
    新链路中，该事件应只由风控闸门或回测兼容胶水生成。
    """

    order_id: str
    symbol: Symbol
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None  # limit/stop 订单需要
    intent_id: str | None = None
    risk_decision_id: str | None = None
    execution_mode: str = "paper"


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
    fee_breakdown: dict[str, Any] | None = None
    fee_rule_id: str | None = None
    fee_rule_version: str | None = None


@dataclass(frozen=True)
class RiskAlertEvent(Event):
    """风控告警事件。"""

    alert_id: str
    rule_name: str
    severity: str  # "warning" / "critical"
    message: str
    symbol: Symbol | None = None
    order_id: str | None = None
