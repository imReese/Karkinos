"""Sweep and compare use one explicit return basis in every real saved run."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from server.services.backtest_views.strategy_inputs import backtest_metrics_from_payload
from tests.server.test_backtest_cash_dividends import _capture, _cash_response
from tests.server.test_backtest_share_distributions import _share_response
from tests.server.test_dataset_corporate_actions import (
    client_context as client_context,
)
from tests.server.test_research_datasets import _backtest_request


def test_explicit_zero_annual_return_overrides_legacy_json_value():
    metrics = backtest_metrics_from_payload(
        {
            "initial_cash": 100_000,
            "final_equity": 100_000,
            "total_return": 0,
            "annual_return": 0,
            "sharpe": 0,
            "metrics_json": {"annual_return": 0.15},
        }
    )
    assert metrics.annual_return == 0


def _request(ref, *, mode):
    body = _backtest_request(
        ref,
        strategy="time_series_momentum",
        params={
            "lookback_period": 2,
            "min_return": -0.1,
            "exit_return": -0.1,
            "target_weight": 0.1,
        },
    ).model_dump(mode="json")
    body["cost_assumptions"] = {"stock_min_commission": 11, "slippage_bps": 25}
    if mode is None:
        body.pop("corporate_action_mode")
    else:
        body["corporate_action_mode"] = mode
    return body


def _batch_request(body, endpoint):
    if endpoint == "sweep":
        return {**body, "param_grid": {"target_weight": [0.1, 0.2]}}
    return {
        **body,
        "runs": [
            {
                "strategy": body["strategy"],
                "params": {**body["params"], "target_weight": weight},
            }
            for weight in (0.1, 0.2)
        ],
    }


@pytest.mark.parametrize("endpoint", ["sweep", "compare"])
@pytest.mark.parametrize(
    "mode", [None, "cash_dividends_gross", "reported_distributions_gross"]
)
def test_every_saved_child_accounts_for_the_selected_return_basis(
    client_context, monkeypatch, tmp_path, endpoint, mode
):
    client, _, _, _ = client_context
    bound = _capture(
        client_context,
        monkeypatch,
        _share_response()
        if mode == "reported_distributions_gross"
        else _cash_response(),
    )

    def no_provider(*_args, **_kwargs):
        pytest.fail("Frozen comparison must not contact an external market provider")

    monkeypatch.setattr("data.manager.DataManager.get_bars", no_provider)
    body = _request(bound, mode=mode)
    response = client.post(
        f"/api/backtest/{endpoint}", json=_batch_request(body, endpoint)
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 2
    assert {item["params"]["target_weight"] for item in results} == {0.1, 0.2}
    for item in results:
        saved_response = client.get(f"/api/backtest/results/{item['result_id']}")
        assert saved_response.status_code == 200, saved_response.text
        saved = saved_response.json()
        assert saved["config"]["corporate_action_mode"] == (mode or "price_only")
        assert saved["config"]["dataset_id"] == bound.dataset_id
        assert saved["config"]["params"] == item["params"]
        assert saved["metrics"] == item["metrics"]
        costs = saved["metrics_json"]["cost_assumptions"]
        assert Decimal(costs["stock"]["min_commission"]) == 11
        assert Decimal(costs["slippage_bps"]) == 25
        baseline_response = client.post(
            "/api/backtest/run",
            json={
                **body,
                "params": item["params"],
                "corporate_action_mode": "price_only",
            },
        )
        assert baseline_response.status_code == 200, baseline_response.text
        baseline = baseline_response.json()
        assert len(baseline["fills"]) == 1
        reloaded = client.get(f"/api/backtest/results/{baseline['id']}").json()
        assert reloaded["fills"] == baseline["fills"]
        eligible = Decimal(str(baseline["fills"][0]["fill_quantity"]))
        assert eligible > 0
        expected_extra_equity = Decimal(0)
        if mode is None:
            assert "cash_dividend_accounting" not in saved["metrics_json"]
        else:
            accounting = saved["metrics_json"]["cash_dividend_accounting"]
            assert accounting["mode"] == mode
            assert (
                Decimal(accounting["distributions"][0]["eligible_quantity"]) == eligible
            )
            assert Decimal(accounting["gross_income"]) == eligible * Decimal("0.1")
            assert Decimal(accounting["cash_paid"]) == eligible * Decimal("0.1")
            expected_extra_equity += eligible * Decimal("0.1")
            if mode == "reported_distributions_gross":
                assert Decimal(accounting["share_quantity"]) == eligible * Decimal(
                    "0.3"
                )
                assert Decimal(accounting["unlisted_quantity"]) == 0
                expected_extra_equity += eligible * Decimal("0.3") * Decimal("10.5")
            assert accounting["coverage_verified"] is False
            assert accounting["historical_availability_verified"] is False
        assert saved["metrics"]["final_equity"] - baseline["metrics"][
            "final_equity"
        ] == pytest.approx(float(expected_extra_equity))
        assert (
            saved["metrics_json"]["dataset_snapshot"]
            == baseline["metrics_json"]["dataset_snapshot"]
        )
        assert (
            saved["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
        )
        report = json.loads(
            (
                tmp_path / "reports" / f"backtest-result-{item['result_id']}.json"
            ).read_text()
        )
        assert report["config"]["corporate_action_mode"] == (mode or "price_only")
        assert report["fills"] == saved["fills"]
        assert report["metrics_json"].get("cash_dividend_accounting") == saved[
            "metrics_json"
        ].get("cash_dividend_accounting")


@pytest.mark.parametrize("endpoint", ["sweep", "compare"])
@pytest.mark.parametrize("bound", [False, True])
def test_gross_comparison_requires_dataset_and_evidence_without_fallback(
    client_context, monkeypatch, endpoint, bound
):
    client, _, ref, _ = client_context

    def no_provider(*_args, **_kwargs):
        pytest.fail("Missing dividend evidence must not trigger a remote data fallback")

    monkeypatch.setattr("data.manager.DataManager.get_bars", no_provider)
    body = _batch_request(_request(ref, mode="reported_distributions_gross"), endpoint)
    if not bound:
        body.pop("dataset_id")
    response = client.post(f"/api/backtest/{endpoint}", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "cash_dividend_evidence_required" if bound else "cash_dividend_dataset_required"
    )
    assert client.get("/api/backtest/results").json() == []


@pytest.mark.parametrize("endpoint", ["sweep", "compare"])
def test_invalid_mode_is_rejected_instead_of_ignored(client_context, endpoint):
    client, _, ref, _ = client_context
    response = client.post(
        f"/api/backtest/{endpoint}",
        json=_batch_request(_request(ref, mode="unknown_distribution_mode"), endpoint),
    )
    assert response.status_code == 422, response.text
    assert client.get("/api/backtest/results").json() == []


@pytest.mark.parametrize("endpoint", ["sweep", "compare"])
def test_cash_only_comparison_rejects_share_terms_before_saving_children(
    client_context, monkeypatch, endpoint
):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _share_response())
    response = client.post(
        f"/api/backtest/{endpoint}",
        json=_batch_request(_request(bound, mode="cash_dividends_gross"), endpoint),
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "cash_dividend_share_distribution_unsupported"
    assert client.get("/api/backtest/results").json() == []
