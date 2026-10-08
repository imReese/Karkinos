"""The registered allocation runs through real Dataset replay and HTTP storage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from core.types import InstrumentKey, InstrumentType
from data.handler import DataHandler
from data.market.contracts import DailyBarRequest
from data.providers.tdx import TdxDailyBarProvider
from server.services.research_datasets import prepare_daily_dataset
from strategy.risk_budget import risk_budget_weights
from tests.server.test_dataset_corporate_actions import client_context as client_context

pytestmark = pytest.mark.product_smoke

DAYS = tuple(stamp.date() for stamp in pd.bdate_range("2026-09-01", periods=15))
INSTRUMENTS = tuple(
    InstrumentKey(symbol, InstrumentType.ETF) for symbol in ("510300", "511010")
)


def frame(symbol, *, flat=False):
    close = [
        10.0
        if flat
        else round(
            10 + (index % 3) * 0.1 + index * (0.02 if symbol == "510300" else 0.01), 2
        )
        for index in range(len(DAYS))
    ]
    return pd.DataFrame(
        {
            "timestamp": [
                datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)
                for day in DAYS
            ],
            "open": close,
            "high": [round(x + 0.01, 2) for x in close],
            "low": [round(x - 0.01, 2) for x in close],
            "close": close,
            "volume": [1_000_000] * len(DAYS),
        }
    )


def publish(root, *, flat=False):
    class Provider:
        def fetch_daily_bars(self, request):
            day = request.start_date
            index = DAYS.index(day)
            response = {}
            for field in ("Open", "High", "Low", "Close", "Volume", "Amount"):
                values = [
                    float(
                        frame(instrument.symbol, flat=flat).iloc[index][field.lower()]
                    )
                    if field != "Amount"
                    else 10_000_000
                    for instrument in request.instruments
                ]
                response[field] = pd.DataFrame(
                    [values],
                    index=[day],
                    columns=[
                        f"{instrument.symbol}.SH" for instrument in request.instruments
                    ],
                )
            adapter = TdxDailyBarProvider(
                SimpleNamespace(get_market_data=lambda **_: response),
                clock=lambda: datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
            )
            return adapter.fetch_daily_bars(request)

    return prepare_daily_dataset(
        root,
        request=DailyBarRequest(INSTRUMENTS, DAYS[0], DAYS[-1]),
        dates=DAYS,
        provider=Provider(),
    )


def body(ref=None):
    return {
        "dataset_id": ref.dataset_id if ref is not None else None,
        "assets": [
            {"symbol": key.symbol, "instrument_type": "etf"} for key in INSTRUMENTS
        ],
        "start_date": DAYS[0].isoformat(),
        "end_date": DAYS[-1].isoformat(),
        "strategy": "risk_parity_macro",
        "initial_cash": 100_000,
        "params": {
            "lookback_period": 10,
            "rebalance_interval": 1,
            "trend_filter": False,
        },
    }


def test_bound_dataset_replays_registered_strategy_with_delayed_fills_and_costs(
    client_context, tmp_path, monkeypatch
):
    client, _, _, _ = client_context
    ref = publish(tmp_path / "research")
    monkeypatch.setattr(
        "data.manager.DataManager.get_bars",
        lambda *_, **__: pytest.fail("No provider fallback"),
    )
    response = client.post("/api/backtest/run", json=body(ref))
    assert response.status_code == 200, response.text
    result = response.json()
    assert {fill["symbol"] for fill in result["fills"]} == {
        key.symbol for key in INSTRUMENTS
    }
    assert (
        min(fill["timestamp"][:10] for fill in result["fills"]) == DAYS[11].isoformat()
    )
    assert all(
        fill["fee_rule_id"] == "cn_fund_etf_default_v1" for fill in result["fills"]
    )
    assert result["metrics"]["total_commission"] > 0
    assert result["metrics"]["total_slippage"] > 0
    saved = client.get(f"/api/backtest/results/{result['id']}").json()
    assert saved["config"]["params"]["cash_proxy"] == "511010"
    assert saved["metrics_json"]["dataset_binding"]["dataset_id"] == ref.dataset_id
    assert saved["metrics_json"]["dataset_binding"]["point_in_time_verified"] is False
    assert (
        verify_backtest_dataset_snapshot_replay(
            saved["metrics_json"]["dataset_snapshot"], store_root=tmp_path
        )["status"]
        == "pass"
    )
    assert saved["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"


@pytest.mark.parametrize("failure", ["zero_variance", "not_converged"])
def test_numeric_failure_is_400_without_saving_a_successful_cash_report(
    client_context, tmp_path, monkeypatch, failure
):
    client, _, _, _ = client_context
    ref = publish(tmp_path / "research", flat=failure == "zero_variance")
    if failure == "not_converged":
        monkeypatch.setattr(
            "strategy.builtins.risk_parity_macro.risk_budget_weights",
            lambda covariance, budget: risk_budget_weights(
                covariance, budget, max_iter=1
            ),
        )
    response = client.post("/api/backtest/run", json=body(ref))
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "risk_budget_covariance_invalid"
        if failure == "zero_variance"
        else "risk_budget_not_converged"
    )
    assert client.get("/api/backtest/results").json() == []


@pytest.mark.parametrize("failure", ["missing_final_bar", "duplicate_bar"])
def test_legacy_data_bar_failure_including_final_session_is_not_swallowed(
    client_context, tmp_path, monkeypatch, failure
):
    client, _, _, _ = client_context
    monkeypatch.chdir(tmp_path)

    def bars(_manager, symbol, *_args, **_kwargs):
        data = frame(symbol)
        if symbol == "511010":
            data = (
                data.iloc[:-1]
                if failure == "missing_final_bar"
                else pd.concat([data.iloc[:5], data.iloc[4:]])
            )
        return DataHandler(data, symbol, instrument_type=InstrumentType.ETF)

    monkeypatch.setattr("data.manager.DataManager.get_bars", bars)
    response = client.post("/api/backtest/run", json=body())
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "risk_parity_macro_incomplete_session"
        if failure == "missing_final_bar"
        else "risk_parity_macro_duplicate_session_bar"
    )
    assert client.get("/api/backtest/results").json() == []
