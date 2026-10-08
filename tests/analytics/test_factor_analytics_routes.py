"""Tests for /api/universes and /api/analytics/factor-evaluation routes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.types import BarFrequency, InstrumentType
from data.store import DataStore
from data.universe import CORE_ETF_UNIVERSE
from server.routes.analytics import create_router
from server.services import factor_analytics


def _save_prices(root, *, omitted_symbol=None, gap_symbol=None):
    store = DataStore(root)
    dates = pd.bdate_range("2026-01-05", periods=80)
    members = [member for member in CORE_ETF_UNIVERSE.members if not member.cash_proxy]
    for index, member in enumerate(members):
        if str(member.symbol) == omitted_symbol:
            continue
        values = 10 * (1 + 0.001 * (index + 1)) ** np.arange(len(dates))
        frame = pd.DataFrame(
            {
                "timestamp": dates,
                "open": values,
                "high": values,
                "low": values,
                "close": values,
                "volume": [1000000] * len(dates),
            }
        )
        if str(member.symbol) == gap_symbol:
            frame = frame.drop(index=30)
        store.save_bars(
            member.symbol,
            BarFrequency.DAILY,
            frame,
            instrument_type=member.instrument_type,
        )
    return store


@pytest.fixture(autouse=True)
def isolated_local_data(tmp_path, monkeypatch):
    # Every route uses an isolated sanitized store. Never access user cache data.
    root = tmp_path / "factor-data"
    monkeypatch.setattr(factor_analytics, "resolve_data_dir", lambda: str(root))
    return root


def test_universes_route() -> None:
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    response = client.get("/api/universes")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3

    u_ids = [u["universe_id"] for u in data]
    assert "core_etf_universe" in u_ids
    assert "sector_etf_universe" in u_ids
    assert "dividend_defensive_universe" in u_ids

    # Detail route
    detail_res = client.get("/api/universes/core_etf_universe")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["universe_id"] == "core_etf_universe"
    assert len(detail["members"]) >= 5


def test_factor_evaluation_route(isolated_local_data) -> None:
    _save_prices(isolated_local_data)
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)

    payload = {
        "universe_id": "core_etf_universe",
        "factor_type": "momentum",
        "lookback_period": 20,
        "forward_period": 5,
        "n_quantiles": 5,
    }
    response = client.post("/api/analytics/factor-evaluation", json=payload)
    assert response.status_code == 200
    res = response.json()

    assert res["universe_id"] == "core_etf_universe"
    assert res["factor_type"] == "momentum"
    assert "summary" in res
    assert "spread_summary" in res
    assert "ic_series" in res
    assert "quantile_cumulative" in res
    assert "latest_cross_section" in res

    # Verify summary fields
    summary = res["summary"]
    assert "mean_ic" in summary
    assert "icir" in summary
    assert "t_stat" in summary
    assert "p_value" in summary
    assert "positive_ratio" in summary

    # Verify latest cross section
    assert len(res["latest_cross_section"]) > 0
    first_member = res["latest_cross_section"][0]
    assert "symbol" in first_member
    assert "name" in first_member
    assert "factor_value" in first_member
    assert "rank" in first_member
    assert res["data_source"] == "local_typed_daily_bars"
    assert res["research_only"] is True
    assert res["return_basis"] == "gross_unadjusted_quantile_diagnostic"
    assert summary["sample_stride"] == 5
    assert summary["annual_periods"] == 50.4
    assert res["sample_count"] == 11
    curve = res["quantile_cumulative"]
    assert len(curve) == 12
    assert curve[0]["q5"] == curve[0]["long_short"] == 1
    top_return = ((1.006**5 - 1) + (1.007**5 - 1)) / 2
    assert curve[-1]["q5"] == pytest.approx((1 + top_return) ** 11, abs=0.0001)
    assert res["spread_summary"]["annualized_spread_return"] < 2


def test_missing_local_data_is_blocked_without_synthetic_prices(isolated_local_data):
    app = FastAPI()
    app.include_router(create_router())
    response = TestClient(app).post("/api/analytics/factor-evaluation", json={})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("factor_price_data_missing:")
    assert "510300" in response.json()["detail"]


@pytest.mark.parametrize("failure", ["missing", "gap"])
def test_entire_typed_universe_is_required_without_forward_filling(
    isolated_local_data, failure
):
    _save_prices(
        isolated_local_data,
        omitted_symbol="518880" if failure == "missing" else None,
        gap_symbol="518880" if failure == "gap" else None,
    )
    with pytest.raises(
        ValueError, match="factor_price_data_missing|factor_price_history_incomplete"
    ):
        factor_analytics.run_factor_evaluation(data_dir=isolated_local_data)


def test_etf_prices_are_not_resolved_from_other_instrument_identity(
    isolated_local_data,
):
    store = _save_prices(isolated_local_data)
    expected = factor_analytics.run_factor_evaluation(data_dir=isolated_local_data)
    member = CORE_ETF_UNIVERSE.members[0]
    frame = store.load_bars(member.symbol, instrument_type=InstrumentType.ETF)
    for column in ("open", "high", "low", "close"):
        frame[column] *= 99
    store.save_bars(
        member.symbol, BarFrequency.DAILY, frame, instrument_type=InstrumentType.STOCK
    )
    assert (
        factor_analytics.run_factor_evaluation(data_dir=isolated_local_data) == expected
    )


def test_insufficient_horizon_is_not_replaced_with_longer_fake_history(
    isolated_local_data,
):
    _save_prices(isolated_local_data)
    with pytest.raises(ValueError, match="factor_price_history_insufficient"):
        factor_analytics.run_factor_evaluation(
            forward_period=60, data_dir=isolated_local_data
        )
