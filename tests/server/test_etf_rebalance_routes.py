"""Tests for /api/trading/etf-rebalance HTTP routes."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes.etf_rebalance import create_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_get_etf_rebalance_plan_returns_structured_payload(client: TestClient):
    response = client.get("/api/trading/etf-rebalance/plan")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert "as_of_date" in data
    assert "total_equity" in data
    assert "turnover_ratio" in data
    assert "orders" in data
    assert "markdown_table" in data
    assert "csv_content" in data
    assert "miniqmt_script" in data

    # Verify orders structure contains symbol names
    for order in data["orders"]:
        assert "symbol" in order
        assert "name" in order
        assert len(order["name"]) > 0
        assert order["side"] in ("buy", "sell")
        assert order["side_display"] in ("买入", "卖出")
        assert order["quantity"] >= 0
        assert order["quantity"] % 100 == 0 or order["side"] == "sell"


def test_post_etf_rebalance_run_with_custom_equity_and_holdings(client: TestClient):
    payload = {
        "total_equity": 200000.0,
        "current_holdings": {
            "511010": 1000,
        },
    }
    response = client.post("/api/trading/etf-rebalance/run", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "success"
    assert data["total_equity"] == 200000.0
    assert len(data["orders"]) >= 1


def test_export_etf_rebalance_csv_and_script(client: TestClient):
    # CSV export
    csv_resp = client.get("/api/trading/etf-rebalance/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert (
        'attachment; filename="etf_rebalance_orders.csv"'
        in csv_resp.headers["content-disposition"]
    )
    csv_text = csv_resp.text
    assert "证券代码,证券名称,买卖方向,委托数量,预估价格,预估金额,调仓说明" in csv_text

    # Script export
    script_resp = client.get("/api/trading/etf-rebalance/script")
    assert script_resp.status_code == 200
    assert "execute_rebalance_miniqmt.py" in script_resp.headers["content-disposition"]
    script_text = script_resp.text
    assert "xtquant" in script_text
    assert "XtQuantTrader" in script_text


def test_get_etf_rebalance_dashboard_provides_strategy_returns_and_orders(
    client: TestClient,
):
    resp = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    # Strategy verified backtest metrics
    assert "strategy" in data
    assert data["strategy"]["cumulative_return_pct"] == 160.53
    assert data["strategy"]["cagr_pct"] == 18.94
    assert data["strategy"]["sharpe_ratio"] == 1.09
    assert data["strategy"]["max_drawdown_pct"] == 11.87

    # Orders and execution readiness
    assert "orders" in data
    assert "execution_status" in data
    assert data["has_pending_orders"] is True


def test_post_etf_rebalance_execute_places_orders_and_returns_receipt(
    client: TestClient,
):
    payload = {"operator": "reese", "note": "一键执行实盘调仓"}
    resp = client.post("/api/trading/etf-rebalance/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    assert data["operator"] == "reese"
    assert "batch_id" in data
    assert data["orders_count"] > 0
    assert len(data["executed_orders"]) == data["orders_count"]

    # Verify each executed order record
    for record in data["executed_orders"]:
        assert record["status"] == "submitted"
        assert record["order_id"].startswith("ORD-")
        assert record["side"] in ("buy", "sell")
        assert len(record["name"]) > 0

    # Verify dashboard now reflects execution
    dash_resp = client.get("/api/trading/etf-rebalance/dashboard")
    dash_data = dash_resp.json()
    assert dash_data["execution_status"] == "already_executed_today"
    assert dash_data["last_execution"]["batch_id"] == data["batch_id"]


def test_etf_rebalance_target_weights_and_cash_budget_bounds(client: TestClient):
    resp = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    rebal = data["rebalance"]
    assert rebal is not None
    assert rebal["total_equity"] > 0
    assert rebal["total_buy_amount"] <= rebal["total_equity"]

    # Sum of target weights must not exceed 1.0 (no leverage)
    target_weight_sum = sum(o["target_weight"] for o in rebal["orders"])
    assert target_weight_sum <= 1.0

    # Ensure negative-momentum/broken-MA asset 510300 is not selected
    buy_symbols = {o["symbol"] for o in rebal["orders"] if o["side"] == "buy"}
    assert "510300" not in buy_symbols

    # Top-K (2 assets) are selected
    assert len(buy_symbols) == 2
    assert "512890" in buy_symbols
    assert "513100" in buy_symbols
