"""Pre-trade risk gate behavior."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, RiskAlertEvent
from core.types import OrderSide, Symbol
from risk.pre_trade import PreTradeContext, PreTradePolicy, PreTradeRiskManager
from server.db import AppDatabase
from server.services.trading_controls import TradingControlState


class StaticContextProvider:
    def __init__(self, controls: TradingControlState) -> None:
        self.controls = controls

    def snapshot(self) -> PreTradeContext:
        return PreTradeContext(
            cash=Decimal("100000"),
            total_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
            positions={},
            instruments={},
            blacklist=set(),
            st_symbols=set(),
            kill_switch_enabled=self.controls.snapshot().kill_switch_enabled,
        )


def _buy_intent(quantity: Decimal = Decimal("100")) -> OrderIntentEvent:
    return OrderIntentEvent(
        timestamp=datetime(2026, 4, 18, 14, 50),
        intent_id="INTENT-1",
        strategy_id="unit_test",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.10"),
        quantity=quantity,
        reference_price=Decimal("100"),
    )


def test_pre_trade_risk_approves_valid_intent_and_audits(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []

    PreTradeRiskManager(
        bus,
        StaticContextProvider(controls),
        PreTradePolicy(execution_mode="manual"),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(_buy_intent())
    bus.drain()

    assert len(orders) == 1
    assert orders[0].intent_id == "INTENT-1"
    assert orders[0].execution_mode == "manual"
    decisions = db.get_risk_decisions_sync()
    assert len(decisions) == 1
    assert decisions[0]["passed"] == 1


def test_pre_trade_risk_blocks_buy_when_kill_switch_enabled(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    controls.set_kill_switch(True, "operator stop")
    orders: list[OrderEvent] = []
    alerts: list[RiskAlertEvent] = []

    PreTradeRiskManager(
        bus,
        StaticContextProvider(controls),
        PreTradePolicy(execution_mode="manual"),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)
    bus.subscribe(RiskAlertEvent, alerts.append)

    bus.publish_and_process(_buy_intent())
    bus.drain()

    assert orders == []
    assert len(alerts) == 1
    assert "kill switch" in alerts[0].message
    decisions = db.get_risk_decisions_sync()
    assert len(decisions) == 1
    assert decisions[0]["passed"] == 0
