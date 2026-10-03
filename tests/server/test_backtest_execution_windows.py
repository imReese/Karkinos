"""A chronological run binds one full Dataset and executes only its own book window."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from analytics.dataset_snapshot import verify_backtest_dataset_snapshot_replay
from server.contracts.content_identity import content_fingerprint
from server.services.backtest_views.execution import (
    prepare_dataset_backtest_inputs,
    run_single_backtest,
    write_backtest_report_file,
)
from server.services.research_datasets import ResearchDatasetError
from tests.server.test_backtest_cash_dividends import _capture, _cash_response
from tests.server.test_backtest_share_distributions import _share_response
from tests.server.test_dataset_corporate_actions import (
    client_context as client_context,
)
from tests.server.test_research_datasets import _backtest_request


def _request(ref, **changes):
    return _backtest_request(
        ref,
        params={"short_period": 1, "long_period": 2},
        cost_assumptions={"stock_min_commission": 11, "slippage_bps": 25},
        **changes,
    )


def test_prepared_source_is_read_once_but_each_window_has_its_own_metrics(
    client_context, monkeypatch, tmp_path
):
    _, state, ref, _ = client_context
    request = _request(ref)
    full = run_single_backtest(request, state.config, state.db)
    assert len(full["fills"]) == 1
    assert "execution_window" not in full["metrics_json"]
    prepared = prepare_dataset_backtest_inputs(request, state.db)
    source_snapshot = json.loads(json.dumps(prepared[3]))

    def no_read(*_args, **_kwargs):
        pytest.fail("A prepared immutable source must not be reloaded or replaced")

    monkeypatch.setattr(
        "server.services.backtest_dataset_inputs.load_dataset_backtest_inputs", no_read
    )
    monkeypatch.setattr("data.manager.DataManager.get_bars", no_read)
    train = run_single_backtest(
        request,
        state.config,
        state.db,
        preloaded_dataset_inputs=prepared,
        history_end=date(2026, 9, 9),
    )
    tested = run_single_backtest(
        request,
        state.config,
        state.db,
        preloaded_dataset_inputs=prepared,
        evaluation_start=date(2026, 9, 10),
    )
    repeated_full = run_single_backtest(
        request, state.config, state.db, preloaded_dataset_inputs=prepared
    )
    assert repeated_full["metrics_json"] == full["metrics_json"]
    assert prepared[1][next(iter(prepared[1]))].total_bars == 5
    assert train["fills"] == []
    assert len(train["equity_curve"]) == 3
    assert train["equity_curve"][-1]["timestamp"].startswith("2026-09-09T")
    assert len(tested["equity_curve"]) == 2
    assert tested["equity_curve"][0]["equity"] == tested["initial_cash"]
    assert tested["duration_days"] == 2
    assert train["duration_days"] == 3
    assert full["duration_days"] == 5
    assert len(tested["fills"]) == 1
    assert tested["fills"][0]["timestamp"].startswith("2026-09-11T")
    assert tested["metrics_json"]["total_commission"] >= 11
    assert tested["metrics_json"]["total_slippage"] > 0
    assert tested["metrics_json"]["capacity_review"]["fill_count"] == 1
    for result in (train, tested):
        metrics = result["metrics_json"]
        assert metrics["dataset_snapshot"] == source_snapshot
        assert metrics["dataset_binding"] == prepared[2]
        assert metrics["cost_assumptions"] == full["metrics_json"]["cost_assumptions"]
        window = dict(metrics["execution_window"])
        fingerprint = window.pop("fingerprint")
        assert content_fingerprint(window) == fingerprint
        assert window["source_dataset_id"] == ref.dataset_id
        assert window["source_snapshot_id"] == source_snapshot["snapshot_id"]
        assert window["source_start_date"] == "2026-09-07"
        assert window["source_end_date"] == "2026-09-11"
        assert window["exploratory"] is True
        assert window["independent_final"] is False
        assert window["independent_initial_cash"] is True
        replay = verify_backtest_dataset_snapshot_replay(
            metrics["dataset_snapshot"],
            store_root=tmp_path / "unused-serving",
            research_root=tmp_path / "research",
        )
        assert replay["status"] == "pass", replay
    assert train["metrics_json"]["execution_window"]["history_end_date"] == "2026-09-09"
    window = tested["metrics_json"]["execution_window"]
    assert (
        window["evaluation_start_date"] == window["metric_start_date"] == "2026-09-10"
    )
    assert window["metric_end_date"] == "2026-09-11"
    path = write_backtest_report_file(
        result_id=17,
        request=request,
        bt_result=tested,
        metrics_json=tested["metrics_json"],
    )
    report = json.loads(path.read_text())
    assert report["config"]["start_date"] == "2026-09-07"
    assert report["config"]["end_date"] == "2026-09-11"
    assert report["metrics_json"]["execution_window"] == window


@pytest.mark.parametrize(
    "mode", ["cash_dividends_gross", "reported_distributions_gross"]
)
def test_future_distribution_is_not_a_training_claim_but_accrued_claims_are_kept(
    client_context, monkeypatch, mode
):
    _, state, _, _ = client_context
    response = (
        _share_response(pay_date="20260914", div_listdate="20260914")
        if mode == "reported_distributions_gross"
        else _cash_response(pay_date="20260914")
    )
    ref = _capture(client_context, monkeypatch, response)
    request = _backtest_request(
        ref,
        strategy="time_series_momentum",
        params={
            "lookback_period": 2,
            "min_return": -0.1,
            "exit_return": -0.1,
            "target_weight": 0.1,
        },
        corporate_action_mode=mode,
    )
    prepared = prepare_dataset_backtest_inputs(request, state.db)
    before_ex = run_single_backtest(
        request,
        state.config,
        state.db,
        preloaded_dataset_inputs=prepared,
        history_end=date(2026, 9, 10),
    )
    at_ex = run_single_backtest(
        request,
        state.config,
        state.db,
        preloaded_dataset_inputs=prepared,
        history_end=date(2026, 9, 11),
    )
    before = before_ex["metrics_json"]["cash_dividend_accounting"]
    assert before["mode"] == mode
    assert before["distributions"] == []
    assert Decimal(before["receivable"]) == 0
    accounting = at_ex["metrics_json"]["cash_dividend_accounting"]
    eligible = Decimal(accounting["distributions"][0]["eligible_quantity"])
    assert eligible > 0
    assert Decimal(accounting["receivable"]) == eligible * Decimal("0.1")
    assert Decimal(accounting["cash_paid"]) == 0
    if mode == "reported_distributions_gross":
        assert Decimal(accounting["unlisted_quantity"]) == eligible * Decimal("0.3")
    assert (
        before_ex["metrics_json"]["dataset_snapshot"]
        == at_ex["metrics_json"]["dataset_snapshot"]
        == prepared[3]
    )
    assert len(prepared[2]["corporate_action_evidence"]["events"]) == 1


@pytest.mark.parametrize(
    "mode", ["cash_dividends_gross", "reported_distributions_gross"]
)
def test_test_book_does_not_receive_warmup_record_date_entitlements(
    client_context, monkeypatch, mode
):
    _, state, _, _ = client_context
    dates = {"record_date": "20260909", "ex_date": "20260910", "pay_date": "20260911"}
    ref = _capture(
        client_context,
        monkeypatch,
        _share_response(**dates)
        if mode == "reported_distributions_gross"
        else _cash_response(**dates),
    )
    request = _request(ref, corporate_action_mode=mode)
    result = run_single_backtest(
        request, state.config, state.db, evaluation_start=date(2026, 9, 10)
    )
    accounting = result["metrics_json"]["cash_dividend_accounting"]
    assert Decimal(accounting["distributions"][0]["eligible_quantity"]) == 0
    assert Decimal(accounting["gross_income"]) == 0
    assert result["equity_curve"][0]["equity"] == result["initial_cash"]
    assert len(result["fills"]) == 1
    if mode == "reported_distributions_gross":
        assert Decimal(accounting["share_quantity"]) == 0


def test_prefix_does_not_hide_malformed_future_distribution_terms(
    client_context, monkeypatch
):
    _, state, _, _ = client_context
    ref = _capture(client_context, monkeypatch, _cash_response(cash_div_tax=None))
    with pytest.raises(
        ResearchDatasetError, match="cash_dividend_gross_amount_missing"
    ):
        run_single_backtest(
            _request(ref, corporate_action_mode="cash_dividends_gross"),
            state.config,
            state.db,
            history_end=date(2026, 9, 9),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"dataset_id": "sha256:" + "0" * 64},
        {"end_date": "2026-09-10"},
        {"assets": [{"symbol": "600001", "asset_class": "stock"}]},
    ],
)
def test_preloaded_source_cannot_be_rebound_to_a_different_request(
    client_context, change
):
    _, state, ref, _ = client_context
    request = _request(ref)
    prepared = prepare_dataset_backtest_inputs(request, state.db)
    with pytest.raises(
        ResearchDatasetError, match="backtest_preloaded_dataset_request_mismatch"
    ):
        run_single_backtest(
            request.model_copy(update=change),
            state.config,
            state.db,
            preloaded_dataset_inputs=prepared,
        )


@pytest.mark.parametrize(
    "window",
    [
        {"history_end": date(2026, 9, 6)},
        {"history_end": date(2026, 9, 12)},
        {"evaluation_start": date(2026, 9, 12)},
        {"history_end": date(2026, 9, 8), "evaluation_start": date(2026, 9, 9)},
    ],
)
def test_window_must_be_ordered_and_inside_full_source(client_context, window):
    _, state, ref, _ = client_context
    with pytest.raises(ResearchDatasetError, match="backtest_execution_window_invalid"):
        run_single_backtest(_request(ref), state.config, state.db, **window)


def test_execution_window_cannot_fall_back_to_serving(client_context, monkeypatch):
    _, state, ref, _ = client_context
    monkeypatch.setattr(
        "data.manager.DataManager.get_bars",
        lambda *_a, **_k: pytest.fail("No provider fallback"),
    )
    with pytest.raises(
        ResearchDatasetError, match="backtest_execution_window_dataset_required"
    ):
        run_single_backtest(
            _request(ref).model_copy(update={"dataset_id": None}),
            state.config,
            state.db,
            history_end=date(2026, 9, 9),
        )
