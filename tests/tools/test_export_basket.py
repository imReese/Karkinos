"""The export CLI consumes actual ticket snapshots, without creating orders."""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

import pytest

from server.contracts.financial_values import EXACT_DECIMAL_WRITE_PROVENANCE
from server.projections.manual_order_export import export_manual_order_review_csv
from tools.export_basket import main


def ticket(**changes):
    return {
        "order_id": "fixture-order",
        "timestamp": "2026-10-08T09:00:00+08:00",
        "symbol": "510300",
        "side": "sell",
        "order_type": "limit",
        "quantity": 125.25,
        "quantity_decimal": "125.25",
        "price": 3.1234567890123457,
        "price_decimal": "3.123456789012345678",
        "currency_code": "CNY",
        "execution_mode": "manual",
        "status": "pending_confirm",
        "intent_id": "fixture-intent",
        "risk_decision_id": "fixture-risk",
        "decimal_provenance": EXACT_DECIMAL_WRITE_PROVENANCE,
        **changes,
    }


def test_cli_preserves_sell_quantity_exact_price_and_unconfirmed_state(tmp_path):
    source = tmp_path / "orders.json"
    destination = tmp_path / "review.csv"
    source.write_text(json.dumps([ticket()]), encoding="utf-8")
    original = source.read_bytes()
    main(["--input", str(source), "--output", str(destination)])
    row = list(csv.DictReader(io.StringIO(destination.read_text())))[0]
    assert row["purpose"] == "review_only"
    assert row["quantity"] == "125.25"  # no lot rounding or BUY-only sizing
    assert row["side"] == "sell"
    assert row["price"] == "3.123456789012345678"
    assert row["status"] == "pending_confirm"
    assert row["risk_decision_id"] == "fixture-risk"
    assert source.read_bytes() == original
    with pytest.raises(SystemExit) as error:
        main(["--input", str(source), "--output", str(destination)])
    assert error.value.code == 2
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": -1, "quantity_decimal": "-1"},
        {"quantity_decimal": "200"},
        {"quantity_decimal": None},
        {"quantity_decimal": []},
        {"quantity": True, "quantity_decimal": "1"},
        {"price": None, "price_decimal": None},
        {"price": 0, "price_decimal": "0"},
        {"quantity": Decimal("NaN"), "quantity_decimal": "NaN"},
        {"side": "long"},
        {"order_type": "stop"},
        {"execution_mode": "paper"},
        {"status": "approved"},
        {"decimal_provenance": None},
        {"order_id": ""},
        {"timestamp": None},
    ],
)
def test_invalid_or_ambiguous_ticket_is_not_exported(change):
    with pytest.raises(ValueError):
        export_manual_order_review_csv([ticket(**change)])


def test_no_price_invention_and_safe_spreadsheet_text():
    rows = list(
        csv.DictReader(
            io.StringIO(
                export_manual_order_review_csv(
                    [
                        ticket(
                            order_type="market",
                            price=None,
                            price_decimal=None,
                            risk_decision_id="=1+1",
                            status="rejected",
                        ),
                    ]
                )
            )
        )
    )
    assert rows[0]["price"] == ""
    assert rows[0]["risk_decision_id"] == "'=1+1"
    assert rows[0]["status"] == "rejected"


def test_legacy_backfill_preserves_its_actual_available_precision():
    rows = list(
        csv.DictReader(
            io.StringIO(
                export_manual_order_review_csv(
                    [
                        ticket(
                            price=3.1234567890123457,
                            price_decimal="3.12345678901235",
                            decimal_provenance="legacy_real_backfill_v1",
                        ),
                    ]
                )
            )
        )
    )
    assert rows[0]["price"] == "3.1234567890123457"
    assert rows[0]["decimal_provenance"] == "legacy_real_backfill_v1"


def test_duplicates_and_partial_bad_batch_leave_no_file(tmp_path):
    source = tmp_path / "orders.json"
    destination = tmp_path / "review.csv"
    for payload in ([ticket(), ticket()], [ticket(), ticket(order_id="bad", side="?")]):
        source.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["--input", str(source), "--output", str(destination)])
        assert not destination.exists()
    source.write_text('[{"order_id":"a","order_id":"b"}]', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--input", str(source), "--output", str(destination)])
    assert not destination.exists()


def test_empty_snapshot_is_header_only_and_cli_has_no_demo_default(capsys):
    assert len(export_manual_order_review_csv([]).splitlines()) == 1
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""
