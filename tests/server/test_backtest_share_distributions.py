"""Real frozen observations feed explicit share accounting and saved API reports."""

import json
from decimal import Decimal

import pytest

from tests.server.test_backtest_cash_dividends import _capture, _cash_response
from tests.server.test_backtest_cash_dividends import _run as _run_cash
from tests.server.test_dataset_corporate_actions import (
    client_context as client_context,
)

MODE = "reported_distributions_gross"


def _run(client, ref, *, mode):
    # Fix the entry quantity for the distribution-accounting assertions; cost
    # and capacity behavior have their own real-fill integration coverage.
    return _run_cash(
        client,
        ref,
        mode=mode,
        cost_assumptions={"slippage_bps": 0, "max_volume_participation": 1},
    )


def _share_response(**changes):
    return _cash_response(
        **{
            "stk_div": "0.3",
            "stk_bo_rate": "0.1",
            "stk_co_rate": "0.2",
            "div_listdate": "20260911",
            **changes,
        }
    )


@pytest.mark.parametrize("listing,listed", [("20260911", True), ("20260914", False)])
def test_explicit_share_mode_persists_quantity_listing_lock_and_original_snapshot(
    client_context, monkeypatch, tmp_path, listing, listed
):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _share_response(div_listdate=listing))
    legacy = _run(client, bound, mode=None)
    response = _run(client, bound, mode=MODE)
    assert legacy.status_code == response.status_code == 200, response.text
    result = response.json()
    assert len(result["fills"]) == 1
    assert result["fills"][0]["fill_quantity"] == 900
    accounting = result["metrics_json"]["cash_dividend_accounting"]
    assert accounting["schema_version"] == "karkinos.backtest_cash_dividends.v2"
    assert accounting["mode"] == MODE
    assert Decimal(accounting["share_quantity"]) == 270
    assert Decimal(accounting["unlisted_quantity"]) == (0 if listed else 270)
    assert Decimal(accounting["gross_income"]) == 90
    assert Decimal(accounting["cash_paid"]) == 90
    distribution = accounting["distributions"][0]
    assert Decimal(distribution["eligible_quantity"]) == 900
    assert Decimal(distribution["shares_per_share"]) == Decimal("0.3")
    assert Decimal(distribution["share_quantity"]) == 270
    assert distribution["shares_listed"] is listed
    assert result["metrics"]["final_equity"] - legacy.json()["metrics"][
        "final_equity"
    ] == pytest.approx(270 * 10.5 + 90)
    assert "cash_dividend_accounting" not in legacy.json()["metrics_json"]
    assert accounting["coverage_verified"] is False
    assert accounting["historical_availability_verified"] is False
    assert result["research_evidence_bundle"]["promotion_gate"]["status"] == "blocked"

    saved = client.get(f"/api/backtest/results/{result['id']}")
    assert saved.status_code == 200
    assert saved.json()["metrics_json"]["cash_dividend_accounting"] == accounting
    assert saved.json()["config"]["corporate_action_mode"] == MODE
    report = json.loads(
        (tmp_path / "reports" / f"backtest-result-{result['id']}.json").read_text()
    )
    assert report["metrics_json"]["cash_dividend_accounting"] == accounting
    assert report["config"]["dataset_id"] == bound.dataset_id
    snapshot = report["metrics_json"]["dataset_snapshot"]
    assert snapshot == legacy.json()["metrics_json"]["dataset_snapshot"]
    assert snapshot["corporate_action_evidence"]["returns_modeled"] is False
    assert "fixture-secret" not in json.dumps(report)


@pytest.mark.parametrize("pay_date", [None, "20260907"])
def test_pure_share_award_does_not_interpret_irrelevant_cash_payment_date(
    client_context, monkeypatch, pay_date
):
    client, _, _, _ = client_context
    bound = _capture(
        client_context,
        monkeypatch,
        _share_response(cash_div_tax="0", cash_div="0", pay_date=pay_date),
    )
    response = _run(client, bound, mode=MODE)
    assert response.status_code == 200, response.text
    accounting = response.json()["metrics_json"]["cash_dividend_accounting"]
    assert Decimal(accounting["share_quantity"]) == 270
    assert Decimal(accounting["gross_income"]) == 0
    assert Decimal(accounting["cash_paid"]) == 0
    assert accounting["distributions"][0]["paid"] is False
    assert accounting["distributions"][0]["shares_listed"] is True


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"div_listdate": None}, "cash_dividend_event_dates_incomplete"),
        ({"div_listdate": "20260910"}, "cash_dividend_terms_invalid"),
        ({"stk_co_rate": "0.1"}, "share_distribution_terms_conflicting"),
        ({"stk_bo_rate": None}, "cash_dividend_share_terms_missing"),
        (
            {"stk_div": "0.01", "stk_bo_rate": "0.001", "stk_co_rate": "0.009"},
            "portfolio_share_distribution_fractional_unsupported",
        ),
    ],
)
def test_unusable_share_terms_are_safe_409_not_silently_rounded_or_saved(
    client_context, monkeypatch, tmp_path, changes, code
):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _share_response(**changes))
    response = _run(client, bound, mode=MODE)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": code}
    assert client.get("/api/backtest/results").json() == []
    assert not (tmp_path / "reports").exists()
    assert "fixture-secret" not in response.text


def test_cash_only_mode_still_rejects_share_terms(client_context, monkeypatch):
    client, _, _, _ = client_context
    bound = _capture(client_context, monkeypatch, _share_response())
    response = _run(client, bound, mode="cash_dividends_gross")
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": "cash_dividend_share_distribution_unsupported"}
