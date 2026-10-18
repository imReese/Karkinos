"""Portfolio explanations retain the canonical trade cash impact."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.config import ServerConfig
from server.db import AppDatabase
from server.dependencies import AppState, AppStateContextMiddleware
from server.projections.portfolio_views.explainability import build_recent_drivers
from server.routes.portfolio import create_router


@pytest.mark.parametrize("checked_kind", ["trade_buy", "trade_sell"])
def test_recent_trade_amounts_include_all_persisted_fees(
    tmp_path, checked_kind
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-01T09:00:00+08:00",
        amount=10_000,
        asset_class="cash",
    )
    trades = [
        ("buy", 10, "5.21", "0", "0.01", "-1005.21"),
        ("sell", 11, "5.761", "0.55", "0.011", "1094.239"),
    ]
    for direction, price, total_fee, stamp_tax, transfer_fee, net in trades:
        day = "02" if direction == "buy" else "03"
        db.insert_ledger_entry_sync(
            entry_type=f"trade_{direction}",
            timestamp=f"2026-09-{day}T10:00:00+08:00",
            symbol="000001",
            direction=direction,
            quantity=100,
            price=price,
            commission=5,
            gross_amount=100 * price,
            net_cash_impact=net,
            fee_breakdown_json=json.dumps(
                {
                    "commission": "5",
                    "stamp_tax": stamp_tax,
                    "transfer_fee": transfer_fee,
                    "other_fees": "0.2",
                    "total_fee": total_fee,
                }
            ),
            fee_rule_id="synthetic",
            fee_rule_version="1",
            asset_class="stock",
        )
    valuation = db.publish_current_valuation_snapshot_sync()
    state = AppState()
    state.db = db
    state.config = ServerConfig(assets=[])
    app = FastAPI()
    app.add_middleware(AppStateContextMiddleware, app_state=state)
    app.include_router(create_router())
    ledger_before = db.get_ledger_entries_sync()
    valuation_before = db.get_valuation_snapshot_sync(valuation["snapshot_id"])

    with TestClient(app) as client:
        response = client.get("/api/portfolio/explainability")

    assert response.status_code == 200, response.text
    payload = response.json()
    drivers = {item["kind"]: item for item in payload["recent_drivers"]}
    expected = {"trade_buy": -1005.21, "trade_sell": 1094.239}
    assert drivers[checked_kind]["amount"] == pytest.approx(expected[checked_kind])
    for direction, price, total_fee, stamp_tax, transfer_fee, net in trades:
        driver = drivers[f"trade_{direction}"]
        assert driver["net_cash_impact"] == pytest.approx(float(net))
        assert driver["gross_amount"] == 100 * price
        assert driver["fee_breakdown"]["total_fee"] == total_fee
    cash = next(item for item in payload["equity_bridge"] if item["key"] == "cash")
    assert cash["value"] == pytest.approx(10_000 - 1005.21 + 1094.239)
    assert db.get_ledger_entries_sync() == ledger_before
    assert db.get_valuation_snapshot_sync(valuation["snapshot_id"]) == valuation_before
    with sqlite3.connect(db._path) as connection:
        for table in ("risk_decisions", "oms_orders", "fills"):
            assert (
                connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            )


@pytest.mark.parametrize("direction", ["buy", "sell"])
@pytest.mark.parametrize("structured_fees", [False, True])
def test_legacy_trade_without_net_field_uses_existing_fee_resolution(
    direction, structured_fees
) -> None:
    state = SimpleNamespace(db=None, scheduler=None, config=ServerConfig(assets=[]))
    entry = {
        "entry_type": f"trade_{direction}",
        "timestamp": "2026-09-03T10:00:00+08:00",
        "symbol": "000001",
        "direction": direction,
        "quantity": 100,
        "price": 10,
        "amount": 1000,
        "commission": 5,
        "asset_class": "stock",
    }
    if structured_fees:
        entry["fee_breakdown_json"] = json.dumps(
            {"commission": 5, "other_fees": 2, "total_fee": 7}
        )
    driver = build_recent_drivers(state, [entry])[0]
    fee = 7 if structured_fees else 5
    expected = -(1000 + fee) if direction == "buy" else 1000 - fee
    assert driver.amount == expected
    assert driver.net_cash_impact == expected
