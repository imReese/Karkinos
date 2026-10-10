import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.db import AppDatabase
from server.persistence.backtest_results import insert_backtest_result
from server.routes.etf_rebalance import create_router
from server.services.etf_rotation_automation import EtfRotationAutomationService


@pytest.fixture(autouse=True)
def isolated_etf_market_data(tmp_path: Path):
    """Generate isolated deterministic ETF bars so tests do not depend on local downloaded files."""
    data_dir = tmp_path / "real_etfs"
    data_dir.mkdir(parents=True, exist_ok=True)

    dates = pd.bdate_range("2026-01-05", periods=80)
    trend_rates = {
        "512890": (2.0, 0.005),  # Strong upward -> Top 1
        "513100": (10.0, 0.004),  # Strong upward -> Top 2
        "518880": (4.0, 0.002),
        "513500": (1.5, 0.001),
        "510500": (6.0, 0.0002),
        "159915": (2.0, -0.001),
        "510300": (4.0, -0.003),  # Downward -> Excluded (below MA)
        "511010": (100.0, 0.0),  # Cash proxy
    }

    for sym, (base_px, rate) in trend_rates.items():
        prices = base_px * ((1.0 + rate) ** np.arange(len(dates)))
        df = pd.DataFrame(
            {
                "timestamp": dates,
                "open": prices,
                "high": prices * 1.01,
                "low": prices * 0.99,
                "close": prices,
                "volume": [1000000] * len(dates),
            }
        )
        df.to_csv(data_dir / f"{sym}.csv", index=False)

    original_dir = EtfRotationAutomationService.default_data_dir
    EtfRotationAutomationService.default_data_dir = data_dir
    EtfRotationAutomationService.reset_state()

    yield

    EtfRotationAutomationService.default_data_dir = original_dir
    EtfRotationAutomationService.reset_state()


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
    assert data["is_custom_simulation"] is True
    assert data["capital_source"] == "custom_simulation"
    assert len(data["orders"]) >= 1

    # Verify dashboard reflects that this plan cannot be executed as real trading
    dash_resp = client.get("/api/trading/etf-rebalance/dashboard")
    dash_data = dash_resp.json()
    assert dash_data["is_custom_simulation"] is True
    assert dash_data["can_execute"] is False
    assert dash_data["capital_quarantined"] is True

    # Verify custom simulation blocks script export
    script_resp = client.get("/api/trading/etf-rebalance/script")
    assert script_resp.status_code == 400
    assert "自定义假设试算模式" in script_resp.json()["detail"]

    # Verify custom simulation marks CSV filename
    csv_resp = client.get("/api/trading/etf-rebalance/csv")
    assert csv_resp.status_code == 200
    assert (
        'filename="custom_etf_rebalance_review.csv"'
        in csv_resp.headers["content-disposition"]
    )


def test_export_etf_rebalance_csv_and_script(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    # Simulate a real ledger account with cash
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    EtfRotationAutomationService.reset_state()

    # CSV export
    csv_resp = client.get("/api/trading/etf-rebalance/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert (
        'filename="etf_rebalance_review.csv"' in csv_resp.headers["content-disposition"]
    )
    csv_text = csv_resp.text
    assert "证券代码,证券名称,买卖方向,委托数量,预估价格,预估金额,调仓说明" in csv_text

    # Script export as read-only draft template
    script_resp = client.get("/api/trading/etf-rebalance/script")
    assert script_resp.status_code == 200
    assert "draft_rebalance_miniqmt.py" in script_resp.headers["content-disposition"]
    script_text = script_resp.text
    assert "DRAFT REVIEW TEMPLATE" in script_text
    assert "xtquant" in script_text
    assert "XtQuantTrader" in script_text
    # Verify no actual order_stock calls exist in the exported script
    assert "order_stock" not in script_text


def test_get_etf_rebalance_dashboard_provides_strategy_returns_and_orders(
    client: TestClient,
):
    resp = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    # Strategy offline reference metrics
    assert "strategy" in data
    assert data["strategy"]["cumulative_return_pct"] == 160.53
    assert data["strategy"]["cagr_pct"] == 18.94
    assert data["strategy"]["sharpe_ratio"] == 1.09
    assert data["strategy"]["max_drawdown_pct"] == 11.87
    assert data["strategy"]["verification_status"] == "offline_reference_unbound"

    # Orders and execution readiness
    assert "orders" in data
    assert "execution_status" in data
    assert data["has_pending_orders"] is True


def test_demo_mode_quarantined_when_account_has_no_cash_or_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    # Simulate account with zero cash and no ledger availability
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal(0), Decimal(0), {}, False),
    )
    EtfRotationAutomationService.reset_state()

    dash_resp = client.get("/api/trading/etf-rebalance/dashboard")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert dash_data["is_demo"] is True
    assert dash_data["can_execute"] is False
    assert dash_data["rebalance"]["capital_source"] == "fallback_demo"

    # In demo mode, script export is blocked and CSV is marked demo
    demo_script_resp = client.get("/api/trading/etf-rebalance/script")
    assert demo_script_resp.status_code == 400
    assert "演示资金隔离模式下禁止导出券商执行脚本" in demo_script_resp.json()["detail"]

    demo_csv_resp = client.get("/api/trading/etf-rebalance/csv")
    assert demo_csv_resp.status_code == 200
    assert (
        'filename="demo_etf_rebalance_review.csv"'
        in demo_csv_resp.headers["content-disposition"]
    )

    # In demo mode, execution is rejected
    demo_exec_resp = client.post(
        "/api/trading/etf-rebalance/execute", json={"operator": "reese"}
    )
    assert demo_exec_resp.status_code == 200
    assert demo_exec_resp.json()["status"] == "rejected"
    assert "演示资金隔离模式" in demo_exec_resp.json()["message"]


def test_post_etf_rebalance_execute_records_simulated_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    # Set up real account with available cash
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    EtfRotationAutomationService.reset_state()

    payload = {"operator": "reese", "note": "模拟调仓试算"}
    resp = client.post("/api/trading/etf-rebalance/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "success"
    assert data["is_simulated"] is True
    assert data["operator"] == "reese"
    assert "batch_id" in data
    assert data["orders_count"] > 0
    assert len(data["executed_orders"]) == data["orders_count"]

    # Verify each executed order record is simulated_preview, NOT claiming broker submission
    for record in data["executed_orders"]:
        assert record["status"] == "simulated_preview"
        assert record["is_simulated"] is True
        assert record["order_id"].startswith("ORD-")
        assert record["side"] in ("buy", "sell")
        assert len(record["name"]) > 0

    # Verify dashboard reflects execution for this exact plan
    dash_resp = client.get("/api/trading/etf-rebalance/dashboard")
    dash_data = dash_resp.json()
    assert dash_data["execution_status"] == "already_executed_today"
    assert dash_data["last_execution"]["batch_id"] == data["batch_id"]

    # Now verify that generating a different plan unblocks execution status for the new plan
    run_resp = client.post(
        "/api/trading/etf-rebalance/run", json={"total_equity": 500000.0}
    )
    assert run_resp.status_code == 200
    new_dash = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert new_dash["execution_status"] == "ready_to_trade"
    assert new_dash["last_execution"] is None


def test_custom_simulation_rejects_execute(client: TestClient):
    client.post("/api/trading/etf-rebalance/run", json={"total_equity": 200000.0})
    resp = client.post("/api/trading/etf-rebalance/execute", json={"operator": "reese"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert "自定义假设输入" in data["message"]


def test_unavailable_status_when_data_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("Missing ETF market bars")

    monkeypatch.setattr(
        EtfRotationAutomationService, "load_aligned_market_data", _raise
    )
    EtfRotationAutomationService.reset_state()

    dash_resp = client.get("/api/trading/etf-rebalance/dashboard")
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert dash_data["execution_status"] == "unavailable"
    assert dash_data["can_execute"] is False
    assert dash_data["rebalance"] is None
    assert dash_data["orders"] == []


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


def test_stale_plan_cache_invalidated_when_cash_or_holdings_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """P1: Verify cache does not serve stale plan when cash drops to 0 or holdings change."""
    # 1. Start with 200k cash
    current_cash = Decimal("200000")
    current_holdings = {}

    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (current_cash, current_cash, current_holdings, True),
    )
    EtfRotationAutomationService.reset_state()

    resp1 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["rebalance"]["total_equity"] == 200000.0
    assert data1["can_execute"] is True
    assert data1["is_demo"] is False
    plan_id_1 = data1["rebalance"]["plan_id"]

    # 2. Simulate cash dropping to 0
    current_cash = Decimal("0")
    # Call dashboard without force_refresh - it should detect staleness, recompute, and quarantine to demo
    resp2 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["is_demo"] is True
    assert data2["can_execute"] is False
    assert data2["rebalance"]["capital_source"] == "fallback_demo"
    assert data2["rebalance"]["plan_id"] != plan_id_1


def test_stale_plan_cache_invalidated_when_market_data_advances(
    client: TestClient, tmp_path: Path
):
    """P1: Verify cache does not serve old date when market data advances."""
    # Run dashboard to populate cache
    resp1 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp1.status_code == 200
    data1 = resp1.json()
    old_date = data1["rebalance"]["as_of_date"]

    # Append a new date row to all ETF CSV files in the data dir
    data_dir = EtfRotationAutomationService.default_data_dir
    new_date_str = "2026-05-15"
    for p in data_dir.glob("*.csv"):
        df = pd.read_csv(p)
        last_row = df.iloc[-1].copy()
        last_row["timestamp"] = new_date_str
        new_df = pd.concat([df, pd.DataFrame([last_row])], ignore_index=True)
        new_df.to_csv(p, index=False)

    # Next dashboard request should detect that market data date advanced and return new date
    resp2 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["rebalance"]["as_of_date"] == new_date_str
    assert data2["rebalance"]["as_of_date"] != old_date


def test_plan_id_incorporates_prices_and_unblocks_execution_on_price_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """P2: Verify modifying prices changes plan_id and unblocks already_executed_today."""
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    EtfRotationAutomationService.reset_state()

    # 1. Execute initial plan
    exec_resp = client.post(
        "/api/trading/etf-rebalance/execute", json={"operator": "reese"}
    )
    assert exec_resp.status_code == 200
    plan_id_1 = exec_resp.json()["plan_id"]

    dash_1 = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert dash_1["execution_status"] == "already_executed_today"
    assert dash_1["can_execute"] is False

    # 2. Modify one ETF price slightly (e.g. from 10.0 to 10.001) in CSV file
    data_dir = EtfRotationAutomationService.default_data_dir
    csv_513100 = data_dir / "513100.csv"
    df = pd.read_csv(csv_513100)
    df.loc[df.index[-1], "close"] = float(df.loc[df.index[-1], "close"]) + 0.05
    df.to_csv(csv_513100, index=False)

    # 3. Next dashboard call should detect price change, produce new plan_id, and unblock execution
    dash_2 = client.get("/api/trading/etf-rebalance/dashboard").json()
    plan_id_2 = dash_2["rebalance"]["plan_id"]
    assert plan_id_2 != plan_id_1
    assert dash_2["execution_status"] == "ready_to_trade"
    assert dash_2["can_execute"] is True
    assert dash_2["last_execution"] is None


def test_dashboard_resolves_saved_backtest_result_and_paper_book(
    client: TestClient, tmp_path: Path
):
    """Verify ETF dashboard dynamically binds saved backtest result and paper book."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    import sqlite3

    with sqlite3.connect(db.path) as conn:
        res_id = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps(
                {
                    "strategy": "etf_rotation",
                    "dataset_id": "sha256:112233445566778899aabbccddeeff00",
                    "start_date": "2021-01-04",
                    "end_date": "2026-10-09",
                    "benchmark_return": -8.65,
                }
            ),
            initial_cash=100000.0,
            final_equity=250000.0,
            total_return=1.50,
            sharpe=1.25,
            max_dd=0.10,
            equity_curve_json="[]",
            annual_return=0.18,
            duration_days=1391,
            metrics_json=json.dumps(
                {
                    "annual_return": 0.18,
                    "calmar": 1.80,
                    "benchmark_return": -8.65,
                }
            ),
        )

        obs_id = "obs-etf-test-01"
        conn.execute(
            """INSERT INTO research_observations
               (id, source_backtest_result_id, source_json, code_binding_json, policy_json, universe_json, started_at, lifecycle, version)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0)""",
            (
                obs_id,
                res_id,
                json.dumps({"strategy_kind": "etf_rotation"}),
                json.dumps({}),
                json.dumps({}),
                json.dumps([]),
                "2026-01-01T00:00:00Z",
            ),
        )

        book_id = "book-etf-test-01"
        conn.execute(
            """INSERT INTO research_paper_books
               (id, observation_id, source_json, policy_json, code_binding_json, instruments_json, initial_cash, started_at, evaluation_start, lifecycle, version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1)""",
            (
                book_id,
                obs_id,
                json.dumps({}),
                json.dumps({"limitations": [], "health_policy": None}),
                json.dumps({}),
                json.dumps([]),
                "100000",
                "2026-01-01T00:00:00Z",
                "2026-01-02",
            ),
        )

        conn.execute(
            """INSERT INTO research_paper_steps
               (book_id, session, book_version, dataset_id, settled_at, input_json, projection_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                book_id,
                "2026-01-05",
                1,
                "sha256:forward_dataset",
                "2026-01-05T15:30:00Z",
                "{}",
                json.dumps(
                    {
                        "session": "2026-01-05",
                        "cash": "105000",
                        "equity": "105000",
                        "dividend_receivable": "0",
                        "dividend_income": "0",
                        "positions": {},
                        "fills": [
                            {
                                "commission": "15.00",
                                "slippage": "25.00",
                                "fill_price": "2.5",
                                "fill_quantity": "10000",
                            }
                        ],
                        "attempts": [],
                    }
                ),
            ),
        )
        conn.commit()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        resp = client.get("/api/trading/etf-rebalance/dashboard")
        assert resp.status_code == 200
        data = resp.json()

        # Strategy verification
        strat = data["strategy"]
        assert strat["verification_status"] == "bound_dataset_verified"
        assert strat["dataset_id"] == "sha256:112233445566778899aabbccddeeff00"
        assert strat["source_result_id"] == res_id
        assert strat["cumulative_return_pct"] == 150.0
        assert strat["cagr_pct"] == 18.0
        assert strat["max_drawdown_pct"] == 10.0
        assert strat["sharpe_ratio"] == 1.25
        assert strat["report_url"] == f"/research?tab=backtest&id={res_id}"

        # Paper book summary
        paper = data["paper_book"]
        assert paper is not None
        assert paper["book_id"] == book_id
        assert paper["observation_id"] == obs_id
        assert paper["settled_sessions"] == 1
        assert paper["net_return_pct"] == 5.0
        assert paper["max_drawdown_pct"] == 0.0
        assert paper["fees_paid"] == "15"
        assert paper["slippage_cost"] == "25"
        assert paper["through_session"] == "2026-01-05"
    finally:
        EtfRotationAutomationService.reset_state()


def test_dashboard_explicit_binding_with_bind_backtest_result(
    client: TestClient, tmp_path: Path
):
    """Verify bind_backtest_result explicitly pins a specific backtest result."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    import sqlite3

    with sqlite3.connect(db.path) as conn:
        res1 = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps(
                {
                    "strategy": "etf_rotation",
                    "dataset_id": "sha256:first_dataset",
                }
            ),
            initial_cash=100000.0,
            final_equity=200000.0,
            total_return=1.00,
            sharpe=1.1,
            max_dd=0.15,
            equity_curve_json="[]",
            annual_return=0.15,
            duration_days=1000,
        )
        res2 = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps(
                {
                    "strategy": "etf_rotation",
                    "dataset_id": "sha256:second_dataset",
                }
            ),
            initial_cash=100000.0,
            final_equity=300000.0,
            total_return=2.00,
            sharpe=1.5,
            max_dd=0.08,
            equity_curve_json="[]",
            annual_return=0.25,
            duration_days=1200,
        )
        conn.commit()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        # Bind res1 explicitly
        EtfRotationAutomationService.bind_backtest_result(res1)
        dash1 = client.get("/api/trading/etf-rebalance/dashboard").json()
        assert dash1["strategy"]["source_result_id"] == res1
        assert dash1["strategy"]["cumulative_return_pct"] == 100.0
        assert dash1["strategy"]["dataset_id"] == "sha256:first_dataset"

        # Bind res2 explicitly
        EtfRotationAutomationService.bind_backtest_result(res2)
        dash2 = client.get("/api/trading/etf-rebalance/dashboard").json()
        assert dash2["strategy"]["source_result_id"] == res2
        assert dash2["strategy"]["cumulative_return_pct"] == 200.0
        assert dash2["strategy"]["dataset_id"] == "sha256:second_dataset"
    finally:
        EtfRotationAutomationService.reset_state()


def test_dashboard_falls_back_gracefully_when_no_saved_backtest(
    client: TestClient, tmp_path: Path
):
    """Verify dashboard falls back to baseline offline reference when no etf_rotation report is found."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        resp = client.get("/api/trading/etf-rebalance/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"]["verification_status"] == "offline_reference_unbound"
        assert data["paper_book"] is None
    finally:
        EtfRotationAutomationService.reset_state()
