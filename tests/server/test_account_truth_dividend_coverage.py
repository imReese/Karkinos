from __future__ import annotations

from types import SimpleNamespace

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement import parse_broker_statement_csv
from server.account_truth_gate import build_latest_account_truth_score_payload
from server.db import AppDatabase

_HEADER = (
    "event_id,event_type,occurred_at,settled_at,symbol,instrument_name,"
    "asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,"
    "cash_balance,position_quantity,cost_basis,note,transfer_fee,"
    "cost_basis_method\n"
)


def _account_truth_payload(
    tmp_path,
    *,
    broker_dividend_amount: str = "16.00",
    broker_symbol: str = "601985",
    cash_snapshot_at: str = "2026-07-17T22:00:00+08:00",
    duplicate_ledger_dividend: bool = False,
) -> dict[str, object]:
    db = AppDatabase(tmp_path / "account-truth-dividend.db")
    db.init_sync()
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp="2026-07-17T09:00:00+08:00",
        amount=1000.0,
        asset_class="cash",
        source_ref="deposit-1",
    )
    db.insert_ledger_entry_sync(
        entry_type="dividend",
        timestamp="2026-07-17T22:09:08+08:00",
        amount=16.0,
        symbol="601985",
        asset_class="stock",
        source="manual",
        note="recorded after the broker dividend occurred",
    )
    if duplicate_ledger_dividend:
        db.insert_ledger_entry_sync(
            entry_type="dividend",
            timestamp="2026-07-17T22:10:00+08:00",
            amount=16.0,
            symbol="601985",
            asset_class="stock",
            source="manual",
            note="duplicate local capture",
        )

    cash_balance = "1032.00" if duplicate_ledger_dividend else "1016.00"
    statement = (
        _HEADER
        + """deposit-1,transfer_in,2026-07-17T09:00:00+08:00,2026-07-17,,,,CNY,0,0,1000.00,0.00,0.00,1000.00,1000.00,,,deposit,0.00,
dividend-1,dividend,2026-07-17T15:00:00+08:00,2026-07-17,{broker_symbol},中国核电,stock,CNY,100,0,{broker_amount},0.00,0.00,{broker_amount},1016.00,100,8.7401,dividend,0.00,broker_remaining_cost
cash-current,cash_snapshot,{cash_snapshot_at},2026-07-17,,,,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance},,,cash snapshot,0.00,
position-current,position_snapshot,2026-07-17T22:00:00+08:00,2026-07-17,601985,中国核电,stock,CNY,0,0,0.00,0.00,0.00,0.00,{cash_balance},0,0.00,position snapshot,0.00,broker_remaining_cost
""".format(
            broker_symbol=broker_symbol,
            broker_amount=broker_dividend_amount,
            cash_snapshot_at=cash_snapshot_at,
            cash_balance=cash_balance,
        )
    )
    repository = BrokerEvidenceRepository(db._path)
    repository.save_preview(
        parse_broker_statement_csv(statement),
        source_name="deterministic-dividend-fixture.csv",
    )
    return build_latest_account_truth_score_payload(
        SimpleNamespace(db=db, config=SimpleNamespace(initial_cash="0"))
    )


def test_exact_broker_dividend_covers_later_same_day_local_capture(tmp_path) -> None:
    payload = _account_truth_payload(tmp_path)

    assert payload["gate_status"] == "pass"
    assert payload["data_freshness_status"] == "fresh"
    assert payload["ledger_coverage"]["status"] == "covered"
    assert payload["ledger_coverage"]["broker_evidence_lineage_entry_count"] == 1


def test_dividend_amount_conflict_remains_stale(tmp_path) -> None:
    payload = _account_truth_payload(
        tmp_path,
        broker_dividend_amount="15.00",
    )

    assert payload["gate_status"] == "blocked"
    assert payload["ledger_coverage"]["status"] == "stale"
    assert payload["ledger_coverage"]["broker_evidence_lineage_entry_count"] == 0


def test_dividend_symbol_conflict_remains_stale(tmp_path) -> None:
    payload = _account_truth_payload(tmp_path, broker_symbol="600000")

    assert payload["gate_status"] == "blocked"
    assert payload["ledger_coverage"]["status"] == "stale"
    assert payload["ledger_coverage"]["broker_evidence_lineage_entry_count"] == 0


def test_dividend_requires_post_event_cash_snapshot(tmp_path) -> None:
    payload = _account_truth_payload(
        tmp_path,
        cash_snapshot_at="2026-07-17T14:00:00+08:00",
    )

    assert payload["gate_status"] == "blocked"
    assert payload["ledger_coverage"]["status"] == "stale"
    assert payload["ledger_coverage"]["broker_evidence_lineage_entry_count"] == 0


def test_one_broker_dividend_cannot_cover_duplicate_local_entries(tmp_path) -> None:
    payload = _account_truth_payload(tmp_path, duplicate_ledger_dividend=True)

    assert payload["gate_status"] == "blocked"
    assert payload["ledger_coverage"]["status"] == "stale"
    assert payload["ledger_coverage"]["broker_evidence_lineage_entry_count"] == 1
