from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from account_truth.broker_evidence import BrokerEvidenceRepository
from account_truth.broker_statement_collector import LocalBrokerStatementCollector
from server.db import AppDatabase

VALID_STATEMENT = """event_id,event_type,occurred_at,settled_at,symbol,instrument_name,asset_class,currency,quantity,price,gross_amount,fee,tax,net_amount,cash_balance,position_quantity,cost_basis,note
synthetic-buy-001,trade_buy,2026-01-05T09:35:00+08:00,2026-01-06,SYN001,Synthetic Stock A,stock,CNY,100,10.23,1023.00,5.00,0.00,-1028.00,8972.00,100,10.28,synthetic buy row
synthetic-position-001,position_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,SYN001,Synthetic Stock A,stock,CNY,0,10.40,0.00,0.00,0.00,0.00,8972.00,100,10.28,synthetic position snapshot
synthetic-cash-001,cash_snapshot,2026-01-15T15:10:00+08:00,2026-01-15,,,,CNY,0,0,0.00,0.00,0.00,0.00,8972.00,,,
"""


def _collector(tmp_path, *, content: str = VALID_STATEMENT, enabled: bool = True):
    statement_path = tmp_path / "broker_statement.csv"
    statement_path.write_text(content, encoding="utf-8")
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    repository = BrokerEvidenceRepository(db._path)
    collector = LocalBrokerStatementCollector(
        repository=repository,
        path=statement_path,
        enabled=enabled,
        poll_interval_seconds=1,
        stability_delay_seconds=1,
        max_file_bytes=1024 * 1024,
        utc_now=lambda: datetime(2026, 7, 17, 14, 30, tzinfo=UTC),
    )
    return collector, repository, db, statement_path


def _collect_stable(collector: LocalBrokerStatementCollector):
    first = collector.collect_once(observed_monotonic=10)
    assert first.state == "pending_stability"
    return collector.collect_once(observed_monotonic=11)


def _ledger_entry_count(db: AppDatabase) -> int:
    with sqlite3.connect(db._path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0])


def test_local_collector_stages_complete_file_without_mutating_ledger(tmp_path):
    collector, repository, db, _statement_path = _collector(tmp_path)
    ledger_count_before = _ledger_entry_count(db)

    status = _collect_stable(collector)

    assert status.state == "imported"
    assert status.validation_status == "pass"
    assert status.row_count == 3
    assert status.valid_row_count == 3
    assert status.import_run_id
    assert status.does_not_mutate_production_ledger is True
    assert status.does_not_contact_provider is True
    assert status.does_not_change_execution_authority is True
    assert len(repository.list_import_runs(limit=10)) == 1
    assert len(repository.list_events(status.import_run_id)) == 3
    assert _ledger_entry_count(db) == ledger_count_before


def test_local_collector_is_idempotent_across_polling_and_restart(tmp_path):
    collector, repository, db, statement_path = _collector(tmp_path)
    first = _collect_stable(collector)

    unchanged = collector.collect_once(observed_monotonic=12)
    assert unchanged.state == "unchanged"
    assert unchanged.import_run_id == first.import_run_id
    assert len(repository.list_import_runs(limit=10)) == 1

    restarted = LocalBrokerStatementCollector(
        repository=repository,
        path=statement_path,
        enabled=True,
        poll_interval_seconds=1,
        stability_delay_seconds=1,
        max_file_bytes=1024 * 1024,
    )
    replay = _collect_stable(restarted)

    assert replay.state == "imported"
    assert replay.import_run_id == first.import_run_id
    assert len(repository.list_import_runs(limit=10)) == 1
    assert len(repository.list_events(first.import_run_id)) == 3
    assert _ledger_entry_count(db) == 0


def test_local_collector_records_duplicate_rows_as_warning_evidence(tmp_path):
    duplicate_statement = VALID_STATEMENT + VALID_STATEMENT.splitlines()[1] + "\n"
    collector, repository, _db, _statement_path = _collector(
        tmp_path,
        content=duplicate_statement,
    )

    status = _collect_stable(collector)

    assert status.state == "imported"
    assert status.validation_status == "warning"
    assert status.duplicate_row_count == 1
    assert status.import_run_id
    events = repository.list_events(status.import_run_id)
    assert len(events) == 4
    assert events[-1].is_row_duplicate is True


def test_local_collector_fails_closed_for_partial_schema(tmp_path):
    collector, repository, db, _statement_path = _collector(
        tmp_path,
        content="event_id,event_type\npartial,trade_buy\n",
    )

    status = _collect_stable(collector)

    assert status.state == "blocked"
    assert status.validation_status == "blocked"
    assert status.error_code == "statement_validation_blocked"
    assert status.import_run_id
    assert repository.list_events(status.import_run_id) == []
    assert len(repository.list_import_runs(limit=10)) == 1
    assert _ledger_entry_count(db) == 0


def test_local_collector_disconnect_preserves_staged_evidence(tmp_path):
    collector, repository, _db, statement_path = _collector(tmp_path)
    imported = _collect_stable(collector)
    statement_path.unlink()

    disconnected = collector.collect_once(observed_monotonic=12)

    assert disconnected.state == "waiting_for_file"
    assert disconnected.file_present is False
    assert disconnected.import_run_id == imported.import_run_id
    assert len(repository.list_import_runs(limit=10)) == 1
    assert len(repository.list_events(imported.import_run_id)) == 3


def test_local_collector_default_closed_mode_does_not_read_or_stage(tmp_path):
    collector, repository, db, statement_path = _collector(
        tmp_path,
        content="not,csv\n",
        enabled=False,
    )
    statement_path.unlink()

    status = collector.collect_once(observed_monotonic=10)

    assert status.state == "disabled"
    assert status.enabled is False
    assert repository.list_import_runs(limit=10) == []
    assert _ledger_entry_count(db) == 0
