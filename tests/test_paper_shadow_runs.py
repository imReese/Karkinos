"""Paper/shadow run persistence tests."""

from __future__ import annotations

import json
import sqlite3

from server.db import AppDatabase


def test_upsert_paper_shadow_run_persists_counts_and_payload(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    run = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:abc123",
        plan_date="2026-07-02",
        input_fingerprint="abc123",
        status="review_required",
        order_intent_count=2,
        simulated_order_count=1,
        simulated_fill_count=1,
        divergence_status="review_required",
        next_manual_review_step="review_shadow_divergence",
        limitations=["One order requires quote review."],
        payload={"orders": [{"order_id": "SHADOW-1"}]},
    )

    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:abc123")

    assert saved is not None
    assert saved["id"] == run["id"]
    assert saved["run_id"] == "shadow:2026-07-02:abc123"
    assert saved["plan_date"] == "2026-07-02"
    assert saved["input_fingerprint"] == "abc123"
    assert saved["status"] == "review_required"
    assert saved["order_intent_count"] == 2
    assert saved["simulated_order_count"] == 1
    assert saved["simulated_fill_count"] == 1
    assert saved["divergence_status"] == "review_required"
    assert saved["next_manual_review_step"] == "review_shadow_divergence"
    assert json.loads(saved["limitations_json"]) == ["One order requires quote review."]
    assert json.loads(saved["payload_json"]) == {
        "orders": [{"order_id": "SHADOW-1"}]
    }


def test_upsert_paper_shadow_run_is_idempotent_by_run_id(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    first = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:abc123",
        plan_date="2026-07-02",
        input_fingerprint="abc123",
        status="review_required",
        order_intent_count=2,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="review_required",
        next_manual_review_step="review_shadow_divergence",
        limitations=["First pass"],
        payload={"attempt": 1},
    )
    second = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:abc123",
        plan_date="2026-07-02",
        input_fingerprint="abc123",
        status="within_expectations",
        order_intent_count=2,
        simulated_order_count=2,
        simulated_fill_count=2,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        limitations=[],
        payload={"attempt": 2},
    )

    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:abc123")

    assert second["id"] == first["id"]
    assert saved is not None
    assert saved["status"] == "within_expectations"
    assert saved["simulated_order_count"] == 2
    assert json.loads(saved["payload_json"]) == {"attempt": 2}
    assert _paper_shadow_run_count(db) == 1


def test_upsert_paper_shadow_run_reuses_same_plan_fingerprint(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    first = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:first",
        plan_date="2026-07-02",
        input_fingerprint="same-inputs",
        status="review_required",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="review_required",
        next_manual_review_step="review_shadow_divergence",
        limitations=[],
        payload={"attempt": 1},
    )
    second = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:second",
        plan_date="2026-07-02",
        input_fingerprint="same-inputs",
        status="within_expectations",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=1,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        limitations=[],
        payload={"attempt": 2},
    )

    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:first")

    assert second["id"] == first["id"]
    assert second["run_id"] == "shadow:2026-07-02:first"
    assert saved is not None
    assert saved["status"] == "within_expectations"
    assert _paper_shadow_run_count(db) == 1


def test_latest_paper_shadow_run_returns_newest_for_plan_date(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-01:old",
        plan_date="2026-07-01",
        input_fingerprint="old",
        status="within_expectations",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=1,
        divergence_status="within_expectations",
        next_manual_review_step="review_manual_confirmation",
        limitations=[],
        payload={},
    )
    newer = db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:newer",
        plan_date="2026-07-02",
        input_fingerprint="newer",
        status="diverged",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=1,
        divergence_status="diverged",
        next_manual_review_step="resolve_shadow_divergence",
        limitations=["Fill differs from order intent."],
        payload={},
    )

    latest = db.latest_paper_shadow_run_sync(plan_date="2026-07-02")

    assert latest is not None
    assert latest["id"] == newer["id"]
    assert latest["run_id"] == "shadow:2026-07-02:newer"
    assert latest["status"] == "diverged"


def test_record_paper_shadow_run_review_preserves_raw_divergence_and_audits(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.upsert_paper_shadow_run_sync(
        run_id="shadow:2026-07-02:diverged",
        plan_date="2026-07-02",
        input_fingerprint="diverged",
        status="diverged",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="diverged",
        next_manual_review_step="resolve_shadow_divergence",
        limitations=["Partial fill requires review."],
        payload={
            "orders": [{"order_id": "SHADOW-1", "divergence_status": "diverged"}]
        },
    )

    reviewed = db.record_paper_shadow_run_review_sync(
        run_id="shadow:2026-07-02:diverged",
        reviewed_at="2026-07-02T10:10:00",
        review_status="accepted_for_manual_confirmation",
        review_notes="Operator accepted the partial-fill simulation evidence.",
        reviewer="local-operator",
    )

    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:diverged")
    events = db.list_events_sync(
        event_type="paper_shadow_run.review_recorded",
        entity_type="paper_shadow_run",
        entity_id="shadow:2026-07-02:diverged",
    )

    assert reviewed is not None
    assert saved is not None
    assert saved["status"] == "diverged"
    assert saved["divergence_status"] == "diverged"
    assert saved["next_manual_review_step"] == "review_manual_confirmation"
    assert saved["review_status"] == "accepted_for_manual_confirmation"
    assert saved["reviewed_at"] == "2026-07-02T10:10:00"
    assert saved["reviewer"] == "local-operator"
    payload = json.loads(saved["payload_json"])
    assert payload["review"] == {
        "review_status": "accepted_for_manual_confirmation",
        "reviewed_at": "2026-07-02T10:10:00",
        "review_notes": "Operator accepted the partial-fill simulation evidence.",
        "reviewer": "local-operator",
        "does_not_submit_broker_order": True,
        "does_not_mutate_production_ledger": True,
    }
    assert len(events) == 1
    event_payload = json.loads(events[0]["payload_json"])
    assert event_payload["review_status"] == "accepted_for_manual_confirmation"
    assert event_payload["divergence_status"] == "diverged"
    assert event_payload["does_not_submit_broker_order"] is True


def _paper_shadow_run_count(db: AppDatabase) -> int:
    with sqlite3.connect(db._path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM paper_shadow_runs").fetchone()[0])
