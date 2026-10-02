"""BacktestEngine — 串联所有组件的回测主循环。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from itertools import groupby
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.cash_dividends import CashDividend, CashDividendReplay
from backtest.equity_curve import canonicalize_equity_curve
from backtest.metrics import (
    build_after_cost_evidence,
    calculate_backtest_metrics,
    summarize_fill_costs,
)
from backtest.result import BacktestResult
from core.clock import SimulatedClock
from core.event_bus import EventBus
from core.events import (
    FillEvent,
    MarketEvent,
    OrderEvent,
    OrderIntentEvent,
    RiskAlertEvent,
    RiskDecisionEvent,
    SignalEvent,
)
from core.types import ZERO, AssetClass, InstrumentType, OrderSide, OrderType, Symbol
from data.handler import DataHandler
from domain.a_share_limits import is_limit_down, is_limit_up, is_suspended
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from execution.commission import (
    CommissionCalculator,
    MultiAssetCommission,
)
from execution.simulator import SimulatedExecution
from execution.slippage import SlippageModel
from execution.tracker import BrokerFillReport, ExecutionOrderTracker
from risk.manager import RiskManager
from strategy.base import Strategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestExecutionConfig:
    """Friction and observation admission for backtests.

    ``observed`` rejects any bar whose availability is missing or later than
    its replay timestamp. It never shifts timestamps or assumes historical
    availability. ``historical_snapshot`` permits explicitly exploratory replay.
    """

    slippage_model: SlippageModel | None = None
    commission_calc: CommissionCalculator | None = None
    availability_mode: Literal["historical_snapshot", "observed"] = (
        "historical_snapshot"
    )


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
        slippage_model: SlippageModel | None = None,
        execution_config: BacktestExecutionConfig | None = None,
        db=None,
        cash_dividends: tuple[CashDividend, ...] | None = None,
    ) -> None:
        self.event_bus = EventBus()
        self.clock = SimulatedClock()
        self.strategy = strategy
        self.instruments = instruments
        self.data_handlers = data_handlers
        self.initial_cash = initial_cash
        self.fills: list[FillEvent] = []
        self.db = db
        self._dividend_replay = (
            CashDividendReplay(cash_dividends) if cash_dividends is not None else None
        )
        if cash_dividends is not None and any(
            item.symbol not in instruments
            or instruments[item.symbol].instrument_type is not InstrumentType.STOCK
            for item in cash_dividends
        ):
            raise ValueError("cash_dividend_stock_required")
        self._availability_mode = (
            execution_config.availability_mode
            if execution_config is not None
            else "historical_snapshot"
        )
        if self._availability_mode not in {"historical_snapshot", "observed"}:
            raise ValueError("backtest_availability_mode_unsupported")
        self._pending_signals: dict[Symbol, SignalEvent] = {}
        self._current_market_event: MarketEvent | None = None
        self._previous_close: dict[Symbol, Decimal] = {}
        self._execution_blocked = {"limit": 0, "suspension": 0, "risk": 0}
        self.execution_tracker = (
            ExecutionOrderTracker(event_bus=self.event_bus, db=db)
            if db is not None
            else None
        )

        # 将策略的 event_bus 指向引擎内部总线
        self.strategy.event_bus = self.event_bus
        self.strategy.fill_tracking_enabled = True

        # 创建组件
        self.portfolio = Portfolio(self.event_bus, initial_cash=initial_cash)
        # Portfolio sizes a target only when the later execution bar is known.
        self.event_bus.unsubscribe(SignalEvent, self.portfolio.on_signal)
        self.event_bus.subscribe(SignalEvent, self._on_signal)
        self.event_bus.subscribe(FillEvent, self.strategy.on_fill)
        for inst in instruments.values():
            self.portfolio.add_instrument(inst)

        configured_slippage = slippage_model or (
            execution_config.slippage_model if execution_config is not None else None
        )
        configured_commission = commission_calc or (
            execution_config.commission_calc if execution_config is not None else None
        )

        # 多资产佣金调度
        if configured_commission is None or isinstance(
            configured_commission, MultiAssetCommission
        ):
            self._multi_commission = configured_commission or MultiAssetCommission()
            self.execution = SimulatedExecution(
                slippage_model=configured_slippage,
                commission_calc=self._multi_commission,
            )
        else:
            self._multi_commission = None
            self.execution = SimulatedExecution(
                slippage_model=configured_slippage,
                commission_calc=configured_commission,
            )

        self.risk_manager = RiskManager(self.event_bus)
        # EventBus broadcasts to every subscriber; enforce risk before execution
        # here so a rejected/modified order cannot also execute its original form.
        self.event_bus.unsubscribe(OrderEvent, self.risk_manager.on_order)

        # 订阅 MarketEvent
        self.event_bus.subscribe(MarketEvent, self._on_market_event)
        # 订阅 OrderIntentEvent — 回测兼容胶水，默认批准并转换为 OrderEvent
        self.event_bus.subscribe(OrderIntentEvent, self._on_order_intent_event)
        # 订阅 OrderEvent — 执行
        self.event_bus.subscribe(OrderEvent, self._on_order_event)

    def run(self) -> BacktestResult:
        """运行回测，返回 BacktestResult。"""
        # Validate availability before any strategy state can observe the input.
        all_events = self._merge_streams()
        if self._dividend_replay is not None:
            self._dividend_replay.validate_events(
                all_events, observed=self._availability_mode == "observed"
            )
        # 初始化策略
        symbols = list(self.instruments.keys())
        self.strategy.on_init(symbols)

        # 主循环
        for current_date, session in groupby(all_events, key=self._session_date):
            session_events = list(session)
            if self.portfolio.equity_curve:
                self.portfolio.advance_settlement_day()
            if self._dividend_replay is not None:
                # This mode requires one simultaneous Shanghai close per symbol.
                # Mark all prices before adding ex-date receivables, so ordering
                # symbols cannot temporarily count both the old price and income.
                self.portfolio.mark_to_market(
                    {event.symbol: event.close for event in session_events}
                )
                self._dividend_replay.before_session(current_date, self.portfolio)
            for market_event in session_events:
                self.clock.advance_to(market_event.timestamp)
                prices = {market_event.symbol: market_event.close}
                self.portfolio.mark_to_market(prices)
                self.risk_manager.set_portfolio_value(
                    total=float(self._calculate_equity()),
                    cash=float(self.portfolio.cash),
                )
                self.event_bus.publish_and_process(market_event)
                self.event_bus.drain()
                self.portfolio.mark_to_market(prices)
                self.portfolio.record_equity(market_event.timestamp, prices)
            if self._dividend_replay is not None:
                self._dividend_replay.after_session(current_date, self.portfolio)

        return self._build_result()

    def _session_date(self, event: MarketEvent) -> date:
        if self._dividend_replay is not None:
            return event.timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
        return event.timestamp.date()

    def _on_market_event(self, event: MarketEvent) -> None:
        """Execute prior targets, then expose this completed bar to the strategy."""
        self._current_market_event = event
        pending = self._pending_signals.get(event.symbol)
        if pending is not None and event.timestamp > pending.timestamp:
            del self._pending_signals[event.symbol]
            self.portfolio.on_signal(
                replace(pending, timestamp=event.timestamp, price=event.close)
            )
            self.event_bus.drain()
        self.strategy.on_data(event)
        self.event_bus.drain()
        self._previous_close[event.symbol] = event.close

    def _on_signal(self, event: SignalEvent) -> None:
        """Retain the latest target until a strictly later bar for that symbol."""
        if self._current_market_event is None:
            return
        decision_at = max(event.timestamp, self._current_market_event.timestamp)
        self._pending_signals[event.symbol] = replace(event, timestamp=decision_at)

    def _tradeable_order(self, event: OrderEvent) -> bool:
        bar = self._current_market_event
        instrument = self.instruments.get(event.symbol)
        if bar is None or instrument is None or bar.symbol != event.symbol:
            return True
        if self._dividend_replay is not None and self._dividend_replay.blocks_execution(
            event.symbol, self._session_date(bar)
        ):
            return False
        if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
            return True
        if is_suspended(bar.volume):
            self._execution_blocked["suspension"] += 1
            return False
        previous = self._previous_close.get(event.symbol)
        if previous is None or instrument.limit_pct <= ZERO:
            return True
        blocked = (
            is_limit_up(
                bar.close, previous, instrument.limit_pct, tick=instrument.price_tick
            )
            if event.side is OrderSide.BUY
            else is_limit_down(
                bar.close, previous, instrument.limit_pct, tick=instrument.price_tick
            )
        )
        if blocked:
            self._execution_blocked["limit"] += 1
        return not blocked

    def _approved_order(self, event: OrderEvent) -> OrderEvent | None:
        """Check the order at its execution time using current portfolio facts."""
        values = {
            "total": float(self._calculate_equity()),
            "cash": float(self.portfolio.cash),
        }
        for rule in self.risk_manager.rules:
            result = rule.check(event, self.portfolio.positions, values)
            if not result.passed:
                self._execution_blocked["risk"] += 1
                self.event_bus.publish(
                    RiskAlertEvent(
                        timestamp=event.timestamp,
                        alert_id=f"RISK-{event.order_id}",
                        rule_name=rule.name,
                        severity="warning",
                        message=result.message or "Order rejected",
                        symbol=event.symbol,
                        order_id=event.order_id,
                    )
                )
                return None
            if result.modified_order is not None:
                event = result.modified_order
        return event

    def _on_order_intent_event(self, event: OrderIntentEvent) -> None:
        """Build an order; the execution boundary records the actual risk decision."""
        decision_id = f"BACKTEST-RISK-{uuid.uuid4().hex[:8]}"
        order_id = f"ORD-{uuid.uuid4().hex[:8]}"
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
        """Execute an approved order at the current bar's modeled close."""
        approved = self._approved_order(event)
        if event.intent_id is not None and event.risk_decision_id is not None:
            passed = approved is not None
            self.event_bus.publish(
                RiskDecisionEvent(
                    timestamp=event.timestamp,
                    decision_id=event.risk_decision_id,
                    intent_id=event.intent_id,
                    passed=passed,
                    symbol=event.symbol,
                    side=event.side,
                    reasons=[
                        "backtest_execution_rules_passed"
                        if passed
                        else "backtest_execution_rule_rejected"
                    ],
                    resulting_order_id=approved.order_id if approved else None,
                    severity="info" if passed else "warning",
                )
            )
        if approved is None or not self._tradeable_order(approved):
            return
        event = approved
        self._record_order_event(event)
        if self._multi_commission is not None:
            inst = self.instruments.get(event.symbol)
            if inst is not None:
                fill = self.execution.execute(event)
                if fill is not None:
                    # 覆盖佣金为按资产类型和最终成交价计算的值。
                    fee_breakdown = self._multi_commission.breakdown_for(
                        inst.commission_type,
                        event.side,
                        fill.fill_price,
                        fill.fill_quantity,
                        symbol=str(event.symbol),
                    )
                    fill = FillEvent(
                        timestamp=fill.timestamp,
                        fill_id=fill.fill_id,
                        order_id=fill.order_id,
                        symbol=fill.symbol,
                        side=fill.side,
                        fill_price=fill.fill_price,
                        fill_quantity=fill.fill_quantity,
                        commission=fee_breakdown.total_fee,
                        slippage=fill.slippage,
                        fee_breakdown=fee_breakdown.to_json_dict(),
                        fee_rule_id=fee_breakdown.fee_rule_id,
                        fee_rule_version=self._multi_commission.fee_rule_version,
                    )
                    self._record_fill_event(fill, event)
                    return

        fill = self.execution.execute(event)
        if fill is not None:
            self._record_fill_event(fill, event)

    def _record_order_event(self, event: OrderEvent) -> None:
        """Persist a shared backtest order fact when a DB sink is configured."""
        if self.db is None or not hasattr(self.db, "record_order_sync"):
            return
        self.db.record_order_sync(
            order_id=event.order_id,
            timestamp=event.timestamp.isoformat(),
            symbol=str(event.symbol),
            side=event.side.value,
            order_type=event.order_type.value,
            quantity=float(event.quantity),
            price=float(event.price) if event.price is not None else None,
            asset_class=self._asset_class_for_order(event).value,
            intent_id=event.intent_id,
            risk_decision_id=event.risk_decision_id,
            execution_mode="backtest",
            status="submitted",
            source="backtest_execution",
            source_ref=event.order_id,
            payload={"order_execution_mode": event.execution_mode},
        )

    def _record_fill_event(self, fill: FillEvent, order: OrderEvent) -> None:
        """Record a fill locally, optionally persist it, and publish it once."""
        if self.execution_tracker is None:
            self.fills.append(fill)
            self.event_bus.publish(fill)
            return

        recorded = self.execution_tracker.record_fill(
            BrokerFillReport(
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                timestamp=fill.timestamp,
                symbol=fill.symbol,
                side=fill.side,
                fill_price=fill.fill_price,
                fill_quantity=fill.fill_quantity,
                commission=fill.commission,
                slippage=fill.slippage,
                asset_class=self._asset_class_for_order(order),
                execution_mode="backtest",
                provider_name="simulated_backtest",
                broker_order_id=order.order_id,
                source="backtest_execution",
                source_ref=fill.fill_id,
                metadata={"order_execution_mode": order.execution_mode},
            )
        )
        self.fills.append(recorded)
        if self.db is not None and hasattr(self.db, "update_order_status_sync"):
            self.db.update_order_status_sync(
                order_id=order.order_id,
                status="filled",
                note="filled by backtest_execution",
            )

    def _asset_class_for_order(self, event: OrderEvent) -> AssetClass:
        inst = self.instruments.get(event.symbol)
        return inst.asset_class if inst is not None else AssetClass.STOCK

    def _merge_streams(self) -> list[MarketEvent]:
        """合并多个 DataHandler 的事件流，按时间排序。"""
        all_events: list[MarketEvent] = []
        for symbol, handler in self.data_handlers.items():
            for event in handler:
                if self._availability_mode == "observed":
                    self._require_available_observation(event)
                all_events.append(event)
        all_events.sort(key=lambda e: (e.timestamp, str(e.symbol)))
        return all_events

    @staticmethod
    def _require_available_observation(event: MarketEvent) -> None:
        if event.available_at is None:
            raise ValueError("backtest_observation_availability_missing")
        try:
            late = event.available_at > event.timestamp
        except TypeError as exc:
            raise ValueError("backtest_observation_timezone_mismatch") from exc
        if late:
            raise ValueError("backtest_observation_unavailable_at_event_time")

    def _calculate_equity(self) -> Decimal:
        """计算总权益。"""
        return self.portfolio.total_equity

    def _build_result(self) -> BacktestResult:
        """构建回测结果。"""
        cost_summary = summarize_fill_costs(self.fills)
        final_equity = self._calculate_equity()
        equity_curve = canonicalize_equity_curve(self.portfolio.equity_curve)
        metrics = calculate_backtest_metrics(
            equity_curve,
            initial_cash=self.initial_cash,
            final_equity=final_equity,
            cost_summary=cost_summary,
        )
        evidence_bundle = build_after_cost_evidence(
            initial_cash=self.initial_cash,
            final_equity=final_equity,
            cost_summary=cost_summary,
        )
        return BacktestResult(
            equity_curve=equity_curve,
            positions=self.portfolio.positions,
            initial_cash=self.initial_cash,
            final_equity=final_equity,
            metrics=metrics,
            fills=list(self.fills),
            cost_summary=cost_summary,
            evidence_bundle=evidence_bundle,
            cash_dividend_accounting=(
                self._dividend_replay.evidence(self.portfolio)
                if self._dividend_replay is not None
                else None
            ),
            execution_timing={
                "schema_version": "karkinos.backtest_execution_timing.v1",
                "policy_id": "karkinos.backtest.next_bar_close.v1",
                "signal_basis": "completed_bar",
                "fill_basis": "strictly_later_same_instrument_bar_close",
                "availability_mode": self._availability_mode,
                "pending_signal_count": len(self._pending_signals),
                "limit_blocked_count": self._execution_blocked["limit"],
                "suspension_blocked_count": self._execution_blocked["suspension"],
                "risk_blocked_count": self._execution_blocked["risk"],
                "historical_pit_verified": False,
            },
        )
