"""Portfolio — 组合管理，目标权重→股数转换 + 持仓管理。"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from core.event_bus import EventBus
from core.events import FillEvent, OrderEvent, SignalEvent
from core.types import ZERO, OrderSide, OrderType, Symbol
from domain.instrument import Instrument
from domain.position import Position

logger = logging.getLogger(__name__)


class Portfolio:
    """组合管理器。

    核心职责：
    - 将目标权重转为具体股数（考虑手数、可用资金）
    - 管理持仓
    - 跟踪资金曲线
    - 每日结算时调用 advance_settlement_day() 解冻 T+1
    """

    def __init__(
        self,
        event_bus: EventBus,
        initial_cash: Decimal = Decimal("100000"),
    ) -> None:
        self.event_bus = event_bus
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions: dict[Symbol, Position] = {}
        self.instruments: dict[Symbol, Instrument] = {}
        self.equity_curve: list[tuple] = []  # (timestamp, equity)

        # 订阅 SignalEvent
        event_bus.subscribe(SignalEvent, self.on_signal)
        # 订阅 FillEvent 更新持仓和资金
        event_bus.subscribe(FillEvent, self.on_fill)

    def add_instrument(self, instrument: Instrument) -> None:
        self.instruments[instrument.symbol] = instrument

    def on_signal(self, event: SignalEvent) -> None:
        """将目标权重转为具体股数，发布 OrderEvent。"""
        symbol = event.symbol
        instrument = self.instruments.get(symbol)
        if instrument is None:
            logger.warning("Unknown instrument: %s", symbol)
            return

        current_price = event.price or Decimal("0")
        if current_price == ZERO:
            return

        # 计算当前持仓权重
        total_equity = self._calculate_equity(current_price)
        current_value = self._position_value(symbol, current_price)
        current_weight = current_value / total_equity if total_equity > ZERO else ZERO

        # 目标权重与当前权重的差
        target_weight = event.target_weight
        weight_diff = target_weight - current_weight

        if abs(weight_diff) < Decimal("0.01"):
            return  # 差异太小，不交易

        # 计算目标金额
        target_value = total_equity * target_weight
        value_diff = target_value - current_value

        if value_diff > ZERO:
            # 买入
            quantity = self._calculate_buy_quantity(
                instrument, current_price, value_diff
            )
            if quantity > ZERO:
                self.event_bus.publish(
                    OrderEvent(
                        timestamp=event.timestamp,
                        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
                        symbol=symbol,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=quantity,
                        price=current_price,
                    )
                )
        elif value_diff < ZERO:
            # 卖出
            quantity = self._calculate_sell_quantity(
                instrument, current_price, abs(value_diff)
            )
            if quantity > ZERO:
                self.event_bus.publish(
                    OrderEvent(
                        timestamp=event.timestamp,
                        order_id=f"ORD-{uuid.uuid4().hex[:8]}",
                        symbol=symbol,
                        side=OrderSide.SELL,
                        order_type=OrderType.MARKET,
                        quantity=quantity,
                        price=current_price,
                    )
                )

    def on_fill(self, event: FillEvent) -> None:
        """更新持仓和资金。"""
        symbol = event.symbol
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol)

        pos = self.positions[symbol]
        pos.update_on_fill(
            side=event.side.value,
            fill_quantity=event.fill_quantity,
            fill_price=event.fill_price,
            commission=event.commission,
        )

        # 更新资金
        if event.side == OrderSide.BUY:
            self.cash -= event.fill_price * event.fill_quantity + event.commission
        else:
            self.cash += event.fill_price * event.fill_quantity - event.commission

    def advance_settlement_day(self) -> None:
        """每日结算：解冻 T+1。"""
        for pos in self.positions.values():
            pos.advance_settlement_day()

    def deposit(self, amount: Decimal) -> None:
        """入金（Live 模式专用）。"""
        if amount <= ZERO:
            raise ValueError("入金金额必须为正数")
        self.cash += amount

    def withdraw(self, amount: Decimal) -> None:
        """出金（Live 模式专用）。"""
        if amount <= ZERO:
            raise ValueError("出金金额必须为正数")
        if amount > self.cash:
            raise ValueError("可用资金不足")
        self.cash -= amount

    def mark_to_market(self, prices: dict[Symbol, Decimal]) -> None:
        """盯市。"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].mark_to_market(price)

    def record_equity(self, timestamp, prices: dict[Symbol, Decimal]) -> None:
        """记录资金曲线。"""
        equity = self._calculate_equity_with_prices(prices)
        self.equity_curve.append((timestamp, equity))

    def _calculate_equity(self, price: Decimal) -> Decimal:
        """估算总权益（简化：用单一价格）。"""
        positions_value = sum(pos.quantity * price for pos in self.positions.values())
        return self.cash + positions_value

    def _calculate_equity_with_prices(self, prices: dict[Symbol, Decimal]) -> Decimal:
        """用多价格计算总权益。"""
        positions_value = ZERO
        for symbol, pos in self.positions.items():
            if symbol in prices:
                positions_value += pos.quantity * prices[symbol]
            else:
                positions_value += pos.market_value
        return self.cash + positions_value

    def _position_value(self, symbol: Symbol, price: Decimal) -> Decimal:
        pos = self.positions.get(symbol)
        if pos is None:
            return ZERO
        return pos.quantity * price

    def _calculate_buy_quantity(
        self,
        instrument: Instrument,
        price: Decimal,
        value_diff: Decimal,
    ) -> Decimal:
        """计算买入股数（按手数取整，不超过可用资金）。"""
        max_shares = value_diff / price
        # 按手数取整
        lot_size = instrument.lot_size
        lots = int(max_shares / lot_size)
        quantity = Decimal(str(lots)) * lot_size

        # 检查资金是否足够
        cost = quantity * price
        if cost > self.cash:
            # 减少手数
            while quantity > ZERO and quantity * price > self.cash:
                quantity -= lot_size

        return quantity

    def _calculate_sell_quantity(
        self,
        instrument: Instrument,
        price: Decimal,
        value_diff: Decimal,
    ) -> Decimal:
        """计算卖出股数（按手数取整，不超过可卖数量）。"""
        pos = self.positions.get(instrument.symbol)
        if pos is None:
            return ZERO

        max_shares = value_diff / price
        lot_size = instrument.lot_size
        lots = int(max_shares / lot_size)
        quantity = Decimal(str(lots)) * lot_size

        # 不超过可卖数量
        available = pos.available_qty
        if quantity > available:
            # 按手数取整
            quantity = (available // lot_size) * lot_size

        return quantity
