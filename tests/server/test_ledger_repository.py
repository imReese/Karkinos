from __future__ import annotations

from server.db import AppDatabase
from server.ledger.models import LedgerEntry
from server.ledger.repository import LedgerRepository


def test_ledger_repository_persists_trade_buy_entry(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = LedgerRepository(db)

    entry = LedgerEntry(
        entry_type="trade_buy",
        timestamp="2026-04-18T09:35:00",
        symbol="600519",
        direction="buy",
        quantity=10.0,
        price=123.45,
        commission=1.23,
        asset_class="stock",
        note="ledger foundation test",
    )

    entry_id = repository.insert_entry(entry)
    assert entry_id > 0

    entries = repository.list_entries()
    assert len(entries) == 1
    saved = entries[0]
    assert saved.entry_type == "trade_buy"
    assert saved.symbol == "600519"
    assert saved.direction == "buy"
    assert saved.quantity == 10.0
    assert saved.price == 123.45
    assert saved.commission == 1.23
    assert saved.asset_class == "stock"
    assert saved.note == "ledger foundation test"


def test_ledger_repository_persists_structured_trade_cost_fields(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = LedgerRepository(db)

    entry = LedgerEntry(
        entry_type="trade_buy",
        timestamp="2026-01-15T11:04:56+08:00",
        symbol="600003",
        direction="buy",
        quantity=200.0,
        price=16.25,
        amount=3250.0,
        commission=5.0527,
        gross_amount=3250.0,
        net_cash_impact=-3255.0527,
        fee_breakdown={
            "commission": "5",
            "stamp_tax": "0",
            "transfer_fee": "0.032500",
            "other_fees": "0",
            "total_fee": "5.032500",
        },
        fee_rule_id="cn_stock_a_local_v1",
        fee_rule_version="local_broker_fee_schedule_v1",
        cost_basis_method="moving_average_buy_cost",
        asset_class="stock",
    )

    repository.insert_entry(entry)

    saved = repository.list_entries()[0]
    assert saved.gross_amount == 3250.0
    assert saved.net_cash_impact == -3255.0527
    assert saved.fee_breakdown == {
        "commission": "5",
        "stamp_tax": "0",
        "transfer_fee": "0.032500",
        "other_fees": "0",
        "total_fee": "5.032500",
    }
    assert saved.fee_rule_id == "cn_stock_a_local_v1"
    assert saved.fee_rule_version == "local_broker_fee_schedule_v1"
    assert saved.cost_basis_method == "moving_average_buy_cost"


def test_ledger_repository_persists_cash_event_and_normalizes_timestamp(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = LedgerRepository(db)

    later_trade = LedgerEntry(
        entry_type="trade_buy",
        timestamp="2026-04-18T11:00:00+02:00",
        symbol="600519",
        direction="buy",
        quantity=10.0,
        price=123.45,
        source="trade-engine",
        source_ref="fill-2",
    )
    earlier_cash = LedgerEntry(
        entry_type="cash_deposit",
        timestamp="2026-04-18 08:00:00",
        amount=1000.0,
        source="bank-feed",
        source_ref="deposit-1",
        note="initial funding",
    )

    repository.insert_entry(later_trade)
    repository.insert_entry(earlier_cash)

    entries = repository.list_entries()
    assert [entry.entry_type for entry in entries] == ["trade_buy", "cash_deposit"]
    assert entries[0].timestamp == "2026-04-18T09:00:00+00:00"
    assert entries[1].timestamp == "2026-04-18T08:00:00+00:00"
    assert entries[1].amount == 1000.0
    assert entries[1].source == "bank-feed"
    assert entries[1].source_ref == "deposit-1"
