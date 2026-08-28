"""Signal journal route tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from core.events import OrderIntentEvent, RiskDecisionEvent
from core.types import OrderSide, Symbol
from server.db import AppDatabase
from server.persistence.signal_journal_projection import (
    index_signal_journal_events,
    latest_signal_journal_event,
)
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


def test_indexed_signal_journal_event_selection_matches_priority_order() -> None:
    events = [
        {
            "source": "orders",
            "source_ref": "order-1",
            "event_type": "order.status_changed",
            "payload": {"source_signal_id": 1},
        },
        {
            "source": "manual_orders",
            "source_ref": "manual-1",
            "event_type": "order.status_changed",
            "payload": {"payload": {"action_id": 10}},
        },
        {
            "source": "signal_reviews",
            "source_ref": "1",
            "event_type": "signal.reviewed",
            "payload": {},
        },
        {
            "source": "decision_outcome_reviews",
            "source_ref": "review-1",
            "event_type": "decision.reviewed",
            "payload": {"signal_id": 1},
        },
        {
            "source": "orders",
            "source_ref": "order-2",
            "event_type": "order.status_changed",
            "payload": {"source_signal_id": 2},
        },
        {
            "source": "manual_orders",
            "source_ref": "manual-2",
            "event_type": "order.status_changed",
            "payload": {"payload": {"action_id": 20}},
        },
        {
            "source": "other",
            "source_ref": "generic-3",
            "event_type": "other.event",
            "payload": {"source_signal_id": 3},
        },
        {
            "source": "risk_decisions",
            "source_ref": "risk-3",
            "event_type": "risk.decided",
            "payload": {},
        },
    ]
    event_index = index_signal_journal_events(events)
    cases = (
        (1, {"id": 10}, {"decision_id": "risk-1"}, "review-1"),
        (2, {"id": 20}, {"decision_id": "risk-2"}, "manual-2"),
        (3, {"id": 30}, {"decision_id": "risk-3"}, "generic-3"),
    )

    for signal_id, action, risk, expected_ref in cases:
        linear = latest_signal_journal_event(
            signal_id=signal_id,
            action_task=action,
            risk_decision=risk,
            events=events,
        )
        indexed = latest_signal_journal_event(
            signal_id=signal_id,
            action_task=action,
            risk_decision=risk,
            events=events,
            event_index=event_index,
        )
        assert indexed == linear
        assert indexed is not None and indexed["source_ref"] == expected_ref


def test_indexed_signal_journal_lookup_scans_event_batch_once() -> None:
    class CountingEvents(list[dict[str, object]]):
        def __init__(self, values: list[dict[str, object]]) -> None:
            super().__init__(values)
            self.iteration_count = 0

        def __iter__(self):
            self.iteration_count += 1
            return super().__iter__()

    events = CountingEvents(
        [
            {
                "source": "orders",
                "source_ref": f"order-{signal_id}",
                "event_type": "order.status_changed",
                "payload": {"source_signal_id": signal_id},
            }
            for signal_id in range(1, 101)
        ]
    )

    event_index = index_signal_journal_events(events)

    assert events.iteration_count == 1
    for signal_id in range(1, 101):
        selected = latest_signal_journal_event(
            signal_id=signal_id,
            action_task=None,
            risk_decision=None,
            events=events,
            event_index=event_index,
        )
        assert selected is not None
        assert selected["source_ref"] == f"order-{signal_id}"
    assert events.iteration_count == 1


@pytest.mark.parametrize("source", ("risk_decisions", "action_tasks"))
def test_indexed_signal_journal_preserves_null_source_ref_fallback(source: str) -> None:
    events = [
        {
            "source": source,
            "source_ref": None,
            "event_type": "legacy.event",
            "payload": {},
        },
        {
            "source": "orders",
            "source_ref": "older-fallback",
            "event_type": "order.created",
            "payload": {"source_signal_id": 1},
        },
    ]

    linear = latest_signal_journal_event(
        signal_id=1,
        action_task=None,
        risk_decision=None,
        events=events,
    )
    indexed = latest_signal_journal_event(
        signal_id=1,
        action_task=None,
        risk_decision=None,
        events=events,
        event_index=index_signal_journal_events(events),
    )

    assert indexed == linear
    assert indexed is not None and indexed["source"] == source


def _seed_signal_chain(db: AppDatabase) -> None:
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


def _review_request(target_fingerprint: str, *, key: str = "review-001"):
    return signal_routes.SignalJournalReviewRequest(
        idempotency_key=key,
        reviewed_by="portfolio-owner",
        user_decision="ignored",
        outcome="not_executed",
        note="No order was created; retain the signal for later evidence review.",
        expected_target_fingerprint=target_fingerprint,
        confirmation=(
            "record_evidence_bound_decision_review_without_trade_or_capital_authority"
        ),
    )


def _seed_bound_contribution_chain(db: AppDatabase) -> dict:
    intent = OrderIntentEvent(
        timestamp=datetime(2026, 4, 18, 9, 32),
        intent_id="INTENT-REVIEW-1",
        strategy_id="dual_ma",
        symbol=Symbol("510300"),
        side=OrderSide.BUY,
        target_weight=Decimal("0.20"),
        quantity=Decimal("100"),
        reference_price=Decimal("4.56"),
        source_signal_id="1",
        reason="decision outcome review fixture",
    )
    db.save_risk_decision_sync(
        intent=intent,
        decision=RiskDecisionEvent(
            timestamp=datetime(2026, 4, 18, 9, 33),
            decision_id="RISK-REVIEW-1",
            intent_id=intent.intent_id,
            passed=True,
            symbol=intent.symbol,
            side=intent.side,
            reasons=[],
            severity="info",
        ),
    )
    db.record_order_sync(
        order_id="ORDER-REVIEW-1",
        timestamp="2026-04-18T09:34:00+08:00",
        symbol="510300",
        side="buy",
        order_type="market",
        quantity=100,
        price=4.57,
        asset_class="fund",
        intent_id=intent.intent_id,
        risk_decision_id="RISK-REVIEW-1",
        execution_mode="manual",
        status="filled",
        source="manual_confirmed_execution",
        source_ref="ORDER-REVIEW-1",
        payload={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.record_fill_sync(
        fill_id="FILL-REVIEW-1",
        order_id="ORDER-REVIEW-1",
        timestamp="2026-04-18T09:35:00+08:00",
        symbol="510300",
        side="buy",
        fill_price=4.57,
        fill_quantity=100,
        commission=5,
        slippage=1.5,
        asset_class="fund",
        execution_mode="manual",
        source="manual_confirmed_execution",
        source_ref="FILL-REVIEW-1",
        metadata={"strategy_id": "dual_ma", "source_signal_id": 1},
    )
    db.insert_ledger_entry_sync(
        entry_type="trade_buy",
        timestamp="2026-04-18T09:35:00+08:00",
        amount=457,
        symbol="510300",
        direction="buy",
        quantity=100,
        price=4.57,
        commission=5,
        gross_amount=457,
        net_cash_impact=-462,
        fee_breakdown_json=('{"commission":"5","stamp_tax":"0","total_fee":"5"}'),
        asset_class="fund",
        note="posted decision review fixture",
        source="controlled_submission_ledger_posting",
        source_ref="FILL-REVIEW-1",
    )
    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.8,
        quote_timestamp="2026-04-18T15:00:00+08:00",
        quote_source="deterministic_fixture",
        provider_name="deterministic_fixture",
        provider_status="ok",
        quote_status="confirmed",
    )
    return db.publish_current_valuation_snapshot_sync()


def test_record_signal_review_outcome_is_evidence_bound_and_journaled(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    endpoint = _endpoint("/api/signals/journal/{signal_id}/review", method="POST")

    preview = asyncio.run(preview_endpoint(1))
    result = asyncio.run(endpoint(1, _review_request(preview["target_fingerprint"])))
    journal_entry = db.list_signal_journal_sync()[0]

    assert preview["financial_evidence_status"] == "not_applicable"
    assert preview["execution_evidence"]["status"] == "not_executed"
    assert preview["persisted_facts_only"] is True
    assert preview["provider_contacted"] is False
    assert preview["database_writes_performed"] is False
    assert result["target_binding_valid"] is True
    assert result["audit_replay"]["valid"] is True
    assert result["does_not_mutate_financial_state"] is True
    assert result["authorizes_execution"] is False
    assert journal_entry["review"]["outcome"] == "not_executed"
    assert journal_entry["review"]["review_notes"].startswith("No order")
    assert journal_entry["latest_event"]["event_type"] == (
        "decision.outcome_review.recorded"
    )
    assert journal_entry["latest_event"]["source"] == "decision_outcome_reviews"
    assert journal_entry["latest_event"]["payload"]["target_fingerprint"] == (
        preview["target_fingerprint"]
    )


def test_signal_review_preview_is_read_only_and_record_is_idempotent(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    review_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review", method="POST"
    )

    with sqlite3.connect(db._path) as conn:
        before = {
            "reviews": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_reviews"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],
        }
    preview = asyncio.run(preview_endpoint(1))
    with sqlite3.connect(db._path) as conn:
        after_preview = {
            "reviews": conn.execute(
                "SELECT COUNT(*) FROM decision_outcome_reviews"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],
        }
    assert after_preview == before

    request = _review_request(preview["target_fingerprint"])
    first = asyncio.run(review_endpoint(1, request))
    second = asyncio.run(review_endpoint(1, request))
    assert first["review"]["review_id"] == second["review"]["review_id"]
    assert first["reused"] is False
    assert second["reused"] is True
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM decision_outcome_reviews").fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM event_log "
                "WHERE source = 'decision_outcome_reviews'"
            ).fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == (
            before["ledger"]
        )


def test_signal_review_rejects_evidence_drift_and_unbound_outcome(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    review_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review", method="POST"
    )

    preview = asyncio.run(preview_endpoint(1))
    db.update_action_task_status_sync(1, "deferred")
    with pytest.raises(HTTPException) as drift:
        asyncio.run(review_endpoint(1, _review_request(preview["target_fingerprint"])))
    assert drift.value.status_code == 409

    current = asyncio.run(preview_endpoint(1))
    unsupported = signal_routes.SignalJournalReviewRequest(
        idempotency_key="review-unbound-outcome",
        reviewed_by="portfolio-owner",
        user_decision="acted",
        outcome="evidence_supported",
        note="This conclusion must not be accepted without bound fill evidence.",
        expected_target_fingerprint=current["target_fingerprint"],
        confirmation=(
            "record_evidence_bound_decision_review_without_trade_or_capital_authority"
        ),
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(review_endpoint(1, unsupported))
    assert rejected.value.status_code == 422
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM decision_outcome_reviews").fetchone()[0]
            == 0
        )


def test_signal_review_replay_detects_tampering(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    review_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review", method="POST"
    )
    replay_endpoint = _endpoint(
        "/api/signals/journal/reviews/{review_id}/replay", method="GET"
    )

    preview = asyncio.run(preview_endpoint(1))
    result = asyncio.run(
        review_endpoint(1, _review_request(preview["target_fingerprint"]))
    )
    review_id = result["review"]["review_id"]
    assert asyncio.run(replay_endpoint(review_id))["valid"] is True

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE decision_outcome_review_events SET payload_json = '{}' "
            "WHERE review_id = ? AND sequence = 1",
            (review_id,),
        )
        conn.commit()
    replay = asyncio.run(replay_endpoint(review_id))
    assert replay["valid"] is False
    assert "event_hash_mismatch" in replay["errors"]


def test_signal_review_read_rejects_tampered_main_record(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    review_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review", method="POST"
    )
    get_endpoint = _endpoint("/api/signals/journal/reviews/{review_id}", method="GET")
    replay_endpoint = _endpoint(
        "/api/signals/journal/reviews/{review_id}/replay", method="GET"
    )

    preview = asyncio.run(preview_endpoint(1))
    recorded = asyncio.run(
        review_endpoint(1, _review_request(preview["target_fingerprint"]))
    )
    review_id = recorded["review"]["review_id"]
    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE decision_outcome_reviews "
            "SET target_json = ?, request_json = ? WHERE review_id = ?",
            ('{"tampered_target":true}', '{"tampered_request":true}', review_id),
        )
        conn.commit()

    result = asyncio.run(get_endpoint(review_id))
    replay = asyncio.run(replay_endpoint(review_id))

    assert result["target_binding_valid"] is False
    assert result["stored_review_integrity_valid"] is False
    assert replay["valid"] is False
    assert "stored_review_request_fingerprint_mismatch" in replay["errors"]
    assert "stored_review_target_fingerprint_mismatch" in replay["errors"]
    assert "stored_review_request_target_binding_mismatch" in replay["errors"]


def test_signal_review_binds_canonical_contribution_and_exposes_later_drift(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    _seed_signal_chain(db)
    published = _seed_bound_contribution_chain(db)
    fake_state = SimpleNamespace(db=db)
    monkeypatch.setattr("server.dependencies.get_app_state", lambda: fake_state)
    preview_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review/preview", method="POST"
    )
    review_endpoint = _endpoint(
        "/api/signals/journal/{signal_id}/review", method="POST"
    )
    get_endpoint = _endpoint("/api/signals/journal/reviews/{review_id}", method="GET")

    preview = asyncio.run(preview_endpoint(1))
    assert preview["financial_evidence_status"] == "bound"
    assert preview["execution_evidence"]["status"] == "fills_linked"
    assert preview["valuation_snapshot_id"] == published["snapshot_id"]
    assert preview["ledger_cutoff_id"] == published["ledger_cutoff_id"]
    assert preview["contribution_fingerprint"]
    assert "evidence_supported" in preview["allowed_outcomes"]

    request = signal_routes.SignalJournalReviewRequest(
        idempotency_key="review-bound-contribution",
        reviewed_by="portfolio-owner",
        user_decision="acted",
        outcome="evidence_supported",
        note="The acted decision is supported by the exact posted-fill contribution.",
        expected_target_fingerprint=preview["target_fingerprint"],
        confirmation=(
            "record_evidence_bound_decision_review_without_trade_or_capital_authority"
        ),
    )
    result = asyncio.run(review_endpoint(1, request))
    assert result["target_binding_valid"] is True

    db.upsert_latest_quote_sync(
        symbol="510300",
        asset_type="fund",
        price=4.9,
        quote_timestamp="2026-04-18T15:05:00+08:00",
        quote_source="deterministic_fixture",
        provider_name="deterministic_fixture",
        provider_status="ok",
        quote_status="confirmed",
    )
    db.publish_current_valuation_snapshot_sync()
    revalidated = asyncio.run(get_endpoint(result["review"]["review_id"]))
    assert revalidated["target_binding_valid"] is False
    assert revalidated["review"]["stored_target_fingerprint"] == (
        preview["target_fingerprint"]
    )
    assert revalidated["current_target"]["target_fingerprint"] != (
        preview["target_fingerprint"]
    )
