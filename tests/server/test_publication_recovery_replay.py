from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from server.contracts.quote_ingestion import QuoteIngestionCommand
from server.db import AppDatabase
from server.persistence.pre_trade_risk_uow import PreTradeRiskUnitOfWork
from server.persistence.valuation_publication_recovery import (
    affected_publications,
    publication_incident_ref,
)
from server.projections.portfolio_quotes import (
    adapt_persistent_quote_for_portfolio,
    current_valuation_snapshot,
)
from server.projections.system_readiness import build_system_readiness
from server.services.market_quote_ingestion import build_quote_ingestion_command

NOW = datetime.fromisoformat("2026-09-04T15:10:00+08:00")


def _quote(symbol="600001", run=None):
    return QuoteIngestionCommand(
        symbol=symbol,
        asset_type="stock",
        price=10.5,
        quote_timestamp="2026-09-04T15:00:00+08:00",
        previous_close=10,
        previous_close_date="2026-09-03",
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_reason="replay",
        captured_at="2026-09-04T15:00:01+08:00",
        fetch_run_id=run,
        daily_close_price=10.5,
        daily_close_date="2026-09-04",
        daily_close_source="market_bar_close",
    )


def _run(db, run_id, symbols, *, at="2026-09-04T15:02:00+08:00"):
    db.create_quote_fetch_run(
        run_id=run_id,
        started_at=at,
        trigger="replay",
        status="running",
        provider="fixture",
        asset_type="stock",
        symbol_count=len(symbols),
        metadata={"requested_symbols": symbols},
    )


def _finish(
    db,
    run_id,
    *,
    status="success",
    success=1,
    failure=0,
    at="2026-09-04T15:03:00+08:00",
):
    return db.finish_quote_fetch_run(
        run_id=run_id,
        finished_at=at,
        status=status,
        success_count=success,
        failure_count=failure,
    )


def _close_incident(db, symbols=("600001", "600002")):
    for symbol in symbols:
        db.persist_quote_ingestion_sync(_quote(symbol))
    _run(db, "bound-close-conflict", list(symbols))
    for symbol in symbols:
        db.persist_quote_ingestion_sync(
            replace(
                _quote(symbol, "bound-close-conflict"),
                quote_timestamp="2026-09-04T15:01:00+08:00",
                captured_at="2026-09-04T15:01:01+08:00",
                daily_close_price=11,
            )
        )
    assert (
        _finish(db, "bound-close-conflict", success=len(symbols))["status"] == "failed"
    )
    with sqlite3.connect(db.path) as conn:
        return affected_publications(conn, {("stock", symbols[0])})[0]


def test_close_failure_captures_entire_batch_before_rollback(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    incident = _close_incident(db)
    assert incident["incident_ref"] == publication_incident_ref(incident)
    binding = incident["daily_close_conflict"]
    assert binding["requested_scope"] == [["stock", "600001"], ["stock", "600002"]]
    assert len(binding["staged_items"]) == 2
    assert len(binding["required_facts"]) == 2
    for fact in binding["required_facts"]:
        assert fact["fact_kind"] == "daily_close"
        assert fact["session"] == "2026-09-04"
        assert fact["conflicting"] is True
        assert fact["existing"]["close_price"] == 10.5
        assert fact["candidate"]["close_price"] == 11
    with sqlite3.connect(db.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM quote_snapshots WHERE fetch_run_id = ?",
                (binding["run_id"],),
            ).fetchone()[0]
            == 0
        )
        assert conn.execute(
            "SELECT close_price FROM daily_close_snapshots_v2"
        ).fetchall() == [(10.5,), (10.5,)]


def test_close_binding_does_not_replace_an_earlier_quote_authority_failure(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    _run(db, "quote-conflict", ["600001"])
    db.persist_quote_ingestion_sync(
        replace(_quote(run="quote-conflict"), price=12, daily_close_price=11)
    )
    _finish(db, "quote-conflict")
    with sqlite3.connect(db.path) as conn:
        incident = affected_publications(conn, {("stock", "600001")})[0]
    assert incident["error_type"] == "ValueError"
    assert "daily_close_conflict" not in incident


def test_pre_close_to_official_close_replay_does_not_guess_session(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    command = build_quote_ingestion_command(
        symbol="600001",
        asset_type="stock",
        snapshot={
            "price": 10.5,
            "previous_close": 10,
            "previous_close_date": "2026-09-04",
            "timestamp": "2026-09-04T09:36:00+08:00",
        },
        quote_source="fixture",
        provider_name="fixture",
        provider_status="live",
        quote_status="live",
        captured_reason="replay",
        fetch_run_id=None,
        captured_at="2026-09-04T09:36:01+08:00",
    )
    db.persist_quote_ingestion_sync(command)
    adapted = adapt_persistent_quote_for_portfolio(command.to_dict())
    assert adapted.get("previous_close_date") is None
    db.persist_quote_ingestion_sync(_quote())
    quote = db.get_latest_quote_sync("600001", "stock")
    assert quote["price"] == 10.5
    with sqlite3.connect(db.path) as conn:
        closes = conn.execute(
            "SELECT trade_date, close_price FROM daily_close_snapshots_v2 WHERE symbol='600001'"
        ).fetchall()
    assert closes == [("2026-09-04", 10.5)]


def test_partial_failure_survives_restart_and_unrelated_success(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-03T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=1,
        price=10,
        asset_class="stock",
    )
    before = current_valuation_snapshot(SimpleNamespace(db=db))
    _run(db, "partial", ["600001", "600002"])
    db.persist_quote_ingestion_sync(replace(_quote(run="partial"), price=11))
    _finish(db, "partial", status="partial_success", failure=1)
    assert db.get_latest_quote_sync("600001", "stock")["price"] == 10.5
    assert (
        current_valuation_snapshot(SimpleNamespace(db=db))["snapshot_id"]
        == before["snapshot_id"]
    )
    db = AppDatabase(db.path)
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote("600003"))
    _run(db, "unrelated", ["600003"], at="2026-09-04T15:04:00+08:00")
    db.persist_quote_ingestion_sync(_quote("600003", "unrelated"))
    _finish(db, "unrelated", at="2026-09-04T15:05:00+08:00")
    readiness = build_system_readiness(db.path, now=NOW)
    assert readiness["subsystems"]["valuation_read"]["status"] == "degraded"
    assert (
        "valuation_publication_recovery_required"
        in readiness["subsystems"]["risk"]["blockers"]
    )
    guard = PreTradeRiskUnitOfWork(db.path, now=lambda: NOW).capture_guard_sync(
        tasks=[]
    )
    assert guard["status"] == "blocked"
    assert {"code": "valuation_publication_recovery_required"} in guard["blockers"]
    _run(db, "recovery", ["600001", "600002"], at="2026-09-04T15:06:00+08:00")
    for symbol in ("600001", "600002"):
        db.persist_quote_ingestion_sync(_quote(symbol, "recovery"))
    _finish(db, "recovery", success=2, at="2026-09-04T15:07:00+08:00")
    assert (
        "valuation_publication_recovery_required"
        in build_system_readiness(db.path, now=NOW)["subsystems"]["risk"]["blockers"]
    )


def test_staging_crash_and_database_lock_preserve_last_good(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    before = current_valuation_snapshot(SimpleNamespace(db=db))
    _run(db, "interrupted", ["600001"])
    db.persist_quote_ingestion_sync(
        replace(
            _quote(run="interrupted"),
            price=11,
            quote_timestamp="2026-09-04T15:01:00+08:00",
            captured_at="2026-09-04T15:01:01+08:00",
        )
    )
    # Reopen after staging, before publication: readers still see only committed facts.
    restarted = AppDatabase(db.path)
    restarted.init_sync()
    assert (
        current_valuation_snapshot(SimpleNamespace(db=restarted))["snapshot_id"]
        == before["snapshot_id"]
    )
    with sqlite3.connect(db.path) as locked:
        locked.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            restarted.persist_quote_ingestion_sync(replace(_quote(), price=12))
        assert (
            current_valuation_snapshot(SimpleNamespace(db=restarted))["snapshot_id"]
            == before["snapshot_id"]
        )
    assert _finish(restarted, "interrupted")["status"] == "success"
    assert restarted.get_latest_quote_sync("600001", "stock")["price"] == 11


def test_readiness_does_not_create_missing_database(tmp_path):
    missing = tmp_path / "missing.db"
    result = build_system_readiness(missing, now=NOW)
    assert result["subsystems"]["valuation_read"]["status"] == "unavailable"
    assert not missing.exists()


def test_same_count_wrong_symbols_cannot_publish_or_redefine_failure_scope(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    before = db.get_runtime_control_sync("valuation_snapshot_publication")
    _run(db, "wrong-members", ["600001", "600002"])
    for symbol in ("600001", "600003"):
        db.persist_quote_ingestion_sync(_quote(symbol, "wrong-members"))
    result = _finish(db, "wrong-members", success=2)
    assert result["status"] == "failed"
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == before
    with sqlite3.connect(db.path) as conn:
        assert affected_publications(conn, {("stock", "600002")})
        assert not affected_publications(conn, {("stock", "600003")})


def test_partial_mixed_run_retains_exact_typed_request_scope(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.create_quote_fetch_run(
        run_id="mixed-failure",
        started_at=NOW.isoformat(),
        trigger="replay",
        status="running",
        asset_type="mixed",
        symbol_count=2,
        metadata={
            "symbols": ["510300", "000001"],
            "instrument_types": ["etf", "open_end_fund"],
        },
    )
    _finish(db, "mixed-failure", status="failed", success=0, failure=2)
    with sqlite3.connect(db.path) as conn:
        assert affected_publications(conn, {("open_end_fund", "000001")})
        assert affected_publications(conn, {("etf", "510300")})
        assert not affected_publications(conn, {("stock", "000001")})


@pytest.mark.parametrize(
    "variant", ["realtime", "wrong_session", "other_provider", "old_materialization"]
)
def test_same_scope_success_is_not_a_close_conflict_resolution_receipt(
    tmp_path, variant
):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    _run(db, "close-conflict", ["600001"])
    db.persist_quote_ingestion_sync(
        replace(_quote(run="close-conflict"), daily_close_price=11)
    )
    assert _finish(db, "close-conflict")["status"] == "failed"
    _run(db, "later-success", ["600001"], at="2026-09-05T16:00:00+08:00")
    command = replace(
        _quote(run="later-success"),
        daily_close_price=None,
        daily_close_date=None,
        daily_close_source=None,
    )
    if variant == "realtime":
        command = replace(
            command,
            price=12,
            quote_timestamp="2026-09-05T14:00:00+08:00",
            captured_at="2026-09-05T16:00:01+08:00",
        )
    elif variant == "wrong_session":
        command = replace(
            command,
            quote_timestamp="2026-09-05T15:00:00+08:00",
            captured_at="2026-09-05T16:00:01+08:00",
            daily_close_price=12,
            daily_close_date="2026-09-05",
            daily_close_source="market_bar_close",
        )
    elif variant == "other_provider":
        command = replace(
            command,
            provider_name="other-provider",
            quote_timestamp="2026-09-04T15:01:00+08:00",
            captured_at="2026-09-05T16:00:01+08:00",
        )
    db.persist_quote_ingestion_sync(command)
    assert (
        _finish(db, "later-success", at="2026-09-05T16:01:00+08:00")["status"]
        == "success"
    )
    with sqlite3.connect(db.path) as conn:
        assert affected_publications(conn, {("stock", "600001")})


def test_unrelated_failed_publication_does_not_block_verified_holdings(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-03T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=1,
        price=10,
        asset_class="stock",
    )
    _run(db, "unrelated-failure", ["600002"])
    _finish(db, "unrelated-failure", status="failed", success=0, failure=1)
    before = db.get_runtime_control_sync("valuation_snapshot_publication")
    status = build_system_readiness(db.path, now=NOW)
    assert status["subsystems"]["market_data"]["status"] == "degraded"
    assert status["subsystems"]["valuation_read"]["status"] == "ready"
    guard = PreTradeRiskUnitOfWork(db.path, now=lambda: NOW).capture_guard_sync(
        tasks=[]
    )
    assert {"code": "valuation_publication_recovery_required"} not in guard["blockers"]
    affected = PreTradeRiskUnitOfWork(db.path, now=lambda: NOW).capture_guard_sync(
        tasks=[{"asset_class": "stock", "symbol": "600002"}]
    )
    assert {"code": "valuation_publication_recovery_required"} in affected["blockers"]
    assert db.get_runtime_control_sync("valuation_snapshot_publication") == before


def test_legacy_failed_current_pointer_survives_startup_republication(tmp_path):
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.persist_quote_ingestion_sync(_quote())
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-03T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=1,
        price=10,
        asset_class="stock",
    )
    _run(db, "legacy-failure", ["600001"])
    _finish(db, "legacy-failure", status="failed", success=0, failure=1)
    failure = db.get_runtime_control_sync("valuation_snapshot_publication_attempt")
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "DELETE FROM runtime_controls WHERE key IN ('valuation_snapshot_publication_attempt','valuation_publication_recovery')"
        )
        conn.execute(
            "UPDATE runtime_controls SET value_json=? WHERE key='valuation_snapshot_publication'",
            (json.dumps(failure),),
        )
    restarted = AppDatabase(db.path)
    restarted.init_sync()
    restarted.publish_current_valuation_snapshot_sync()
    assert (
        current_valuation_snapshot(SimpleNamespace(db=restarted))["status"]
        == "complete"
    )
    assert (
        "valuation_publication_recovery_required"
        in build_system_readiness(restarted.path, now=NOW)["subsystems"][
            "valuation_read"
        ]["blockers"]
    )


def _preview_fixture(tmp_path):
    import pandas as pd

    from data.store import DataStore

    store = DataStore(tmp_path)
    receipt = store.ingest_market_daily_batch(
        trade_date="2026-09-04",
        provider_name="fixture",
        bars=pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "timestamp": "2026-09-04T15:00:00+08:00",
                    "open": 10,
                    "high": 11,
                    "low": 10,
                    "close": 11,
                    "volume": 100,
                }
                for symbol in ("600001", "600002")
            ]
        ),
    )
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    for symbol in ("600001", "600002"):
        db.persist_quote_ingestion_sync(_quote(symbol))
    _run(db, "preview-conflict", ["600001", "600002"])
    for symbol in ("600001", "600002"):
        db.persist_quote_ingestion_sync(
            replace(
                _quote(symbol, "preview-conflict"),
                quote_timestamp="2026-09-04T15:01:00+08:00",
                captured_at="2026-09-04T15:01:01+08:00",
                daily_close_price=11,
                metadata={
                    "receipt_fingerprint": receipt["receipt_fingerprint"],
                    "market_dataset_fingerprint": receipt["dataset_fingerprint"],
                },
            )
        )
    assert _finish(db, "preview-conflict", success=2)["status"] == "failed"
    with sqlite3.connect(db.path) as conn:
        incident = affected_publications(conn, {("stock", "600001")})[0]
    for symbol in ("600001", "600002"):
        db.save_daily_close_snapshot_sync(
            symbol=symbol,
            asset_class="stock",
            trade_date="2026-09-04",
            close_price=11,
            source="market_bar_close",
        )
    return (
        db,
        store,
        incident,
        {
            key: receipt[key]
            for key in ("trade_date", "provider_name", "receipt_fingerprint")
        },
    )


def _preview(db, store, incident, refs):
    from server.persistence.valuation_recovery_preview import (
        preview_daily_close_recovery,
    )

    return preview_daily_close_recovery(
        db.path,
        market_database_path=store._meta_path,
        incident_ref=incident["incident_ref"],
        resolution_evidence_refs=refs,
    )


def test_verified_candidate_does_not_adjudicate_prior_close(tmp_path, monkeypatch):
    import socket

    from data.store import DataStore

    db, store, incident, ref = _preview_fixture(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("preview attempted provider contact or store initialization")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(DataStore, "__init__", forbidden)
    with (
        sqlite3.connect(db.path) as app_observer,
        sqlite3.connect(store._meta_path) as meta_observer,
    ):
        before = [
            conn.execute("PRAGMA data_version").fetchone()
            for conn in (app_observer, meta_observer)
        ]
        first = _preview(db, store, incident, [ref])
        assert first == _preview(db, store, incident, [ref])
        assert first["candidate_evidence_verified"] is True
        assert first["status"] == "blocked"
        assert first["blockers"] == ["prior_evidence_disposition_unproven"]
        assert first["authorizes_execution"] is False
        assert len(first["required_facts"]) == 2
        assert first["resolution_evidence_refs"] == [ref]
        assert before == [
            conn.execute("PRAGMA data_version").fetchone()
            for conn in (app_observer, meta_observer)
        ]
        assert affected_publications(app_observer, {("stock", "600001")}) == [incident]


@pytest.mark.parametrize(
    "variant, blocker",
    [
        ("missing_ref", "resolution_evidence_missing"),
        ("wrong_session", "resolution_evidence_not_found"),
        ("other_provider", "resolution_evidence_not_found"),
        ("tampered_ref", "resolution_evidence_revision_drift"),
        ("tampered_receipt", "resolution_evidence_integrity_failed"),
        ("tampered_bar", "resolution_evidence_integrity_failed"),
        ("partial_current", "canonical_close_not_reconciled"),
        ("old_materialization", "canonical_close_not_reconciled"),
        ("source_string_only", "canonical_close_not_reconciled"),
        ("wrong_type", "canonical_close_not_reconciled"),
        ("staged_tamper", "staged_item_identity_drift"),
        ("run_incomplete", "failed_run_binding_mismatch"),
        ("incident_tamper", "incident_identity_drift"),
    ],
)
def test_preview_rejects_missing_conflicting_or_drifting_evidence(
    tmp_path, variant, blocker
):
    db, store, incident, ref = _preview_fixture(tmp_path)
    refs = [ref]
    if variant == "missing_ref":
        refs = []
    elif variant == "wrong_session":
        ref["trade_date"] = "2026-09-03"
    elif variant == "other_provider":
        ref["provider_name"] = "another-provider"
    elif variant == "tampered_ref":
        ref["receipt_fingerprint"] = "sha256:" + "0" * 64
    elif variant in {"tampered_receipt", "tampered_bar"}:
        with sqlite3.connect(store._meta_path) as conn:
            if variant == "tampered_bar":
                conn.execute("UPDATE market_bars_v2 SET close=12 WHERE symbol='600002'")
            else:
                row = conn.execute(
                    "SELECT receipt_json FROM market_daily_ingestion_receipts"
                ).fetchone()
                receipt = json.loads(row[0])
                receipt["provider_contact_performed_during_ingestion"] = False
                conn.execute(
                    "UPDATE market_daily_ingestion_receipts SET receipt_json=?",
                    (json.dumps(receipt),),
                )
    else:
        with sqlite3.connect(db.path) as conn:
            if variant == "partial_current":
                conn.execute(
                    "DELETE FROM daily_close_snapshots_v2 WHERE symbol='600002'"
                )
            elif variant == "old_materialization":
                conn.execute("UPDATE daily_close_snapshots_v2 SET close_price=10.5")
            elif variant == "source_string_only":
                conn.execute(
                    "UPDATE daily_close_snapshots_v2 SET source='reported_previous_close'"
                )
            elif variant == "wrong_type":
                conn.execute(
                    "UPDATE daily_close_snapshots_v2 SET instrument_type='etf'"
                )
            elif variant == "staged_tamper":
                conn.execute(
                    "UPDATE quote_ingestion_items SET payload_fingerprint='tampered' WHERE symbol='600002'"
                )
            elif variant == "run_incomplete":
                conn.execute(
                    "UPDATE quote_fetch_runs SET status='running' WHERE run_id='preview-conflict'"
                )
            elif variant == "incident_tamper":
                changed = {**incident, "failed_at": "tampered"}
                conn.execute(
                    "UPDATE runtime_controls SET value_json=? WHERE key='valuation_publication_recovery'",
                    (json.dumps({"failures": [changed]}),),
                )
    result = _preview(db, store, incident, refs)
    assert result["status"] == "blocked"
    assert result["candidate_evidence_verified"] is False
    assert result["blockers"] == [blocker]


def test_legacy_incident_has_no_inferred_fact_binding(tmp_path):
    from server.persistence.valuation_recovery_preview import (
        preview_daily_close_recovery,
    )

    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _run(db, "legacy", ["600001"])
    _finish(db, "legacy", status="failed", success=0, failure=1)
    with sqlite3.connect(db.path) as conn:
        incident = affected_publications(conn, {("stock", "600001")})[0]
    result = preview_daily_close_recovery(
        db.path, incident_ref=incident["incident_ref"]
    )
    assert result["blockers"] == ["incident_fact_binding_missing"]
    assert result["required_facts"] == []


def test_preview_binds_new_current_revision_without_resolving(tmp_path):
    db, store, incident, ref = _preview_fixture(tmp_path)
    before = _preview(db, store, incident, [ref])
    with sqlite3.connect(db.path) as conn:
        conn.execute(
            "UPDATE daily_close_snapshots_v2 SET captured_at='2026-09-05T15:00:00+08:00'"
        )
    after = _preview(db, store, incident, [ref])
    assert before["proof_fingerprint"] != after["proof_fingerprint"]
    assert after["candidate_evidence_verified"] is True
    assert after["status"] == "blocked"


def test_receipt_and_bars_share_a_read_snapshot_during_concurrent_change(
    tmp_path, monkeypatch
):
    import server.persistence.valuation_recovery_preview as preview_module

    db, store, incident, ref = _preview_fixture(tmp_path)
    app_writer = sqlite3.connect(db.path)
    meta_writer = sqlite3.connect(store._meta_path)
    for writer in (app_writer, meta_writer):
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    read_incident = preview_module._read_bound_incident
    writes = []

    def change_between_databases(conn, incident_ref, observed):
        meta_writer.execute("UPDATE market_bars_v2 SET close=12")
        meta_writer.commit()
        app_writer.execute("UPDATE daily_close_snapshots_v2 SET close_price=12")
        app_writer.commit()
        writes.append(True)
        return read_incident(conn, incident_ref, observed)

    monkeypatch.setattr(
        preview_module, "_read_bound_incident", change_between_databases
    )
    result = _preview(db, store, incident, [ref])
    assert writes == [True]
    assert result["blockers"] == ["canonical_close_not_reconciled"]
    assert result["candidate_evidence_verified"] is False
    monkeypatch.setattr(preview_module, "_read_bound_incident", read_incident)
    assert _preview(db, store, incident, [ref])["blockers"] == [
        "resolution_evidence_integrity_failed"
    ]

    app_writer.close()
    meta_writer.close()


def test_missing_preview_databases_are_never_created(tmp_path):
    from server.persistence.valuation_recovery_preview import (
        preview_daily_close_recovery,
    )

    path = tmp_path / "missing.db"
    result = preview_daily_close_recovery(path, incident_ref="sha256:missing")
    assert result["blockers"] == ["evidence_database_missing"]
    assert not path.exists()
