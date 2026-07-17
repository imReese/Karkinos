from __future__ import annotations

import sqlite3
from pathlib import Path

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv

ALL_EVENT_TYPES_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,合成样例股票A,stock,CNY,20,10.50,210.00,5.00,0.21,204.79,9176.79,80,10.28,synthetic sell row
synthetic-dividend-001,dividend,2026-01-12T15:30:00+08:00,2026-01-12,SYN001,合成样例股票A,stock,CNY,80,0,12.50,0.00,0.00,12.50,9189.29,80,10.28,synthetic dividend row
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,9188.04,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,9187.29,,,
synthetic-transfer-in-001,transfer_in,2026-01-15T08:45:00+08:00,2026-01-15,,,,CNY,0,0,500.00,0.00,0.00,500.00,9687.29,,,
synthetic-transfer-out-001,transfer_out,2026-01-15T09:45:00+08:00,2026-01-15,,,,CNY,0,0,-300.00,0.00,0.00,-300.00,9387.29,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,9387.29,80,10.28,synthetic position snapshot
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,9387.29,,,
"""

OPTIONAL_COMPONENT_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method,broker_order_id,client_order_id
synthetic-sell-001,trade_sell,2026-01-06T10:10:00+08:00,2026-01-07,SYN001,合成样例股票A,stock,CNY,100,12.00,1200.00,1.80,1.20,1196.40,10196.40,0,8.80,synthetic sell row,0.60,broker_remaining_cost,BROKER-ORDER-001,KARK-CLIENT-001
synthetic-position-001,position_snapshot,2026-01-06T15:10:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,0,12.00,0.00,0.00,0.00,0.00,10196.40,0,8.80,synthetic position snapshot,,broker_remaining_cost,,
synthetic-cash-001,cash_snapshot,2026-01-06T15:10:00+08:00,2026-01-06,,,,CNY,0,0,0.00,0.00,0.00,0.00,10196.40,,,,,,,
"""


def test_broker_evidence_repository_stages_import_run_and_events(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "account-truth.db"
    repository = BrokerEvidenceRepository(db_path)
    preview = parse_broker_statement_csv(ALL_EVENT_TYPES_STATEMENT)

    import_run = repository.save_preview(
        preview,
        source_name="synthetic-safe-example.csv",
    )

    assert import_run.import_run_id.startswith("import_")
    assert import_run.source_type == "canonical_broker_statement_csv"
    assert import_run.source_name == "synthetic-safe-example.csv"
    assert import_run.file_fingerprint == preview.file_fingerprint
    assert import_run.row_count == 9
    assert import_run.valid_row_count == 9
    assert import_run.invalid_row_count == 0
    assert import_run.row_duplicate_count == 0
    assert import_run.file_duplicate_count == 0
    assert import_run.validation_status == "pass"
    assert import_run.limitations == preview.limitations

    saved_events = repository.list_events(import_run.import_run_id)
    assert [event.event_type for event in saved_events] == [
        "trade_buy",
        "trade_sell",
        "dividend",
        "fee",
        "tax",
        "transfer_in",
        "transfer_out",
        "position_snapshot",
        "cash_snapshot",
    ]
    assert saved_events[0].import_run_id == import_run.import_run_id
    assert saved_events[0].event_id == "synthetic-buy-001"
    assert saved_events[0].symbol == "SYN001"
    assert saved_events[0].quantity == "100"
    assert saved_events[0].fee == "5.00"
    assert saved_events[0].net_amount == "-1028.00"


def test_broker_evidence_repository_persists_optional_reconciliation_components(
    tmp_path: Path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(OPTIONAL_COMPONENT_STATEMENT)
    import_run = repository.save_preview(
        preview,
        source_name="synthetic-components.csv",
    )

    saved_events = repository.list_events(import_run.import_run_id)

    assert saved_events[0].transfer_fee == "0.60"
    assert saved_events[0].cost_basis_method == "broker_remaining_cost"
    assert saved_events[1].transfer_fee == "0"
    assert saved_events[1].cost_basis_method == "broker_remaining_cost"


def test_broker_evidence_repository_persists_order_identity_evidence(
    tmp_path: Path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(OPTIONAL_COMPONENT_STATEMENT)
    import_run = repository.save_preview(
        preview,
        source_name="synthetic-order-identity.csv",
    )

    saved_events = repository.list_events(import_run.import_run_id)

    assert saved_events[0].broker_order_id == "BROKER-ORDER-001"
    assert saved_events[0].client_order_id == "KARK-CLIENT-001"
    assert saved_events[1].broker_order_id == ""
    assert saved_events[1].client_order_id == ""


def test_broker_evidence_repository_migrates_legacy_order_identity_columns(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy-account-truth.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE broker_evidence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_run_id TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                row_fingerprint TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                settled_at TEXT NOT NULL,
                symbol TEXT NOT NULL,
                instrument_name TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                currency TEXT NOT NULL,
                quantity TEXT NOT NULL,
                price TEXT NOT NULL,
                gross_amount TEXT NOT NULL,
                fee TEXT NOT NULL,
                tax TEXT NOT NULL,
                net_amount TEXT NOT NULL,
                cash_balance TEXT,
                position_quantity TEXT,
                cost_basis TEXT,
                note TEXT NOT NULL,
                is_row_duplicate INTEGER NOT NULL,
                duplicate_of_row_number INTEGER,
                transfer_fee TEXT NOT NULL DEFAULT '0',
                cost_basis_method TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
        """)
        conn.execute(
            """
            INSERT INTO broker_evidence_events (
                import_run_id, row_number, row_fingerprint, event_id, event_type,
                occurred_at, settled_at, symbol, instrument_name, asset_class,
                currency, quantity, price, gross_amount, fee, tax, net_amount,
                note, is_row_duplicate, transfer_fee, cost_basis_method, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-import",
                1,
                "legacy-row",
                "legacy-event",
                "trade_buy",
                "2026-01-05T09:35:00+08:00",
                "2026-01-06",
                "SYN001",
                "合成样例股票A",
                "stock",
                "CNY",
                "100",
                "10.23",
                "1023.00",
                "5.00",
                "0.00",
                "-1028.00",
                "legacy evidence",
                0,
                "0",
                "",
                "2026-01-05T01:35:00+00:00",
            ),
        )
        conn.commit()

    BrokerEvidenceRepository(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("""
            SELECT broker_order_id, client_order_id
            FROM broker_evidence_events
            WHERE event_id = 'legacy-event'
            """).fetchone()

    assert row == ("", "")


def test_broker_evidence_repository_reimports_same_file_idempotently(
    tmp_path: Path,
) -> None:
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(ALL_EVENT_TYPES_STATEMENT)

    first_run = repository.save_preview(preview, source_name="first.csv")
    first_seen_at = "2026-01-15T07:10:00+00:00"
    with sqlite3.connect(repository._path) as conn:
        conn.execute(
            "UPDATE broker_import_runs SET created_at = ? WHERE import_run_id = ?",
            (first_seen_at, first_run.import_run_id),
        )
        conn.commit()
    second_run = repository.save_preview(preview, source_name="second.csv")
    import_runs = repository.list_import_runs(limit=10)

    assert second_run.import_run_id == first_run.import_run_id
    assert second_run.created_at == first_seen_at
    assert second_run.source_name == "second.csv"
    assert second_run.file_duplicate_count == 0
    assert second_run.duplicate_of_import_run_id is None
    assert second_run.validation_status == "pass"
    assert len(import_runs) == 1
    assert import_runs[0].import_run_id == first_run.import_run_id
    assert import_runs[0].source_name == "second.csv"
    assert len(repository.list_events(second_run.import_run_id)) == 9


def test_broker_evidence_repository_does_not_mutate_production_ledger(
    tmp_path: Path,
) -> None:
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
            ("cash_deposit", 1000.0),
        )
        conn.commit()

    repository = BrokerEvidenceRepository(db_path)
    preview = parse_broker_statement_csv(ALL_EVENT_TYPES_STATEMENT)
    repository.save_preview(preview, source_name="synthetic-safe-example.csv")

    with sqlite3.connect(db_path) as conn:
        ledger_count = conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
        ledger_amount = conn.execute(
            "SELECT SUM(amount) FROM ledger_entries"
        ).fetchone()[0]

    assert ledger_count == 1
    assert ledger_amount == 1000.0
