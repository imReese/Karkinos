from __future__ import annotations

import json
from types import SimpleNamespace

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.account_truth_gate import build_reconciliation_report_for_import_run
from server.db import AppDatabase


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
