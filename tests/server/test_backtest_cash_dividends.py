"""Explicit gross cash-dividend accounting through frozen Dataset and HTTP owners."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset.model import DatasetRef
from data.dataset.reader import read_daily_bar_dataset
from data.providers import tushare_corporate_actions as provider_module
from tests.server.test_dataset_corporate_actions import (
    CAPTURED,
    _response,
)
from tests.server.test_dataset_corporate_actions import (
    client_context as client_context,
)
from tests.server.test_research_datasets import _backtest_request


def _cash_response(**changes):
    response = _response()
    # A real built-in strategy buys at the record-date close in this five-bar fixture.
    for field, value in {
        "record_date": "20260910",
        "ex_date": "20260911",
        "pay_date": "20260911",
        **changes,
    }.items():
        response.loc[0, field] = value
    return response


def _capture(client_context, monkeypatch, response):
    client, _, original, store = client_context
    collect = provider_module.collect_tushare_dividend_observation

    def collect_with_fake_sdk(store, *, instrument, token):
        return collect(
            store,
            instrument=instrument,
            client=SimpleNamespace(dividend=lambda **_: response.copy(deep=True)),
            clock=lambda: CAPTURED,
        )

    monkeypatch.setattr(
        provider_module,
        "collect_tushare_dividend_observation",
        collect_with_fake_sdk,
    )
    captured = client.post(
        f"/api/backtest/datasets/{original.dataset_id}/corporate-actions", json={}
    )
    assert captured.status_code == 200, captured.text
    return DatasetRef(store.resolve_ref(captured.json()["dataset_id"]))


def _run(client, ref, *, mode="cash_dividends_gross", cost_assumptions=None):
    request = _backtest_request(
        ref,
        strategy="time_series_momentum",
        params={
            "lookback_period": 2,
            "min_return": -0.1,
            "exit_return": -0.1,
            "target_weight": 0.1,
        },
    ).model_dump(mode="json")
    if cost_assumptions is not None:
        request["cost_assumptions"] = cost_assumptions
    if mode is None:
        request.pop("corporate_action_mode")
    else:
        request["corporate_action_mode"] = mode
    return client.post("/api/backtest/run", json=request)


@pytest.mark.parametrize("pay_date,paid", [("20260911", True), ("20260914", False)])
def test_explicit_gross_run_persists_entitlement_and_cash_without_changing_price_mode(
    client_context, monkeypatch, tmp_path, pay_date, paid
):
    client, _, original, _ = client_context
    bound = _capture(client_context, monkeypatch, _cash_response(pay_date=pay_date))
    assert bound != original

    legacy_response = _run(client, bound, mode=None)
    gross_response = _run(client, bound)
    assert legacy_response.status_code == 200, legacy_response.text
    assert gross_response.status_code == 200, gross_response.text
    legacy, gross = legacy_response.json(), gross_response.json()
    assert legacy["config"]["corporate_action_mode"] == "price_only"
    assert "cash_dividend_accounting" not in legacy["metrics_json"]
    assert gross["config"]["corporate_action_mode"] == "cash_dividends_gross"

    assert len(gross["fills"]) == len(legacy["fills"]) == 1
    fill = gross["fills"][0]
    assert fill["side"] == "buy"
    assert fill["timestamp"].startswith("2026-09-10T")
    assert fill["fill_quantity"] == legacy["fills"][0]["fill_quantity"]
    eligible = Decimal(str(fill["fill_quantity"]))
    assert eligible > 0
    income = eligible * Decimal("0.1")
    accounting = gross["metrics_json"]["cash_dividend_accounting"]
    assert Decimal(accounting["gross_income"]) == income
    assert Decimal(accounting["cash_paid"]) == (income if paid else 0)
    assert Decimal(accounting["receivable"]) == (0 if paid else income)
    distribution = accounting["distributions"][0]
    assert Decimal(distribution["eligible_quantity"]) == eligible
    assert Decimal(distribution["gross_amount"]) == income
    assert distribution["paid"] is paid
    assert distribution["record_date"] == "2026-09-10"
    assert distribution["ex_date"] == "2026-09-11"
    assert accounting["taxes_modeled"] is False
    assert accounting["coverage_verified"] is False
    assert accounting["historical_availability_verified"] is False
    assert gross["metrics"]["final_equity"] - legacy["metrics"][
        "final_equity"
    ] == pytest.approx(float(income))
    assert gross["equity_curve"][:-1] == legacy["equity_curve"][:-1]
    assert gross["equity_curve"][-1]["equity"] == gross["metrics"]["final_equity"]

    saved = client.get(f"/api/backtest/results/{gross['id']}")
    assert saved.status_code == 200, saved.text
    assert saved.json()["config"] == gross["config"]
    assert saved.json()["metrics_json"]["cash_dividend_accounting"] == accounting
    report = json.loads(
        (tmp_path / "reports" / f"backtest-result-{gross['id']}.json").read_text()
    )
    assert report["config"]["corporate_action_mode"] == "cash_dividends_gross"
    assert report["metrics_json"]["cash_dividend_accounting"] == accounting
    assert report["fills"] == gross["fills"]
    snapshot = report["metrics_json"]["dataset_snapshot"]
    assert snapshot["immutable_dataset_id"] == bound.dataset_id
    assert snapshot["research_use"] == "exploratory_backtest"
    # Capturing facts and modeling an entitlement do not establish historical PIT.
    assert snapshot["corporate_action_evidence"]["returns_modeled"] is False
    assert gross["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
    assert (
        gross["research_evidence_bundle"]["promotion_gate"]["does_not_enable_execution"]
        is True
    )
    assert "fixture-secret" not in json.dumps(report)


@pytest.mark.parametrize("bound", [False, True])
def test_gross_mode_requires_dataset_and_bound_evidence_before_any_remote_fallback(
    client_context, monkeypatch, bound
):
    client, _, original, _ = client_context

    def no_network(*args, **kwargs):
        pytest.fail("Gross replay must not fall back to an external data source")

    monkeypatch.setattr("data.manager.DataManager.get_bars", no_network)
    request = _backtest_request(original).model_dump(mode="json")
    request["corporate_action_mode"] = "cash_dividends_gross"
    if not bound:
        request.pop("dataset_id")
    response = client.post("/api/backtest/run", json=request)
    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "cash_dividend_evidence_required"
        if bound
        else "cash_dividend_dataset_required"
    }
    assert client.get("/api/backtest/results").json() == []


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"stk_div": "0.1"}, "cash_dividend_share_distribution_unsupported"),
        ({"stk_div": None}, "cash_dividend_share_terms_missing"),
        ({"pay_date": None}, "cash_dividend_event_dates_incomplete"),
        ({"pay_date": "20260910"}, "cash_dividend_terms_invalid"),
        ({"record_date": "20260911"}, "cash_dividend_terms_invalid"),
        ({"div_proc": "预案"}, "cash_dividend_implemented_stock_required"),
    ],
)
def test_unsupported_or_incomplete_terms_fail_with_safe_409_and_no_report(
    client_context, monkeypatch, tmp_path, changes, code
):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _cash_response(**changes))
    response = _run(client, bound)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": code}
    assert "fixture-secret" not in response.text
    assert client.get("/api/backtest/results").json() == []
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize(
    "revised_cash,announcement,expected_order",
    [
        ("0.1", "20260821", ["0.1", "0.1"]),
        ("0.2", "20260821", ["0.1", "0.2"]),
        ("0", "20260821", ["0.1", "0"]),
        ("0", "20260819", ["0", "0.1"]),
    ],
)
def test_duplicate_implementation_announcements_cannot_double_pay(
    client_context, monkeypatch, revised_cash, announcement, expected_order
):
    client, _, _, store = client_context
    rows = pd.concat(
        [
            _cash_response(),
            _cash_response(ann_date=announcement, cash_div_tax=revised_cash),
        ],
        ignore_index=True,
    )
    bound = _capture(client_context, monkeypatch, rows)
    frozen = read_daily_bar_dataset(store, bound).corporate_action_evidence
    assert [event["cash_div_tax"] for event in frozen["events"]] == expected_order
    response = _run(client, bound)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "cash_dividend_conflicting_implementation"}
    assert client.get("/api/backtest/results").json() == []


def test_empty_reported_events_keep_coverage_unverified_and_do_not_invent_income(
    client_context, monkeypatch
):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _cash_response().iloc[:0])
    gross = _run(client, bound)
    legacy = _run(client, bound, mode=None)
    assert gross.status_code == legacy.status_code == 200, gross.text
    result = gross.json()
    accounting = result["metrics_json"]["cash_dividend_accounting"]
    assert accounting["distributions"] == []
    assert all(
        Decimal(accounting[field]) == 0
        for field in ("gross_income", "cash_paid", "receivable")
    )
    assert accounting["coverage_verified"] is False
    assert accounting["historical_availability_verified"] is False
    assert result["metrics_json"]["dataset_snapshot"]["research_use"] == (
        "exploratory_backtest"
    )
    assert result["equity_curve"] == legacy.json()["equity_curve"]
    assert result["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"
