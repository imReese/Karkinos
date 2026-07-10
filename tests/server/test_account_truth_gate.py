from __future__ import annotations

import json
from types import SimpleNamespace

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.account_truth_gate import build_reconciliation_report_for_import_run
from server.db import AppDatabase
from server.ledger.repository import LedgerRepository


def test_account_truth_gate_uses_structured_ledger_cash_and_fee_facts(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-01-05T09:00:00+08:00",
        amount=2000.0,
        asset_class="cash",
        source_ref="deposit-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-01-05T10:00:00+08:00",
        amount=880.0,
        symbol="SYN001",
        direction="buy",
        quantity=100.0,
        price=8.8,
        gross_amount=880.0,
        net_cash_impact=-880.0,
        fee_breakdown_json=json.dumps(
            {
                "commission": "0",
                "stamp_tax": "0",
                "transfer_fee": "0",
                "total_fee": "0",
            }
        ),
        asset_class="stock",
        source_ref="buy-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp="2026-01-06T10:00:00+08:00",
        amount=1200.0,
        symbol="SYN001",
        direction="sell",
        quantity=100.0,
        price=12.0,
        commission=1.8,
        gross_amount=1200.0,
        net_cash_impact=1196.4,
        fee_breakdown_json=json.dumps(
            {
                "commission": "1.80",
                "stamp_tax": "1.20",
                "transfer_fee": "0.60",
                "total_fee": "3.60",
            }
        ),
        asset_class="stock",
        source_ref="sell-1",
    )
    statement = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
deposit-1,transfer_in,2026-01-05T09:00:00+08:00,2026-01-05,,,,CNY,0,0,2000.00,0.00,0.00,2000.00,2000.00,,,deposit,0.00,
buy-1,trade_buy,2026-01-05T10:00:00+08:00,2026-01-05,SYN001,合成样例股票A,stock,CNY,100,8.80,880.00,0.00,0.00,-880.00,1120.00,100,8.80,buy,0.00,moving_average_buy_cost
sell-1,trade_sell,2026-01-06T10:00:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,100,12.00,1200.00,1.80,1.20,1196.40,2316.40,0,0.00,sell,0.60,moving_average_buy_cost
cash-current,cash_snapshot,2026-01-06T15:00:00+08:00,2026-01-06,,,,CNY,0,0,0.00,0.00,0.00,0.00,2316.40,,,cash snapshot,0.00,
position-current,position_snapshot,2026-01-06T15:00:00+08:00,2026-01-06,SYN001,合成样例股票A,stock,CNY,0,0,0.00,0.00,0.00,0.00,2316.40,0,0.00,position snapshot,0.00,moving_average_buy_cost
"""
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(statement)
    import_run = repository.save_preview(preview, source_name="broker.csv")
    state = SimpleNamespace(db=db, config=SimpleNamespace(initial_cash="0"))

    report = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )

    assert report.status == "pass"
    assert report.unresolved_count == 0
    assert report.suggested_review_actions == []


def test_broker_settlement_confirmation_removes_rounding_mismatch(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-06-01T09:00:00+08:00",
        amount=10000.0,
        asset_class="cash",
        source_ref="deposit-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-06-16T11:04:56+08:00",
        amount=5270.0,
        symbol="600066",
        direction="buy",
        quantity=200,
        price=26.35,
        commission=5.0,
        gross_amount=5270.0,
        net_cash_impact=-5275.05,
        fee_breakdown_json=json.dumps(
            {
                "commission": "5.00",
                "stamp_tax": "0",
                "transfer_fee": "0.05",
                "total_fee": "5.05",
            }
        ),
        asset_class="stock",
        source_ref="buy-stock-600066-20260616",
    )
    first_sell_id = db.insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp="2026-06-29T11:00:05+08:00",
        amount=2776.0,
        symbol="600066",
        direction="sell",
        quantity=100,
        price=27.76,
        commission=5.0,
        gross_amount=2776.0,
        net_cash_impact=2769.58424,
        fee_breakdown_json=json.dumps(
            {
                "commission": "5.00",
                "stamp_tax": "1.388000",
                "transfer_fee": "0.027760",
                "total_fee": "6.415760",
            }
        ),
        asset_class="stock",
        source_ref="sell-stock-600066-20260629",
    )
    second_sell_id = db.insert_ledger_entry_sync(
        entry_type="trade_sell",
        timestamp="2026-07-03T14:08:29+08:00",
        amount=2896.0,
        symbol="600066",
        direction="sell",
        quantity=100,
        price=28.96,
        commission=5.0,
        gross_amount=2896.0,
        net_cash_impact=2889.52304,
        fee_breakdown_json=json.dumps(
            {
                "commission": "5.00",
                "stamp_tax": "1.448000",
                "transfer_fee": "0.028960",
                "total_fee": "6.476960",
            }
        ),
        asset_class="stock",
        source_ref="sell-stock-600066-20260703",
    )
    statement = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note,transfer_fee,cost_basis_method
deposit-1,transfer_in,2026-06-01T09:00:00+08:00,2026-06-01,,,,CNY,0,0,10000.00,0.00,0.00,10000.00,10000.00,,,deposit,0.00,
buy-1,trade_buy,2026-06-16T11:04:56+08:00,2026-06-16,600066,合成样例股票,stock,CNY,200,26.35,5270.00,5.00,0.00,-5275.05,4724.95,200,26.37525,buy,0.05,moving_average_buy_cost
sell-1,trade_sell,2026-06-29T11:00:05+08:00,2026-06-29,600066,合成样例股票,stock,CNY,100,27.76,2776.00,5.00,1.39,2769.58,7494.53,100,26.37525,sell,0.03,moving_average_buy_cost
sell-2,trade_sell,2026-07-03T14:08:29+08:00,2026-07-03,600066,合成样例股票,stock,CNY,100,28.96,2896.00,5.00,1.45,2889.52,10384.05,0,26.37525,sell,0.03,moving_average_buy_cost
cash-current,cash_snapshot,2026-07-03T15:00:00+08:00,2026-07-03,,,,CNY,0,0,0.00,0.00,0.00,0.00,10384.05,,,cash snapshot,0.00,
position-current,position_snapshot,2026-07-03T15:00:00+08:00,2026-07-03,600066,合成样例股票,stock,CNY,0,0,0.00,0.00,0.00,0.00,10384.05,0,0.00,position snapshot,0.00,broker_remaining_cost
"""
    repository = BrokerEvidenceRepository(tmp_path / "account-truth.db")
    preview = parse_broker_statement_csv(statement)
    import_run = repository.save_preview(preview, source_name="broker.csv")
    state = SimpleNamespace(db=db, config=SimpleNamespace(initial_cash="0"))

    before = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )
    assert before.status == "mismatch"
    assert abs(before.cash_difference) > 0

    ledger = LedgerRepository(db)
    ledger.confirm_trade_settlement(
        entry_id=first_sell_id,
        commission=5.0,
        net_cash_impact=2769.58,
        fee_breakdown={
            "commission": "5.0",
            "stamp_tax": "1.39",
            "transfer_fee": "0.03",
            "other_fees": "0.0",
            "total_fee": "6.42",
            "confirmation_source": "broker_statement",
        },
        settled_at="2026-06-29T11:00:05+08:00",
        settlement_source="broker_statement",
        settlement_source_ref="sell-stock-600066-20260629",
    )
    ledger.confirm_trade_settlement(
        entry_id=second_sell_id,
        commission=5.0,
        net_cash_impact=2889.52,
        fee_breakdown={
            "commission": "5.0",
            "stamp_tax": "1.45",
            "transfer_fee": "0.03",
            "other_fees": "0.0",
            "total_fee": "6.48",
            "confirmation_source": "broker_statement",
        },
        settled_at="2026-07-03T14:08:29+08:00",
        settlement_source="broker_statement",
        settlement_source_ref="sell-stock-600066-20260703",
    )

    after = build_reconciliation_report_for_import_run(
        state,
        repository=repository,
        import_run=import_run,
    )

    assert after.status == "pass"
    assert after.cash_difference == 0
    assert after.unresolved_count == 0
