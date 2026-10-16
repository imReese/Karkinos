"""Exact failed-refresh retirement keeps market facts and unsafe incidents intact."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server.db import AppDatabase
from server.persistence.valuation_publication_recovery import (
    UNPUBLISHED_RECOVERY_CONFIRMATION,
    discard_proven_unpublished_quote_refreshes,
    require_valuation_recovery_clear,
    unresolved_publications,
)
from server.persistence.valuation_recovery_preview import (
    preview_unpublished_quote_recovery,
)
from server.services.ai_shadow_research_qualification_support import (
    require_complete_valuation,
)
from tests.server.test_publication_recovery_replay import _finish, _quote, _run

NOW = datetime(2026, 9, 4, 7, 10, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    value = AppDatabase(tmp_path / "app.db")
    value.init_sync()
    value.insert_ledger_entry_sync(
        entry_type="cash_deposit",
        timestamp=NOW.isoformat(),
        amount=100_000,
        asset_class="cash",
    )
    value.persist_quote_ingestion_sync(_quote())
    value.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-09-03T10:00:00+08:00",
        symbol="600001",
        direction="buy",
        quantity=100,
        price=10,
        asset_class="stock",
    )
    return value


def failed_refresh(db, identity="failed-refresh", *, variant="ordinary"):
    symbols = ["600001", "600002"]
    trigger = (
        "scheduler_poll"
        if variant == "scheduler"
        else "manual_refresh"
        if variant == "manual"
        else "fixture"
    )
    db.create_quote_fetch_run(
        run_id=identity,
        started_at="2026-09-04T15:02:00+08:00",
        trigger=trigger,
        status="running",
        provider="fixture",
        asset_type="stock",
        symbol_count=2,
        metadata={"requested_symbols": symbols, "instrument_types": ["stock", "stock"]},
    )
    db.persist_quote_ingestion_sync(_quote(run=identity))
    kwargs = {"status": "partial_success", "success_count": 1, "failure_count": 1}
    metadata = {}
    error = None
    if variant == "scheduler":
        kwargs = {"status": "failed", "success_count": 0, "failure_count": 2}
        error = "scheduler quote is stale: 600002"
        metadata = {"success_symbols": [], "failed_symbols": symbols}
    elif variant == "manual":
        db.persist_quote_ingestion_sync(_quote("600002", identity))
        kwargs = {"status": "partial_success", "success_count": 1, "failure_count": 0}
        metadata = {
            "refreshed_symbols": ["600001"],
            "failed_symbols": [],
            "skipped_symbols": ["600002"],
        }
    db.finish_quote_fetch_run(
        run_id=identity,
        finished_at="2026-09-04T15:03:00+08:00",
        **kwargs,
        metadata=metadata,
        error_message=error,
    )
    # Persist the false incident produced by historical releases. Current
    # staged-only acquisition failures intentionally no longer create it.
    from server.persistence.financial_facts_valuation import (
        record_valuation_publication_failure_on_connection,
    )

    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        record_valuation_publication_failure_on_connection(
            conn,
            updated_at="2026-09-04T15:03:00+08:00",
            reason="quote_fetch_run_not_fully_successful",
            quote_fetch_run_id=identity,
            quote_fetch_run_status=kwargs["status"],
        )


def financial_rows(db):
    with sqlite3.connect(db.path) as conn:
        return {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "quote_snapshots",
                "latest_quotes",
                "daily_close_snapshots_v2",
                "daily_close_snapshots",
                "valuation_snapshots",
                "ledger_entries",
                "quote_ingestion_items",
                "quote_fetch_runs",
            )
        }


def discard(db, plan, **options):
    return discard_proven_unpublished_quote_refreshes(
        db.path,
        incident_refs=[x["incident_ref"] for x in plan["repairs"]],
        expected_proof_fingerprint=plan["proof_fingerprint"],
        actor="human:fixture-owner",
        confirmation=UNPUBLISHED_RECOVERY_CONFIRMATION,
        now=NOW,
        **options,
    )


@pytest.mark.parametrize(
    "variant,basis",
    [
        ("ordinary", "terminal_counts"),
        ("scheduler", "scheduler_rejected_complete_batch"),
        ("manual", "manual_refresh_explicit_skipped_group"),
    ],
)
def test_recovery_reopens_exact_proof_preserves_facts_and_is_idempotent(
    db, variant, basis
):
    failed_refresh(db, variant=variant)
    before = financial_rows(db)
    plan = preview_unpublished_quote_recovery(db.path)
    assert plan["status"] == "ready", plan
    assert plan["repairs"][0]["counter_basis"] == basis
    result = discard(db, plan)
    assert result["resolved_count"] == 1 and result["reused"] is False
    assert result["resolved_incidents"][0]["quote_fetch_run_id"] == "failed-refresh"
    assert financial_rows(db) == before
    with sqlite3.connect(db.path) as conn:
        assert unresolved_publications(conn) == []
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='market.quote.unpublished_refresh.discarded'"
            ).fetchone()[0]
            == 1
        )
    restarted = AppDatabase(db.path)
    repeated = discard(restarted, plan)
    assert repeated["reused"] is True
    assert repeated["completed_at"] == result["completed_at"]
    assert financial_rows(db) == before


def test_unknown_count_mismatch_and_price_conflict_remain_scoped_and_auditable(db):
    failed_refresh(db)
    _run(db, "actual-conflict", ["600001"])
    db.persist_quote_ingestion_sync(replace(_quote(run="actual-conflict"), price=11))
    assert _finish(db, "actual-conflict")["status"] == "failed"
    plan = preview_unpublished_quote_recovery(db.path)
    assert plan["status"] == "partially_ready"
    assert len(plan["repairs"]) == 1
    assert plan["blocked_incidents"][0]["blockers"] == [
        "recovery_prior_financial_fact_requires_resolution"
    ]
    discarded = discard(db, plan)
    assert discarded["resolved_count"] == 1
    with sqlite3.connect(db.path) as conn:
        remaining = unresolved_publications(conn)
    assert (
        len(remaining) == 1 and remaining[0]["quote_fetch_run_id"] == "actual-conflict"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "stage",
        "stage_time",
        "quote_event",
        "legacy_quote_event",
        "published_quote",
        "close",
    ],
)
def test_changed_or_published_evidence_cannot_use_an_old_preview(db, mutation):
    failed_refresh(db)
    plan = preview_unpublished_quote_recovery(db.path)
    with sqlite3.connect(db.path) as conn:
        if mutation == "stage":
            conn.execute(
                "UPDATE quote_ingestion_items SET payload_fingerprint='changed' WHERE run_id='failed-refresh'"
            )
        elif mutation == "stage_time":
            conn.execute(
                "UPDATE quote_ingestion_items SET staged_at='2026-09-05T00:00:00+08:00' WHERE run_id='failed-refresh'"
            )
        elif mutation in {"quote_event", "legacy_quote_event"}:
            conn.execute(
                "INSERT INTO event_log(event_type,timestamp,source,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    "market.quote.refreshed"
                    if mutation == "legacy_quote_event"
                    else "market.quote.snapshot.recorded",
                    NOW.isoformat(),
                    "quote_snapshots",
                    json.dumps({"fetch_run_id": "failed-refresh"}),
                    NOW.isoformat(),
                ),
            )
        elif mutation == "published_quote":
            conn.execute(
                "UPDATE quote_snapshots SET fetch_run_id='failed-refresh' WHERE symbol='600001'"
            )
        else:
            conn.execute(
                "UPDATE daily_close_snapshots_v2 SET captured_at='2026-09-04T15:02:30+08:00' WHERE symbol='600001'"
            )
    before = financial_rows(db)
    with pytest.raises(ValueError, match="recovery_proof_changed_or_not_ready"):
        discard(db, plan)
    assert financial_rows(db) == before
    with sqlite3.connect(db.path) as conn:
        assert len(unresolved_publications(conn)) == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='market.quote.unpublished_refresh.discarded'"
            ).fetchone()[0]
            == 0
        )


def test_recovery_fence_is_shared_by_qualification_and_publication_preview(
    db, monkeypatch
):
    from server.persistence.ai_shadow_research import ShadowResearchStore
    from server.services.recommendation_publication import (
        RecommendationPublicationService,
    )
    from server.services.valuation_snapshot import build_current_valuation_snapshot

    valuation = build_current_valuation_snapshot(db, now=NOW, persist=True)
    assert valuation["status"] == "complete"
    failed_refresh(db)
    with pytest.raises(ValueError, match="valuation_publication_recovery_required"):
        require_complete_valuation(valuation, db)
    monkeypatch.setattr(
        "server.services.valuation_snapshot.build_current_valuation_snapshot",
        lambda *args, **kwargs: valuation,
    )
    service = RecommendationPublicationService(
        db, ShadowResearchStore(db.path), state=SimpleNamespace()
    )
    assert service.preview({})["preview_blockers"] == [
        "valuation_publication_recovery_required"
    ]
    # Unknown incident scopes affect all accounts; a known unrelated scope does
    # not turn a research/empty-cash account into the affected account.
    require_valuation_recovery_clear(db, {"quotes": []})
    result = discard(db, preview_unpublished_quote_recovery(db.path))
    assert result["resolved_count"] == 1
    assert (
        require_complete_valuation(valuation, db)["snapshot_id"]
        == valuation["snapshot_id"]
    )


def fund_estimate_conflict(db, monkeypatch, *, candidate_source="sina_fund_estimate"):
    clock = [datetime(2026, 9, 4, 7, 0, 1, tzinfo=timezone.utc)]
    db._financial_facts._now = lambda tz=None: clock[0]
    monkeypatch.setattr(
        "server.persistence.event_log.datetime",
        SimpleNamespace(now=lambda *args, **kwargs: clock[0]),
    )
    published = replace(
        _quote("000001"),
        asset_type="open_end_fund",
        nav_date="2026-09-04",
        quote_source="eastmoney_fund_page",
        daily_close_price=None,
        daily_close_date=None,
    )
    db.persist_quote_ingestion_sync(published)
    db.create_quote_fetch_run(
        run_id="estimate-conflict",
        started_at="2026-09-04T15:02:00+08:00",
        trigger="fixture",
        status="running",
        provider="fixture",
        asset_type="open_end_fund",
        symbol_count=1,
        metadata={
            "requested_symbols": ["000001"],
            "instrument_types": ["open_end_fund"],
        },
    )
    clock[0] = datetime(2026, 9, 4, 7, 2, 30, tzinfo=timezone.utc)
    db.persist_quote_ingestion_sync(
        replace(
            published,
            price=11,
            quote_source=candidate_source,
            fetch_run_id="estimate-conflict",
        )
    )
    assert _finish(db, "estimate-conflict")["status"] == "failed"
    return published, clock


def test_unpublished_estimate_is_disposed_against_original_published_nav(
    db, monkeypatch
):
    fund_estimate_conflict(db, monkeypatch)
    before = financial_rows(db)
    plan = preview_unpublished_quote_recovery(db.path)
    assert plan["status"] == "ready", plan
    proof = plan["repairs"][0]
    assert (
        proof["classification"] == "unpublished_estimate_rejected_below_published_nav"
    )
    assert len(proof["prior_published_nav"]) == 1
    result = discard(db, plan)
    assert result["resolved_count"] == 1
    assert financial_rows(db) == before
    assert db.get_latest_quote_sync("000001", "open_end_fund")["price"] == 10.5


@pytest.mark.parametrize(
    "mutation", ["authoritative_candidate", "prior_event", "published_nav_conflict"]
)
def test_prior_nav_resolution_never_guesses_between_authoritative_facts(
    db, monkeypatch, mutation
):
    published, clock = fund_estimate_conflict(
        db,
        monkeypatch,
        candidate_source="tushare_fund_nav"
        if mutation == "authoritative_candidate"
        else "sina_fund_estimate",
    )
    if mutation == "prior_event":
        with sqlite3.connect(db.path) as conn:
            row = conn.execute(
                "SELECT source_ref,payload_json FROM event_log WHERE event_type='market.quote.snapshot.recorded' AND json_extract(payload_json,'$.symbol')='000001'"
            ).fetchone()
            payload = json.loads(row[1])
            payload["price"] = 12
            conn.execute(
                "INSERT INTO event_log(event_type,timestamp,source,source_ref,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    "market.quote.snapshot.recorded",
                    "2026-09-04T15:00:00+08:00",
                    "quote_snapshots",
                    row[0],
                    json.dumps(payload),
                    "2026-09-04T15:00:01+08:00",
                ),
            )
    elif mutation == "published_nav_conflict":
        clock[0] = datetime(2026, 9, 4, 7, 2, 45, tzinfo=timezone.utc)
        db.persist_quote_ingestion_sync(
            replace(
                published,
                price=12,
                quote_timestamp="2026-09-04T15:01:00+08:00",
                captured_at="2026-09-04T15:01:01+08:00",
            )
        )
    plan = preview_unpublished_quote_recovery(db.path)
    assert plan["status"] == "blocked"
    assert plan["repairs"] == []
    assert plan["blocked_incidents"][0]["blockers"] == [
        {
            "authoritative_candidate": "recovery_prior_financial_fact_requires_resolution",
            "prior_event": "recovery_prior_nav_event_missing_or_ambiguous",
            "published_nav_conflict": "recovery_prior_published_nav_conflicting",
        }[mutation]
    ]


def test_receipt_and_incident_resolution_rollback_together(db):
    failed_refresh(db)
    plan = preview_unpublished_quote_recovery(db.path)
    with sqlite3.connect(db.path) as conn:
        conn.execute("""CREATE TRIGGER fail_recovery_control BEFORE UPDATE ON runtime_controls
            WHEN OLD.key='valuation_publication_recovery'
            BEGIN SELECT RAISE(ABORT,'recovery commit interrupted'); END""")
    before = financial_rows(db)
    with pytest.raises(sqlite3.IntegrityError, match="recovery commit interrupted"):
        discard(db, plan)
    assert financial_rows(db) == before
    with sqlite3.connect(db.path) as conn:
        assert len(unresolved_publications(conn)) == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='market.quote.unpublished_refresh.discarded'"
            ).fetchone()[0]
            == 0
        )


def duplicate_quote_conflict(db, monkeypatch):
    """Exercise the real legacy latest-quote writer and atomic run rollback."""
    clock = [datetime(2026, 9, 4, 7, 0, 1, tzinfo=timezone.utc)]
    db._financial_facts._now = lambda tz=None: clock[0]
    monkeypatch.setattr(
        "server.persistence.event_log.datetime",
        SimpleNamespace(now=lambda *args, **kwargs: clock[0]),
    )
    proposal = replace(
        _quote("600003"),
        daily_close_price=None,
        daily_close_date=None,
        daily_close_source=None,
    )
    fields = {
        name: value
        for name, value in proposal.to_dict().items()
        if name
        in {
            "symbol",
            "asset_type",
            "price",
            "quote_timestamp",
            "captured_at",
            "previous_close",
            "change",
            "change_percent",
            "volume",
            "turnover",
            "quote_source",
            "provider_name",
            "provider_status",
            "quote_status",
            "stale_reason",
            "captured_reason",
            "nav_date",
            "metadata",
        }
    }
    db.upsert_latest_quote_sync(**fields)
    _run(db, "duplicate-conflict", ["600003"])
    clock[0] = datetime(2026, 9, 4, 7, 2, 30, tzinfo=timezone.utc)
    db.persist_quote_ingestion_sync(
        replace(
            proposal,
            volume=1000,
            fetch_run_id="duplicate-conflict",
        )
    )
    # Reconstruct the historical strict duplicate rejection with canonical
    # completion/failure owners. The current writer deliberately accepts these
    # derived-field updates, so it cannot produce this old persisted failure.
    from server.persistence.financial_facts_quote_ingestion_uow import (
        _finish_quote_run,
        quote_completion_fingerprint,
    )
    from server.persistence.financial_facts_valuation import (
        record_valuation_publication_failure_on_connection,
    )

    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "SELECT * FROM quote_fetch_runs WHERE run_id='duplicate-conflict'"
        ).fetchone()
        finished_at = "2026-09-04T15:03:00+08:00"
        record_valuation_publication_failure_on_connection(
            conn,
            updated_at=finished_at,
            reason="quote_batch_publication_failed",
            error_type="ValueError",
            quote_fetch_run_id="duplicate-conflict",
            quote_fetch_run_status="failed",
            daily_close_conflict=None,
        )
        _finish_quote_run(
            conn,
            run=run,
            finished_at=finished_at,
            status="failed",
            success_count=1,
            failure_count=0,
            cache_hit_count=0,
            error_message="valuation snapshot publication failed: ValueError",
            metadata={
                "valuation_snapshot_publication": "failed",
                "quote_publication_completion_fingerprint": quote_completion_fingerprint(
                    finished_at=finished_at,
                    status="success",
                    success_count=1,
                    failure_count=0,
                    cache_hit_count=0,
                    error_message=None,
                    metadata=None,
                ),
            },
        )


def test_duplicate_proposal_preserves_original_legacy_event_and_financial_facts(
    db,
    monkeypatch,
):
    duplicate_quote_conflict(db, monkeypatch)
    before = financial_rows(db)
    plan = preview_unpublished_quote_recovery(db.path)
    assert plan["status"] == "ready", plan
    proof = plan["repairs"][0]
    assert proof["classification"] == "unpublished_duplicate_quote_proposal_rejected"
    assert proof["prior_quote_events"][0]["rejected_difference_fields"] == ["volume"]
    assert discard(db, plan)["resolved_count"] == 1
    assert financial_rows(db) == before
    assert db.get_latest_quote_sync("600003", "stock")["volume"] is None


@pytest.mark.parametrize("recorded_after_failure", [False, True])
def test_duplicate_proof_cannot_adjudicate_a_conflicting_prior_price(
    db, monkeypatch, recorded_after_failure
):
    from server.persistence.event_log import insert_event_sync

    duplicate_quote_conflict(db, monkeypatch)
    initial = preview_unpublished_quote_recovery(db.path)
    assert initial["status"] == "ready", initial
    monkeypatch.setattr(
        "server.persistence.event_log.datetime",
        SimpleNamespace(
            now=lambda *args, **kwargs: datetime(
                2026,
                9,
                4,
                7,
                20 if recorded_after_failure else 2,
                30,
                tzinfo=timezone.utc,
            )
        ),
    )
    with sqlite3.connect(db.path) as conn:
        original = json.loads(
            conn.execute(
                "SELECT payload_json FROM event_log WHERE event_type='market.quote.refreshed' "
                "AND json_extract(payload_json,'$.symbol')='600003'"
            ).fetchone()[0]
        )
        insert_event_sync(
            conn,
            event_type="market.quote.refreshed",
            timestamp=original["quote_timestamp"],
            entity_type="instrument",
            entity_id=original["symbol"],
            source="latest_quotes",
            source_ref=str(original["quote_id"]),
            payload={**original, "price": 20},
        )
    plan = preview_unpublished_quote_recovery(db.path)
    if recorded_after_failure:
        assert plan == initial
    else:
        assert plan["status"] == "blocked"
        assert plan["blocked_incidents"][0]["blockers"] == [
            "recovery_prior_financial_fact_requires_resolution"
        ]


@pytest.mark.parametrize(
    "representation", ["current", "identity_default", "other_missing_field"]
)
def test_legacy_completion_event_uses_actual_terminal_time_without_rewriting_incident(
    db,
    representation,
):
    from server.persistence.event_log import insert_event_sync
    from server.persistence.valuation_publication_recovery import RECOVERY_KEY

    _run(db, "legacy-failed", ["600001", "600002"])
    db.persist_quote_ingestion_sync(_quote(run="legacy-failed"))
    incident = {
        "error_type": "ValueError",
        "quote_fetch_run_id": "legacy-failed",
        "quote_fetch_run_status": "partial_success",
        "reason": "quote_fetch_run_not_fully_successful",
        "status": "failed",
        "scope": [["stock", "600001"], ["stock", "600002"]],
    }
    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        if representation != "current":
            from server.persistence.database_normalization import (
                stable_json_fingerprint,
            )

            item = conn.execute(
                "SELECT id,payload_json FROM quote_ingestion_items WHERE run_id='legacy-failed'"
            ).fetchone()
            raw = json.loads(item["payload_json"])
            raw.pop("identity_provenance")
            raw["metadata"].pop("identity_provenance")
            if representation == "other_missing_field":
                raw.pop("volume")
            conn.execute(
                "UPDATE quote_ingestion_items SET payload_json=?,payload_fingerprint=? WHERE id=?",
                (json.dumps(raw), stable_json_fingerprint(raw), item["id"]),
            )
        conn.execute(
            "UPDATE quote_fetch_runs SET status='partial_success',success_count=1,"
            "failure_count=1,finished_at='2026-09-04T15:03:00+08:00' WHERE run_id='legacy-failed'"
        )
        run = dict(
            conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id='legacy-failed'"
            ).fetchone()
        )
        metadata = json.loads(run["metadata_json"])
        insert_event_sync(
            conn,
            event_type="task_run.completed",
            timestamp=run["finished_at"],
            entity_type="task_run",
            entity_id=run["run_id"],
            source="quote_fetch_runs",
            source_ref=run["run_id"],
            payload={
                **{k: v for k, v in run.items() if k != "metadata_json"},
                "metadata": metadata,
            },
        )
        conn.execute(
            "INSERT INTO runtime_controls(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (RECOVERY_KEY, json.dumps({"failures": [incident]}), NOW.isoformat()),
        )
    before = financial_rows(db)
    plan = preview_unpublished_quote_recovery(db.path)
    if representation == "other_missing_field":
        assert plan["status"] == "blocked"
        assert plan["blocked_incidents"][0]["blockers"] == [
            "recovery_staged_payload_changed"
        ]
        assert financial_rows(db) == before
        return
    assert plan["status"] == "ready", plan
    assert plan["repairs"][0]["completion_binding"] == "legacy_exact_completed_event"
    payload = plan["repairs"][0]["staged_payloads"][0]
    assert (
        payload["payload_fingerprint"] == payload["canonical_command_fingerprint"]
    ) == (representation == "current")
    receipt = discard(db, plan)
    assert receipt["resolved_incidents"] == [incident]
    assert "failed_at" not in receipt["resolved_incidents"][0]
    assert financial_rows(db) == before


def legacy_misdated_close_batch(db, tmp_path, monkeypatch, *, receipt_schema="current"):
    """Persist an actual two-day market owner plus the old failed-run format."""
    import hashlib

    import pandas as pd

    from data.store import DataStore
    from server.persistence.event_log import insert_event_sync
    from server.persistence.valuation_publication_recovery import RECOVERY_KEY

    capture = datetime(2026, 9, 4, 7, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "data.market_daily_store.datetime", SimpleNamespace(now=lambda: capture)
    )
    market = DataStore(tmp_path / "market")
    receipts = {}
    for day, price in (("2026-09-03", 10), ("2026-09-04", 10.5)):
        frame = pd.DataFrame(
            [
                {
                    "symbol": "600003",
                    "timestamp": pd.Timestamp(day),
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 10000,
                    "amount": price * 10000,
                }
            ]
        )
        receipt = market.ingest_market_daily_batch(
            trade_date=day,
            provider_name="tushare",
            bars=frame,
        )
        if receipt_schema == "legacy":
            # Retain the real legacy receipt representation consumed in production.
            core = {
                k: v
                for k, v in receipt.items()
                if k not in {"receipt_fingerprint", "units", "price_basis"}
            }
            core.update(
                schema_version="karkinos.market_daily_ingestion_receipt.v1",
                storage_authority="sqlite_market_bars",
            )
            receipt = {
                **core,
                "receipt_fingerprint": "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
            }
            with sqlite3.connect(market._meta_path) as conn:
                conn.execute(
                    "UPDATE market_daily_ingestion_receipts SET receipt_json=? WHERE trade_date=?",
                    (json.dumps(receipt), day),
                )
        receipts[day] = receipt
    current = receipts["2026-09-04"]
    binding = {
        "receipt_fingerprint": current["receipt_fingerprint"],
        "market_dataset_fingerprint": current["dataset_fingerprint"],
    }
    db.create_quote_fetch_run(
        run_id="legacy-misdated",
        started_at="2026-09-04T15:02:00+08:00",
        trigger="fixture",
        status="running",
        provider="fixture",
        asset_type="stock",
        symbol_count=1,
        metadata={
            "symbols": ["600003"],
            "market_data_provider": "tushare",
            "target_trade_date": "2026-09-04",
            **binding,
        },
    )
    db.persist_quote_ingestion_sync(
        replace(
            _quote("600003", "legacy-misdated"),
            provider_name="tushare",
            quote_source="market_bar_close",
            metadata=binding,
        )
    )
    incident = {
        "error_type": "ValueError",
        "quote_fetch_run_id": "legacy-misdated",
        "quote_fetch_run_status": "failed",
        "reason": "quote_batch_publication_failed",
        "status": "failed",
        "scope": [["stock", "600003"]],
    }
    with sqlite3.connect(db.path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO daily_close_snapshots(symbol,asset_class,trade_date,close_price,source,captured_at) VALUES(?,?,?,?,?,?)",
            (
                "600003",
                "stock",
                "2026-09-04",
                10,
                "reported_previous_close",
                "2026-09-04T15:00:00+08:00",
            ),
        )
        row = conn.execute(
            "SELECT * FROM quote_fetch_runs WHERE run_id='legacy-misdated'"
        ).fetchone()
        metadata = {
            **json.loads(row["metadata_json"]),
            "valuation_snapshot_publication": "failed",
        }
        conn.execute(
            "UPDATE quote_fetch_runs SET status='failed',success_count=1,failure_count=0,finished_at=?,error_message=?,metadata_json=? WHERE run_id='legacy-misdated'",
            (
                "2026-09-04T15:03:00+08:00",
                "valuation snapshot publication failed: ValueError",
                json.dumps(metadata),
            ),
        )
        run = dict(
            conn.execute(
                "SELECT * FROM quote_fetch_runs WHERE run_id='legacy-misdated'"
            ).fetchone()
        )
        insert_event_sync(
            conn,
            event_type="task_run.completed",
            timestamp=run["finished_at"],
            entity_type="task_run",
            entity_id=run["run_id"],
            source="quote_fetch_runs",
            source_ref=run["run_id"],
            payload={
                **{k: v for k, v in run.items() if k != "metadata_json"},
                "metadata": metadata,
            },
        )
        conn.execute(
            "INSERT INTO runtime_controls(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (RECOVERY_KEY, json.dumps({"failures": [incident]}), NOW.isoformat()),
        )
    return market, incident


@pytest.mark.parametrize("receipt_schema", ["current", "legacy"])
def test_legacy_close_disposition_replays_both_dates_without_rewriting_raw_facts(
    db,
    tmp_path,
    monkeypatch,
    receipt_schema,
):
    market, incident = legacy_misdated_close_batch(
        db, tmp_path, monkeypatch, receipt_schema=receipt_schema
    )
    before = financial_rows(db)
    missing = preview_unpublished_quote_recovery(db.path)
    assert missing["blocked_incidents"][0]["blockers"] == [
        "recovery_legacy_market_evidence_required"
    ]
    plan = preview_unpublished_quote_recovery(
        db.path, market_database_path=market._meta_path
    )
    assert plan["status"] == "ready", plan
    disposition = plan["repairs"][0]["legacy_close_disposition"]
    assert disposition["financial_facts_changed"] is False
    assert disposition["historical_point_in_time_status_upgraded"] is False
    assert disposition["facts"][0]["typed_close_adopted"] is False
    assert [
        r["receipt"]["trade_date"] for r in disposition["facts"][0]["dated_receipts"]
    ] == ["2026-09-03", "2026-09-04"]
    result = discard(db, plan, market_database_path=market._meta_path)
    assert result["resolved_incidents"] == [incident]
    assert financial_rows(db) == before
    assert discard(db, plan, market_database_path=market._meta_path)["reused"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "previous_receipt",
        "candidate_receipt",
        "bar",
        "legacy_close",
        "typed_adoption",
        "current_consumer",
    ],
)
def test_legacy_close_disposition_reopens_market_and_app_facts_under_command_lock(
    db,
    tmp_path,
    monkeypatch,
    mutation,
):
    market, _ = legacy_misdated_close_batch(db, tmp_path, monkeypatch)
    plan = preview_unpublished_quote_recovery(
        db.path, market_database_path=market._meta_path
    )
    assert plan["status"] == "ready", plan
    if mutation in {"previous_receipt", "candidate_receipt", "bar"}:
        with sqlite3.connect(market._meta_path) as conn:
            if mutation == "bar":
                conn.execute(
                    "UPDATE market_bars SET close=20 WHERE symbol='600003' AND substr(timestamp,1,10)='2026-09-03'"
                )
            else:
                day = "2026-09-03" if mutation == "previous_receipt" else "2026-09-04"
                conn.execute(
                    "DELETE FROM market_daily_ingestion_receipts WHERE trade_date=?",
                    (day,),
                )
    elif mutation == "current_consumer":
        db.upsert_latest_quote_sync(
            symbol="600003",
            asset_type="stock",
            price=10.5,
            previous_close=10,
            quote_timestamp="2026-09-04T15:00:00+08:00",
            metadata={"previous_close_date": "2026-09-04"},
        )
    else:
        with sqlite3.connect(db.path) as conn:
            if mutation == "legacy_close":
                conn.execute(
                    "UPDATE daily_close_snapshots SET close_price=20 WHERE symbol='600003'"
                )
            else:
                conn.execute(
                    "INSERT INTO daily_close_snapshots_v2(symbol,instrument_type,trade_date,close_price,source,captured_at,identity_provenance) VALUES(?,?,?,?,?,?,?)",
                    (
                        "600003",
                        "stock",
                        "2026-09-04",
                        10,
                        "reported_previous_close",
                        NOW.isoformat(),
                        "fixture",
                    ),
                )
    before = financial_rows(db)
    with pytest.raises(ValueError, match="recovery_proof_changed_or_not_ready"):
        discard(db, plan, market_database_path=market._meta_path)
    assert financial_rows(db) == before
    with sqlite3.connect(db.path) as conn:
        assert len(unresolved_publications(conn)) == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM event_log WHERE event_type='market.quote.unpublished_refresh.discarded'"
            ).fetchone()[0]
            == 0
        )
