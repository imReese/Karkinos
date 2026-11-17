"""BacktestEngine — 串联所有组件的回测主循环。"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from heapq import merge
from itertools import groupby
from typing import Any, Literal, cast
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
from core.types import (
    ZERO,
    AssetClass,
    ExecutionModel,
    InstrumentType,
    OrderSide,
    OrderType,
    Symbol,
)
from data.handler import DataHandler
from domain.a_share_limits import (
    is_limit_down,
    is_limit_up,
    is_suspended,
    limit_down_price,
    limit_up_price,
)
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
    Streaming opts into distinct sorted DataHandlers whose frames stay private
    and unchanged; every row still receives preflight before strategy initialization.
    ``execution_model`` selects whether next-session fills occur at open or close.
    """

    slippage_model: SlippageModel | None = None
    commission_calc: CommissionCalculator | None = None
    max_volume_participation: Decimal | None = None
    availability_mode: Literal["historical_snapshot", "observed"] = (
        "historical_snapshot"
    )
    stream_sorted_data_handlers: bool = False
    execution_model: ExecutionModel = ExecutionModel.NEXT_BAR_CLOSE


def research_execution_config(
    commission_calc: CommissionCalculator | None = None,
    *,
    slippage_bps: Decimal = RESEARCH_SLIPPAGE_BPS,
    max_volume_participation: Decimal | None = RESEARCH_MAX_VOLUME_PARTICIPATION,
    stream_sorted_data_handlers: bool = False,
    execution_model: ExecutionModel | str = ExecutionModel.NEXT_BAR_CLOSE,
) -> BacktestExecutionConfig:
    """The same explicit friction assumption for automatic research consumers."""
    model = ExecutionModel.from_value(execution_model)
    return BacktestExecutionConfig(
        commission_calc=commission_calc,
        slippage_model=PercentSlippage(slippage_bps / Decimal("10000")),
        max_volume_participation=max_volume_participation,
        stream_sorted_data_handlers=stream_sorted_data_handlers,
        execution_model=model,
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
        session_decision: Callable[[date], None] | None = None,
        execution_model: ExecutionModel | str | None = None,
    ) -> None:
        if evaluation_start is not None and type(evaluation_start) is not date:
            raise ValueError("backtest_evaluation_start_invalid")
        self.event_bus = EventBus(raise_handler_errors=strict_event_errors)
        self._session_completed = session_completed
        self._session_decision = session_decision
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
        if execution_model is not None:
            self._execution_model = ExecutionModel.from_value(execution_model)
        elif (
            execution_config is not None
            and execution_config.execution_model is not None
        ):
            self._execution_model = ExecutionModel.from_value(
                execution_config.execution_model
            )
        else:
            self._execution_model = ExecutionModel.NEXT_BAR_CLOSE
        self._executing_at_open = False
        self._session_open_equity: Decimal | None = None
        self._stream_sorted_data_handlers = (
            execution_config.stream_sorted_data_handlers
            if execution_config is not None
            else False
        )
        if type(self._stream_sorted_data_handlers) is not bool:
            raise ValueError("backtest_streaming_data_handlers_flag_invalid")
        self._pending_signals: dict[Symbol, SignalEvent] = {}
        self._current_market_event: MarketEvent | None = None
        self._previous_close: dict[Symbol, Decimal] = {}
        self._open_signal_context: tuple[Symbol, str] | None = None
        self._open_authorized_intent_id: str | None = None
        self._open_authorized_order_id: str | None = None
        self._execution_blocked = {
            "limit": 0,
            "suspension": 0,
            "risk": 0,
            "cash": 0,
            "timing": 0,
        }
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
        if (
            self._execution_model is ExecutionModel.NEXT_BAR_OPEN
            and self._max_volume_participation is not None
        ):
            raise ValueError("next_bar_open_volume_participation_unsupported")
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
        events: Callable[[], Iterable[MarketEvent]]
        if self._stream_sorted_data_handlers:
            self._validate_sorted_data_handlers()
            events = self._merge_sorted_data_handlers
        else:
            all_events = self._merge_streams()
            events = lambda: iter(all_events)
        if self._warmup_final_bar_targets:
            self._warmup_target_timestamps = {
                event.symbol: event.timestamp
                for event in events()
                if self._session_date(event) < self.evaluation_start
            }
        if self._dividend_replay is not None:
            self._dividend_replay.validate_events(
                events(), observed=self._availability_mode == "observed"
            )
        # 初始化策略
        symbols = list(self.instruments.keys())
        self.strategy.on_init(symbols)
        if self.evaluation_start is not None:
            self.event_bus.drain()

        # 主循环
        for current_date, session in groupby(events(), key=self._session_date):
            self._bar_filled_quantity.clear()
            session_events = list(session)
            if self._execution_model is ExecutionModel.NEXT_BAR_OPEN:
                seen_symbols: set[Symbol] = set()
                session_timestamps: set[datetime] = set()
                for ev in session_events:
                    if ev.symbol in seen_symbols:
                        raise ValueError("duplicate_symbol_bar_in_session")
                    seen_symbols.add(ev.symbol)
                    session_timestamps.add(ev.timestamp)
                if len(session_timestamps) != 1:
                    raise ValueError("session_bars_timestamp_inconsistent")

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
                if self._session_decision is not None:
                    self._session_decision(current_date)
                    self.event_bus.drain()
                continue
            if self.portfolio.equity_curve:
                self.portfolio.advance_settlement_day()
            if self._dividend_replay is not None:
                # This mode requires one simultaneous Shanghai close per symbol.
                # Mark all prices before adding ex-date receivables, so ordering
                # symbols cannot temporarily count both the old price and income.
                pre_div_prices = {
                    event.symbol: (
                        event.open
                        if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                        else event.close
                    )
                    for event in session_events
                }
                self.portfolio.mark_to_market(pre_div_prices)
                self._dividend_replay.before_session(current_date, self.portfolio)
                # Awards change quantities without fills. Revalue every holding
                # before any symbol is sized, then sync strategy position state.
                self.portfolio.mark_to_market(pre_div_prices)
                for symbol, position in self.portfolio.positions.items():
                    self.strategy.on_position_update(symbol, position.quantity)
            if self._execution_model is ExecutionModel.NEXT_BAR_OPEN:
                # 1. Snapshot and extract eligible pending signals prior to today's open
                eligible_signals: dict[Symbol, SignalEvent] = {}
                for event in session_events:
                    pending = self._pending_signals.get(event.symbol)
                    if pending is not None and event.timestamp > pending.timestamp:
                        eligible_signals[event.symbol] = pending
                        del self._pending_signals[event.symbol]

                # 2. Mark all session symbols to Open before any order execution
                # Instruments without a bar today remain at their last known mark.
                open_prices = {event.symbol: event.open for event in session_events}
                self.portfolio.mark_to_market(open_prices)
                self._session_open_equity = self._calculate_equity()
                self.risk_manager.set_portfolio_value(
                    total=float(self._session_open_equity),
                    cash=float(self.portfolio.cash),
                )

                # 3. Open Phase: Order execution & matching (sells before buys)
                open_session_events = list(session_events)
                open_session_events.sort(
                    key=lambda ev: self._open_session_event_order(
                        ev, signals=eligible_signals
                    )
                )

                for market_event in open_session_events:
                    pending = eligible_signals.get(market_event.symbol)
                    if pending is None:
                        continue
                    self._execute_open_signal(market_event, pending)

                self._session_open_equity = None

                # 4. Close Phase: Close valuation, broadcast completed MarketEvent & equity recording
                close_prices = {event.symbol: event.close for event in session_events}
                self.portfolio.mark_to_market(close_prices)
                self.risk_manager.set_portfolio_value(
                    total=float(self._calculate_equity()),
                    cash=float(self.portfolio.cash),
                )

                for market_event in session_events:
                    self.clock.advance_to(market_event.timestamp)
                    self.event_bus.publish_and_process(market_event)
                    self.event_bus.drain()

                session_timestamp = session_events[0].timestamp
                self.portfolio.record_equity(session_timestamp, close_prices)
            else:
                self._session_open_equity = None
                if self._session_decision is not None:
                    # One simultaneous daily close values the complete book before
                    # any next-session target is executed. Exits execute first but
                    # only actual proceeds can finance subsequent buys.
                    if len({event.timestamp for event in session_events}) != 1:
                        raise ValueError(
                            "session_portfolio_requires_simultaneous_daily_bars"
                        )
                    self.portfolio.mark_to_market(
                        {event.symbol: event.close for event in session_events}
                    )
                    session_events.sort(
                        key=lambda event: (
                            self._pending_signals.get(event.symbol) is None
                            or self._pending_signals[event.symbol].target_weight != 0,
                            str(event.symbol),
                        )
                    )
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
                    close_prices = {market_event.symbol: market_event.close}
                    self.portfolio.mark_to_market(close_prices)
                    self.portfolio.record_equity(market_event.timestamp, close_prices)
            self._session_open_equity = None
            if self._dividend_replay is not None:
                self._dividend_replay.after_session(current_date, self.portfolio)
            if self._session_decision is not None:
                self._session_decision(current_date)
                self.event_bus.drain()
            if self._session_completed is not None:
                self._session_completed(current_date)

        return self._build_result()

    def _session_date(self, event: MarketEvent) -> date:
        if self._dividend_replay is not None:
            return event.timestamp.astimezone(ZoneInfo("Asia/Shanghai")).date()
        return event.timestamp.date()

    def _open_session_event_order(
        self,
        event: MarketEvent,
        signals: dict[Symbol, SignalEvent] | None = None,
    ) -> tuple[int, str]:
        source = signals if signals is not None else self._pending_signals
        pending = source.get(event.symbol)
        if pending is None:
            return (3, str(event.symbol))
        if pending.target_weight == ZERO:
            return (0, str(event.symbol))
        pos = self.portfolio.positions.get(event.symbol)
        current_val = pos.market_value if pos is not None else ZERO
        target_val = (
            self._session_open_equity * pending.target_weight
            if self._session_open_equity is not None
            else ZERO
        )
        if target_val < current_val:
            return (1, str(event.symbol))
        return (2, str(event.symbol))

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

    @property
    def execution_model(self) -> ExecutionModel:
        return self._execution_model

    def _on_position_fill(self, event: FillEvent) -> None:
        position = self.portfolio.positions[event.symbol]
        self.strategy.on_position_update(event.symbol, position.quantity)

    def _execute_open_signal(self, event: MarketEvent, pending: SignalEvent) -> None:
        self.clock.advance_to(event.timestamp)
        self._current_market_event = event
        self._open_signal_context = (event.symbol, uuid.uuid4().hex)
        self._open_authorized_intent_id = None
        self._open_authorized_order_id = None
        self._executing_at_open = True
        try:
            self.portfolio.on_signal(
                replace(
                    pending,
                    timestamp=event.timestamp,
                    price=event.open,
                ),
                reference_equity=self._session_open_equity,
            )
            self.event_bus.drain()
        finally:
            self._executing_at_open = False
            self._open_signal_context = None
            self._open_authorized_intent_id = None
            self._open_authorized_order_id = None

    def _execute_close_signal(self, event: MarketEvent) -> None:
        pending = self._pending_signals.get(event.symbol)
        if (
            not self._warming_up
            and pending is not None
            and event.timestamp > pending.timestamp
        ):
            del self._pending_signals[event.symbol]
            self.portfolio.on_signal(
                replace(pending, timestamp=event.timestamp, price=event.close),
                reference_equity=None,
            )
            self.event_bus.drain()

    def _on_market_event(self, event: MarketEvent) -> None:
        """Expose this completed bar to the strategy and update market state."""
        self._current_market_event = event
        if self._execution_model is ExecutionModel.NEXT_BAR_CLOSE:
            self._execute_close_signal(event)
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
        check_price = (
            bar.open
            if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
            else bar.close
        )
        blocked = (
            is_limit_up(
                check_price, previous, instrument.limit_pct, tick=instrument.price_tick
            )
            if event.side is OrderSide.BUY
            else is_limit_down(
                check_price, previous, instrument.limit_pct, tick=instrument.price_tick
            )
        )
        if blocked:
            self._execution_blocked["limit"] += 1
        return not blocked

    def _known_market_price(self, symbol: Symbol) -> Decimal | None:
        bar = self._current_market_event
        if bar is not None and bar.symbol == symbol:
            return (
                bar.open
                if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                and self._executing_at_open
                else bar.close
            )
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
            available = position.available_qty if position is not None else ZERO
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
        if self._execution_model is ExecutionModel.NEXT_BAR_OPEN:
            is_authorized = (
                self._open_signal_context is not None
                and self._open_signal_context[0] == event.symbol
                and self._open_authorized_intent_id is None
            )
            if not is_authorized:
                self._execution_blocked["timing"] += 1
                if event.intent_id is not None:
                    self.event_bus.publish(
                        RiskDecisionEvent(
                            timestamp=event.timestamp,
                            decision_id=f"BACKTEST-RISK-{uuid.uuid4().hex[:8]}",
                            intent_id=event.intent_id,
                            passed=False,
                            symbol=event.symbol,
                            side=event.side,
                            reasons=["next_bar_open_direct_order_unsupported"],
                            resulting_order_id=None,
                            severity="warning",
                        )
                    )
                return
            self._open_authorized_intent_id = event.intent_id

        decision_id = f"BACKTEST-RISK-{uuid.uuid4().hex[:8]}"
        order_id = f"ORD-{uuid.uuid4().hex[:8]}"
        if self._execution_model is ExecutionModel.NEXT_BAR_OPEN:
            self._open_authorized_order_id = order_id
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
        if self._execution_model is ExecutionModel.NEXT_BAR_OPEN:
            is_authorized = (
                self._open_signal_context is not None
                and self._open_signal_context[0] == event.symbol
                and event.order_id == self._open_authorized_order_id
            )
            if not is_authorized:
                self._execution_blocked["timing"] += 1
                if event.intent_id is not None and event.risk_decision_id is not None:
                    self.event_bus.publish(
                        RiskDecisionEvent(
                            timestamp=event.timestamp,
                            decision_id=event.risk_decision_id,
                            intent_id=event.intent_id,
                            passed=False,
                            symbol=event.symbol,
                            side=event.side,
                            reasons=["next_bar_open_order_not_authorized"],
                            resulting_order_id=None,
                            severity="warning",
                        )
                    )
                self.event_bus.publish(
                    RiskAlertEvent(
                        timestamp=event.timestamp,
                        alert_id=f"RISK-{event.order_id}",
                        rule_name="OrderTimingRule",
                        severity="warning",
                        message="Order rejected: NEXT_BAR_OPEN prohibits direct order execution outside authorized open signal context",
                        symbol=event.symbol,
                        order_id=event.order_id,
                    )
                )
                return
            self._open_authorized_order_id = None

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
        if fill is None:
            return None
        inst = self.instruments.get(event.symbol)
        if self._multi_commission is not None and inst is not None:
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
        bar = self._current_market_event
        previous = self._previous_close.get(event.symbol)
        if (
            bar is not None
            and bar.symbol == event.symbol
            and inst is not None
            and previous is not None
            and inst.limit_pct > ZERO
            and inst.instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}
        ):
            tick = inst.price_tick or Decimal("0.01")
            up = limit_up_price(previous, inst.limit_pct, tick=tick)
            down = limit_down_price(previous, inst.limit_pct, tick=tick)
            if event.side is OrderSide.BUY and fill.fill_price > up:
                self._execution_blocked["limit"] += 1
                return None
            if event.side is OrderSide.SELL and fill.fill_price < down:
                self._execution_blocked["limit"] += 1
                return None
        fill_metadata: dict[str, Any] = {
            "bar_timestamp": fill.timestamp.isoformat(),
            "session_date": (
                self._session_date(bar).isoformat() if bar is not None else None
            ),
            "execution_phase": "open" if self._executing_at_open else "close",
            "execution_model": self._execution_model.value,
        }
        if fill.metadata:
            fill_metadata.update(fill.metadata)
        fill = replace(fill, metadata=fill_metadata)
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

        report_metadata: dict[str, Any] = {
            "order_execution_mode": order.execution_mode,
            "fee_breakdown": fill.fee_breakdown,
            "fee_rule_id": fill.fee_rule_id,
            "fee_rule_version": fill.fee_rule_version,
        }
        if fill.metadata:
            report_metadata.update(fill.metadata)

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
                metadata=report_metadata,
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

    def _validate_sorted_data_handlers(self) -> None:
        """Preflight every row before initialization without retaining events.

        This opt-in path requires private, unchanged, repeatable DataHandlers.
        Generic iterables retain the eager collect/sort path by default.
        """
        seen_handlers: set[int] = set()
        reference_timestamp = None
        for symbol, handler in self.data_handlers.items():
            if (
                type(handler) is not DataHandler
                or handler._symbol != symbol
                or id(handler) in seen_handlers
            ):
                raise ValueError("backtest_streaming_requires_distinct_data_handlers")
            seen_handlers.add(id(handler))
            previous = None
            for event in handler._iter_replay_events():
                if self._availability_mode == "observed":
                    self._require_available_observation(event)
                timestamp = event.timestamp
                if not isinstance(timestamp, datetime) or pd.isna(timestamp):
                    raise ValueError("backtest_streaming_timestamp_invalid")
                try:
                    if previous is not None and timestamp < previous:
                        raise ValueError("backtest_streaming_data_handler_unsorted")
                    if previous is None and reference_timestamp is not None:
                        # Establish comparability across streams before on_init.
                        _ = timestamp < reference_timestamp
                except TypeError as exc:
                    raise ValueError("backtest_streaming_timestamp_mismatch") from exc
                previous = timestamp
                if reference_timestamp is None:
                    reference_timestamp = timestamp

    def _merge_sorted_data_handlers(self) -> Iterable[MarketEvent]:
        """A fresh resettable merge for each prepass and the execution pass."""
        return merge(
            # heapq's single-stream tail calls iter() again. A generator wrapper
            # prevents DataHandler.__iter__ from resetting an active stream.
            *(
                (event for event in cast(DataHandler, handler)._iter_replay_events())
                for handler in self.data_handlers.values()
            ),
            key=lambda event: (event.timestamp, str(event.symbol)),
        )

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
                "execution_model": self._execution_model.value,
                "policy_id": (
                    "karkinos.backtest.next_bar_open.v1"
                    if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                    else "karkinos.backtest.next_bar_close.v2"
                ),
                "signal_basis": "completed_bar",
                "fill_basis": (
                    "strictly_later_same_instrument_bar_open"
                    if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                    else "strictly_later_same_instrument_bar_close"
                ),
                "availability_mode": self._availability_mode,
                "pending_signal_count": len(self._pending_signals),
                "limit_blocked_count": self._execution_blocked["limit"],
                "suspension_blocked_count": self._execution_blocked["suspension"],
                "risk_blocked_count": self._execution_blocked["risk"],
                "cash_blocked_count": self._execution_blocked["cash"],
                "cash_resized_count": self._cash_resized_count,
                "timing_blocked_count": self._execution_blocked.get("timing", 0),
                "capacity_model": (
                    "cumulative_bar_share_participation"
                    if self._max_volume_participation is not None
                    else (
                        "unsimulated_open_capacity"
                        if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                        else "unconstrained"
                    )
                ),
                "open_capacity_simulated": (
                    False
                    if self._execution_model is ExecutionModel.NEXT_BAR_OPEN
                    and self._max_volume_participation is None
                    else True
                    if self._max_volume_participation is not None
                    else False
                ),
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
