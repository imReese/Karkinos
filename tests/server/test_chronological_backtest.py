"""Train-only parameter selection and a fresh test book through ordinary HTTP."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from server.routes.research_observations import create_router
from tests.server.test_dataset_corporate_actions import client_context as client_context
from tests.server.test_research_observation_inputs import dataset

pytestmark = pytest.mark.product_smoke

DAYS = tuple(
    date(2026, 9, day) for day in (14, 15, 16, 17, 18, 21, 22, 23, 24, 25, 28, 29, 30)
)
CLOSES = (
    "10.3",
    "10.2",
    "10.1",
    "10",
    "10.2",
    "10.4",
    "10.6",
    "10.5",
    "10.4",
    "10.3",
    "10.5",
    "10.7",
    "10.8",
)


def publish(tmp_path, closes=CLOSES):
    return dataset(
        tmp_path / "research",
        days=DAYS,
        closes=dict(zip(DAYS, closes, strict=True)),
        cutoff=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )[1]


def body(ref, **changes):
    return {
        "dataset_id": ref.dataset_id,
        "start_date": DAYS[0].isoformat(),
        "end_date": DAYS[-1].isoformat(),
        "initial_cash": 100_000,
        "strategy": "dual_ma",
        "param_grid": {"short_period": [2, 1, 2], "long_period": [3]},
        "test_start_date": DAYS[7].isoformat(),
        "cost_assumptions": {"stock_min_commission": 11, "slippage_bps": 12.5},
        **changes,
    }


def sweep(client, request):
    response = client.post("/api/backtest/sweep", json=request)
    assert response.status_code == 200, response.text
    return response.json()


def saved(client, identity):
    response = client.get(f"/api/backtest/results/{identity}")
    assert response.status_code == 200, response.text
    return response.json()


def test_real_sweep_selects_on_training_then_persists_replayable_test_report(
    client_context, tmp_path, monkeypatch
):
    client, _, _, _ = client_context
    ref = publish(tmp_path)
    monkeypatch.setattr(
        "data.manager.DataManager.get_bars",
        lambda *args, **kwargs: pytest.fail("No provider fallback"),
    )
    result = sweep(client, body(ref))
    assert result["tested_count"] == 2
    selection = result["chronological_validation"]
    assert selection["selection_basis"] == "training_only"
    assert selection["independent_final"] is False
    assert selection["selected_params"] == result["results"][0]["params"]
    assert selection["selected_training_result_id"] == result["results"][0]["result_id"]
    assert len(selection["training_result_ids"]) == 2
    reports = [saved(client, row["result_id"]) for row in result["results"]]
    test = saved(client, result["selected_test_result_id"])
    snapshot = test["metrics_json"]["dataset_snapshot"]
    assert (
        verify_backtest_dataset_snapshot_replay(snapshot, store_root=tmp_path)["status"]
        == "pass"
    )
    for report in [*reports, test]:
        assert report["config"]["start_date"] == DAYS[0].isoformat()
        assert report["config"]["end_date"] == DAYS[-1].isoformat()
        assert report["metrics_json"]["dataset_snapshot"] == snapshot
        assert report["metrics_json"]["dataset_binding"]["dataset_id"] == ref.dataset_id
        costs = report["metrics_json"]["cost_assumptions"]
        assert Decimal(costs["stock"]["min_commission"]) == 11
        assert Decimal(costs["slippage_bps"]) == Decimal("12.5")
        assert (
            report["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
        )
        bundle = report["research_evidence_bundle"]
        oos = next(item for item in bundle["analyzers"] if item["name"] == "oos")
        assert oos["status"] == "degraded"
        assert oos["details"]["validation_mode"] == "chronological_train_select_test"
        assert oos["details"]["independent_final"] is False
        assert bundle["evidence_references"]["oos_evidence_available"] is (
            report["id"] == test["id"]
        )
    for report in reports:
        assert report["metrics_json"]["chronological_validation"]["role"] == "training"
        assert all(
            point["timestamp"][:10] < DAYS[7].isoformat()
            for point in report["equity_curve"]
        )
        assert (
            report["metrics_json"]["execution_window"]["metric_end_date"]
            == DAYS[6].isoformat()
        )
    assert test["metrics_json"]["chronological_validation"]["role"] == "test"
    assert (
        test["metrics_json"]["execution_window"]["metric_start_date"]
        == DAYS[7].isoformat()
    )
    assert test["equity_curve"][0]["equity"] == 100_000
    assert all(
        point["timestamp"][:10] >= DAYS[7].isoformat() for point in test["equity_curve"]
    )
    assert all(fill["timestamp"][:10] > DAYS[7].isoformat() for fill in test["fills"])
    assert test["fills"]
    assert test["metrics"]["total_commission"] > 0
    # The saved selected ordinary strategy can enter independent observation
    # without inventing an AI run, candidate or account qualification identity.
    client.app.include_router(create_router())
    started = client.post(
        "/api/research-observations",
        json={
            "request_id": str(uuid4()),
            "source_backtest_result_id": test["id"],
        },
    )
    assert started.status_code == 200, started.text
    assert started.json()["version"] == 0
    detail = client.get(f"/api/research-observations/{started.json()['id']}").json()
    assert detail["source"]["parameters"] == selection["selected_params"]
    assert detail["source"]["source_code_verified"] is False


def test_changing_only_test_prices_or_grid_order_cannot_change_training_choice(
    client_context, tmp_path
):
    client, _, _, _ = client_context
    first = sweep(client, body(publish(tmp_path)))
    altered = (*CLOSES[:7], "10.5", "10.6", "10.7", "10.8", "10.6", "10.4")
    second = sweep(
        client,
        body(
            publish(tmp_path, altered),
            param_grid={"long_period": [3], "short_period": [1, 2]},
        ),
    )
    assert (
        first["chronological_validation"]["selected_params"]
        == second["chronological_validation"]["selected_params"]
    )
    assert (
        first["chronological_validation"]["training_trials"]
        == second["chronological_validation"]["training_trials"]
    )
    assert [(row["params"], row["metrics"]) for row in first["results"]] == [
        (row["params"], row["metrics"]) for row in second["results"]
    ]
    assert (
        saved(client, first["selected_test_result_id"])["equity_curve"]
        != saved(client, second["selected_test_result_id"])["equity_curve"]
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"dataset_id": None},
        {"test_start_date": "2026-09-14"},
        {"test_start_date": "2026-09-19"},
        {"test_start_date": "2026-09-30"},
        {"test_start_date": "2026-09-16"},
        {"start_date": "not-a-date"},
        {"initial_cash": -1},
        {"param_grid": {"short_period": [1, 5], "long_period": [3]}},
    ],
)
def test_invalid_window_or_candidate_fails_before_any_result_is_saved(
    client_context, tmp_path, changes
):
    client, _, _, _ = client_context
    ref = publish(tmp_path)
    response = client.post("/api/backtest/sweep", json=body(ref, **changes))
    assert response.status_code in {409, 422}, response.text
    listing = client.get("/api/backtest/results").json()
    assert listing == []
