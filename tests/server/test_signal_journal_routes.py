"""Signal journal route tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.routing import APIRoute

from server.db import AppDatabase
from server.routes import signals as signal_routes


def _endpoint(path: str, method: str = "GET"):
    router = signal_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def test_record_signal_review_outcome_is_journaled(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    db.save_signal_sync(
        timestamp="2026-04-18T09:30:00",
        strategy_id="dual_ma",
        symbol="510300",
        direction="buy",
        target_weight=0.2,
        price=4.56,
        asset_class="fund",
    )
    db.upsert_action_task_sync(
        source_signal_id=1,
        symbol="510300",
        title="建议增持 510300",
        detail="dual_ma 触发，目标仓位 20%",
        direction="buy",
        urgency="high",
        target_weight=0.2,
        price=4.56,
        strategy_id="dual_ma",
        timestamp="2026-04-18T09:30:00",
        asset_class="fund",
    )
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.app.get_app_state", lambda: fake_state)
    endpoint = _endpoint("/api/signals/journal/{signal_id}/review", method="POST")

    event = asyncio.run(
        endpoint(
            1,
            signal_routes.SignalJournalReviewRequest(
                reviewed_at="2026-04-20T16:00:00",
                user_decision="ignored",
                outcome="risk_block_validated",
                review_notes="Risk review confirmed the skipped signal avoided excess concentration.",
            ),
        )
    )
    journal_entry = db.list_signal_journal_sync()[0]

    assert event.event_type == "signal.review.recorded"
    assert event.source == "signal_reviews"
    assert event.source_ref == "1"
    assert event.payload["signal_id"] == 1
    assert event.payload["user_decision"] == "ignored"
    assert event.payload["outcome"] == "risk_block_validated"
    assert journal_entry["review"]["outcome"] == "risk_block_validated"
    assert journal_entry["review"]["review_notes"].startswith("Risk review confirmed")
    assert journal_entry["latest_event"]["event_type"] == "signal.review.recorded"
