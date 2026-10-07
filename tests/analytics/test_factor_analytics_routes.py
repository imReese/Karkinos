"""Tests for /api/universes and /api/analytics/factor-evaluation routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.routes.analytics import create_router


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


def test_factor_evaluation_route() -> None:
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
