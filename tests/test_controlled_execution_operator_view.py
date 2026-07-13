from __future__ import annotations

import json
from datetime import datetime, timezone

from server.db import AppDatabase
from server.services.controlled_execution_operator_view import (
    ControlledExecutionOperatorViewService,
)


class _PersistedFactFixture:
    def __init__(self, *, paused: bool = False) -> None:
        self.calls: list[str] = []
        self.paused = paused
        self.session_id = "a" * 64
        self.reservation_id = "b" * 64

    def list_controlled_session_runtime_sessions_sync(self, *, limit: int):
        self.calls.append("sessions")
        return [
            {
                "id": 1,
                "session_id": self.session_id,
                "session_fingerprint": "c" * 64,
                "reservation_id": self.reservation_id,
                "authorization_id": "AUTH-LOCAL-1",
                "account_alias": "local-review",
                "strategy_id": "fixture-strategy",
                "effective_at": "2026-07-13T09:00:00+00:00",
                "expires_at": "2026-07-13T11:00:00+00:00",
                "status": "enabled",
                "token_salt": "private-salt-must-not-leak",
                "token_hash": "private-hash-must-not-leak",
                "payload_json": "{}",
                "created_at": "2026-07-13T08:59:00+00:00",
            }
        ]

    def list_controlled_session_budget_reservations_sync(self, *, limit: int):
        self.calls.append("reservations")
        return [
            {
                "id": 1,
                "reservation_id": self.reservation_id,
                "status": "reserved",
                "payload_json": json.dumps(
                    {
                        "reserved_budget": {
                            "gross_order_value": "30000.00",
                            "buy_value": "20000.00",
                            "daily_turnover_value": "30000.00",
                            "order_count": 2,
                            "by_symbol": {"510300": "30000.00"},
                        },
                        "reservation_capacity": {
                            "capital_value": "100000.00",
                            "cash_value": "80000.00",
                            "daily_turnover_value": "120000.00",
                            "order_count": 4,
                            "by_symbol": {"510300": "50000.00"},
                        },
                    },
                    sort_keys=True,
                ),
            }
        ]

    def list_controlled_session_rate_admissions_sync(self, *, limit: int):
        self.calls.append("admissions")
        return [
            {
                "id": 1,
                "admission_id": "d" * 64,
                "session_id": self.session_id,
                "order_id": "OMS-FIXTURE-1",
                "admitted_at_epoch_ms": 1783936795000,
                "admitted_at": "2026-07-13T09:59:55+00:00",
                "status": "admitted",
            }
        ]

    def list_controlled_session_gate_snapshots_sync(self, *, limit: int):
        self.calls.append("gate_snapshots")
        return [
            {
                "id": 1,
                "snapshot_id": "e" * 64,
                "session_id": self.session_id,
                "observed_at_epoch_ms": 1783936790000,
                "observed_at": "2026-07-13T09:59:50+00:00",
                "status": "clear",
                "blockers_json": "[]",
            }
        ]

    def list_controlled_broker_submit_intents_sync(self, *, limit: int):
        self.calls.append("submission_intents")
        return []

    def list_execution_reconciliation_runs_sync(self, *, limit: int):
        self.calls.append("reconciliation_runs")
        return [
            {
                "run_id": "execution-reconciliation:2026-07-13",
                "run_date": "2026-07-13",
                "status": "clear",
                "item_count": 1,
                "open_item_count": 0,
                "updated_at": "2026-07-13T09:59:58+00:00",
            }
        ]

    def list_execution_reconciliation_items_sync(self, run_id: str):
        self.calls.append(f"reconciliation_items:{run_id}")
        return [
            {
                "order_id": "OMS-FIXTURE-1",
                "item_status": "matched",
                "suggested_action": "no_action",
            }
        ]

    def get_controlled_session_runtime_state_sync(self, session_id: str):
        self.calls.append(f"pause_state:{session_id}")
        if not self.paused:
            return None
        return {
            "session_id": self.session_id,
            "status": "paused",
            "pause_event_id": "f" * 64,
            "paused_at": "2026-07-13T09:59:59+00:00",
            "reasons_json": json.dumps(["kill_switch_enabled"]),
        }


def test_operator_view_projects_bounded_capital_and_remaining_slots_without_provider_call():
    db = _PersistedFactFixture()

    summary = ControlledExecutionOperatorViewService(
        db=db,
        clock=lambda: datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
    ).summary()

    assert summary["status"] == "clear_read_only_evidence"
    assert summary["provider_contact_performed"] is False
    assert summary["runtime_connector_query_performed"] is False
    assert summary["broker_submission_enabled"] is False
    assert summary["authority_issue_enabled"] is False
    session = summary["sessions"][0]
    assert session["status"] == "current_clear_evidence"
    assert session["authorized_capital"] == "100000.00"
    assert session["effective_capital_at_risk"] == "30000.00"
    assert session["remaining_budget"] == {
        "capital_headroom": "70000.00",
        "cash_headroom": "60000.00",
        "turnover_headroom": "90000.00",
        "remaining_order_slots": 1,
        "reserved_order_count": 2,
        "admitted_order_count": 1,
    }
    assert session["last_order"]["order_id"] == "OMS-FIXTURE-1"
    assert session["last_reconciliation"]["suggested_action"] == "no_action"
    serialized = json.dumps(summary, sort_keys=True)
    assert "private-salt-must-not-leak" not in serialized
    assert "private-hash-must-not-leak" not in serialized
    assert db.calls == [
        "sessions",
        "reservations",
        "admissions",
        "gate_snapshots",
        "submission_intents",
        "reconciliation_runs",
        "reconciliation_items:execution-reconciliation:2026-07-13",
        f"pause_state:{db.session_id}",
    ]


def test_operator_view_surfaces_pause_reason_without_resume_authority():
    db = _PersistedFactFixture(paused=True)

    summary = ControlledExecutionOperatorViewService(
        db=db,
        clock=lambda: datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
    ).summary()

    assert summary["status"] == "blocked"
    session = summary["sessions"][0]
    assert session["status"] == "paused"
    assert session["pause"]["reasons"] == ["kill_switch_enabled"]
    assert session["pause"]["resume_available"] is False
    assert session["pause"]["replacement_review_required"] is True
    assert "runtime_session_paused" in session["blockers"]
    assert summary["authority_resume_enabled"] is False


def test_operator_view_empty_database_stays_default_closed(tmp_path):
    db = AppDatabase(tmp_path / "controlled-operator-view.db")
    db.init_sync()

    summary = ControlledExecutionOperatorViewService(db=db).summary()

    assert summary["status"] == "no_session_evidence"
    assert summary["sessions"] == []
    assert summary["next_operator_action"] == "no_action_default_disabled"
    assert summary["broker_submission_enabled"] is False
    assert summary["broker_cancel_enabled"] is False
    assert summary["automatic_scale_up_enabled"] is False


def test_operator_view_unavailable_persisted_sources_fail_closed():
    summary = ControlledExecutionOperatorViewService(db=object()).summary()

    assert summary["status"] == "blocked"
    assert summary["next_operator_action"] == "review_controlled_execution_blockers"
    assert "runtime_session_source_unavailable" in summary["source_blockers"]
    assert (
        "execution_reconciliation_item_source_unavailable" in summary["source_blockers"]
    )
    assert summary["sessions"] == []
    assert summary["provider_contact_performed"] is False
    assert summary["broker_submission_enabled"] is False
