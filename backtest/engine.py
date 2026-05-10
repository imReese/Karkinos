"""BacktestEngine — 串联所有组件的回测主循环。"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

import pandas as pd

from backtest.result import BacktestResult
from core.clock import SimulatedClock
from core.event_bus import EventBus
from core.events import (
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderIntentEvent,
    RiskDecisionEvent,
    SignalEvent,
)
from core.types import ZERO, OrderType, Symbol
from data.handler import DataHandler
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from execution.commission import (
    CommissionCalculator,
    MultiAssetCommission,
    StockACommission,
)
from execution.simulator import SimulatedExecution
from risk.manager import RiskManager
from strategy.base import Strategy

logger = logging.getLogger(__name__)


class BacktestEngine:
    """回测引擎。

    主循环：DataHandler.stream → MarketEvent → Strategy → SignalEvent
            → Portfolio → OrderEvent → RiskManager → Execution
            → FillEvent → Portfolio

    每日结算时调用 position.advance_settlement_day() 解冻 T+1。
    """

    def __init__(
        self,
        strategy: Strategy,
        instruments: dict[Symbol, Instrument],
        data_handlers: dict[Symbol, DataHandler],
        initial_cash: Decimal = Decimal("100000"),
        commission_calc: CommissionCalculator | None = None,
    ) -> None:
        self.event_bus = EventBus()
        self.clock = SimulatedClock()
        self.strategy = strategy
        self.instruments = instruments
        self.data_handlers = data_handlers
        self.initial_cash = initial_cash

        # 将策略的 event_bus 指向引擎内部总线
        self.strategy.event_bus = self.event_bus

        # 创建组件
        self.portfolio = Portfolio(self.event_bus, initial_cash=initial_cash)
        for inst in instruments.values():
            self.portfolio.add_instrument(inst)

        # 多资产佣金调度
        if commission_calc is None:
            self._multi_commission = MultiAssetCommission()
            self.execution = SimulatedExecution(commission_calc=self._multi_commission)
        else:
            self._multi_commission = None
            self.execution = SimulatedExecution(commission_calc=commission_calc)

        self.risk_manager = RiskManager(self.event_bus)

        # 订阅 MarketEvent
        self.event_bus.subscribe(MarketEvent, self._on_market_event)
        # 订阅 OrderIntentEvent — 回测兼容胶水，默认批准并转换为 OrderEvent
        self.event_bus.subscribe(OrderIntentEvent, self._on_order_intent_event)
        # 订阅 OrderEvent — 执行
        self.event_bus.subscribe(OrderEvent, self._on_order_event)

    def run(self) -> BacktestResult:
        """运行回测，返回 BacktestResult。"""
        # 初始化策略
        symbols = list(self.instruments.keys())
        self.strategy.on_init(symbols)

        # 合并所有 data handler 的事件流，按时间排序
        all_events = self._merge_streams()

        # 主循环
        prev_date = None
        for market_event in all_events:
            current_date = market_event.timestamp.date()

            # 新的一天：结算 T+1
            if prev_date is not None and current_date != prev_date:
                self.portfolio.advance_settlement_day()

            prev_date = current_date

            # 推进时钟
            self.clock.advance_to(market_event.timestamp)

            # 更新风控组合价值
            prices = {market_event.symbol: market_event.close}
            self.portfolio.mark_to_market(prices)
            equity = self._calculate_equity()
            self.risk_manager.set_portfolio_value(
                total=float(equity),
                cash=float(self.portfolio.cash),
            )

            # 发布 MarketEvent
            self.event_bus.publish_and_process(market_event)

            # 处理后续事件（Signal → Order → Risk → Fill）
            self.event_bus.drain()

            # 记录资金曲线
            self.portfolio.record_equity(
                market_event.timestamp,
                {market_event.symbol: market_event.close},
            )

        return self._build_result()

    def _on_market_event(self, event: MarketEvent) -> None:
        """转发给策略。"""
        self.strategy.on_data(event)

    def _on_order_intent_event(self, event: OrderIntentEvent) -> None:
        """回测中将交易意图转换为已批准订单。

        实盘路径应由 PreTradeRiskManager 生成 OrderEvent；这里仅保持
        当前回测引擎在阶段 1 改造期间的确定性行为。
        """
        decision_id = f"BACKTEST-RISK-{uuid.uuid4().hex[:8]}"
        order_id = f"ORD-{uuid.uuid4().hex[:8]}"
        self.event_bus.publish(
            RiskDecisionEvent(
                timestamp=event.timestamp,
                decision_id=decision_id,
                intent_id=event.intent_id,
                passed=True,
                symbol=event.symbol,
                side=event.side,
                reasons=["backtest_default_approved"],
                resulting_order_id=order_id,
                severity="info",
            )
        )
        self.event_bus.publish(
            OrderEvent(
                timestamp=event.timestamp,
                order_id=order_id,
                symbol=event.symbol,
                side=event.side,
                order_type=OrderType.MARKET,
                quantity=event.quantity,
                price=event.reference_price,
                intent_id=event.intent_id,
                risk_decision_id=decision_id,
                execution_mode="paper",
            )
        )

    def _on_order_event(self, event: OrderEvent) -> None:
        """执行委托单。"""
        if self._multi_commission is not None:
            inst = self.instruments.get(event.symbol)
            if inst is not None:
                commission = self._multi_commission.calculate_for(
                    inst.commission_type,
                    event.side,
                    event.price or ZERO,
                    event.quantity,
                )
                fill = self.execution.execute(event)
                if fill is not None:
                    # 覆盖佣金为按资产类型计算的值
                    fill = FillEvent(
                        timestamp=fill.timestamp,
                        fill_id=fill.fill_id,
                        order_id=fill.order_id,
                        symbol=fill.symbol,
                        side=fill.side,
                        fill_price=fill.fill_price,
                        fill_quantity=fill.fill_quantity,
                        commission=commission,
                        slippage=fill.slippage,
                    )
                    self.event_bus.publish(fill)
                    return

        fill = self.execution.execute(event)
        if fill is not None:
            self.event_bus.publish(fill)

    def _merge_streams(self) -> list[MarketEvent]:
        """合并多个 DataHandler 的事件流，按时间排序。"""
        all_events: list[MarketEvent] = []
        for symbol, handler in self.data_handlers.items():
            for event in handler:
                all_events.append(event)
        all_events.sort(key=lambda e: e.timestamp)
        return all_events

    def _calculate_equity(self) -> Decimal:
        """计算总权益。"""
        positions_value = ZERO
        for symbol, pos in self.portfolio.positions.items():
            positions_value += pos.market_value
        return self.portfolio.cash + positions_value

    def _build_result(self) -> BacktestResult:
        """构建回测结果。"""
        return BacktestResult(
            equity_curve=self.portfolio.equity_curve,
            positions=self.portfolio.positions,
            initial_cash=self.initial_cash,
            final_equity=self._calculate_equity(),
        )
