"""Pre-trade risk gate behavior."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, RiskAlertEvent
from core.types import OrderSide, Symbol
from risk.pre_trade import PreTradeContext, PreTradePolicy, PreTradeRiskManager
from server.db import AppDatabase
from server.services.trading_controls import TradingControlState


class StaticContextProvider:
    def __init__(
        self,
        controls: TradingControlState,
        *,
        cash: Decimal = Decimal("100000"),
        total_equity: Decimal = Decimal("100000"),
        positions: dict[Symbol, object] | None = None,
        data_quality_issues: dict[Symbol, list[str]] | None = None,
    ) -> None:
        self.controls = controls
        self.cash = cash
        self.total_equity = total_equity
        self.positions = positions or {}
        self.data_quality_issues = data_quality_issues or {}

    def snapshot(self) -> PreTradeContext:
        return PreTradeContext(
            cash=self.cash,
            total_equity=self.total_equity,
            peak_equity=self.total_equity,
            positions=self.positions,
            instruments={},
            blacklist=set(),
            st_symbols=set(),
            kill_switch_enabled=self.controls.snapshot().kill_switch_enabled,
            data_quality_issues=self.data_quality_issues,
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


def test_pre_trade_risk_blocks_order_notional_and_preserves_audit_payload(
    tmp_path,
) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []
    alerts: list[RiskAlertEvent] = []

    PreTradeRiskManager(
        bus,
        StaticContextProvider(controls),
        PreTradePolicy(
            execution_mode="manual",
            max_order_notional=Decimal("5000"),
        ),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)
    bus.subscribe(RiskAlertEvent, alerts.append)

    bus.publish_and_process(_buy_intent(quantity=Decimal("100")))
    bus.drain()

    assert orders == []
    assert len(alerts) == 1
    assert "order notional exceeds max_order_notional" in alerts[0].message
    decisions = db.get_risk_decisions_sync()
    assert len(decisions) == 1
    assert decisions[0]["passed"] == 0
    payload = json.loads(decisions[0]["payload_json"])
    assert payload["decision"]["metadata"]["order_value"] == "10000"
    assert payload["decision"]["metadata"]["policy"]["max_order_notional"] == "5000"


def test_pre_trade_risk_blocks_cash_reserve_breach(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []

    PreTradeRiskManager(
        bus,
        StaticContextProvider(controls, cash=Decimal("12000")),
        PreTradePolicy(
            execution_mode="manual",
            min_cash_reserve=Decimal("3000"),
        ),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(_buy_intent(quantity=Decimal("100")))
    bus.drain()

    assert orders == []
    decisions = db.get_risk_decisions_sync()
    assert (
        "cash reserve would fall below min_cash_reserve" in decisions[0]["reasons_json"]
    )


def test_pre_trade_risk_blocks_projected_position_weight(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []
    positions = {
        Symbol("600519"): SimpleNamespace(market_value=Decimal("45000")),
    }

    PreTradeRiskManager(
        bus,
        StaticContextProvider(
            controls,
            cash=Decimal("55000"),
            total_equity=Decimal("100000"),
            positions=positions,
        ),
        PreTradePolicy(
            execution_mode="manual",
            max_position_weight=Decimal("0.50"),
        ),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(_buy_intent(quantity=Decimal("100")))
    bus.drain()

    assert orders == []
    decisions = db.get_risk_decisions_sync()
    assert (
        "projected position weight exceeds max_position_weight"
        in decisions[0]["reasons_json"]
    )


def test_pre_trade_risk_blocks_data_quality_issues(tmp_path) -> None:
    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []

    PreTradeRiskManager(
        bus,
        StaticContextProvider(
            controls,
            data_quality_issues={Symbol("600519"): ["duplicate timestamps"]},
        ),
        PreTradePolicy(execution_mode="manual"),
        db=db,
    )
    bus.subscribe(OrderEvent, orders.append)

    bus.publish_and_process(_buy_intent())
    bus.drain()

    assert orders == []
    decisions = db.get_risk_decisions_sync()
    assert "data quality issue: duplicate timestamps" in decisions[0]["reasons_json"]


def test_pre_trade_risk_preview_reuses_rules_without_publishing_or_auditing(
    tmp_path,
) -> None:
    from risk.pre_trade import preview_pre_trade_risk

    bus = EventBus()
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    controls = TradingControlState()
    orders: list[OrderEvent] = []
    bus.subscribe(OrderEvent, orders.append)

    context = StaticContextProvider(
        controls,
        cash=Decimal("12000"),
        total_equity=Decimal("12000"),
    ).snapshot()
    preview = preview_pre_trade_risk(
        intent=_buy_intent(quantity=Decimal("100")),
        context=context,
        policy=PreTradePolicy(
            execution_mode="manual",
            min_cash_reserve=Decimal("3000"),
        ),
    )

    assert preview == {
        "schema_version": "karkinos.pre_trade_risk_preview.v1",
        "passed": False,
        "status": "blocked",
        "severity": "warning",
        "reasons": ["cash reserve would fall below min_cash_reserve"],
        "manual_confirmation_required": True,
        "does_not_create_order": True,
        "does_not_persist_decision": True,
        "metadata": {
            "quantity": "100",
            "reference_price": "100",
            "target_weight": "0.10",
            "cash": "12000",
            "total_equity": "12000",
            "order_value": "10000",
            "projected_cash": "2000",
            "current_position_value": "0",
            "projected_position_value": "10000",
            "projected_position_weight": "0.8333333333333333333333333333",
            "policy": {
                "execution_mode": "manual",
                "max_order_notional": None,
                "min_cash_reserve": "3000",
                "max_position_weight": None,
            },
        },
    }
    assert orders == []
    assert db.get_risk_decisions_sync() == []
