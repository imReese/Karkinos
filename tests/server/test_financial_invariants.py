from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from server.contracts.portfolio_cash_flows import CashFlowWrite
from server.db import AppDatabase
from server.ledger.models import LedgerEntry
from server.ledger.repository import LedgerRepository


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _buy(repository: LedgerRepository, *, ref: str, price: float = 100.0) -> int:
    return repository.insert_entry(
        LedgerEntry(
            entry_type="trade_buy",
            timestamp="2026-09-17T10:00:00+08:00",
            symbol="600519",
            direction="buy",
            quantity=1,
            price=price,
            commission=5,
            gross_amount=price,
            net_cash_impact=-(price + 5),
            source="fixture",
            source_ref=ref,
        )
    )


def test_v17_rejects_real_only_financial_insert(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()
    with _connect(path) as conn:
        with pytest.raises(
            sqlite3.IntegrityError, match="exact financial values required"
        ):
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type, quantity,
                    asset_class, execution_mode, status, source, payload_json,
                    created_at, updated_at
                ) VALUES ('raw-1', '2026-09-17T10:00:00+08:00', '600519',
                          'buy', 'market', 1, 'stock', 'paper', 'submitted',
                          'fixture', '{}', '2026-09-17T10:00:00+08:00',
                          '2026-09-17T10:00:00+08:00')
                """
            )


def test_v17_order_terms_are_immutable_but_status_can_transition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app.db"
    db = AppDatabase(path)
    db.init_sync()
    db.record_order_sync(
        order_id="order-1",
        timestamp="2026-09-17T10:00:00+08:00",
        symbol="600519",
        side="buy",
        order_type="limit",
        quantity=100,
        price=25.5,
        status="submitted",
        source="fixture",
        source_ref="order-1",
        payload={},
    )
    updated = db.update_order_status_sync(order_id="order-1", status="confirmed")
    assert updated is not None and updated["status"] == "confirmed"
    with _connect(path) as conn:
        with pytest.raises(
            sqlite3.IntegrityError, match="financial terms are immutable"
        ):
            conn.execute("UPDATE orders SET quantity = 200 WHERE order_id = 'order-1'")
        with pytest.raises(
            sqlite3.IntegrityError, match="financial terms are immutable"
        ):
            conn.execute(
                "UPDATE orders SET price_decimal = '26' WHERE order_id = 'order-1'"
            )


def test_v17_financial_facts_and_audit_events_are_append_only(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    db = AppDatabase(path)
    db.init_sync()
    db.record_cash_flow_sync(
        CashFlowWrite(
            command_id="cash-1",
            operator_id="operator",
            timestamp="2026-09-17T09:00:00+08:00",
            amount=1000,
            flow_type="deposit",
        )
    )
    db.record_fill_sync(
        fill_id="fill-1",
        order_id="external-order-1",
        timestamp="2026-09-17T10:00:00+08:00",
        symbol="600519",
        side="buy",
        fill_price=25.5,
        fill_quantity=100,
        commission=5,
        source="fixture",
        source_ref="fill-1",
    )
    with _connect(path) as conn:
        for sql, message in (
            (
                "UPDATE cash_flows SET amount = 999 WHERE id = 1",
                "cash flow facts are append-only",
            ),
            ("DELETE FROM cash_flows WHERE id = 1", "cash flow facts are append-only"),
            (
                "UPDATE fills SET metadata_json = '{}' WHERE fill_id = 'fill-1'",
                "fill facts are append-only",
            ),
            (
                "DELETE FROM fills WHERE fill_id = 'fill-1'",
                "fill facts are append-only",
            ),
            (
                "UPDATE event_log SET payload_json = '{}' WHERE id = 1",
                "audit events are append-only",
            ),
            ("DELETE FROM event_log WHERE id = 1", "audit events are append-only"),
        ):
            with pytest.raises(sqlite3.IntegrityError, match=message):
                conn.execute(sql)


def test_v17_ledger_allows_one_terminal_settlement_only(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    db = AppDatabase(path)
    db.init_sync()
    repository = LedgerRepository(db)
    entry_id = _buy(repository, ref="buy-1")
    settled = repository.confirm_trade_settlement(
        entry_id=entry_id,
        commission=5,
        net_cash_impact=-105,
        fee_breakdown={"commission": "5", "total_fee": "5"},
        settled_at="2026-09-17T10:01:00+08:00",
        settlement_source="broker_statement",
        settlement_source_ref="broker-1",
    )
    assert settled.settlement_status == "confirmed"
    with _connect(path) as conn:
        with pytest.raises(
            sqlite3.IntegrityError, match="immutable except one terminal"
        ):
            conn.execute(
                "UPDATE ledger_entries SET note = 'tampered' WHERE id = ?", (entry_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))
        with pytest.raises(
            sqlite3.IntegrityError, match="immutable except one terminal"
        ):
            conn.execute(
                "UPDATE ledger_entries SET settlement_note = 'second mutation' WHERE id = ?",
                (entry_id,),
            )


def test_v17_settlement_evidence_is_unique_at_database_layer(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    db = AppDatabase(path)
    db.init_sync()
    repository = LedgerRepository(db)
    first = _buy(repository, ref="buy-1", price=100)
    second = _buy(repository, ref="buy-2", price=101)
    repository.confirm_trade_settlement(
        entry_id=first,
        commission=5,
        net_cash_impact=-105,
        fee_breakdown={"commission": "5", "total_fee": "5"},
        settled_at="2026-09-17T10:01:00+08:00",
        settlement_source="broker_statement",
        settlement_source_ref="same-evidence",
    )
    with _connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            conn.execute(
                """
                UPDATE ledger_entries
                SET settlement_status='confirmed',
                    settled_at='2026-09-17T10:02:00+08:00',
                    settlement_source='broker_statement',
                    settlement_source_ref='same-evidence',
                    settlement_note='raw duplicate'
                WHERE id=?
                """,
                (second,),
            )


def test_v17_pending_fund_economics_are_one_way(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT INTO pending_fund_orders (
                submitted_at, symbol, display_name, amount, amount_decimal,
                commission, commission_decimal, target_trade_date, status,
                created_at, updated_at, currency_code, decimal_provenance
            ) VALUES (?, '018125', 'fixture', 1000, '1000', 5, '5', ?,
                      'pending', ?, ?, 'CNY', 'exact_decimal_write_v1')
            """,
            (
                "2026-09-17T10:00:00+08:00",
                "2026-09-17",
                *(["2026-09-17T10:00:00+08:00"] * 2),
            ),
        )
        row_id = int(conn.execute("SELECT id FROM pending_fund_orders").fetchone()[0])
        conn.execute(
            """
            UPDATE pending_fund_orders
            SET status='confirmed', confirmed_nav=1.2345,
                confirmed_nav_decimal='1.2345', confirmed_quantity=806.399351964358,
                confirmed_quantity_decimal='806.399351964358'
            WHERE id=?
            """,
            (row_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="one-way and exact"):
            conn.execute(
                "UPDATE pending_fund_orders SET confirmed_nav=1.3, confirmed_nav_decimal='1.3' WHERE id=?",
                (row_id,),
            )
        with pytest.raises(
            sqlite3.IntegrityError, match="subscription terms are immutable"
        ):
            conn.execute(
                "UPDATE pending_fund_orders SET amount=900 WHERE id=?", (row_id,)
            )


def test_v18_rejects_noncanonical_decimal_text_on_direct_insert(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    AppDatabase(path).init_sync()
    with _connect(path) as conn:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="canonical financial decimals required",
        ):
            conn.execute(
                """
                INSERT INTO orders (
                    order_id, timestamp, symbol, side, order_type,
                    quantity, quantity_decimal, price, price_decimal,
                    asset_class, execution_mode, status, source, payload_json,
                    created_at, updated_at, currency_code, decimal_provenance
                ) VALUES (
                    'raw-noncanonical', '2026-09-17T10:00:00+08:00', '600519',
                    'buy', 'limit', 1, '01', 25.5, '25.50', 'stock', 'paper',
                    'submitted', 'fixture', '{}', '2026-09-17T10:00:00+08:00',
                    '2026-09-17T10:00:00+08:00', 'CNY', 'exact_decimal_write_v1'
                )
                """
            )


def test_v18_rejects_noncanonical_decimal_text_on_terminal_updates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "app.db"
    db = AppDatabase(path)
    db.init_sync()
    repository = LedgerRepository(db)
    entry_id = _buy(repository, ref="canonical-update")
    with _connect(path) as conn:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="ledger settlement canonical financial decimals required",
        ):
            conn.execute(
                """
                UPDATE ledger_entries
                SET settlement_status='confirmed', settled_at=?,
                    settlement_source='fixture', settlement_source_ref='statement-1',
                    commission=5, commission_decimal='5.0',
                    net_cash_impact=-105, net_cash_impact_decimal='-105'
                WHERE id=?
                """,
                ("2026-09-17T10:01:00+08:00", entry_id),
            )
