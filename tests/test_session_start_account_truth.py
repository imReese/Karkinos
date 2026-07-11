from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from server.db import AppDatabase
from server.services.session_start_account_truth import (
    SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE,
    SessionStartAccountTruthRejected,
    SessionStartAccountTruthService,
)

NOW = datetime(2026, 7, 11, 3, 30, tzinfo=timezone.utc)


def _source() -> dict:
    return {
        "status": "clear",
        "source_fingerprint": "a" * 64,
        "import_run_id": "account-truth-import-1",
        "captured_at": NOW.isoformat(),
        "data_freshness_status": "fresh",
        "reconciliation_status": "clear",
        "gate_status": "pass",
        "score": 100,
        "cash_status": "pass",
        "position_status": "pass",
        "fee_status": "pass",
        "cost_basis_status": "pass",
        "unresolved_mismatch_count": 0,
        "resolved_review_count": 2,
        "does_not_mutate_production_ledger": True,
        "does_not_issue_execution_authority": True,
        "broker_submission_enabled": False,
        "private_statement_path": "must-not-be-returned",
        "account_id": "must-not-be-returned",
    }


def _service(tmp_path, source: list[dict], current_time: list[datetime]):
    db = AppDatabase(tmp_path / "session-start-account-truth.db")
    db.init_sync()
    return db, SessionStartAccountTruthService(
        db=db,
        account_truth_provider=lambda: source[0],
        clock=lambda: current_time[0],
    )


def _preview(service: SessionStartAccountTruthService) -> dict:
    return service.preview(
        evidence_connector_id="qmt-readonly-session",
        account_alias="qmt-session-review",
    )


def test_session_start_account_truth_preview_is_clear_sanitized_and_read_only(
    tmp_path,
) -> None:
    source = [_source()]
    db, service = _service(tmp_path, source, [NOW])

    preview = _preview(service)
    localized_alias = service.preview(
        evidence_connector_id="qmt-readonly-session",
        account_alias="中信证券88**16",
    )

    assert preview["review_status"] == "ready_to_record"
    assert preview["review_ready"] is True
    assert preview["blockers"] == []
    assert preview["source_freshness_status"] == "fresh"
    assert preview["runtime_session_authority"] == "disabled"
    assert preview["broker_submission_enabled"] is False
    assert preview["authorizes_execution"] is False
    assert "must-not-be-returned" not in json.dumps(preview)
    assert localized_alias["review_ready"] is True
    assert db.list_events_sync(event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE) == []


def test_session_start_account_truth_record_reuses_and_resolves_current_source(
    tmp_path,
) -> None:
    source = [_source()]
    current_time = [NOW]
    db, service = _service(tmp_path, source, current_time)
    preview = _preview(service)

    first = service.record(
        evidence_connector_id="qmt-readonly-session",
        account_alias="qmt-session-review",
        account_truth_fingerprint=preview["account_truth_fingerprint"],
        acknowledgement=SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    )
    rerun = service.record(
        evidence_connector_id="qmt-readonly-session",
        account_alias="qmt-session-review",
        account_truth_fingerprint=preview["account_truth_fingerprint"],
        acknowledgement=SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    )
    current_time[0] = NOW + timedelta(seconds=5)
    resolved = service.resolve(preview["account_truth_fingerprint"])

    assert first["status"] == "recorded_clear"
    assert rerun["event_id"] == first["event_id"]
    assert rerun["reused"] is True
    assert resolved["status"] == "clear"
    assert resolved["source_fingerprint"] == "a" * 64
    assert resolved["runtime_session_authority"] == "disabled"
    assert resolved["authorizes_execution"] is False
    assert (
        len(db.list_events_sync(event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE)) == 1
    )


def test_session_start_account_truth_source_drift_and_expiry_fail_closed(
    tmp_path,
) -> None:
    source = [_source()]
    current_time = [NOW]
    _, service = _service(tmp_path, source, current_time)
    preview = _preview(service)
    service.record(
        evidence_connector_id="qmt-readonly-session",
        account_alias="qmt-session-review",
        account_truth_fingerprint=preview["account_truth_fingerprint"],
        acknowledgement=SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
    )

    source[0] = {**source[0], "source_fingerprint": "b" * 64}
    drifted = service.resolve(preview["account_truth_fingerprint"])
    source[0] = _source()
    current_time[0] = NOW + timedelta(seconds=121)
    expired = service.resolve(preview["account_truth_fingerprint"])

    assert drifted["status"] == "blocked"
    assert drifted["blockers"] == ["account_truth_source_changed"]
    assert expired["status"] == "blocked"
    assert expired["blockers"] == ["account_truth_record_expired"]


def test_session_start_account_truth_gate_and_freshness_fail_closed(tmp_path) -> None:
    source = [
        {
            **_source(),
            "status": "blocked",
            "gate_status": "fail",
            "reconciliation_status": "blocked",
            "unresolved_mismatch_count": 2,
            "captured_at": (NOW - timedelta(seconds=121)).isoformat(),
        }
    ]
    _, service = _service(tmp_path, source, [NOW])

    preview = _preview(service)

    assert "account_truth_status_not_clear" in preview["blockers"]
    assert "account_truth_gate_not_pass" in preview["blockers"]
    assert "account_truth_reconciliation_not_clear" in preview["blockers"]
    assert "account_truth_unresolved_mismatches" in preview["blockers"]
    assert "account_truth_source_stale_for_session_start" in preview["blockers"]
    assert preview["review_ready"] is False
    assert preview["authorizes_execution"] is False


def test_session_start_account_truth_provider_failure_is_sanitized(tmp_path) -> None:
    db = AppDatabase(tmp_path / "session-start-account-truth.db")
    db.init_sync()

    def failed_provider() -> dict:
        raise RuntimeError("private Account Truth detail must not leak")

    service = SessionStartAccountTruthService(
        db=db,
        account_truth_provider=failed_provider,
        clock=lambda: NOW,
    )

    preview = _preview(service)

    assert "account_truth_provider_failed" in preview["blockers"]
    assert "private Account Truth detail must not leak" not in json.dumps(preview)
    assert preview["runtime_session_authority"] == "disabled"


def test_rejected_session_start_account_truth_attempt_is_audited(tmp_path) -> None:
    source = [{**_source(), "gate_status": "fail"}]
    db, service = _service(tmp_path, source, [NOW])
    preview = _preview(service)

    with pytest.raises(SessionStartAccountTruthRejected) as exc_info:
        service.record(
            evidence_connector_id="qmt-readonly-session",
            account_alias="qmt-session-review",
            account_truth_fingerprint=preview["account_truth_fingerprint"],
            acknowledgement=SESSION_START_ACCOUNT_TRUTH_ACKNOWLEDGEMENT,
        )

    evidence = exc_info.value.evidence
    assert evidence["status"] == "rejected"
    assert evidence["rejection_reasons"] == ["session_start_account_truth_blocked"]
    assert evidence["authorizes_execution"] is False
    assert (
        len(db.list_events_sync(event_type=SESSION_START_ACCOUNT_TRUTH_EVENT_TYPE)) == 1
    )
