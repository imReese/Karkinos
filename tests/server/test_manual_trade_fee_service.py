from __future__ import annotations

from types import SimpleNamespace


def test_manual_trade_fee_service_formats_stock_sell_components():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.0002,
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
        price=16.25,
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json == {
        "commission": "5.00",
        "stamp_tax": "1.625000",
        "transfer_fee": "0.032500",
        "other_fees": "0.000000",
        "total_fee": "6.657500",
    }
    assert resolved.commission == 5.0
    assert resolved.total_fee == 6.6575
    assert resolved.fee_rule_id == "manual_configured_commission"
    assert resolved.fee_rule_version == "broker_fee_schedule"
    assert "万2" in resolved.note


def test_manual_trade_fee_service_prefers_broker_fee_schedule_account_terms():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.0002,
            account_min_commission=5,
            broker_fee_schedule=SimpleNamespace(
                schedule_id="citic-account-fees",
                stock_a_commission_rate=0.00015,
                stock_a_min_commission=3,
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
            ),
        ),
        asset_class="stock",
        direction="buy",
        quantity=1000,
        price=10,
        symbol="600000",
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json["commission"] == "3.00"
    assert resolved.fee_rule_version == "citic-account-fees"
    assert "万1.5" in resolved.note


def test_manual_trade_fee_service_uses_symbol_exchange_transfer_fee_split():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    config = SimpleNamespace(
        account_commission_rate=0.00015,
        account_min_commission=5,
        broker_fee_schedule=SimpleNamespace(
            stamp_tax_rate=0.0005,
            transfer_fee_rate=0.00001,
            exchange_transfer_fee_rates={
                "shanghai": "0.00001",
                "shenzhen": "0",
            },
            other_fee_rate=0,
            limitations=(
                "transfer_fee_exchange_not_split",
                "broker_regulatory_fees_assumed_absorbed",
            ),
        ),
    )

    shenzhen = resolve_manual_trade_fee_breakdown(
        config,
        asset_class="stock",
        direction="sell",
        quantity=1000,
        price=10,
        symbol="000001",
    )
    shanghai = resolve_manual_trade_fee_breakdown(
        config,
        asset_class="stock",
        direction="sell",
        quantity=1000,
        price=10,
        symbol="600000",
    )

    assert shenzhen is not None
    assert shanghai is not None
    assert shenzhen.fee_breakdown_json["transfer_fee"] == "0.000000"
    assert shenzhen.fee_breakdown_json["total_fee"] == "10.000000"
    assert shanghai.fee_breakdown_json["transfer_fee"] == "0.100000"
    assert shanghai.fee_breakdown_json["total_fee"] == "10.100000"


def test_manual_trade_fee_service_uses_account_profile_and_schedule_as_fee_rule_version():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.00015,
            account_min_commission=5,
            broker_fee_schedule=SimpleNamespace(
                schedule_id="local_broker_fee_schedule",
                account_profile_id="primary-citic-securities",
                stamp_tax_rate=0.0005,
                transfer_fee_rate=0.00001,
                other_fee_rate=0,
            ),
        ),
        asset_class="stock",
        direction="buy",
        quantity=100,
        price=10,
        symbol="600000",
    )

    assert resolved is not None
    assert resolved.fee_rule_id == "manual_configured_commission"
    assert (
        resolved.fee_rule_version
        == "primary-citic-securities/local_broker_fee_schedule"
    )


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


def test_manual_trade_fee_service_formats_bond_without_stock_taxes():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.00004,
            account_min_commission=1,
            broker_fee_schedule=SimpleNamespace(other_fee_rate=0),
        ),
        asset_class="bond",
        direction="sell",
        quantity=1000,
        price=100,
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json == {
        "commission": "4.00",
        "stamp_tax": "0.000000",
        "transfer_fee": "0.000000",
        "other_fees": "0.000000",
        "total_fee": "4.000000",
    }
    assert resolved.commission == 4.0
    assert resolved.total_fee == 4.0
    assert resolved.fee_rule_id == "manual_configured_commission"
    assert resolved.fee_rule_version == "broker_fee_schedule"


def test_manual_trade_fee_service_treats_convertible_bond_as_exchange_bond_fee():
    from server.services.manual_trade_fees import resolve_manual_trade_fee_breakdown

    resolved = resolve_manual_trade_fee_breakdown(
        SimpleNamespace(
            account_commission_rate=0.00004,
            account_min_commission=1,
            broker_fee_schedule=SimpleNamespace(other_fee_rate=0.000001),
        ),
        asset_class="convertible_bond",
        direction="sell",
        quantity=100,
        price=115,
        symbol="113001",
    )

    assert resolved is not None
    assert resolved.fee_breakdown_json == {
        "commission": "1.00",
        "stamp_tax": "0.000000",
        "transfer_fee": "0.000000",
        "other_fees": "0.011500",
        "total_fee": "1.011500",
    }
    assert resolved.commission == 1.0
    assert resolved.total_fee == 1.0115
    assert resolved.fee_rule_id == "manual_configured_commission"
    assert resolved.fee_rule_version == "broker_fee_schedule"


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
