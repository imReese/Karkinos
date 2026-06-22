from __future__ import annotations

import sqlite3
from decimal import Decimal

from account_truth.broker_connector import (
    BrokerCashFact,
    BrokerConnectorHealth,
    BrokerConnectorSnapshot,
    BrokerFillFact,
    BrokerPositionFact,
)
from account_truth.broker_connector_evidence import (
    BROKER_CONNECTOR_SOURCE_TYPE,
    build_broker_connector_evidence_preview,
)
from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.reconciliation import (
    KarkinosLedgerFact,
    KarkinosPositionFact,
    build_reconciliation_report,
)


def test_connector_snapshot_normalizes_into_reconciliation_ready_evidence(tmp_path):
    snapshot = _healthy_snapshot()

    preview = build_broker_connector_evidence_preview(snapshot)

    assert preview.source_type == BROKER_CONNECTOR_SOURCE_TYPE
    assert preview.validation_status == "pass"
    assert preview.row_count == 3
    assert preview.valid_row_count == 3
    assert preview.invalid_row_count == 0
    assert preview.duplicate_row_count == 0
    assert [event.event_type for event in preview.events] == [
        "trade_buy",
        "cash_snapshot",
        "position_snapshot",
    ]
    assert preview.events[0].event_id == "fake_qmt_readonly:fill:synthetic-fill-001"
    assert preview.events[0].fee == Decimal("5.00")
    assert preview.events[0].tax == Decimal("0.00")
    assert preview.events[1].cash_balance == Decimal("8972.00")
    assert preview.events[2].position_quantity == Decimal("100")
    assert preview.events[2].cost_basis == Decimal("10.28")

    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    import_run = repository.save_preview(
        preview,
        source_name=snapshot.source_name,
    )
    report = build_reconciliation_report(
        import_run_id=import_run.import_run_id,
        broker_events=repository.list_events(import_run.import_run_id),
        ledger_facts=[
            KarkinosLedgerFact(
                event_type="trade_buy",
                symbol="SYN001",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("5.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1028.00"),
            )
        ],
        cash_balance=Decimal("8972.00"),
        positions=[
            KarkinosPositionFact(
                symbol="SYN001",
                quantity=Decimal("100"),
                cost_basis=Decimal("10.28"),
            )
        ],
    )

    assert import_run.source_type == BROKER_CONNECTOR_SOURCE_TYPE
    assert report.status == "pass"
    assert report.unresolved_count == 0


def test_connector_evidence_persistence_does_not_mutate_production_ledger(tmp_path):
    db_path = tmp_path / "account-truth.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type TEXT NOT NULL,
                amount REAL
            )
            """)
        conn.execute(
            "INSERT INTO ledger_entries (entry_type, amount) VALUES (?, ?)",
            ("cash_deposit", 3000.0),
        )
        conn.commit()

    repository = BrokerEvidenceRepository(db_path)
    preview = build_broker_connector_evidence_preview(_healthy_snapshot())
    repository.save_preview(preview, source_name="synthetic readonly connector")

    with sqlite3.connect(db_path) as conn:
        ledger_count = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        ledger_amount = conn.execute(
            "SELECT SUM(amount) FROM ledger_entries"
        ).fetchone()[0]

    assert ledger_count == 1
    assert ledger_amount == 3000.0


def test_connector_evidence_builder_is_exported_from_account_truth_package():
    from account_truth import (
        BROKER_CONNECTOR_SOURCE_TYPE as exported_source_type,
        build_broker_connector_evidence_preview as exported_builder,
    )

    assert exported_source_type == BROKER_CONNECTOR_SOURCE_TYPE
    assert exported_builder is build_broker_connector_evidence_preview


def _healthy_snapshot() -> BrokerConnectorSnapshot:
    return BrokerConnectorSnapshot(
        connector_id="fake_qmt_readonly",
        source_name="synthetic qmt readonly fixture",
        account_id="synthetic-account",
        account_alias="safe-local-alias",
        captured_at="2026-06-22T15:05:00+08:00",
        health=BrokerConnectorHealth(
            status="healthy",
            checked_at="2026-06-22T15:05:00+08:00",
            message="synthetic connector is healthy",
        ),
        cash=BrokerCashFact(
            currency="CNY",
            balance=Decimal("8972.00"),
            available=Decimal("8800.00"),
        ),
        positions=[
            BrokerPositionFact(
                symbol="SYN001",
                instrument_name="合成样例股票A",
                asset_class="stock",
                quantity=Decimal("100"),
                available_quantity=Decimal("0"),
                cost_basis=Decimal("10.28"),
                market_price=Decimal("10.40"),
            )
        ],
        fills=[
            BrokerFillFact(
                fill_id="synthetic-fill-001",
                order_id="synthetic-order-001",
                symbol="SYN001",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("10.23"),
                fee=Decimal("5.00"),
                tax=Decimal("0.00"),
                net_amount=Decimal("-1028.00"),
                filled_at="2026-06-22T10:05:05+08:00",
            )
        ],
        limitations=["Synthetic fixture; no broker client is contacted."],
    )
