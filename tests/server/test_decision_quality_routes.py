"""Deterministic tests for the evidence-bound Decision Quality Score."""

from __future__ import annotations

import asyncio
import copy
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from server.db import AppDatabase
from server.routes import decision as decision_routes
from server.services.decision_quality import build_decision_quality_target


def _endpoint(path: str, method: str = "GET"):
    router = decision_routes.create_router()
    return next(
        route.endpoint
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    )


def _candidate() -> dict:
    return {
        "action_id": 11,
        "action": "buy",
        "symbol": "510300",
        "target_weight": 0.2,
        "evidence": {
            "signal": {"id": 7, "strategy_id": "quality_fixture"},
            "risk_gate": {
                "status": "passed",
                "decision_id": "RISK-QUALITY-1",
                "passed": True,
            },
            "after_cost_oos_validation": {
                "status": "attached",
                "backtest_result_id": 42,
                "oos_validation": {
                    "benchmark_role": "csi_300_total_return",
                    "benchmark_return": 0.01,
                    "passed_benchmark": True,
                    "validation_status": "benchmark_passed",
                },
            },
            "data_freshness": {
                "status": "confirmed",
                "quote_timestamp": "2026-07-17T15:00:00+08:00",
            },
            "journal": {
                "has_journal_entry": True,
                "latest_event_type": "risk.signal.recorded",
            },
        },
    }


def _decision_payload(*, candidates: list[dict] | None = None) -> dict:
    resolved_candidates = [_candidate()] if candidates is None else candidates
    return {
        "lane": "daily",
        "decision_date": "2026-07-17",
        "generated_at": "2026-07-17T15:01:00+08:00",
        "decision": "buy" if resolved_candidates else "no_action",
        "summary": {
            "candidate_count": len(resolved_candidates),
            "portfolio": {
                "status": "available",
                "fact_authority": "persisted_valuation_snapshot",
                "valuation_snapshot_id": "valuation-quality-fixture",
                "valuation_status": "complete",
                "ledger_cutoff_id": 17,
                "ledger_fingerprint": "ledger-quality-fixture",
                "quote_set_fingerprint": "quotes-quality-fixture",
            },
            "market_data": {"source_health": "confirmed"},
            "account_truth": {"gate_status": "pass", "has_evidence": True},
        },
        "candidates": resolved_candidates,
        "no_action_reasons": [] if resolved_candidates else ["no_pending_actions"],
    }


def _capture_body(target_fingerprint: str, *, key: str = "quality-capture-001"):
    return decision_routes.DecisionQualityCaptureBody(
        idempotency_key=key,
        captured_by="portfolio-owner",
        expected_target_fingerprint=target_fingerprint,
        confirmation=(
            "capture_decision_quality_evidence_without_financial_or_trading_authority"
        ),
    )


def test_quality_target_requires_all_five_north_star_dimensions() -> None:
    target = build_decision_quality_target(_decision_payload())

    assert target.qualified is True
    assert target.diagnostic_score_percent == 100
    assert [item.name for item in target.dimensions] == [
        "data_complete",
        "risk_checked",
        "benchmark_aware",
        "journaled",
        "later_reviewable",
    ]
    assert target.valuation_snapshot_id == "valuation-quality-fixture"
    assert target.ledger_cutoff_id == 17
    assert target.to_dict()["provider_contacted"] is False
    assert target.to_dict()["authorizes_execution"] is False

    incomplete = _decision_payload()
    incomplete["candidates"][0]["evidence"]["risk_gate"] = {
        "status": "not_checked",
        "decision_id": None,
    }
    incomplete["candidates"][0]["evidence"]["after_cost_oos_validation"][
        "oos_validation"
    ]["benchmark_return"] = None
    incomplete["summary"]["account_truth"]["gate_status"] = "blocked"
    blocked = build_decision_quality_target(incomplete)

    assert blocked.qualified is False
    assert blocked.diagnostic_score_percent == 40
    assert {
        blocker for dimension in blocked.dimensions for blocker in dimension.blockers
    } >= {
        "account_truth_gate_not_passed",
        "pre_trade_risk_evidence_incomplete",
        "benchmark_evidence_incomplete",
    }


def test_quality_target_rejects_unbound_or_estimated_financial_evidence() -> None:
    payload = _decision_payload()
    payload["summary"]["portfolio"]["ledger_cutoff_id"] = 0
    payload["candidates"][0]["evidence"]["data_freshness"].update(
        {
            "status": "live",
            "quote_source": "eastmoney_fund_estimate",
        }
    )

    target = build_decision_quality_target(payload)
    data_dimension = next(
        item for item in target.dimensions if item.name == "data_complete"
    )

    assert target.qualified is False
    assert data_dimension.status == "blocked"
    assert set(data_dimension.blockers) >= {
        "ledger_cutoff_missing",
        "candidate_data_not_complete",
    }
    assert data_dimension.evidence["incomplete_candidates"] == ["11:510300"]


def test_no_action_day_is_reviewable_without_fake_risk_or_benchmark() -> None:
    target = build_decision_quality_target(_decision_payload(candidates=[]))
    by_name = {item.name: item for item in target.dimensions}

    assert target.qualified is True
    assert by_name["risk_checked"].status == "not_applicable_no_action"
    assert by_name["benchmark_aware"].status == ("not_applicable_no_strategy_action")
    assert by_name["journaled"].status == "satisfied_by_daily_capture"
    assert by_name["later_reviewable"].status == (
        "satisfied_by_content_addressed_capture"
    )


def test_quality_get_is_read_only_and_capture_is_restart_safe_and_idempotent(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    payload = _decision_payload()
    state = SimpleNamespace(db=db)

    async def current_payload(_state):
        return copy.deepcopy(payload)

    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    monkeypatch.setattr(decision_routes, "_today_decision_payload", current_payload)
    get_quality = _endpoint("/api/decision/quality")
    capture_quality = _endpoint("/api/decision/quality/capture", method="POST")

    with sqlite3.connect(db._path) as conn:
        before = {
            "quality": conn.execute(
                "SELECT COUNT(*) FROM decision_quality_snapshots"
            ).fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0],
            "ledger": conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0],
            "risk": conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0],
            "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        }

    preview = asyncio.run(get_quality())
    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM decision_quality_snapshots").fetchone()[
                0
            ]
            == before["quality"]
        )
        assert conn.execute("SELECT COUNT(*) FROM event_log").fetchone()[0] == (
            before["events"]
        )

    request = _capture_body(preview["current_target"]["target_fingerprint"])
    first = asyncio.run(capture_quality(request))
    second = asyncio.run(capture_quality(request))

    assert first["capture"]["snapshot_id"] == second["capture"]["snapshot_id"]
    assert first["reused"] is False
    assert second["reused"] is True
    assert first["target_binding_valid"] is True
    assert first["audit_replay"]["valid"] is True
    assert first["report"]["score_percent"] == 100
    assert first["report"]["evaluated_day_count"] == 1
    assert first["does_not_mutate_financial_state"] is True
    assert first["authorizes_execution"] is False

    with sqlite3.connect(db._path) as conn:
        assert (
            conn.execute("SELECT COUNT(*) FROM decision_quality_snapshots").fetchone()[
                0
            ]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM event_log "
                "WHERE source = 'decision_quality_snapshots'"
            ).fetchone()[0]
            == 1
        )
        assert conn.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0] == (
            before["ledger"]
        )
        assert conn.execute("SELECT COUNT(*) FROM risk_decisions").fetchone()[0] == (
            before["risk"]
        )
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == (
            before["orders"]
        )


def test_quality_capture_rejects_drift_and_latest_day_replaces_old_score(
    monkeypatch, tmp_path
) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    payload = _decision_payload()
    state = SimpleNamespace(db=db)

    async def current_payload(_state):
        return copy.deepcopy(payload)

    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    monkeypatch.setattr(decision_routes, "_today_decision_payload", current_payload)
    get_quality = _endpoint("/api/decision/quality")
    capture_quality = _endpoint("/api/decision/quality/capture", method="POST")

    initial = asyncio.run(get_quality())
    asyncio.run(
        capture_quality(_capture_body(initial["current_target"]["target_fingerprint"]))
    )
    payload["summary"]["account_truth"]["gate_status"] = "blocked"

    with pytest.raises(HTTPException) as drift:
        asyncio.run(
            capture_quality(
                _capture_body(
                    initial["current_target"]["target_fingerprint"],
                    key="quality-capture-drift",
                )
            )
        )
    assert drift.value.status_code == 409

    current = asyncio.run(get_quality())
    assert current["current_binding_valid"] is False
    blocked = asyncio.run(
        capture_quality(
            _capture_body(
                current["current_target"]["target_fingerprint"],
                key="quality-capture-blocked",
            )
        )
    )
    assert blocked["capture"]["qualified"] is False
    assert blocked["report"]["evaluated_day_count"] == 1
    assert blocked["report"]["total_capture_count"] == 2
    assert blocked["report"]["score_percent"] == 0
    assert blocked["report"]["latest_by_day"][0]["snapshot_id"] == (
        blocked["capture"]["snapshot_id"]
    )


def test_quality_replay_detects_target_tampering(monkeypatch, tmp_path) -> None:
    db = AppDatabase(tmp_path / "app.db")
    db.init_sync()
    payload = _decision_payload()
    state = SimpleNamespace(db=db)

    async def current_payload(_state):
        return copy.deepcopy(payload)

    monkeypatch.setattr("server.app.get_app_state", lambda: state)
    monkeypatch.setattr(decision_routes, "_today_decision_payload", current_payload)
    get_quality = _endpoint("/api/decision/quality")
    capture_quality = _endpoint("/api/decision/quality/capture", method="POST")
    replay_quality = _endpoint("/api/decision/quality/snapshots/{snapshot_id}/replay")

    preview = asyncio.run(get_quality())
    result = asyncio.run(
        capture_quality(_capture_body(preview["current_target"]["target_fingerprint"]))
    )
    snapshot_id = result["capture"]["snapshot_id"]
    assert asyncio.run(replay_quality(snapshot_id))["valid"] is True

    with sqlite3.connect(db._path) as conn:
        conn.execute(
            "UPDATE decision_quality_snapshots SET target_json = '{}' "
            "WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        conn.commit()
    replay = asyncio.run(replay_quality(snapshot_id))
    assert replay["valid"] is False
    assert "target_fingerprint_mismatch" in replay["errors"]
    assert "target_document_fingerprint_mismatch" in replay["errors"]
