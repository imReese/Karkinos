"""Cross-surface contracts for canonical portfolio accounting."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.event_bus import EventBus
from core.events import FillEvent
from core.types import OrderSide, Symbol
from domain.portfolio import Portfolio
from domain.position import Position
from risk.manager import RiskManager
from server.config import BrokerFeeScheduleConfig
from server.ledger.models import LedgerEntry
from server.projections.service import build_portfolio_projection
from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown
from server.services.portfolio_ledger import rebuild_portfolio_from_ledger

pytestmark = [pytest.mark.unit, pytest.mark.trading_safety]


def test_simulation_and_ledger_projection_share_fee_inclusive_cost_basis() -> None:
    position = Position(Symbol("600519"))
    position.update_on_fill(
        "buy", Decimal("100"), Decimal("10"), commission=Decimal("5")
    )
    position.update_on_fill(
        "buy", Decimal("100"), Decimal("12"), commission=Decimal("5")
    )
    position.advance_settlement_day()
    position.update_on_fill(
        "sell", Decimal("50"), Decimal("14"), commission=Decimal("2")
    )

    projection = build_portfolio_projection(
        [
            LedgerEntry(
                entry_type="trade_buy",
                timestamp="2026-08-20T09:30:00+08:00",
                symbol="600519",
                direction="buy",
                quantity=100,
                price=10,
                commission=5,
            ),
            LedgerEntry(
                entry_type="trade_buy",
                timestamp="2026-08-21T09:30:00+08:00",
                symbol="600519",
                direction="buy",
                quantity=100,
                price=12,
                commission=5,
            ),
            LedgerEntry(
                entry_type="trade_sell",
                timestamp="2026-08-22T14:30:00+08:00",
                symbol="600519",
                direction="sell",
                quantity=50,
                price=14,
                commission=2,
            ),
        ]
    )
    projected = projection.positions["600519"]

    assert position.quantity == projected.quantity == Decimal("150")
    assert position.avg_cost == projected.avg_cost == Decimal("11.05")
    assert position.realized_pnl == projected.realized_pnl == Decimal("145.50")
    assert position.commission_paid == projected.commission_paid == Decimal("12")


def test_configured_total_fee_matches_live_rebuild_and_persisted_projection() -> None:
    config = SimpleNamespace(
        initial_cash=5000,
        assets=[],
        account_commission_rate=Decimal("0.0001"),
        account_min_commission=Decimal("5"),
        broker_fee_schedule=BrokerFeeScheduleConfig(
            stock_a_commission_rate=Decimal("0.0001"),
            stock_a_min_commission=Decimal("5"),
            stamp_tax_rate=Decimal("0.0005"),
            transfer_fee_rate=Decimal("0.00001"),
            other_fee_rate=Decimal("0.00002"),
        ),
    )
    rows = [
        _configured_trade(config, 1, "2026-08-20T09:30:00+08:00", "buy", 100, 10),
        _configured_trade(config, 2, "2026-08-21T09:30:00+08:00", "buy", 100, 12),
        _configured_trade(config, 3, "2026-08-22T14:30:00+08:00", "sell", 50, 14),
    ]

    position = Position(Symbol("600519"))
    live_portfolio = Portfolio(EventBus(), initial_cash=Decimal("5000"))
    risk_manager = RiskManager(EventBus())
    projection_entries = []
    for row in rows:
        total_fee = Decimal(row["fee_breakdown"]["total_fee"])
        position.update_on_fill(
            row["direction"],
            Decimal(str(row["quantity"])),
            Decimal(str(row["price"])),
            commission=total_fee,
        )
        fill = FillEvent(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            fill_id=f"LIVE-{row['id']}",
            order_id=f"LIVE-ORDER-{row['id']}",
            symbol=Symbol("600519"),
            side=(OrderSide.BUY if row["direction"] == "buy" else OrderSide.SELL),
            fill_price=Decimal(str(row["price"])),
            fill_quantity=Decimal(str(row["quantity"])),
            # FillEvent's legacy field carries the complete fee; the explicit
            # breakdown remains authoritative and must not be added again.
            commission=total_fee,
            slippage=Decimal("0"),
            fee_breakdown=row["fee_breakdown"],
        )
        live_portfolio.on_fill(fill)
        risk_manager.on_fill(fill)
        projection_entries.append(
            LedgerEntry(
                entry_type=f"trade_{row['direction']}",
                timestamp=row["timestamp"],
                symbol="600519",
                direction=row["direction"],
                quantity=row["quantity"],
                price=row["price"],
                commission=float(row["fee_breakdown"]["commission"]),
                fee_breakdown=row["fee_breakdown"],
            )
        )

    projection = build_portfolio_projection(
        projection_entries,
        initial_cash=5000,
    )
    rebuilt = rebuild_portfolio_from_ledger(
        config,
        _MatchedLedgerDb(rows),
    ).portfolio

    live = live_portfolio.positions[Symbol("600519")]
    projected = projection.positions["600519"]
    replayed = rebuilt.positions[Symbol("600519")]
    risk = risk_manager.positions[Symbol("600519")]
    for actual in (position, live, risk, projected, replayed):
        assert actual.quantity == Decimal("150")
        assert actual.avg_cost == Decimal("11.05033")
        assert actual.realized_pnl == Decimal("142.11250")
        assert actual.commission_paid == Decimal("15.437000")

    assert (
        live_portfolio.cash == projection.cash == rebuilt.cash == Decimal("3484.563000")
    )
    assert rows[0]["fee_breakdown"]["transfer_fee"] == "0.010000"
    assert rows[0]["fee_breakdown"]["other_fees"] == "0.020000"
    assert rows[2]["fee_breakdown"]["stamp_tax"] == "0.350000"


def _configured_trade(
    config,
    trade_id: int,
    timestamp: str,
    direction: str,
    quantity: int,
    price: int,
) -> dict:
    fee = resolve_manual_trade_fee_breakdown(
        config,
        asset_class="stock",
        direction=direction,
        quantity=quantity,
        price=price,
        symbol="600519",
    )
    assert fee is not None
    return {
        "id": trade_id,
        "timestamp": timestamp,
        "symbol": "600519",
        "direction": direction,
        "quantity": quantity,
        "price": price,
        "commission": fee.commission,
        "fee_breakdown": fee.fee_breakdown_json,
        "fee_rule_id": fee.fee_rule_id,
        "fee_rule_version": fee.fee_rule_version,
        "asset_class": "stock",
        "note": "",
    }


class _MatchedLedgerDb:
    """Legacy trade rows plus their authoritative structured ledger facts."""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def get_cash_flows_sync(self, *, limit: int, offset: int) -> list[dict]:
        return []

    def get_trades_sync(self, *, limit: int, offset: int) -> list[dict]:
        return [
            {
                key: value
                for key, value in row.items()
                if key not in {"fee_breakdown", "fee_rule_id", "fee_rule_version"}
            }
            for row in self._rows
        ]

    def get_ledger_entries_sync(self, *, limit: int, offset: int) -> list[dict]:
        return [
            {
                **row,
                "entry_type": f"trade_{row['direction']}",
                "source_ref": f"trade:{row['id']}",
                "fee_breakdown_json": json.dumps(row["fee_breakdown"]),
            }
            for row in self._rows
        ]
