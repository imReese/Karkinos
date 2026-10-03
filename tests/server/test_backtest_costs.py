"""Research cost inputs affect real fills and survive the saved-report journey."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.types import CommissionType, OrderSide
from execution.commission import ETFCommission, StockACommission
from server.contracts.http.strategy_models import BacktestCostAssumptions
from server.services.backtest_costs import resolve_backtest_costs
from tests.server.test_dataset_corporate_actions import (
    client_context as client_context,
)
from tests.server.test_research_datasets import _backtest_request


def _request(ref):
    return _backtest_request(
        ref,
        strategy="time_series_momentum",
        params={
            "lookback_period": 2,
            "min_return": -0.1,
            "exit_return": -0.1,
            "target_weight": 0.1,
        },
    ).model_dump(mode="json")


def test_run_applies_and_freezes_effective_costs_with_capacity(
    client_context, tmp_path, monkeypatch
):
    client, _, ref, _ = client_context

    def no_provider(*args, **kwargs):
        pytest.fail("Bound research must not contact providers")

    monkeypatch.setattr("data.manager.DataManager.get_bars", no_provider)
    original = client.post("/api/backtest/run", json=_request(ref))
    assert original.status_code == 200, original.text
    baseline = original.json()
    assumptions = {
        "stock_commission_rate": 0.001,
        "stock_min_commission": 11,
        "etf_min_commission": 2,
        "slippage_bps": 25,
    }
    response = client.post(
        "/api/backtest/run", json={**_request(ref), "cost_assumptions": assumptions}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["fills"]) == len(baseline["fills"]) == 1
    fill = result["fills"][0]
    assert fill["fill_price"] == pytest.approx(
        baseline["fills"][0]["fill_price"] * 1.0025
    )
    notional = Decimal(str(fill["fill_price"])) * Decimal(str(fill["fill_quantity"]))
    fees = fill["fee_breakdown"]
    assert Decimal(fees["commission"]) == max(notional * Decimal("0.001"), 11)
    assert Decimal(fees["transfer_fee"]) == notional * Decimal("0.00001")
    assert Decimal(fees["stamp_tax"]) == 0
    assert fill["fee_rule_id"] == "cn_stock_research_override_v1"
    assert result["metrics"]["final_equity"] < baseline["metrics"]["final_equity"]
    effective = result["metrics_json"]["cost_assumptions"]
    assert effective["schema_version"] == "karkinos.backtest_cost_assumptions.v1"
    assert Decimal(effective["slippage_bps"]) == 25
    assert Decimal(effective["stock"]["min_commission"]) == 11
    assert Decimal(effective["etf"]["min_commission"]) == 2
    capacity = result["metrics_json"]["capacity_review"]
    assert capacity["schema_version"] == "karkinos.backtest_capacity.v2"
    assert capacity["fill_count"] == capacity["observation_count"] == 1
    assert capacity["bar_observations"][0]["symbol"] == fill["symbol"]
    assert result["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
    saved = client.get(f"/api/backtest/results/{result['id']}")
    assert saved.status_code == 200, saved.text
    assert saved.json()["metrics_json"]["cost_assumptions"] == effective
    assert saved.json()["metrics_json"]["capacity_review"] == capacity
    assert (
        saved.json()["config"]["cost_assumptions"]
        == result["config"]["cost_assumptions"]
    )
    report = json.loads(
        (tmp_path / "reports" / f"backtest-result-{result['id']}.json").read_text()
    )
    assert report["metrics_json"]["cost_assumptions"] == effective
    assert report["metrics_json"]["capacity_review"] == capacity
    assert report["fills"] == result["fills"]


def test_sweep_and_compare_keep_one_cost_setting_in_every_saved_child(client_context):
    client, _, ref, _ = client_context
    assumptions = {"stock_min_commission": 23, "slippage_bps": 40}
    body = {**_request(ref), "cost_assumptions": assumptions}
    sweep = client.post(
        "/api/backtest/sweep",
        json={**body, "param_grid": {"lookback_period": [2, 3]}},
    )
    compare = client.post(
        "/api/backtest/compare",
        json={
            **body,
            "runs": [
                {"strategy": body["strategy"], "params": body["params"]},
                {
                    "strategy": body["strategy"],
                    "params": {**body["params"], "lookback_period": 3},
                },
            ],
        },
    )
    effective = []
    for response in (sweep, compare):
        assert response.status_code == 200, response.text
        assert len(response.json()["results"]) == 2
        for item in response.json()["results"]:
            saved = client.get(f"/api/backtest/results/{item['result_id']}").json()
            assert saved["config"]["cost_assumptions"]["stock_min_commission"] == 23
            evidence = saved["metrics_json"]["cost_assumptions"]
            assert Decimal(evidence["slippage_bps"]) == 40
            assert Decimal(evidence["stock"]["min_commission"]) == 23
            effective.append(evidence)
    assert all(item == effective[0] for item in effective)


def test_omission_keeps_existing_models_and_explicit_zero_keeps_taxes():
    default, effective = resolve_backtest_costs(None)
    zero, zero_effective = resolve_backtest_costs(
        BacktestCostAssumptions(
            stock_commission_rate=0,
            stock_min_commission=0,
            etf_commission_rate=0,
            etf_min_commission=0,
        )
    )
    for commission_type, original in (
        (CommissionType.STOCK_A, StockACommission()),
        (CommissionType.FUND_ETF, ETFCommission()),
    ):
        for side in (OrderSide.BUY, OrderSide.SELL):
            before = original.breakdown(side, Decimal("10"), Decimal("100"))
            actual = default.commission_calc.breakdown_for(
                commission_type, side, Decimal("10"), Decimal("100")
            )
            assert actual == before
            after = zero.commission_calc.breakdown_for(
                commission_type, side, Decimal("10"), Decimal("100")
            )
            assert after.commission == 0
            assert after.stamp_tax == before.stamp_tax
            assert after.transfer_fee == before.transfer_fee
    assert Decimal(effective["slippage_bps"]) == 0
    assert Decimal(zero_effective["stock"]["commission_rate"]) == 0


@pytest.mark.parametrize(
    "invalid",
    [
        {"slippage_bps": -1},
        {"slippage_bps": 10000},
        {"slippage_bps": float("nan")},
        {"stock_commission_rate": float("inf")},
        {"stock_commission_rate": 1.1},
        {"etf_min_commission": -1},
        {"stamp_tax_rate": 0},
    ],
)
def test_invalid_cost_inputs_are_rejected(invalid):
    with pytest.raises(ValidationError):
        BacktestCostAssumptions(**invalid)


def test_old_saved_reports_do_not_invent_effective_costs(client_context):
    client, state, ref, _ = client_context
    config = _request(ref)
    config.pop("cost_assumptions")
    result_id = asyncio.run(
        state.db.save_backtest_result(
            config_json=json.dumps(config),
            initial_cash=100000,
            final_equity=100000,
            total_return=0,
            sharpe=0,
            max_dd=0,
            equity_curve_json="[]",
        )
    )
    response = client.get(f"/api/backtest/results/{result_id}")
    assert response.status_code == 200, response.text
    assert response.json()["config"]["cost_assumptions"] is None
    assert "cost_assumptions" not in response.json()["metrics_json"]
