"""Demonstrate the Phase 1 safe trading pipeline.

Run:
    uv run python scripts/demo_phase1_pipeline.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.events import OrderEvent, OrderIntentEvent, RiskAlertEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
from domain.position import Position
from execution.gateway import ManualConfirmGateway
from risk.pre_trade import PreTradePolicy, PreTradeRiskManager
from server.services.live_context import LiveContextProvider
from server.services.trading_controls import TradingControlState


class InMemoryDemoDb:
    """Tiny in-memory SQLite adapter for the demo pipeline."""

    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE risk_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL,
                intent_id TEXT NOT NULL,
                passed INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                reasons_json TEXT NOT NULL,
                resulting_order_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE manual_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                intent_id TEXT,
                risk_decision_id TEXT,
                execution_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def save_risk_decision_sync(self, *, intent, decision) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO risk_decisions (
                decision_id, intent_id, passed, symbol, side, reasons_json,
                resulting_order_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                decision.intent_id,
                1 if decision.passed else 0,
                str(decision.symbol),
                decision.side.value,
                json.dumps(decision.reasons, ensure_ascii=False),
                decision.resulting_order_id,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_risk_decisions_sync(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM risk_decisions ORDER BY id ASC"
        ).fetchall()
        return [dict(row) for row in rows]

    def save_manual_order_sync(
        self,
        *,
        order_id: str,
        timestamp: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None,
        intent_id: str | None,
        risk_decision_id: str | None,
        execution_mode: str,
        status: str,
        payload: dict[str, Any],
    ) -> int:
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            """
            INSERT INTO manual_orders (
                order_id, timestamp, symbol, side, order_type, quantity, price,
                intent_id, risk_decision_id, execution_mode, status, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                order_id,
                timestamp,
                symbol,
                side,
                order_type,
                quantity,
                price,
                intent_id,
                risk_decision_id,
                execution_mode,
                status,
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def get_manual_order_sync(self, order_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM manual_orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_manual_order_status_sync(
        self, *, order_id: str, status: str, note: str = ""
    ) -> dict[str, Any] | None:
        self.conn.execute(
            """
            UPDATE manual_orders
            SET status = ?, note = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (status, note, datetime.now().isoformat(), order_id),
        )
        self.conn.commit()
        return self.get_manual_order_sync(order_id)


def make_portfolio() -> SimpleNamespace:
    symbol = Symbol("600519")
    position = Position(symbol)
    position.quantity = Decimal("100")
    position.market_value = Decimal("17000")
    return SimpleNamespace(
        cash=Decimal("100000"),
        positions={symbol: position},
        instruments={},
    )


def make_intent(intent_id: str) -> OrderIntentEvent:
    return OrderIntentEvent(
        timestamp=datetime.now(),
        intent_id=intent_id,
        strategy_id="demo_strategy",
        symbol=Symbol("600519"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("170.00"),
        reason="demo target-weight rebalance",
    )


def print_decision(prefix: str, decision: dict[str, Any]) -> None:
    reasons = json.loads(decision["reasons_json"])
    print(
        f"{prefix}: decision_id={decision['decision_id']} "
        f"passed={bool(decision['passed'])} reasons={reasons} "
        f"resulting_order_id={decision['resulting_order_id']}"
    )


def main() -> None:
    db = InMemoryDemoDb()
    bus = EventBus()
    controls = TradingControlState()
    portfolio = make_portfolio()

    context_provider = LiveContextProvider(
        portfolio_getter=lambda: portfolio,
        controls=controls,
    )
    PreTradeRiskManager(
        bus,
        context_provider,
        PreTradePolicy(execution_mode="manual"),
        db=db,
    )
    gateway = ManualConfirmGateway(bus, db=db)

    decisions: list[RiskDecisionEvent] = []
    orders: list[OrderEvent] = []
    alerts: list[RiskAlertEvent] = []
    bus.subscribe(RiskDecisionEvent, decisions.append)
    bus.subscribe(OrderEvent, orders.append)
    bus.subscribe(RiskAlertEvent, alerts.append)

    print("1) Submit BUY intent while kill switch is off")
    bus.publish_and_process(make_intent("INTENT-DEMO-1"))
    bus.drain()

    first_decision = db.get_risk_decisions_sync()[-1]
    print_decision("   Risk audit", first_decision)

    pending_order_id = first_decision["resulting_order_id"]
    pending_order = db.get_manual_order_sync(pending_order_id)
    print(
        "   Manual gateway: "
        f"order_id={pending_order['order_id']} status={pending_order['status']}"
    )

    confirmed = gateway.confirm_order(pending_order_id)
    print(
        "   Operator confirm: "
        f"order_id={confirmed['order_id']} status={confirmed['status']}"
    )

    print("\n2) Enable kill switch and submit another BUY intent")
    controls.set_kill_switch(True, "demo kill switch")
    bus.publish_and_process(make_intent("INTENT-DEMO-2"))
    bus.drain()

    second_decision = db.get_risk_decisions_sync()[-1]
    print_decision("   Risk audit", second_decision)
    if alerts:
        print(f"   Risk alert: {alerts[-1].message}")

    print("\nDemo complete.")


if __name__ == "__main__":
    main()
