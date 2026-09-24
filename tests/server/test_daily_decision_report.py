"""Historical daily reports preserve failed, missing, and research-only days."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import pytest

from server.contracts.content_identity import content_fingerprint
from server.services import daily_decision_report as report
from server.services.daily_decision_evidence_identity import (
    daily_candidate_input_fingerprint,
    daily_candidate_record_fingerprint,
)


def _calendar(year: int) -> dict[str, Any]:
    current = date(year, 1, 1)
    days = []
    while current.year == year:
        days.append(
            {"date": current.isoformat(), "is_trading_day": current.weekday() < 5}
        )
        current += timedelta(days=1)
    source = "a" * 64
    return {
        "exchange": "SSE",
        "year": year,
        "days_json": json.dumps(days),
        "trading_day_count": sum(item["is_trading_day"] for item in days),
        "closed_day_count": sum(not item["is_trading_day"] for item in days),
        "source_fingerprint": source,
        "verification_source_fingerprint": source,
        "official_source_fingerprint": "b" * 64,
        "official_source_url": "https://example.test/calendar",
        "official_verified_at": f"{year}-01-01T00:00:00+08:00",
        "official_verified_by": "test",
        "official_verification_status": "verified",
    }


def _run(
    run_type: str,
    status: str,
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    source_ref: str | None = None,
    run_date: str = "2026-09-24",
) -> dict[str, Any]:
    return {
        "run_id": run_id or f"{run_type}:{status}",
        "run_type": run_type,
        "run_date": run_date,
        "status": status,
        "started_at": f"{run_date}T09:36:00+08:00",
        "finished_at": f"{run_date}T09:37:00+08:00",
        "created_at": f"{run_date}T09:36:00+08:00",
        "source_ref": source_ref,
        "payload_json": json.dumps(payload),
    }


class _DB:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calendars = {2026: _calendar(2026)}

    def get_market_calendar_snapshot_sync(
        self, *, exchange: str, year: int
    ) -> dict[str, Any] | None:
        assert exchange == "SSE"
        return self.calendars.get(year)

    def list_automation_runs_sync(
        self, *, run_type: str, run_date: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        assert limit == -1 and offset == 0
        return [
            row
            for row in self.rows
            if row["run_type"] == run_type and row["run_date"] == run_date
        ]


def _scan(
    *,
    status: str = "completed",
    run_id: str = "scan:one",
    signal_id: int = 41,
    action_id: int = 91,
    account_blocked_buys: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    blocked_buys = account_blocked_buys or []
    payload = {
        "status": status,
        "blockers": [],
        "normal_no_signal": status == "completed_no_signal" and not blocked_buys,
        "account_blocked_buys": blocked_buys,
        "market_date": "2026-09-23",
        "receipt_fingerprints": ["receipt:one"],
        "selected_signal_count": 1 if status == "completed" else 0,
        "selected_signals": (
            [
                {
                    "symbol": "600869",
                    "direction": "buy",
                    "strategy_id": "strategy:one",
                    "frozen_close": 22.03,
                    "frozen_market_date": "2026-09-23",
                }
            ]
            if status == "completed"
            else []
        ),
        "action_tasks": (
            [{"source_signal_id": signal_id, "action_id": action_id}]
            if status == "completed"
            else []
        ),
    }
    payload["raw_signals"] = [
        *payload["selected_signals"],
        *[
            {
                "symbol": item["symbol"],
                "strategy_id": item["strategy_id"],
                "direction": "buy",
                "frozen_close": 66.0,
                "frozen_market_date": "2026-09-23",
            }
            for item in blocked_buys
        ],
    ]
    payload["raw_signal_count"] = len(payload["raw_signals"])
    payload["output_fingerprint"] = "sha256:" + content_fingerprint(payload)
    return _run("promoted_strategy_universe_scan", status, payload, run_id=run_id)


def _evidence(
    *,
    outcome: str,
    action_ids: list[int],
    scan_run_id: str | None = "scan:one",
    gate_status: str = "pass",
) -> dict[str, Any]:
    payload = {
        "decision_outcome": outcome,
        "production_gate": {
            "status": gate_status,
            "blockers": [] if gate_status == "pass" else ["account_truth_blocked"],
        },
        "input_snapshot": {"promoted_strategy_scan_run_id": scan_run_id},
        "promoted_strategy_scan_run_id": scan_run_id,
        "manual_order_ticket_candidates": [
            {"action_id": action_id} for action_id in action_ids
        ],
        "no_action_reasons": [] if action_ids else ["no_strategy_action"],
    }
    payload["input_fingerprint"] = daily_candidate_input_fingerprint(payload)
    payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
        payload
    )
    return _run(
        "daily_decision_evidence",
        "paper_shadow_completed" if action_ids else "no_candidates",
        payload,
        run_id="daily:one",
    )


def _attempt(
    *,
    outcome: str = "manual_order_ticket_candidate",
    scan_run_id: str | None = "scan:one",
) -> dict[str, Any]:
    return _run(
        "daily_candidate_background_attempt",
        "completed",
        {
            "result_run_id": "daily:one",
            "decision_outcome": outcome,
            "promoted_strategy_scan_run_id": scan_run_id,
        },
        run_id="attempt:one",
        source_ref="daily:one",
    )


def test_missing_market_day_remains_visible_without_a_run(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB()

    index = report.list_daily_decision_reports(db, limit=2, as_of=date(2026, 9, 24))

    assert index["status"] == "complete"
    assert [item["report_date"] for item in index["reports"]] == [
        "2026-09-24",
        "2026-09-23",
    ]
    assert all(item["status"] == "missing_run" for item in index["reports"])
    assert index["calendar_evidence_refs"]


def test_failed_attempt_exposes_stage_without_claiming_no_signal(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    failed = _run(
        "daily_candidate_background_attempt",
        "failed_closed",
        {
            "failure_stage": "portfolio_snapshot",
            "failure_code": "market_revision_conflict",
            "error_type": "PortfolioReadSnapshotRejected",
            "evidence_refs": ["snapshot:42"],
        },
    )

    daily = report.get_daily_decision_report(_DB([failed]), "2026-09-24")

    assert daily["status"] == "failed"
    assert daily["attempts"][0]["failure_stage"] == "portfolio_snapshot"
    assert daily["attempts"][0]["evidence_refs"] == ["snapshot:42"]
    assert daily["authoritative_candidate_count"] == 0


def test_orphan_scan_is_visible_but_not_a_completed_daily_report(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})

    daily = report.get_daily_decision_report(_DB([_scan()]), "2026-09-24")

    assert daily["status"] == "missing_run"
    assert daily["scans"][0]["run_id"] == "scan:one"
    assert daily["candidates"][0]["signal_id"] == 41
    assert daily["candidates"][0]["report_authoritative"] is False
    assert "promoted_scan_without_daily_attempt" in daily["reason_codes"]


def test_older_scan_without_raw_signal_details_keeps_its_valid_selected_signal(
    monkeypatch,
) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    scan = _scan()
    payload = json.loads(scan["payload_json"])
    payload.pop("raw_signals")
    payload["raw_signal_count"] = 17
    payload.pop("output_fingerprint")
    payload["output_fingerprint"] = "sha256:" + content_fingerprint(payload)
    scan["payload_json"] = json.dumps(payload)

    daily = report.get_daily_decision_report(_DB([scan]), "2026-09-24")

    assert daily["scans"][0]["integrity_valid"] is True
    assert daily["candidates"][0]["symbol"] == "600869"
    assert daily["candidates"][0]["report_authoritative"] is False


def test_exact_completed_chain_identifies_formal_candidate(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(),
            _evidence(outcome="manual_order_ticket_candidate", action_ids=[91]),
            _attempt(),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "formal_candidate"
    assert daily["authoritative_candidate_count"] == 1
    assert daily["candidates"][0]["report_authoritative"] is True
    assert daily["candidates"][0]["frozen_price"] == 22.03
    assert daily["candidates"][0]["source_ref"] == "scan:one:signal:41"


def test_old_unbound_scan_cannot_become_formal_even_with_unique_action(
    monkeypatch,
) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(run_id="scan:one"),
            _evidence(
                outcome="manual_order_ticket_candidate",
                action_ids=[91],
                scan_run_id=None,
            ),
            _attempt(scan_run_id=None),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "blocked"
    assert daily["authoritative_candidate_count"] == 0
    assert daily["candidates"][0]["report_authoritative"] is False
    assert "final_scan_linkage_missing" in daily["reason_codes"]


def test_exact_scan_binding_selects_only_its_candidate_across_scans(
    monkeypatch,
) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(run_id="scan:one"),
            _scan(run_id="scan:two"),
            _evidence(outcome="manual_order_ticket_candidate", action_ids=[91]),
            _attempt(),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "formal_candidate"
    assert daily["authoritative_candidate_count"] == 1
    assert [
        (item["scan_run_id"], item["report_authoritative"])
        for item in daily["candidates"]
    ] == [
        ("scan:one", True),
        ("scan:two", False),
    ]


@pytest.mark.parametrize(
    "conflict", ["top_level_scan", "attempt_scan", "input_fingerprint"]
)
def test_conflicting_final_chain_cannot_create_formal_candidate(
    monkeypatch, conflict: str
) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    evidence = _evidence(outcome="manual_order_ticket_candidate", action_ids=[91])
    attempt = _attempt()
    if conflict == "top_level_scan":
        payload = json.loads(evidence["payload_json"])
        payload["promoted_strategy_scan_run_id"] = "scan:two"
        evidence["payload_json"] = json.dumps(payload)
    elif conflict == "attempt_scan":
        payload = json.loads(attempt["payload_json"])
        payload["promoted_strategy_scan_run_id"] = "scan:two"
        attempt["payload_json"] = json.dumps(payload)
    else:
        payload = json.loads(evidence["payload_json"])
        payload["input_fingerprint"] = "stale"
        payload["production_record_fingerprint"] = daily_candidate_record_fingerprint(
            payload
        )
        evidence["payload_json"] = json.dumps(payload)

    daily = report.get_daily_decision_report(
        _DB([_scan(), evidence, attempt]), "2026-09-24"
    )

    assert daily["status"] == "blocked"
    assert daily["authoritative_candidate_count"] == 0
    assert daily["candidates"][0]["report_authoritative"] is False


def test_verified_completed_no_signal_is_distinct_from_missing_run(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(status="completed_no_signal"),
            _evidence(outcome="no_action", action_ids=[]),
            _attempt(outcome="no_action"),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "completed_no_signal"
    assert daily["candidates"] == []


def test_no_signal_with_blocked_production_gate_remains_blocked(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(status="completed_no_signal"),
            _evidence(outcome="no_action", action_ids=[], gate_status="blocked"),
            _attempt(outcome="no_action"),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "blocked"
    assert daily["authoritative_candidate_count"] == 0


def test_account_blocked_buy_is_not_normal_no_signal(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB(
        [
            _scan(
                status="completed_no_signal",
                account_blocked_buys=[
                    {
                        "symbol": "301251",
                        "strategy_id": "strategy:one",
                        "board": "chinext",
                        "reason": "board_permission_disabled",
                    }
                ],
            ),
            _evidence(outcome="no_action", action_ids=[]),
            _attempt(outcome="no_action"),
        ]
    )

    daily = report.get_daily_decision_report(db, "2026-09-24")

    assert daily["status"] == "blocked"
    assert daily["scans"][0]["account_blocked_buys"][0]["symbol"] == "301251"
    assert daily["blocked_signals"][0]["frozen_price"] == 66.0
    assert daily["blocked_signals"][0]["source_bound"] is True
    assert daily["blocked_signals"][0]["report_authoritative"] is False
    assert (
        "account_buy_blocked:301251:board_permission_disabled" in daily["reason_codes"]
    )


def test_unverified_calendar_cannot_create_history(monkeypatch) -> None:
    monkeypatch.setattr(report, "_research_by_date", lambda _db, _dates: {})
    db = _DB()
    db.calendars = {}

    index = report.list_daily_decision_reports(db, as_of=date(2026, 9, 24))

    assert index["status"] == "unavailable"
    assert index["reports"] == []
    with pytest.raises(LookupError, match="verified market calendar unavailable"):
        report.get_daily_decision_report(db, "2026-09-24")


def test_research_preview_does_not_change_generation_status(monkeypatch) -> None:
    preview = {
        "run_id": "research:one",
        "selection_id": "selection:one",
        "status": "no_selection",
        "research_only": True,
        "operations": [
            {"symbol": "301251", "operation": "buy_candidate", "research_only": True}
        ],
    }
    monkeypatch.setattr(
        report,
        "_research_by_date",
        lambda _db, _dates: {"2026-09-24": [preview]},
    )

    daily = report.get_daily_decision_report(_DB(), "2026-09-24")

    assert daily["status"] == "missing_run"
    assert daily["research_previews"][0]["operations"][0]["symbol"] == "301251"
    assert daily["authoritative_candidate_count"] == 0
