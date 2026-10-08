"""BacktestEngine — 串联所有组件的回测主循环。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from itertools import groupby
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.costs import RESEARCH_MAX_VOLUME_PARTICIPATION, RESEARCH_SLIPPAGE_BPS
from backtest.distributions import DistributionReplay, StockDistribution
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
from domain.a_share_limits import is_limit_down, is_limit_up, is_suspended
from domain.instrument import Instrument
from domain.portfolio import Portfolio
from domain.portfolio_accounting import total_trade_fee
from execution.commission import (
    CommissionCalculator,
    MultiAssetCommission,
)
from execution.simulator import SimulatedExecution
from execution.slippage import (
    PercentSlippage,
    SlippageModel,
)
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
    max_volume_participation: Decimal | None = None
    availability_mode: Literal["historical_snapshot", "observed"] = (
        "historical_snapshot"
    )


def research_execution_config(
    commission_calc: CommissionCalculator | None = None,
    *,
    slippage_bps: Decimal = RESEARCH_SLIPPAGE_BPS,
) -> BacktestExecutionConfig:
    """The same explicit friction assumption for automatic research consumers."""
    return BacktestExecutionConfig(
        commission_calc=commission_calc,
        slippage_model=PercentSlippage(slippage_bps / Decimal("10000")),
        max_volume_participation=RESEARCH_MAX_VOLUME_PARTICIPATION,
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
        data_handlers: Mapping[Symbol, Iterable[MarketEvent]],
        initial_cash: Decimal = Decimal("100000"),
        commission_calc: CommissionCalculator | None = None,
        slippage_model: SlippageModel | None = None,
        execution_config: BacktestExecutionConfig | None = None,
        db=None,
        cash_dividends: tuple[StockDistribution, ...] | None = None,
        include_share_distributions: bool = False,
        evaluation_start: date | None = None,
        warmup_final_bar_targets: bool = False,
        strict_event_errors: bool = False,
        session_completed: Callable[[date], None] | None = None,
    ) -> None:
        if evaluation_start is not None and type(evaluation_start) is not date:
            raise ValueError("backtest_evaluation_start_invalid")
        self.event_bus = EventBus(raise_handler_errors=strict_event_errors)
        self._session_completed = session_completed
        self.clock = SimulatedClock()
        self.strategy = strategy
        self.instruments = instruments
        self.data_handlers = data_handlers
        self.initial_cash = initial_cash
        self.evaluation_start = evaluation_start
        if type(warmup_final_bar_targets) is not bool or (
            warmup_final_bar_targets and evaluation_start is None
        ):
            raise ValueError("backtest_warmup_targets_require_evaluation_window")
        self._warmup_final_bar_targets = warmup_final_bar_targets
        self._warmup_target_timestamps = {}
        # Earlier bars initialize strategy history, never a carried trading book.
        # Initialization emissions are also discarded for an evaluation window.
        self._warming_up = evaluation_start is not None
        self.fills: list[FillEvent] = []
        self.db = db
        self._dividend_replay = (
            DistributionReplay(
                cash_dividends, include_shares=include_share_distributions
            )
            if cash_dividends is not None
            else None
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
        self._execution_blocked = {"limit": 0, "suspension": 0, "risk": 0, "cash": 0}
        self._cash_resized_count = 0
        self._max_volume_participation = (
            execution_config.max_volume_participation
            if execution_config is not None
            else None
        )
        if self._max_volume_participation is not None and (
            not self._max_volume_participation.is_finite()
            or not ZERO < self._max_volume_participation <= Decimal("1")
        ):
            raise ValueError("backtest_volume_participation_invalid")
        self._bar_filled_quantity: dict[tuple[Symbol, object], Decimal] = {}
        self._capacity_resized_count = 0
        self._capacity_unfilled_quantity = ZERO
        self._execution_blocked["capacity"] = 0
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
        # Finish the research book's cash, quantities and marks before strategy
        # callbacks can synchronously publish another order.
        self.event_bus.unsubscribe(FillEvent, self.portfolio.on_fill)
        self.event_bus.subscribe(FillEvent, self._on_portfolio_fill)
        # Portfolio sizes a target only when the later execution bar is known.
        self.event_bus.unsubscribe(SignalEvent, self.portfolio.on_signal)
        self.event_bus.subscribe(SignalEvent, self._on_signal)
        self.event_bus.subscribe(FillEvent, self.strategy.on_fill)
        self.event_bus.subscribe(FillEvent, self._on_position_fill)
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
        # Portfolio owns this research book. Risk reads the same positions and
        # must not reconstruct a second fill-only book that misses share awards.
        self.event_bus.unsubscribe(FillEvent, self.risk_manager.on_fill)
        self.risk_manager.positions = self.portfolio.positions
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
        if self._warmup_final_bar_targets:
            self._warmup_target_timestamps = {
                event.symbol: event.timestamp
                for event in all_events
                if self._session_date(event) < self.evaluation_start
            }
        if self._dividend_replay is not None:
            self._dividend_replay.validate_events(
                all_events, observed=self._availability_mode == "observed"
            )
        # 初始化策略
        symbols = list(self.instruments.keys())
        self.strategy.on_init(symbols)
        if self.evaluation_start is not None:
            self.event_bus.drain()

        # 主循环
        for current_date, session in groupby(all_events, key=self._session_date):
            self._bar_filled_quantity.clear()
            session_events = list(session)
            self._warming_up = (
                self.evaluation_start is not None
                and current_date < self.evaluation_start
            )
            if self._warming_up:
                # Retain crossover state and previous close for tradability. No
                # valuation, settlement, cost or record-date entitlement exists
                # before the fresh evaluation book starts.
                for market_event in session_events:
                    self.clock.advance_to(market_event.timestamp)
                    self.event_bus.publish_and_process(market_event)
                    self.event_bus.drain()
                continue
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
                # Awards change quantities without fills. Revalue every holding
                # before any symbol is sized, then sync strategy position state.
                self.portfolio.mark_to_market(
                    {event.symbol: event.close for event in session_events}
                )
                for symbol, position in self.portfolio.positions.items():
                    self.strategy.on_position_update(symbol, position.quantity)
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
            if self._session_completed is not None:
                self._session_completed(current_date)

        return self._build_result()

    def _session_date(self, event: MarketEvent) -> date:
        if self._dividend_replay is not None:
            return event.timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
        return event.timestamp.date()

    def _on_portfolio_fill(self, event: FillEvent) -> None:
        market_price = self._known_market_price(event.symbol)
        if market_price is None:
            raise ValueError("backtest_fill_market_price_missing")
        self.portfolio.on_fill(event)
        # Revalue at the observed market close, not the slipped execution price,
        # before the next queued order can inspect equity or concentration.
        self.portfolio.positions[event.symbol].mark_to_market(market_price)
        self.risk_manager.set_portfolio_value(
            total=float(self._calculate_equity()), cash=float(self.portfolio.cash)
        )

    def _on_position_fill(self, event: FillEvent) -> None:
        position = self.portfolio.positions[event.symbol]
        self.strategy.on_position_update(event.symbol, position.quantity)

    def _on_market_event(self, event: MarketEvent) -> None:
        """Execute prior targets, then expose this completed bar to the strategy."""
        self._current_market_event = event
        pending = self._pending_signals.get(event.symbol)
        if (
            not self._warming_up
            and pending is not None
            and event.timestamp > pending.timestamp
        ):
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
        if self._warming_up and (
            not self._warmup_final_bar_targets
            or self._current_market_event.timestamp
            != self._warmup_target_timestamps.get(event.symbol)
        ):
            return
        decision_at = max(event.timestamp, self._current_market_event.timestamp)
        self._pending_signals[event.symbol] = replace(event, timestamp=decision_at)

    def _tradeable_order(self, event: OrderEvent) -> bool:
        bar = self._current_market_event
        instrument = self.instruments.get(event.symbol)
        market_price = self._known_market_price(event.symbol)
        if market_price is None or not market_price.is_finite() or market_price <= ZERO:
            self._execution_blocked["risk"] += 1
            return False
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

    def _known_market_price(self, symbol: Symbol) -> Decimal | None:
        bar = self._current_market_event
        if bar is not None and bar.symbol == symbol:
            return bar.close
        return self._previous_close.get(symbol)

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
        if event.side is OrderSide.SELL:
            position = self.portfolio.positions.get(event.symbol)
            instrument = self.instruments.get(event.symbol)
            available = ZERO
            if position is not None:
                available = position.available_qty
                if instrument is not None and not instrument.is_t_plus_1:
                    available = position.quantity - position.unlisted_qty
            # Direct orders and risk-modified quantities must respect the same
            # T+1 and unlisted-share locks as target sizing.
            if event.quantity > available:
                self._execution_blocked["risk"] += 1
                return None
        return event

    def _on_order_intent_event(self, event: OrderIntentEvent) -> None:
        """Build an order; the execution boundary records the actual risk decision."""
        if self._warming_up:
            return
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
        if self._warming_up:
            return
        approved = self._approved_order(event)
        execution = None
        if approved is not None and self._tradeable_order(approved):
            capacity_order = self._capacity_order(approved)
            if capacity_order is not None:
                execution = self._cash_funded_fill(capacity_order)
        if event.intent_id is not None and event.risk_decision_id is not None:
            passed = execution is not None
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
                    resulting_order_id=execution[0].order_id if execution else None,
                    severity="info" if passed else "warning",
                )
            )
        if execution is None:
            return
        event, fill = execution
        bar = self._current_market_event
        if bar is not None and bar.symbol == event.symbol:
            key = (bar.symbol, bar.timestamp)
            self._bar_filled_quantity[key] = (
                self._bar_filled_quantity.get(key, ZERO) + fill.fill_quantity
            )
        self._record_order_event(event)
        self._record_fill_event(fill, event)

    def _capacity_order(self, order: OrderEvent) -> OrderEvent | None:
        """One bar's cumulative share budget; unfilled remainder is cancelled.

        This is an explicit research participation assumption, not a calibrated
        impact model or a standing order. Missing/invalid volume cannot fund a
        capacity-constrained fill. Cash sizing still re-quotes the capped order.
        """
        if self._max_volume_participation is None:
            return order
        if not order.quantity.is_finite() or order.quantity <= ZERO:
            self._execution_blocked["risk"] += 1
            return None
        bar = self._current_market_event
        inst = self.instruments.get(order.symbol)
        if bar is None or bar.symbol != order.symbol or inst is None:
            self._execution_blocked["capacity"] += 1
            self._capacity_unfilled_quantity += order.quantity
            return None
        volume = bar.volume
        remaining = ZERO
        if volume.is_finite() and volume > ZERO:
            remaining = max(
                ZERO,
                volume * self._max_volume_participation
                - self._bar_filled_quantity.get((bar.symbol, bar.timestamp), ZERO),
            )
        quantity = min(order.quantity, (remaining // inst.lot_size) * inst.lot_size)
        # A complete odd-lot liquidation is legal if it fits the share budget.
        if order.side is OrderSide.SELL and order.quantity <= remaining:
            quantity = order.quantity
        if quantity < order.quantity:
            self._capacity_unfilled_quantity += order.quantity - quantity
            self._capacity_resized_count += 1
        if quantity <= ZERO:
            self._execution_blocked["capacity"] += 1
            return None
        return replace(order, quantity=quantity)

    def _resolve_fill(self, event: OrderEvent) -> FillEvent | None:
        """Resolve one price and complete fee; never re-execute an accepted fill."""
        fill = self.execution.execute(event)
        inst = self.instruments.get(event.symbol)
        if fill is not None and self._multi_commission is not None and inst is not None:
            breakdown = self._multi_commission.breakdown_for(
                inst.commission_type,
                fill.side,
                fill.fill_price,
                fill.fill_quantity,
                symbol=str(fill.symbol),
            )
            fill = replace(
                fill,
                commission=breakdown.total_fee,
                fee_breakdown=breakdown.to_json_dict(),
                fee_rule_id=breakdown.fee_rule_id,
                fee_rule_version=self._multi_commission.fee_rule_version,
            )
        return fill

    def _cash_funded_fill(
        self, order: OrderEvent
    ) -> tuple[OrderEvent, FillEvent] | None:
        """Shrink buys by legal lots, checking the actual candidate after each quote.

        The next quantity is conservative at the quoted price and fee. Custom
        models need not be monotonic: every new quantity is quoted again and only
        the exact affordable fill is used, without promising a maximal fill.
        """
        inst = self.instruments.get(order.symbol)
        if inst is None or not order.quantity.is_finite() or order.quantity <= ZERO:
            return None
        quantity = order.quantity
        if order.side is OrderSide.BUY:
            quantity = (quantity // inst.lot_size) * inst.lot_size
        while quantity > ZERO:
            candidate = replace(order, quantity=quantity)
            fill = self._resolve_fill(candidate)
            if fill is None:
                return None
            fee = total_trade_fee(
                commission=fill.commission, fee_breakdown=fill.fee_breakdown
            )
            if (
                not fill.fill_price.is_finite()
                or fill.fill_price <= ZERO
                or not fee.is_finite()
            ):
                raise ValueError("backtest_fill_cost_invalid")
            notional = fill.fill_price * fill.fill_quantity
            cash_debit = (
                notional + fee if order.side is OrderSide.BUY else fee - notional
            )
            if cash_debit <= self.portfolio.cash:
                if quantity != order.quantity:
                    self._cash_resized_count += 1
                return candidate, fill
            if order.side is OrderSide.SELL:
                break
            quantity = min(
                quantity - inst.lot_size,
                ((self.portfolio.cash - fee) / fill.fill_price // inst.lot_size)
                * inst.lot_size,
            )
        self._execution_blocked["cash"] += 1
        return None

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
            self.event_bus.publish_and_process(fill)
            return

        self.execution_tracker.record_fill(
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
                metadata={
                    "order_execution_mode": order.execution_mode,
                    "fee_breakdown": fill.fee_breakdown,
                    "fee_rule_id": fill.fee_rule_id,
                    "fee_rule_version": fill.fee_rule_version,
                },
            ),
            publish=False,
        )
        self.fills.append(fill)
        self.event_bus.publish_and_process(fill)
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
                "policy_id": "karkinos.backtest.next_bar_close.v2",
                "signal_basis": "completed_bar",
                "fill_basis": "strictly_later_same_instrument_bar_close",
                "availability_mode": self._availability_mode,
                "pending_signal_count": len(self._pending_signals),
                "limit_blocked_count": self._execution_blocked["limit"],
                "suspension_blocked_count": self._execution_blocked["suspension"],
                "risk_blocked_count": self._execution_blocked["risk"],
                "cash_blocked_count": self._execution_blocked["cash"],
                "cash_resized_count": self._cash_resized_count,
                "capacity_model": "cumulative_bar_share_participation"
                if self._max_volume_participation is not None
                else "unconstrained",
                "max_volume_participation": str(self._max_volume_participation)
                if self._max_volume_participation is not None
                else None,
                "capacity_resized_count": self._capacity_resized_count,
                "capacity_blocked_count": self._execution_blocked["capacity"],
                "capacity_unfilled_quantity": str(self._capacity_unfilled_quantity),
                "unfilled_remainder_policy": "cancel_after_one_execution_attempt",
                "historical_pit_verified": False,
                **(
                    {
                        "evaluation_start": self.evaluation_start.isoformat(),
                        "warmup_basis": "strategy_history_only_fresh_book",
                        "warmup_final_bar_targets": self._warmup_final_bar_targets,
                    }
                    if self.evaluation_start is not None
                    else {}
                ),
            },
        )
