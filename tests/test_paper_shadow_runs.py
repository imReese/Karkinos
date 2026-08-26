"""Paper/shadow run persistence tests."""

from __future__ import annotations

import json

import pytest

from server.db import AppDatabase
from tests.paper_shadow_fixtures import insert_paper_shadow_evidence


def test_latest_paper_shadow_run_returns_newest_for_plan_date(tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()

    insert_paper_shadow_evidence(
        db,
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
    newer = insert_paper_shadow_evidence(
        db,
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
    insert_paper_shadow_evidence(
        db,
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
        payload={"orders": [{"order_id": "SHADOW-1", "divergence_status": "diverged"}]},
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


def test_record_paper_shadow_run_review_rejects_failed_run_manual_handoff(
    tmp_path,
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    insert_paper_shadow_evidence(
        db,
        run_id="shadow:2026-07-02:failed",
        plan_date="2026-07-02",
        input_fingerprint="failed",
        status="failed",
        order_intent_count=1,
        simulated_order_count=1,
        simulated_fill_count=0,
        divergence_status="failed",
        next_manual_review_step="inspect_failed_run",
        limitations=["Paper/shadow simulation failed."],
        payload={"orders": [{"order_id": "SHADOW-1", "status": "failed"}]},
    )

    try:
        db.record_paper_shadow_run_review_sync(
            run_id="shadow:2026-07-02:failed",
            reviewed_at="2026-07-02T10:10:00",
            review_status="accepted_for_manual_confirmation",
            review_notes="Operator tried to accept failed simulation evidence.",
            reviewer="local-operator",
        )
    except ValueError as exc:
        assert "failed paper/shadow run" in str(exc)
    else:
        raise AssertionError("failed paper/shadow run was accepted for manual handoff")

    saved = db.get_paper_shadow_run_sync("shadow:2026-07-02:failed")
    assert saved is not None
    assert saved["status"] == "failed"
    assert saved["review_status"] is None
    assert saved["next_manual_review_step"] == "inspect_failed_run"
    assert (
        db.list_events_sync(
            event_type="paper_shadow_run.review_recorded",
            entity_type="paper_shadow_run",
            entity_id="shadow:2026-07-02:failed",
        )
        == []
    )
