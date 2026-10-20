import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import Symbol
from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.db import AppDatabase
from server.persistence.backtest_results import insert_backtest_result
from server.routes.etf_rebalance import create_router
from server.services.market.etf_rotation_automation import EtfRotationAutomationService
from server.services.portfolio.trades import (
    ManualTradeRequest,
    PortfolioTradeCommandService,
)


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


@pytest.mark.parametrize("funded", [False, True])
def test_account_capital_and_etf_holdings_are_rebuilt_from_persisted_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, funded: bool
) -> None:
    database = AppDatabase(tmp_path / "account.db")
    database.init_sync()
    if funded:
        database.record_cash_flow_sync(
            CashFlowWrite(
                command_id="synthetic-deposit",
                operator_id="synthetic-owner",
                timestamp="2026-09-01T09:00:00+08:00",
                amount=10_000.0,
                flow_type="deposit",
            )
        )
        trades = PortfolioTradeCommandService(
            SimpleNamespace(
                db=database, config=SimpleNamespace(assets=[]), scheduler=None
            )
        )
        for symbol, asset_class, price, commission in (
            ("510300", "etf", 4.0, 1.0),
            ("600000", "stock", 10.0, 2.0),
        ):
            trades.create(
                ManualTradeRequest(
                    command_id=f"synthetic-buy-{symbol}",
                    operator_id="synthetic-owner",
                    timestamp="2026-09-01T10:00:00+08:00",
                    symbol=symbol,
                    asset_class=asset_class,
                    direction="buy",
                    quantity=100.0,
                    price=price,
                    commission=commission,
                )
            )
    monkeypatch.setattr(EtfRotationAutomationService, "_database_path", database.path)

    cash, _, holdings, available = (
        EtfRotationAutomationService().resolve_account_capital_and_holdings()
    )

    assert available is True
    assert cash == (Decimal("8597") if funded else Decimal("0"))
    assert holdings == ({Symbol("510300"): 100} if funded else {})


def test_cold_reads_do_not_calculate_or_initialize_market_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from data.store import DataStore

    selected = tmp_path / "selected-data"
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(selected))
    monkeypatch.setattr(EtfRotationAutomationService, "default_data_dir", None)

    def forbidden(*args, **kwargs):
        pytest.fail("An ordinary read must not load, calculate, or prepare market data")

    monkeypatch.setattr(DataStore, "__init__", forbidden)
    monkeypatch.setattr(EtfRotationAutomationService, "evaluate_rebalance", forbidden)
    monkeypatch.setattr(
        EtfRotationAutomationService, "load_aligned_market_data", forbidden
    )
    for _ in range(2):
        dashboard = client.get("/api/trading/etf-rebalance/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["execution_status"] == "unavailable"
        assert dashboard.json()["can_execute"] is False
        for resource in ("plan", "csv", "script"):
            response = client.get(f"/api/trading/etf-rebalance/{resource}")
            assert response.status_code == 503
            assert response.json()["detail"] == "rebalance_plan_unavailable"
    assert not selected.exists()


def test_explicit_run_is_readable_without_reloading_market_data(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from data.store import DataStore

    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    result = client.post("/api/trading/etf-rebalance/run", json={})
    assert result.status_code == 200

    def forbidden(*args, **kwargs):
        pytest.fail("Reading an existing plan must not reload or recalculate it")

    monkeypatch.setattr(DataStore, "__init__", forbidden)
    monkeypatch.setattr(EtfRotationAutomationService, "evaluate_rebalance", forbidden)
    monkeypatch.setattr(
        EtfRotationAutomationService, "load_aligned_market_data", forbidden
    )
    for resource in ("dashboard", "plan", "csv", "script"):
        assert client.get(f"/api/trading/etf-rebalance/{resource}").status_code == 200
    assert client.get("/api/trading/etf-rebalance/plan").json() == result.json()


@pytest.mark.parametrize("change_at", ["during_read", "after_read", "before_publish"])
def test_changed_market_input_cannot_publish_a_plan_for_older_bars(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change_at: str
):
    from execution.rebalance_order_generator import RebalancePlan

    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    price_file = tmp_path / "real_etfs" / "513100.csv"
    read_csv = pd.read_csv

    def update_price():
        frame = read_csv(price_file)
        frame.loc[frame.index[-1], "close"] *= 2
        frame.to_csv(price_file, index=False)

    if change_at == "during_read":

        def change_while_reading(path, *args, **kwargs):
            frame = read_csv(path, *args, **kwargs)
            if Path(path) == price_file:
                update_price()
            return frame

        monkeypatch.setattr(pd, "read_csv", change_while_reading)
    elif change_at == "after_read":
        load = EtfRotationAutomationService.load_aligned_market_data

        def change_after_read(self):
            loaded = load(self)
            update_price()
            return loaded

        monkeypatch.setattr(
            EtfRotationAutomationService, "load_aligned_market_data", change_after_read
        )
    else:
        to_csv = RebalancePlan.to_csv

        def change_before_publish(self):
            result = to_csv(self)
            update_price()
            return result

        monkeypatch.setattr(RebalancePlan, "to_csv", change_before_publish)

    response = client.post("/api/trading/etf-rebalance/run", json={})
    assert response.status_code == 500
    assert "etf_market_data_changed_during_evaluation" in response.json()["detail"]
    dashboard = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert dashboard["execution_status"] == "unavailable"
    assert dashboard["can_execute"] is False
    assert dashboard["rebalance"] is None
    assert client.get("/api/trading/etf-rebalance/plan").status_code == 503


def test_empty_wal_created_by_bar_reads_does_not_abort_evaluation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from data.store import DataStore

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    wal = tmp_path / "meta.db-wal"
    initialize = DataStore.__init__
    load_bars = DataStore.load_bars

    def prepare_without_empty_wal(self, *args, **kwargs):
        initialize(self, *args, **kwargs)
        if wal.exists() and wal.stat().st_size == 0:
            wal.unlink()

    def read_and_create_empty_wal(self, *args, **kwargs):
        bars = load_bars(self, *args, **kwargs)
        wal.touch(exist_ok=True)
        assert wal.stat().st_size == 0
        return bars

    monkeypatch.setattr(DataStore, "__init__", prepare_without_empty_wal)
    monkeypatch.setattr(DataStore, "load_bars", read_and_create_empty_wal)
    response = client.post("/api/trading/etf-rebalance/run", json={})
    assert response.status_code == 200
    dashboard = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert dashboard["rebalance"]["plan_id"] == response.json()["plan_id"]
    assert dashboard["can_execute"] is True


def test_empty_wal_lifecycle_does_not_invalidate_an_existing_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    response = client.post("/api/trading/etf-rebalance/run", json={})
    assert response.status_code == 200
    wal = tmp_path / "meta.db-wal"
    wal.touch(exist_ok=True)
    assert wal.stat().st_size == 0
    assert (
        client.get("/api/trading/etf-rebalance/dashboard").json()["can_execute"] is True
    )
    wal.unlink()
    assert client.get("/api/trading/etf-rebalance/plan").json() == response.json()
    assert (
        client.get("/api/trading/etf-rebalance/dashboard").json()["can_execute"] is True
    )


def test_nonempty_wal_changes_still_invalidate_cached_plans(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from contextlib import closing

    from data.meta_store_connection import connect_meta_sqlite
    from data.store import DataStore

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    DataStore(tmp_path)
    with closing(connect_meta_sqlite(tmp_path / "meta.db")) as connection:
        connection.execute("CREATE TABLE wal_change_fixture (value INTEGER)")
        connection.execute("INSERT INTO wal_change_fixture VALUES (1)")
        connection.commit()
        assert (tmp_path / "meta.db-wal").stat().st_size > 0
        response = client.post("/api/trading/etf-rebalance/run", json={})
        assert response.status_code == 200
        connection.execute("UPDATE wal_change_fixture SET value = 2")
        connection.commit()
        assert (tmp_path / "meta.db-wal").stat().st_size > 0
        assert client.get("/api/trading/etf-rebalance/plan").status_code == 503
        dashboard = client.get("/api/trading/etf-rebalance/dashboard").json()
        assert dashboard["can_execute"] is False
        assert dashboard["rebalance"] is None


def test_default_market_directory_uses_selected_runtime_not_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    selected = tmp_path / "selected-data"
    other_cwd = tmp_path / "unrelated-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.setenv("KARKINOS_DATA_DIR", str(selected))
    monkeypatch.setattr(EtfRotationAutomationService, "default_data_dir", None)
    service = EtfRotationAutomationService()
    assert service.data_dir == selected / "real_etfs"
    assert not selected.exists()
    with pytest.raises(FileNotFoundError):
        service.load_aligned_market_data()
    assert (selected / "meta.db").exists()
    assert not (other_cwd / "data").exists()
    explicit = tmp_path / "explicit-data"
    assert EtfRotationAutomationService(explicit).data_dir == explicit


@pytest.mark.parametrize("change", ["session_advanced", "calendar_unverified"])
def test_cached_plan_fails_closed_when_session_changes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: str
):
    from server.services.market import calendar as market_calendar_dates

    monkeypatch.setenv("KARKINOS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(EtfRotationAutomationService, "default_data_dir", None)
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (Decimal("200000"), Decimal("200000"), {}, True),
    )
    session = {"calendar_verified": True, "latest_completed_trade_date": "2026-01-05"}
    monkeypatch.setattr(
        market_calendar_dates, "project_market_session", lambda db: session
    )
    result = client.post("/api/trading/etf-rebalance/run", json={})
    assert result.status_code == 200
    assert (
        client.get("/api/trading/etf-rebalance/dashboard").json()["can_execute"] is True
    )
    if change == "session_advanced":
        session["latest_completed_trade_date"] = "2099-01-01"
    else:
        session["calendar_verified"] = False
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "evaluate_rebalance",
        lambda self, **kwargs: pytest.fail(
            "Session drift must not cause GET computation"
        ),
    )
    dashboard = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert dashboard["execution_status"] == "unavailable"
    assert dashboard["can_execute"] is False
    assert client.get("/api/trading/etf-rebalance/script").status_code == 503


def test_get_etf_rebalance_plan_returns_structured_payload(client: TestClient):
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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

    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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

    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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


@pytest.mark.parametrize("change", ["cash", "holdings", "unavailable"])
def test_stale_plan_cache_invalidated_when_cash_or_holdings_change(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, change: str
):
    """P1: Verify cache does not serve stale plan when cash drops to 0 or holdings change."""
    # 1. Start with 200k cash
    current_cash = Decimal("200000")
    current_holdings = {}
    account_available = True

    monkeypatch.setattr(
        EtfRotationAutomationService,
        "resolve_account_capital_and_holdings",
        lambda self: (current_cash, current_cash, current_holdings, account_available),
    )
    EtfRotationAutomationService.reset_state()

    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
    resp1 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["rebalance"]["total_equity"] == 200000.0
    assert data1["can_execute"] is True
    assert data1["is_demo"] is False
    if change == "cash":
        current_cash = Decimal("0")
    elif change == "holdings":
        current_holdings = {"510300": 100}
    else:
        account_available = False
    monkeypatch.setattr(
        EtfRotationAutomationService,
        "evaluate_rebalance",
        lambda self, **kwargs: pytest.fail("GET must not recalculate a stale plan"),
    )
    resp2 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["execution_status"] == "unavailable"
    assert data2["can_execute"] is False
    assert data2["rebalance"] is None
    assert client.get("/api/trading/etf-rebalance/plan").status_code == 503


def test_stale_plan_cache_invalidated_when_market_data_advances(
    client: TestClient, tmp_path: Path
):
    """P1: Verify cache does not serve old date when market data advances."""
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
    resp1 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp1.status_code == 200
    data1 = resp1.json()
    old_date = data1["rebalance"]["as_of_date"]

    # Append a new date row to all ETF CSV files in the data dir
    data_dir = EtfRotationAutomationService.default_data_dir
    assert data_dir is not None
    new_date_str = "2026-05-15"
    for p in data_dir.glob("*.csv"):
        df = pd.read_csv(p)
        last_row = df.iloc[-1].copy()
        last_row["timestamp"] = new_date_str
        new_df = pd.concat([df, pd.DataFrame([last_row])], ignore_index=True)
        new_df.to_csv(p, index=False)

    # A read invalidates the stale plan; only an explicit command may replace it.
    resp2 = client.get("/api/trading/etf-rebalance/dashboard")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["rebalance"] is None
    assert data2["can_execute"] is False
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
    refreshed = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert refreshed["rebalance"]["as_of_date"] == new_date_str
    assert refreshed["rebalance"]["as_of_date"] != old_date


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
    assert data_dir is not None
    csv_513100 = data_dir / "513100.csv"
    df = pd.read_csv(csv_513100)
    df.loc[df.index[-1], "close"] = float(df.loc[df.index[-1], "close"]) + 0.05
    df.to_csv(csv_513100, index=False)

    # The changed price invalidates the read; explicit evaluation produces a new ID.
    stale = client.get("/api/trading/etf-rebalance/dashboard").json()
    assert stale["rebalance"] is None
    assert stale["can_execute"] is False
    assert client.post("/api/trading/etf-rebalance/run", json={}).status_code == 200
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
        assert strat["verification_status"] == "unverified_dataset_binding"
        assert strat["dataset_id"] == "sha256:112233445566778899aabbccddeeff00"
        assert strat["source_result_id"] == res_id
        assert strat["cumulative_return_pct"] == 150.0
        assert strat["cagr_pct"] == 18.0
        assert strat["max_drawdown_pct"] == 10.0
        assert strat["sharpe_ratio"] == 1.25
        assert strat["report_url"] == f"/backtest?id={res_id}"

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


def test_single_etf_report_does_not_overwrite_core_rotation_plan(
    client: TestClient, tmp_path: Path
):
    """Saving an etf_rotation report with only 1 ETF must not overwrite the 8-ETF rotation plan."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    import sqlite3

    with sqlite3.connect(db.path) as conn:
        # User saved a 1-ETF backtest
        single_etf_id = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps(
                {
                    "strategy": "etf_rotation",
                    "assets": [{"symbol": "510300"}],
                    "symbols": ["510300"],
                    "start_date": "2021-01-04",
                    "end_date": "2026-10-09",
                }
            ),
            initial_cash=100000.0,
            final_equity=999999.0,
            total_return=8.99,
            sharpe=3.0,
            max_dd=0.01,
            equity_curve_json="[]",
            annual_return=0.50,
            duration_days=1391,
        )
        conn.commit()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        resp = client.get("/api/trading/etf-rebalance/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        strat = data["strategy"]
        # Must NOT adopt the 1-ETF report's 899% return!
        assert strat.get("source_result_id") != single_etf_id
        assert strat["verification_status"] == "offline_reference_unbound"
        assert strat["universe_summary"].startswith("8 支核心标的")
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


def test_benchmark_return_zero_and_missing_are_truthful(
    client: TestClient, tmp_path: Path
):
    """Verify legitimate 0% benchmark is not replaced by -8.65%, and missing benchmark is None."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    import sqlite3

    with sqlite3.connect(db.path) as conn:
        # Case 1: benchmark_return = 0.0
        res_zero = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps(
                {
                    "strategy": "etf_rotation",
                    "benchmark_return": 0.0,
                }
            ),
            initial_cash=100000.0,
            final_equity=120000.0,
            total_return=0.20,
            sharpe=1.0,
            max_dd=0.05,
            equity_curve_json="[]",
            annual_return=0.10,
            duration_days=500,
        )
        conn.commit()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        EtfRotationAutomationService.bind_backtest_result(res_zero)
        dash = client.get("/api/trading/etf-rebalance/dashboard").json()
        strat = dash["strategy"]
        # Legitimate 0.0 must be preserved, not defaulted to -8.65
        assert strat["benchmark_return_pct"] == 0.0
        assert strat["excess_return_pct"] == 20.0

        # Case 2: benchmark_return is omitted
        with sqlite3.connect(db.path) as conn:
            res_none = insert_backtest_result(
                conn,
                created_at=datetime.now().isoformat(),
                config_json=json.dumps(
                    {
                        "strategy": "etf_rotation",
                    }
                ),
                initial_cash=100000.0,
                final_equity=120000.0,
                total_return=0.20,
                sharpe=1.0,
                max_dd=0.05,
                equity_curve_json="[]",
                annual_return=0.10,
                duration_days=500,
            )
            conn.commit()

        EtfRotationAutomationService.bind_backtest_result(res_none)
        dash_none = client.get("/api/trading/etf-rebalance/dashboard").json()
        strat_none = dash_none["strategy"]
        assert strat_none["benchmark_return_pct"] is None
        assert strat_none["excess_return_pct"] is None
    finally:
        EtfRotationAutomationService.reset_state()


def test_paper_book_resolution_not_masked_by_observation_without_paper(
    client: TestClient, tmp_path: Path
):
    """Verify that an observation without a paper book does not mask an earlier/coexisting observation with one."""
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    import sqlite3

    with sqlite3.connect(db.path) as conn:
        res_id = insert_backtest_result(
            conn,
            created_at=datetime.now().isoformat(),
            config_json=json.dumps({"strategy": "etf_rotation"}),
            initial_cash=100000.0,
            final_equity=150000.0,
            total_return=0.50,
            sharpe=1.0,
            max_dd=0.05,
            equity_curve_json="[]",
            annual_return=0.10,
            duration_days=500,
        )

        # Obs 1 has paper book
        conn.execute(
            """INSERT INTO research_observations
               (id, source_backtest_result_id, source_json, code_binding_json, policy_json, universe_json, started_at, lifecycle, version)
               VALUES ('obs-with-paper', ?, '{}', '{}', '{}', '[]', '2026-01-01T00:00:00Z', 'active', 0)""",
            (res_id,),
        )
        conn.execute(
            """INSERT INTO research_paper_books
               (id, observation_id, source_json, policy_json, code_binding_json, instruments_json, initial_cash, started_at, evaluation_start, lifecycle, version)
               VALUES ('book-real', 'obs-with-paper', '{}', ?, '{}', '[]', '100000', '2026-01-01T00:00:00Z', '2026-01-02', 'active', 1)""",
            (json.dumps({"limitations": [], "health_policy": None}),),
        )

        # Obs 2 created later (or higher ID) but HAS NO PAPER BOOK
        conn.execute(
            """INSERT INTO research_observations
               (id, source_backtest_result_id, source_json, code_binding_json, policy_json, universe_json, started_at, lifecycle, version)
               VALUES ('obs-without-paper', ?, '{}', '{}', '{}', '[]', '2026-01-02T00:00:00Z', 'active', 0)""",
            (res_id,),
        )
        conn.commit()

    EtfRotationAutomationService.set_database_path(db.path)
    try:
        EtfRotationAutomationService.bind_backtest_result(res_id)
        dash = client.get("/api/trading/etf-rebalance/dashboard").json()
        assert dash["paper_book"] is not None
        assert dash["paper_book"]["book_id"] == "book-real"
        assert dash["paper_book"]["observation_id"] == "obs-with-paper"
    finally:
        EtfRotationAutomationService.reset_state()
