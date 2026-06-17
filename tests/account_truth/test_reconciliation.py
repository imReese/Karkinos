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
        "fee",
        "tax",
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
    assert report.unresolved_count == 5
    assert report.suggested_review_actions == [
        "review_cash_difference",
        "review_position_difference",
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
