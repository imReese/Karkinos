from __future__ import annotations

from types import SimpleNamespace


def test_manual_trade_fee_service_formats_stock_sell_components():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.00015,
            account_min_commission=5,
            broker_fee_schedule=SimpleNamespace(
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
                limitations=(
                    "transfer_fee_exchange_not_split",
                    "broker_regulatory_fees_assumed_absorbed",
                ),
            ),
        ),
        asset_class="stock",
        direction="sell",
        quantity=200,
        price=26.35,
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json == {
        "commission": "5.00",
        "stamp_tax": "2.635000",
        "transfer_fee": "0.052700",
        "other_fees": "0.000000",
        "total_fee": "7.687700",
    }
    assert resolved.commission == 5.0
    assert resolved.total_fee == 7.6877
    assert resolved.fee_rule_id == "manual_configured_commission"
    assert resolved.fee_rule_version == "account_commission_rate"
    assert "万1.5" in resolved.note


def test_manual_trade_fee_service_formats_etf_without_stamp_tax():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.00012,
            account_min_commission=5,
            broker_fee_schedule=SimpleNamespace(
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
            ),
        ),
        asset_class="etf",
        direction="buy",
        quantity=1000,
        price=4.0,
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json == {
        "commission": "5.00",
        "stamp_tax": "0.000000",
        "transfer_fee": "0.040000",
        "other_fees": "0.000000",
        "total_fee": "5.040000",
    }


def test_manual_trade_fee_service_leaves_unsupported_assets_to_explicit_fee():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    assert (
        resolve_manual_trade_fee_breakdown(
            SimpleNamespace(account_commission_rate=0.00015, account_min_commission=5),
            asset_class="fund",
            direction="buy",
            quantity=100,
            price=1.0,
        )
        is None
    )
