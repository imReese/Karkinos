from __future__ import annotations

from decimal import Decimal

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    build_reconciliation_report,
)

MATCHING_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,8970.75,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,8970.00,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,8970.00,100,10.28,synthetic position snapshot
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,8970.00,,,
"""

COMPONENT_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,合成样例股票A,stock,CNY,100,12.00,1200.00,1.80,1.20,1196.40,10196.40,0,8.80,synthetic sell row,0.60,broker_remaining_cost
synthetic-position-001,position_snapshot,2026-01-06T15:10:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,0,12.00,0.00,0.00,0.00,0.00,10196.40,0,8.80,synthetic position snapshot,,broker_remaining_cost
synthetic-cash-001,cash_snapshot,2026-01-06T15:10:00+08:00,2026-01-06,,,,CNY,0,0,0.00,0.00,0.00,0.00,10196.40,,,,,
"""

STOCK_POSITION_SCOPE_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
synthetic-stock-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,STK001,合成股票持仓,stock,CNY,0,10.50,0.00,0.00,0.00,0.00,,100,10.20,stock account snapshot,,broker_remaining_cost
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,1000.00,,,,,
"""


def test_reconciliation_report_passes_when_account_facts_match(tmp_path) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(MATCHING_STATEMENT)
    import_run = repository.save_preview(preview, source_name="matching.csv")
    broker_events = repository.list_events(import_run.import_run_id)

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=broker_events,
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_buy",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("5.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1028.00"),
            ),
            KarkinosLedgerFact(
                event_type="fee",
                fee=Decimal("1.25"),
                net_amount=Decimal("-1.25"),
            ),
            KarkinosLedgerFact(
                event_type="tax",
                tax=Decimal("0.75"),
                net_amount=Decimal("-0.75"),
            ),
        ],
        cash_balance=Decimal("8970.00"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("100"),
                cost_basis=Decimal("10.28"),
            )
        ],
    )

    assert report.schema_version == "karkinos.account_truth.reconciliation.v1"
    assert report.import_run_id == import_run.import_run_id
    assert report.status == "pass"
    assert report.cash_difference == Decimal("0.00")
    assert report.fee_difference == Decimal("0.00")
    assert report.tax_difference == Decimal("0.00")
    assert report.unresolved_count == 0
    assert report.suggested_review_actions == []
    assert {item.category for item in report.items} == {
        "cash",
        "position",
        "trade_gross_amount",
        "net_cash_impact",
        "fee",
        "tax",
        "transfer_fee",
        "cost_basis",
    }


def test_reconciliation_report_surfaces_mismatches_with_review_actions(
    tmp_path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(MATCHING_STATEMENT)
    import_run = repository.save_preview(preview, source_name="mismatch.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_buy",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("4.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1027.00"),
            )
        ],
        cash_balance=Decimal("9000.00"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("99"),
                cost_basis=Decimal("10.20"),
            )
        ],
    )

    assert report.status == "mismatch"
    assert report.cash_difference == Decimal("-30.00")
    assert report.fee_difference == Decimal("2.25")
    assert report.tax_difference == Decimal("0.75")
    assert report.unresolved_count == 7
    assert report.suggested_review_actions == [
        "review_cash_difference",
        "review_position_difference",
        "review_net_cash_impact_difference",
        "review_fee_difference",
        "review_tax_difference",
        "review_cost_basis_difference",
    ]

    by_category = {item.category: item for item in report.items}
    assert by_category["cash"].status == "mismatch"
    assert by_category["cash"].broker_value == "8970.00"
    assert by_category["cash"].karkinos_value == "9000.00"
    assert by_category["cash"].difference == "-30.00"
    assert by_category["position"].symbol == "SYN001"
    assert by_category["position"].difference == "1"
    assert by_category["position"].detail_code == (
        "account_truth.position_quantity_compared"
    )
    assert by_category["net_cash_impact"].difference == "-1.00"
    assert by_category["fee"].difference == "2.25"
    assert by_category["tax"].difference == "0.75"
    assert by_category["cost_basis"].difference == "0.08"


def test_reconciliation_report_blocks_without_broker_evidence() -> None:
    report = build_reconciliation_report(
        import_run_id="import_empty",
        broker_events=[],
        ledger_facts=[],
        cash_balance=Decimal("0.00"),
        positions=[],
    )

    assert report.status == "blocked"
    assert report.unresolved_count == 1
    assert report.items[0].category == "import"
    assert report.items[0].suggested_review_action == "import_broker_evidence"


def test_reconciliation_report_warns_when_snapshot_evidence_is_incomplete(
    tmp_path,
) -> None:
    statement = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,,,,synthetic fee only
"""
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(statement)
    import_run = repository.save_preview(preview, source_name="warning.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="fee",
                fee=Decimal("1.25"),
                net_amount=Decimal("-1.25"),
            )
        ],
        cash_balance=Decimal("1000.00"),
        positions=[],
    )

    assert report.status == "warning"
    assert report.unresolved_count == 2
    assert report.suggested_review_actions == [
        "provide_cash_snapshot",
        "provide_position_snapshot",
    ]
    assert [(item.category, item.status) for item in report.items[:2]] == [
        ("cash", "warning"),
        ("position", "warning"),
    ]


def test_reconciliation_scopes_position_snapshot_to_covered_asset_classes(
    tmp_path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(STOCK_POSITION_SCOPE_STATEMENT)
    import_run = repository.save_preview(preview, source_name="stock-account.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[],
        cash_balance=Decimal("1000.00"),
        positions=[
            KarkinosPositionFact(
                symbol="STK001",
                quantity=Decimal("100"),
                cost_basis=Decimal("10.20"),
                cost_basis_method="broker_remaining_cost",
                asset_class="stock",
            ),
            KarkinosPositionFact(
                symbol="FUND001",
                quantity=Decimal("50"),
                cost_basis=Decimal("2.00"),
                asset_class="fund",
            ),
        ],
    )

    by_key = {(item.category, item.symbol): item for item in report.items}

    assert by_key[("position", "STK001")].status == "pass"
    assert by_key[("cost_basis", "STK001")].status == "pass"
    assert ("position", "FUND001") not in by_key
    assert ("cost_basis", "FUND001") not in by_key

    scope_item = by_key[("position", "")]
    assert scope_item.status == "warning"
    assert scope_item.suggested_review_action == "provide_position_snapshot"
    assert scope_item.detail_context == {
        "covered_asset_classes": "stock",
        "uncovered_asset_classes": "fund",
    }
    assert report.status == "warning"


def test_reconciliation_report_distinguishes_trade_cash_fee_tax_transfer_and_cost_basis(
    tmp_path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(COMPONENT_STATEMENT)
    import_run = repository.save_preview(preview, source_name="components.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_sell",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("12.00"),
                gross_amount=Decimal("1200.00"),
                fee=Decimal("1.50"),
                tax=Decimal("1.20"),
                transfer_fee=Decimal("0.60"),
                net_amount=Decimal("1196.70"),
            )
        ],
        cash_balance=Decimal("10196.40"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("0"),
                cost_basis=Decimal("8.70"),
            )
        ],
    )

    by_key = {(item.category, item.symbol): item for item in report.items}

    assert by_key[("trade_gross_amount", "SYN001")].status == "pass"
    assert by_key[("trade_gross_amount", "SYN001")].broker_value == "1200.00"
    assert by_key[("trade_gross_amount", "SYN001")].karkinos_value == "1200.00"

    net_cash_item = by_key[("net_cash_impact", "SYN001")]
    assert net_cash_item.status == "mismatch"
    assert net_cash_item.broker_value == "1196.40"
    assert net_cash_item.karkinos_value == "1196.70"
    assert net_cash_item.difference == "-0.30"
    assert net_cash_item.suggested_review_action == (
        "review_net_cash_impact_difference"
    )

    fee_item = by_key[("fee", "SYN001")]
    assert fee_item.status == "mismatch"
    assert fee_item.broker_value == "1.80"
    assert fee_item.karkinos_value == "1.50"
    assert fee_item.difference == "0.30"

    assert by_key[("tax", "SYN001")].status == "pass"
    assert by_key[("transfer_fee", "SYN001")].status == "pass"

    cost_basis_item = by_key[("cost_basis", "SYN001")]
    assert cost_basis_item.status == "mismatch"
    assert cost_basis_item.difference == "0.10"
    assert cost_basis_item.detail_code == "account_truth.cost_basis_compared"
    assert cost_basis_item.detail_context == {
        "broker_cost_basis_method": "broker_remaining_cost",
        "karkinos_cost_basis_method": "moving_average_buy_cost",
        "comparison_unit": "per_share_cost_basis",
        "comparison_precision": "decimal_string_no_rounding",
        "precision_limitation": (
            "broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding"
        ),
    }
    assert "broker_remaining_cost" in cost_basis_item.detail


def test_reconciliation_report_treats_tiny_decimal_noise_as_pass(tmp_path) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(COMPONENT_STATEMENT)
    import_run = repository.save_preview(preview, source_name="components.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_sell",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("12.00000000000000011667"),
                gross_amount=Decimal("1200.000000000000011667"),
                fee=Decimal("1.80"),
                tax=Decimal("1.20"),
                transfer_fee=Decimal("0.60"),
                net_amount=Decimal("1196.400000000000011667"),
            )
        ],
        cash_balance=Decimal("10196.40"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("0"),
                cost_basis=Decimal("8.80"),
            )
        ],
    )

    noisy_items = [
        item
        for item in report.items
        if item.category in {"trade_gross_amount", "net_cash_impact"}
    ]
    assert all(item.status == "pass" for item in noisy_items)
    assert all(item.difference == "0" for item in noisy_items)


def test_reconciliation_report_treats_sub_cent_money_differences_as_pass(
    tmp_path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(COMPONENT_STATEMENT)
    import_run = repository.save_preview(preview, source_name="components.csv")

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_sell",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("12.00"),
                gross_amount=Decimal("1200.00"),
                fee=Decimal("1.80"),
                tax=Decimal("1.198"),
                transfer_fee=Decimal("0.59776"),
                net_amount=Decimal("1196.40424"),
            )
        ],
        cash_balance=Decimal("10196.40"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("0"),
                cost_basis=Decimal("8.80"),
            )
        ],
    )

    money_items = [
        item
        for item in report.items
        if item.category in {"net_cash_impact", "tax", "transfer_fee"}
    ]
    assert all(item.status == "pass" for item in money_items)
    assert all(item.difference == "0" for item in money_items)


def test_reconciliation_cost_basis_context_explains_methods_and_precision(
    tmp_path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(COMPONENT_STATEMENT)
    import_run = repository.save_preview(
        preview,
        source_name="cost-basis-context.csv",
    )

    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_sell",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("12.00"),
                gross_amount=Decimal("1200.00"),
                fee=Decimal("1.80"),
                tax=Decimal("1.20"),
                transfer_fee=Decimal("0.60"),
                net_amount=Decimal("1196.40"),
            )
        ],
        cash_balance=Decimal("10196.40"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("0"),
                cost_basis=Decimal("8.8000"),
                cost_basis_method="broker_remaining_cost",
            )
        ],
    )

    cost_basis_item = next(
        item
        for item in report.items
        if item.category == "cost_basis" and item.symbol == "SYN001"
    )

    assert cost_basis_item.status == "pass"
    assert cost_basis_item.detail_context == {
        "broker_cost_basis_method": "broker_remaining_cost",
        "karkinos_cost_basis_method": "broker_remaining_cost",
        "comparison_unit": "per_share_cost_basis",
        "comparison_precision": "decimal_string_no_rounding",
        "precision_limitation": (
            "broker_display_precision_fee_allocation_tax_timing_transfer_fee_rounding"
        ),
    }
    assert "per-share" in cost_basis_item.detail
    assert "precision" in cost_basis_item.detail
