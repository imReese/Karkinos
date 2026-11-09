"""A failed standalone valuation rebuild is retried, never cleared by a read."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.persistence.valuation_publication_recovery import (
    VALUATION_RETRY_CONFIRMATION,
    publication_incident_ref,
    require_valuation_recovery_clear,
    unresolved_publications,
)
from tests.server.test_publication_recovery_replay import _quote

NOW = datetime(2026, 9, 4, 7, 10, tzinfo=timezone.utc)
EVENT = "valuation.snapshot.failed_publication.retried"


def rows(db, tables):
    with sqlite3.connect(db.path) as conn:
        return {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in tables
        }


def financial_facts(db):
    with sqlite3.connect(db.path) as conn:
        fee_tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fee%'"
            )
        ]
    return rows(
        db,
        [
            "ledger_entries",
            "quote_snapshots",
            "latest_quotes",
            "daily_close_snapshots",
            "daily_close_snapshots_v2",
            "quote_ingestion_items",
            "quote_fetch_runs",
            *fee_tables,
        ],
    )


def publication_state(db):
    return rows(db, ["valuation_snapshots", "runtime_controls", "event_log"])


def incidents(db):
    with sqlite3.connect(db.path) as conn:
        return unresolved_publications(conn)


def replace_incidents(db, values):
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "UPDATE runtime_controls SET value_json=? WHERE key=?",
            (json.dumps({"failures": values}), "valuation_publication_recovery"),
        )


@pytest.fixture
def failed(db_path, monkeypatch):
    db = AppDatabase(db_path)
    db.init_sync()
    repo = db._financial_facts
    monkeypatch.setattr(repo, "_now", lambda tz=None: NOW)
    db.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=NOW.isoformat(),
        amount=100_000,
        asset_class="cash",
    )
    db.persist_quote_ingestion_sync(_quote())
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-03T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=100,
        price=10,
        asset_class="stock",
    )
    original = repo._valuation_transaction_writer
    good = db.publish_current_valuation_snapshot_sync(now=NOW)
    assert good["status"] == "complete"
    old_snapshots = rows(db, ["valuation_snapshots"])

    def fail_after_writes(conn, **kwargs):
        original(conn, **kwargs)
        raise sqlite3.OperationalError("synthetic standalone writer interruption")

    monkeypatch.setattr(repo, "_valuation_transaction_writer", fail_after_writes)
    with pytest.raises(sqlite3.OperationalError):
        db.publish_current_valuation_snapshot_sync(now=NOW)
    monkeypatch.setattr(repo, "_valuation_transaction_writer", original)
    assert rows(db, ["valuation_snapshots"]) == old_snapshots
    (incident,) = incidents(db)
    assert incident["reason"] == "valuation_snapshot_publication_failed"
    return db, repo, incident, good


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "app.db"


def retry(repo, incident, **overrides):
    return repo.retry_failed_valuation_publication_sync(
        **{
            "incident_ref": incident["incident_ref"],
            "actor": "fixture:owner",
            "confirmation": VALUATION_RETRY_CONFIRMATION,
            "now": NOW + timedelta(seconds=1),
            **overrides,
        }
    )


def test_canonical_retry_rebuilds_preserves_facts_and_retains_failure(
    failed, monkeypatch
):
    db, repo, incident, _ = failed
    # An ordinary successful rebuild deliberately leaves the old fence intact.
    good = db.publish_current_valuation_snapshot_sync(now=NOW)
    assert incidents(db) == [incident]
    with pytest.raises(ValueError, match="valuation_publication_recovery_required"):
        require_valuation_recovery_clear(db, good)
    before = financial_facts(db)
    original = repo._valuation_transaction_writer
    calls = []

    def counted(conn, **kwargs):
        calls.append((conn.in_transaction, kwargs))
        return original(conn, **kwargs)

    monkeypatch.setattr(repo, "_valuation_transaction_writer", counted)
    result = retry(repo, incident)
    assert result["reused"] is False
    assert result["resolved_incident"] == incident
    assert result["valuation"]["status"] == "complete"
    assert calls == [(True, {"now": NOW + timedelta(seconds=1)})]
    assert financial_facts(db) == before
    assert incidents(db) == []
    require_valuation_recovery_clear(db, good)
    with sqlite3.connect(db.path) as conn:
        (receipt,) = conn.execute(
            "SELECT payload_json FROM event_log WHERE event_type=?", (EVENT,)
        ).fetchall()
    assert json.loads(receipt[0])["resolved_incident"] == incident
    state = publication_state(db)
    repeated = retry(repo, incident, now=NOW + timedelta(seconds=2))
    assert repeated["reused"] is True
    assert repeated["completed_at"] == result["completed_at"]
    assert len(calls) == 1
    assert publication_state(db) == state


@pytest.mark.parametrize("fault", ["writer", "receipt", "last_good_only", "incomplete"])
def test_failed_retry_rolls_back_snapshot_pointer_receipt_and_incident(
    failed, monkeypatch, fault
):
    db, repo, incident, good = failed
    before, facts = publication_state(db), financial_facts(db)
    original = repo._valuation_transaction_writer
    options = {}
    if fault == "writer":

        def interrupt(conn, **kwargs):
            original(conn, **kwargs)
            raise sqlite3.OperationalError("synthetic retry interruption")

        monkeypatch.setattr(repo, "_valuation_transaction_writer", interrupt)
    elif fault == "receipt":

        def interrupt_receipt(*args, **kwargs):
            raise sqlite3.OperationalError("synthetic receipt interruption")

        monkeypatch.setattr(
            "server.persistence.valuation_publication_recovery.insert_event_sync",
            interrupt_receipt,
        )
    elif fault == "last_good_only":
        monkeypatch.setattr(
            repo, "_valuation_transaction_writer", lambda *a, **kw: good
        )
    else:
        options["now"] = NOW + timedelta(days=7)
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        retry(repo, incident, **options)
    assert publication_state(db) == before
    assert financial_facts(db) == facts
    assert incidents(db) == [incident]


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "quote_batch_publication_failed"},
        {"error_type": "ValueError"},
        {"status": "pending"},
        {"scope": [["stock", "600001"]]},
        {"quote_fetch_run_id": None},
        {"daily_close_conflict": None},
        {"failed_at": "2026-09-04T07:10:00"},
        {"failed_at": "2026-09-05T07:10:00+00:00"},
    ],
)
def test_unknown_or_ambiguous_failure_cannot_retry(failed, monkeypatch, change):
    db, repo, incident, _ = failed
    changed = {**incident, **change}
    changed["incident_ref"] = publication_incident_ref(changed)
    replace_incidents(db, [changed])
    before = publication_state(db)
    monkeypatch.setattr(
        repo,
        "_valuation_transaction_writer",
        lambda *a, **kw: pytest.fail("unsupported incident reached writer"),
    )
    with pytest.raises(ValueError, match="valuation_recovery_retry_"):
        retry(repo, changed)
    assert publication_state(db) == before


@pytest.mark.parametrize(
    "variant", ["other_incident", "identity_changed", "no_incident"]
)
def test_changed_or_additional_incident_blocks_exact_retry(
    failed, monkeypatch, variant
):
    db, repo, incident, _ = failed
    changed = {**incident, "failed_at": (NOW - timedelta(seconds=1)).isoformat()}
    changed["incident_ref"] = publication_incident_ref(changed)
    replace_incidents(
        db,
        [incident, changed]
        if variant == "other_incident"
        else [changed]
        if variant == "identity_changed"
        else [],
    )
    before = publication_state(db)
    monkeypatch.setattr(
        repo,
        "_valuation_transaction_writer",
        lambda *a, **kw: pytest.fail("changed incident reached writer"),
    )
    with pytest.raises(ValueError, match="valuation_recovery_retry_"):
        retry(repo, incident)
    assert publication_state(db) == before


@pytest.mark.parametrize(
    "options",
    [{"confirmation": "clear"}, {"actor": " "}, {"now": NOW.replace(tzinfo=None)}],
)
def test_retry_requires_exact_intent_and_aware_time(failed, options):
    db, repo, incident, _ = failed
    before = publication_state(db)
    with pytest.raises(ValueError, match="valuation_recovery_retry_command_invalid"):
        retry(repo, incident, **options)
    assert publication_state(db) == before
