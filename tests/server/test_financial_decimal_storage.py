from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from server.contracts.order_state import OmsOrderCommand
from server.db import AppDatabase
from server.persistence import migrations
from server.persistence.financial_decimal_storage import assert_exact_financial_storage
from server.persistence.initializer import initialize_database
from server.projections.valuation_snapshot import ledger_identity_from_rows


def _rows(path: Path, table: str) -> list[dict[str, object]]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        ]


def _legacy_v15_database(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = tuple(item for item in migrations._MIGRATIONS if item.version <= 15)
    with monkeypatch.context() as context:
        context.setattr(migrations, "_MIGRATIONS", legacy)
        AppDatabase(path).init_sync()


def _initialize_through(
    path: Path, version: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tuple(item for item in migrations._MIGRATIONS if item.version <= version)
    with monkeypatch.context() as context:
        context.setattr(migrations, "_MIGRATIONS", registry)
        initialize_database(path)


def test_v16_backfills_legacy_real_without_changing_ledger_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy-v15.db"
    _legacy_v15_database(path, monkeypatch)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO ledger_entries (
                entry_type, timestamp, amount, quantity, price, commission,
                gross_amount, net_cash_impact, asset_class, source, source_ref,
                created_at
            ) VALUES ('trade_buy', ?, 1000.0, ?, 2.1914, 5.0,
                      1000.0, -1005.0, 'fund', 'fixture', 'legacy-1', ?)
            """,
            (
                "2026-09-14T15:00:00+08:00",
                456.62100456621005,
                "2026-09-14T15:00:01+08:00",
            ),
        )
        conn.commit()
    before = _rows(path, "ledger_entries")
    before_identity = ledger_identity_from_rows(before)["ledger_fingerprint"]

    _initialize_through(path, 16, monkeypatch)

    after = _rows(path, "ledger_entries")
    after_identity = ledger_identity_from_rows(after)["ledger_fingerprint"]
    assert after_identity == before_identity
    assert after[0]["quantity"] == before[0]["quantity"]
    assert Decimal(str(after[0]["quantity_decimal"])) == Decimal(
        str(after[0]["quantity"])
    )
    assert after[0]["decimal_provenance"] == "legacy_real_backfill_v1"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        assert_exact_financial_storage(conn)
        version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
            0
        ]
    assert version == 16


def test_v16_new_authoritative_writes_persist_canonical_decimal_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "exact.db"
    db = AppDatabase(path)
    _initialize_through(path, 16, monkeypatch)
    db.record_order_sync(
        order_id="order-1",
        timestamp="2026-09-17T10:00:00+08:00",
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=100.125,
        price=1.2345,
        asset_class="fund",
        execution_mode="paper",
        status="submitted",
        source="fixture",
        source_ref="order-1",
        payload={"kind": "test"},
    )
    db.record_fill_sync(
        fill_id="fill-1",
        order_id="order-1",
        timestamp="2026-09-17T10:00:01+08:00",
        symbol="510300",
        side="buy",
        fill_price=1.2345,
        fill_quantity=100.125,
        commission=5.09516,
        slippage=0.0,
        asset_class="fund",
        execution_mode="paper",
        source="fixture",
        source_ref="fill-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-09-17T09:00:00+08:00",
        amount=1000.01,
        asset_class="cash",
        source="fixture",
        source_ref="cash-1",
    )
    db.create_oms_order_sync(
        OmsOrderCommand(
            idempotency_key="oms-1",
            order_id="oms-1",
            symbol="510300",
            side="buy",
            asset_class="fund",
            quantity=100.125,
            order_type="limit",
            limit_price=1.2345,
            initial_status="awaiting_manual_confirmation",
            broker_submission_enabled=False,
            source="fixture",
            source_ref="oms-1",
        )
    )

    order = _rows(path, "orders")[0]
    fill = _rows(path, "fills")[0]
    ledger = _rows(path, "ledger_entries")[0]
    oms = _rows(path, "oms_orders")[0]
    assert (order["quantity_decimal"], order["price_decimal"]) == (
        "100.125",
        "1.2345",
    )
    assert (
        fill["fill_price_decimal"],
        fill["fill_quantity_decimal"],
        fill["commission_decimal"],
    ) == ("1.2345", "100.125", "5.09516")
    assert ledger["amount_decimal"] == "1000.01"
    assert (oms["quantity_decimal"], oms["limit_price_decimal"]) == (
        "100.125",
        "1.2345",
    )
    for row in (order, fill, ledger, oms):
        assert row["currency_code"] == "CNY"
        assert row["decimal_provenance"] == "exact_decimal_write_v1"


def test_v16_real_projection_drift_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "real-drift.db"
    db = AppDatabase(path)
    _initialize_through(path, 16, monkeypatch)
    db.record_order_sync(
        order_id="order-1",
        timestamp="2026-09-17T10:00:00+08:00",
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=100.125,
        price=1.2345,
        source="fixture",
        source_ref="order-1",
        payload={},
    )
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE orders SET quantity = 999 WHERE order_id = 'order-1'")
        conn.commit()

    with pytest.raises(RuntimeError, match="financial_decimal_projection_drift"):
        _initialize_through(path, 16, monkeypatch)


def test_v16_noncanonical_exact_write_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "exact-drift.db"
    db = AppDatabase(path)
    _initialize_through(path, 16, monkeypatch)
    db.record_order_sync(
        order_id="order-1",
        timestamp="2026-09-17T10:00:00+08:00",
        symbol="510300",
        side="buy",
        order_type="limit",
        quantity=100.125,
        price=1.2345,
        source="fixture",
        source_ref="order-1",
        payload={},
    )
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE orders SET quantity_decimal = '100.1250' WHERE order_id = 'order-1'"
        )
        conn.commit()

    with pytest.raises(RuntimeError, match="financial_decimal_not_canonical"):
        _initialize_through(path, 16, monkeypatch)
