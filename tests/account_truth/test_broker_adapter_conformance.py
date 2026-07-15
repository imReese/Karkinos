from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
    BrokerAdapterConformanceRejected,
    BrokerAdapterConformanceRepository,
    preview_broker_adapter_conformance_result,
)
from account_truth.broker_adapter_conformance_fixtures import (
    run_deterministic_broker_adapter_conformance,
)
from account_truth.broker_adapter_release import (
    BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    BrokerAdapterReleaseRejected,
    BrokerAdapterReleaseReviewRepository,
)
from tests.account_truth.test_broker_adapter_release import (
    REVIEWED_AT,
    collector_binding,
    preview_manifest,
)


def conformance_preview(
    *,
    run_id: str = "deterministic-conformance-v1",
) -> dict:
    return run_deterministic_broker_adapter_conformance(
        preview_manifest(),
        run_id=run_id,
    )


def result_payload(preview: dict) -> dict:
    return {
        "schema_version": BROKER_ADAPTER_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": preview["run_id"],
        "release_evidence_ref": preview["release_evidence_ref"],
        "manifest_fingerprint": preview["manifest_fingerprint"],
        "suite_version": preview["suite_version"],
        "fixture_kind": preview["fixture_kind"],
        "scenarios": deepcopy(preview["scenarios"]),
        "provider_contacted": False,
        "adapter_registered": False,
        "broker_write_contacted": False,
    }


def failed_conformance_preview(*, run_id: str) -> dict:
    payload = result_payload(conformance_preview(run_id=run_id))
    payload["scenarios"][0]["observed_status"] = "unexpected"
    return preview_broker_adapter_conformance_result(payload)


def record_conformance(
    repository: BrokerAdapterConformanceRepository,
    preview: dict,
) -> dict:
    return repository.record_report(
        preview,
        acknowledgement=BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    )


def test_suite_runs_exact_provider_neutral_scenarios_and_passes() -> None:
    preview = conformance_preview()
    replay = conformance_preview(run_id="deterministic-conformance-v1-replay")

    assert preview["validation_status"] == "passed"
    assert preview["recordable"] is True
    assert len(preview["scenarios"]) == 12
    assert {item["scenario"] for item in preview["scenarios"]} == {
        "healthy_snapshot",
        "disconnected_snapshot",
        "stale_snapshot",
        "permission_limited_snapshot",
        "incomplete_snapshot",
        "snapshot_schema_drift",
        "lifecycle_idempotent_replay",
        "lifecycle_duplicate",
        "lifecycle_out_of_order",
        "lifecycle_disconnect",
        "lifecycle_partial_batch",
        "lifecycle_restart_replay",
    }
    assert all(
        item["observed_status"] == item["expected_status"]
        for item in preview["scenarios"]
    )
    assert replay["scenarios"] == preview["scenarios"]
    assert preview["deterministic_local"] is True
    assert preview["provider_contacted"] is False
    assert preview["adapter_registered"] is False
    assert preview["broker_write_contacted"] is False
    assert preview["authorizes_execution"] is False


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "expectation"])
def test_scenario_set_and_expected_outcomes_are_strict(mutation: str) -> None:
    payload = result_payload(conformance_preview())
    if mutation == "missing":
        payload["scenarios"].pop()
    elif mutation == "duplicate":
        payload["scenarios"].append(deepcopy(payload["scenarios"][0]))
    else:
        payload["scenarios"][0]["expected_status"] = "blocked"

    preview = preview_broker_adapter_conformance_result(payload)

    assert preview["recordable"] is False
    assert preview["validation_status"] == "blocked"
    assert preview["record_blockers"]


def test_unknown_and_sensitive_fields_are_rejected_without_value_echo() -> None:
    payload = result_payload(conformance_preview())
    payload["api_token"] = "must-never-enter-conformance-evidence"

    preview = preview_broker_adapter_conformance_result(payload)

    assert preview["recordable"] is False
    assert "broker_adapter_conformance_auth_material_not_allowed" in (
        preview["record_blockers"]
    )
    assert "must-never-enter-conformance-evidence" not in json.dumps(preview)


def test_explicit_record_is_idempotent_restart_safe_and_latest_failure_wins(
    tmp_path,
) -> None:
    db_path = tmp_path / "conformance.db"
    repository = BrokerAdapterConformanceRepository(db_path)
    passed_preview = conformance_preview()

    first = record_conformance(repository, passed_preview)
    replay = record_conformance(repository, passed_preview)
    with pytest.raises(BrokerAdapterConformanceRejected) as conflict:
        record_conformance(
            repository,
            failed_conformance_preview(run_id=passed_preview["run_id"]),
        )
    restarted = BrokerAdapterConformanceRepository(db_path, ensure_schema=False)
    clear = restarted.verify_release_binding(
        release_evidence_ref=passed_preview["release_evidence_ref"],
        manifest_fingerprint=passed_preview["manifest_fingerprint"],
    )
    failed = record_conformance(
        repository,
        failed_conformance_preview(run_id="deterministic-conformance-v2-failed"),
    )
    blocked = restarted.verify_release_binding(
        release_evidence_ref=passed_preview["release_evidence_ref"],
        manifest_fingerprint=passed_preview["manifest_fingerprint"],
    )

    assert first["status"] == "passed"
    assert first["persisted"] is True
    assert replay["reused"] is True
    assert "broker_adapter_conformance_run_id_conflict" in (
        conflict.value.evidence["blockers"]
    )
    assert clear["status"] == "clear"
    assert failed["status"] == "blocked"
    assert blocked["status"] == "blocked"
    assert "broker_adapter_conformance_latest_report_not_passed" in (
        blocked["blockers"]
    )


def test_manifest_drift_and_report_tampering_fail_closed(tmp_path) -> None:
    db_path = tmp_path / "conformance.db"
    repository = BrokerAdapterConformanceRepository(db_path)
    preview = conformance_preview()
    record_conformance(repository, preview)

    drifted = repository.verify_release_binding(
        release_evidence_ref=preview["release_evidence_ref"],
        manifest_fingerprint="e" * 64,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE broker_adapter_conformance_reports
            SET report_json = '{}'
            WHERE run_id = ?
            """,
            (preview["run_id"],),
        )
        conn.commit()
    tampered = repository.verify_release_binding(
        release_evidence_ref=preview["release_evidence_ref"],
        manifest_fingerprint=preview["manifest_fingerprint"],
    )

    assert "broker_adapter_conformance_manifest_mismatch" in drifted["blockers"]
    assert "broker_adapter_conformance_report_integrity_invalid" in (
        tampered["blockers"]
    )
    assert "broker_adapter_conformance_report_structure_invalid" in (
        tampered["blockers"]
    )


def test_wrong_acknowledgement_and_read_only_lookup_have_no_report(tmp_path) -> None:
    absent_path = tmp_path / "absent.db"
    read_only = BrokerAdapterConformanceRepository(absent_path, ensure_schema=False)

    assert read_only.get_latest("fixture-release-reviewed-v1")["status"] == (
        "not_configured"
    )
    assert absent_path.exists() is False

    repository = BrokerAdapterConformanceRepository(tmp_path / "record.db")
    with pytest.raises(BrokerAdapterConformanceRejected) as rejected:
        repository.record_report(conformance_preview(), acknowledgement="")
    assert "broker_adapter_conformance_acknowledgement_mismatch" in (
        rejected.value.evidence["blockers"]
    )
    assert repository.get_latest("fixture-release-reviewed-v1")["status"] == (
        "not_found"
    )


def test_release_acceptance_requires_and_exactly_binds_latest_conformance(
    tmp_path,
) -> None:
    db_path = tmp_path / "release.db"
    release_repository = BrokerAdapterReleaseReviewRepository(db_path)
    release_preview = preview_manifest()

    with pytest.raises(BrokerAdapterReleaseRejected) as missing:
        release_repository.record_review(
            release_preview,
            review_id="release-review-without-conformance",
            decision="accepted",
            reviewer_ref="fixture-human-reviewer",
            reviewed_at=REVIEWED_AT,
            reason_ref="fixture-review-approved",
            acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
        )
    assert "broker_adapter_release_conformance_blocked" in (
        missing.value.evidence["blockers"]
    )

    conformance_repository = BrokerAdapterConformanceRepository(db_path)
    first_conformance = conformance_preview(run_id="release-conformance-v1")
    record_conformance(conformance_repository, first_conformance)
    accepted = release_repository.record_review(
        release_preview,
        review_id="release-review-with-conformance-v1",
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at=REVIEWED_AT,
        reason_ref="fixture-review-approved",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    clear = release_repository.verify_collector_binding(collector_binding())

    assert accepted["conformance_run_id"] == first_conformance["run_id"]
    assert clear["status"] == "clear"

    second_conformance = conformance_preview(run_id="release-conformance-v2")
    record_conformance(conformance_repository, second_conformance)
    drifted = release_repository.verify_collector_binding(collector_binding())
    assert drifted["status"] == "blocked"
    assert "broker_adapter_release_conformance_review_drift" in drifted["blockers"]

    reaccepted = release_repository.record_review(
        release_preview,
        review_id="release-review-with-conformance-v2",
        decision="accepted",
        reviewer_ref="fixture-human-reviewer",
        reviewed_at="2026-07-15T09:00:00+00:00",
        reason_ref="fixture-conformance-rereviewed",
        acknowledgement=BROKER_ADAPTER_RELEASE_REVIEW_ACKNOWLEDGEMENT,
    )
    assert reaccepted["conformance_run_id"] == second_conformance["run_id"]
    assert (
        release_repository.verify_collector_binding(collector_binding())["status"]
        == "clear"
    )


def test_conformance_table_cannot_mutate_trading_domains(tmp_path) -> None:
    db_path = tmp_path / "conformance.db"
    repository = BrokerAdapterConformanceRepository(db_path)
    record_conformance(repository, conformance_preview())

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "broker_adapter_conformance_reports" in tables
    assert "oms_orders" not in tables
    assert "fills" not in tables
    assert "ledger_entries" not in tables
    assert "risk_decisions" not in tables
    assert "capital_authorizations" not in tables


def test_release_review_schema_adds_explicit_conformance_binding_columns(
    tmp_path,
) -> None:
    db_path = tmp_path / "pre-conformance-release.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE broker_adapter_release_review_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id TEXT NOT NULL UNIQUE,
                release_evidence_ref TEXT NOT NULL,
                manifest_fingerprint TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer_ref TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                reason_ref TEXT NOT NULL,
                review_fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        conn.commit()

    BrokerAdapterReleaseReviewRepository(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(broker_adapter_release_review_events)"
            ).fetchall()
        }
    assert "conformance_run_id" in columns
    assert "conformance_report_fingerprint" in columns
