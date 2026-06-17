from __future__ import annotations

from decimal import Decimal

from account_truth.broker_statement import (
    BROKER_STATEMENT_EVENT_TYPES,
    BROKER_STATEMENT_REQUIRED_COLUMNS,
    parse_broker_statement_csv,
)

SYNTHETIC_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row
synthetic-dividend-001,dividend,2026-01-12T15:30:00+08:00,2026-01-12,SYN001,合成样例股票A,stock,CNY,100,0,12.50,0.00,0.00,12.50,8984.50,100,10.28,synthetic dividend row
synthetic-fee-001,fee,2026-01-13T15:30:00+08:00,2026-01-13,,,,CNY,0,0,0.00,1.25,0.00,-1.25,8983.25,,,
synthetic-tax-001,tax,2026-01-14T15:30:00+08:00,2026-01-14,,,,CNY,0,0,0.00,0.00,0.75,-0.75,8982.50,,,
synthetic-transfer-001,transfer_in,2026-01-15T08:45:00+08:00,2026-01-15,,,,CNY,0,0,500.00,0.00,0.00,500.00,9482.50,,,
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,合成样例股票A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,9482.50,100,10.28,synthetic position snapshot
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,9482.50,,,
"""


def test_canonical_broker_statement_preview_normalizes_synthetic_rows() -> None:
    preview = parse_broker_statement_csv(SYNTHETIC_STATEMENT)

    assert preview.schema_version == "karkinos.broker_statement.v1"
    assert preview.source_type == "canonical_broker_statement_csv"
    assert preview.validation_status == "pass"
    assert preview.row_count == 7
    assert preview.valid_row_count == 7
    assert preview.invalid_row_count == 0
    assert preview.duplicate_row_count == 0
    assert len(preview.file_fingerprint) == 64
    assert preview.limitations == [
        "Import preview is broker evidence only; it does not mutate the production ledger.",
        "Synthetic examples are safe for tests and docs, but real broker exports must stay local.",
    ]

    first_event = preview.events[0]
    assert first_event.event_type == "trade_buy"
    assert first_event.event_id == "synthetic-buy-001"
    assert first_event.symbol == "SYN001"
    assert first_event.instrument_name == "合成样例股票A"
    assert first_event.asset_class == "stock"
    assert first_event.quantity == Decimal("100")
    assert first_event.price == Decimal("10.23")
    assert first_event.fee == Decimal("5.00")
    assert first_event.tax == Decimal("0.00")
    assert first_event.net_amount == Decimal("-1028.00")
    assert first_event.row_number == 2
    assert len(first_event.row_fingerprint) == 64

    assert {event.event_type for event in preview.events} == {
        "trade_buy",
        "dividend",
        "fee",
        "tax",
        "transfer_in",
        "position_snapshot",
        "cash_snapshot",
    }
    assert set(BROKER_STATEMENT_REQUIRED_COLUMNS).issubset(preview.normalized_columns)
    assert set(BROKER_STATEMENT_EVENT_TYPES).issuperset(
        event.event_type for event in preview.events
    )


def test_broker_statement_preview_reports_duplicate_rows_deterministically() -> None:
    duplicate_statement = (
        SYNTHETIC_STATEMENT + SYNTHETIC_STATEMENT.splitlines()[1] + "\n"
    )

    preview = parse_broker_statement_csv(duplicate_statement)

    assert preview.validation_status == "warning"
    assert preview.row_count == 8
    assert preview.valid_row_count == 8
    assert preview.duplicate_row_count == 1
    assert preview.events[-1].is_duplicate is True
    assert preview.events[-1].duplicate_of_row_number == 2
    assert preview.events[-1].row_fingerprint == preview.events[0].row_fingerprint


def test_broker_statement_preview_blocks_missing_required_columns() -> None:
    statement = "event_id,event_type,occurred_at\nrow-1,trade_buy,2026-01-01\n"

    preview = parse_broker_statement_csv(statement)

    assert preview.validation_status == "blocked"
    assert preview.row_count == 0
    assert preview.events == []
    assert "missing required columns" in preview.errors[0].message


def test_broker_statement_preview_marks_invalid_event_type() -> None:
    statement = SYNTHETIC_STATEMENT.replace("trade_buy", "unknown_event", 1)

    preview = parse_broker_statement_csv(statement)

    assert preview.validation_status == "blocked"
    assert preview.invalid_row_count == 1
    assert preview.errors[0].row_number == 2
    assert "unsupported event_type" in preview.errors[0].message


def test_broker_statement_preview_requires_symbol_for_trade_events() -> None:
    statement = SYNTHETIC_STATEMENT.replace("SYN001,合成样例股票A", ",合成样例股票A", 1)

    preview = parse_broker_statement_csv(statement)

    assert preview.validation_status == "blocked"
    assert preview.invalid_row_count == 1
    assert preview.errors[0].row_number == 2
    assert "symbol is required" in preview.errors[0].message
