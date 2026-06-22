"""Strategy runtime lifecycle contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.events import FillEvent, MarketEvent, OrderEvent
from core.types import BarFrequency, OrderSide, OrderType, Symbol
from strategy import (
    STRATEGY_RUNTIME_LIFECYCLE_HOOKS,
    StrategyLifecycleHook,
    StrategyRuntimeContext,
    StrategyRuntimeRunner,
)


def test_strategy_runtime_interface_declares_full_lifecycle_hooks() -> None:
    assert [hook.value for hook in STRATEGY_RUNTIME_LIFECYCLE_HOOKS] == [
        "initialize",
        "before_market_open",
        "on_bar",
        "on_tick",
        "after_market_close",
        "on_order_update",
        "on_fill_update",
    ]


def test_strategy_runtime_runner_invokes_hooks_in_deterministic_order() -> None:
    context = StrategyRuntimeContext(
        strategy_id="recording_strategy",
        run_id="run-001",
        symbols=(Symbol("600519"),),
        parameters={"lookback": 20},
        metadata={"dataset_id": "sha256:fixture"},
    )
    bar = MarketEvent(
        timestamp=datetime(2026, 6, 22, 9, 31, tzinfo=UTC),
        symbol=Symbol("600519"),
        open=Decimal("10.00"),
        high=Decimal("10.50"),
        low=Decimal("9.90"),
        close=Decimal("10.20"),
        volume=Decimal("1000"),
        frequency=BarFrequency.MIN_1,
    )
    tick = MarketEvent(
        timestamp=datetime(2026, 6, 22, 9, 31, 30, tzinfo=UTC),
        symbol=Symbol("600519"),
        open=Decimal("10.20"),
        high=Decimal("10.20"),
        low=Decimal("10.20"),
        close=Decimal("10.20"),
        volume=Decimal("100"),
        frequency=BarFrequency.TICK,
    )
    order_update = OrderEvent(
        timestamp=datetime(2026, 6, 22, 9, 32, tzinfo=UTC),
        order_id="paper-order-001",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("100"),
        price=Decimal("10.20"),
        execution_mode="paper",
    )
    fill_update = FillEvent(
        timestamp=datetime(2026, 6, 22, 9, 33, tzinfo=UTC),
        fill_id="paper-fill-001",
        order_id="paper-order-001",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        fill_price=Decimal("10.20"),
        fill_quantity=Decimal("100"),
        commission=Decimal("5"),
        slippage=Decimal("0"),
    )
    strategy = _RecordingRuntimeStrategy()

    result = StrategyRuntimeRunner().run_session(
        strategy=strategy,
        context=context,
        bars=(bar,),
        ticks=(tick,),
        order_updates=(order_update,),
        fill_updates=(fill_update,),
    )

    assert strategy.calls == [
        ("initialize", "run-001"),
        ("before_market_open", "run-001"),
        ("on_bar", "600519", "1m"),
        ("on_tick", "600519", "tick"),
        ("after_market_close", "run-001"),
        ("on_order_update", "paper-order-001"),
        ("on_fill_update", "paper-fill-001"),
    ]
    assert [record.hook for record in result.records] == [
        StrategyLifecycleHook.INITIALIZE,
        StrategyLifecycleHook.BEFORE_MARKET_OPEN,
        StrategyLifecycleHook.ON_BAR,
        StrategyLifecycleHook.ON_TICK,
        StrategyLifecycleHook.AFTER_MARKET_CLOSE,
        StrategyLifecycleHook.ON_ORDER_UPDATE,
        StrategyLifecycleHook.ON_FILL_UPDATE,
    ]
    assert result.strategy_id == "recording_strategy"
    assert result.run_id == "run-001"


def test_strategy_runtime_context_is_read_only_without_broker_submit_capability() -> (
    None
):
    account_facts = {"cash": Decimal("10000"), "source": "fixture"}
    positions = {
        "600519": {"quantity": Decimal("100"), "available": Decimal("0")},
    }
    risk_limits = {"max_single_symbol_weight": Decimal("0.20")}

    context = StrategyRuntimeContext(
        strategy_id="read_only_strategy",
        run_id="run-002",
        symbols=(Symbol("600519"),),
        account_facts=account_facts,
        positions=positions,
        risk_limits=risk_limits,
    )

    account_facts["cash"] = Decimal("0")
    positions["600519"]["quantity"] = Decimal("999")
    risk_limits["max_single_symbol_weight"] = Decimal("1.00")

    assert context.account_facts["cash"] == Decimal("10000")
    assert context.positions["600519"]["quantity"] == Decimal("100")
    assert context.risk_limits["max_single_symbol_weight"] == Decimal("0.20")

    with pytest.raises(TypeError):
        context.account_facts["cash"] = Decimal("1")
    with pytest.raises(TypeError):
        context.positions["600519"]["quantity"] = Decimal("1")
    with pytest.raises(TypeError):
        context.risk_limits["max_single_symbol_weight"] = Decimal("0.50")

    with pytest.raises(Exception):
        context.run_id = "mutated"

    assert context.broker_order_submission_enabled is False
    assert not hasattr(context, "submit_order")
    assert not hasattr(context, "broker")
    assert not hasattr(context, "broker_client")


class _RecordingRuntimeStrategy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def initialize(self, context: StrategyRuntimeContext) -> None:
        self.calls.append(("initialize", context.run_id))

    def before_market_open(self, context: StrategyRuntimeContext) -> None:
        self.calls.append(("before_market_open", context.run_id))

    def on_bar(self, context: StrategyRuntimeContext, event: MarketEvent) -> None:
        self.calls.append(("on_bar", str(event.symbol), event.frequency.value))

    def on_tick(self, context: StrategyRuntimeContext, event: MarketEvent) -> None:
        self.calls.append(("on_tick", str(event.symbol), event.frequency.value))

    def after_market_close(self, context: StrategyRuntimeContext) -> None:
        self.calls.append(("after_market_close", context.run_id))

    def on_order_update(
        self,
        context: StrategyRuntimeContext,
        event: OrderEvent,
    ) -> None:
        self.calls.append(("on_order_update", event.order_id))

    def on_fill_update(
        self,
        context: StrategyRuntimeContext,
        event: FillEvent,
    ) -> None:
        self.calls.append(("on_fill_update", event.fill_id))
