from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest

from account_truth.broker_execution_edge_conformance import (
    BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
    BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION,
    BrokerExecutionEdgeConformanceRejected,
    BrokerExecutionEdgeConformanceRepository,
    preview_broker_execution_edge_conformance_result,
    preview_broker_execution_edge_manifest,
)
from account_truth.broker_execution_edge_conformance_fixtures import (
    run_deterministic_broker_execution_edge_conformance,
)


def execution_edge_manifest() -> dict:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_MANIFEST_SCHEMA_VERSION,
        "execution_edge_ref": "fixture-execution-edge-v1",
        "adapter_ref": "fixture-adapter-contract",
        "adapter_version": "fixture-v1",
        "provider": "deterministic-fixture",
        "gateway_id": "fixture-execution-edge",
        "account_alias": "fixture-account",
        "deployment_fingerprint": "a" * 64,
        "capabilities": {
            "can_dry_run_orders": True,
            "can_submit_orders": True,
            "can_query_orders": True,
            "can_cancel_orders": True,
            "supports_idempotent_client_order_id": True,
        },
        "boundaries": {
            "runtime_auth_material_external": True,
            "default_registered": False,
            "production_enabled": False,
            "strategy_imports_adapter": False,
            "ai_imports_adapter": False,
            "core_imports_provider_sdk": False,
            "writes_oms": False,
            "writes_production_ledger": False,
            "writes_risk_state": False,
            "writes_kill_switch": False,
            "writes_capital_authority": False,
        },
        "review_refs": {
            "write_adapter_adr": "fixture-write-adapter-adr",
            "capability_matrix": "fixture-capability-matrix",
            "threat_model": "fixture-threat-model",
            "deployment_runbook": "fixture-deployment-runbook",
            "rollback_runbook": "fixture-rollback-runbook",
            "incident_runbook": "fixture-incident-runbook",
            "privacy_review": "fixture-privacy-review",
        },
        "limitations": [
            "This manifest is a deterministic local fixture, not an adapter release."
        ],
    }


def manifest_preview() -> dict:
    return preview_broker_execution_edge_manifest(
        json.dumps(execution_edge_manifest()),
        source_name="fixture-execution-edge.json",
    )


def conformance_preview(*, run_id: str = "fixture-execution-conf-v1") -> dict:
    return run_deterministic_broker_execution_edge_conformance(
        manifest_preview(),
        run_id=run_id,
    )


def result_payload(preview: dict) -> dict:
    return {
        "schema_version": BROKER_EXECUTION_EDGE_CONFORMANCE_RESULT_SCHEMA_VERSION,
        "run_id": preview["run_id"],
        "execution_edge_ref": preview["execution_edge_ref"],
        "manifest_fingerprint": preview["manifest_fingerprint"],
        "suite_version": preview["suite_version"],
        "fixture_kind": preview["fixture_kind"],
        "scenarios": deepcopy(preview["scenarios"]),
        "provider_contacted": False,
        "adapter_registered": False,
        "production_broker_contacted": False,
        "real_order_side_effect_count": 0,
    }


def failed_preview(*, run_id: str) -> dict:
    payload = result_payload(conformance_preview(run_id=run_id))
    payload["scenarios"][0]["observed_status"] = "unexpected"
    return preview_broker_execution_edge_conformance_result(payload)


def record(
    repository: BrokerExecutionEdgeConformanceRepository,
    preview: dict,
) -> dict:
    return repository.record_report(
        preview,
        acknowledgement=BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    )


def test_manifest_is_strict_complete_and_default_closed() -> None:
    preview = manifest_preview()

    assert preview["validation_status"] == "pass"
    assert preview["recordable"] is True
    assert preview["provider_contacted"] is False
    assert preview["adapter_registered"] is False
    assert preview["default_registered"] is False
    assert preview["broker_submission_enabled"] is False
    assert preview["broker_cancellation_enabled"] is False
    assert preview["authorizes_execution"] is False


def test_suite_runs_exact_broker_neutral_execution_scenarios() -> None:
    preview = conformance_preview()
    replay = conformance_preview(run_id="fixture-execution-conf-replay")

    assert preview["validation_status"] == "passed"
    assert preview["recordable"] is True
    assert len(preview["scenarios"]) == 15
    assert {item["scenario"] for item in preview["scenarios"]} == {
        "capability_contract_default_closed",
        "dry_run_no_side_effect",
        "submit_exact_identity",
        "submit_definitive_rejection",
        "duplicate_submit_idempotent",
        "concurrent_submit_idempotent",
        "submit_timeout_classified_unknown",
        "unknown_query_same_identity",
        "unknown_not_found_no_resubmit",
        "restart_query_recovery",
        "cancel_requires_separate_exact_command",
        "cancel_exact_identity",
        "duplicate_cancel_idempotent",
        "partial_fill_cancel_race",
        "disconnect_query_fail_closed",
    }
    assert all(
        item["observed_status"] == item["expected_status"]
        for item in preview["scenarios"]
    )
    assert replay["scenarios"] == preview["scenarios"]
    assert preview["provider_contacted"] is False
    assert preview["production_broker_contacted"] is False
    assert preview["real_order_side_effect_count"] == 0
    assert preview["authorizes_execution"] is False
    assert "qmt" not in json.dumps(preview).lower()
    assert "ptrade" not in json.dumps(preview).lower()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "expectation"])
def test_scenario_matrix_and_expected_results_are_strict(mutation: str) -> None:
    payload = result_payload(conformance_preview())
    if mutation == "missing":
        payload["scenarios"].pop()
    elif mutation == "duplicate":
        payload["scenarios"].append(deepcopy(payload["scenarios"][0]))
    else:
        payload["scenarios"][0]["expected_status"] = "blocked"

    preview = preview_broker_execution_edge_conformance_result(payload)

    assert preview["recordable"] is False
    assert preview["validation_status"] == "blocked"
    assert preview["record_blockers"]


def test_unknown_sensitive_and_boundary_drift_fail_closed_without_value_echo() -> None:
    manifest = execution_edge_manifest()
    manifest["api_key"] = "must-never-enter-evidence"
    sensitive = preview_broker_execution_edge_manifest(json.dumps(manifest))

    drifted_manifest = execution_edge_manifest()
    drifted_manifest["boundaries"]["production_enabled"] = True
    drifted = preview_broker_execution_edge_manifest(json.dumps(drifted_manifest))

    assert sensitive["recordable"] is False
    assert "broker_execution_edge_auth_material_not_allowed" in (
        sensitive["record_blockers"]
    )
    assert "must-never-enter-evidence" not in json.dumps(sensitive)
    assert drifted["recordable"] is True
    assert drifted["validation_status"] == "blocked"
    assert "broker_execution_edge_boundary_violation:production_enabled" in (
        drifted["blockers"]
    )

    malformed_result = result_payload(conformance_preview())
    malformed_result["real_order_side_effect_count"] = False
    malformed = preview_broker_execution_edge_conformance_result(malformed_result)
    assert malformed["recordable"] is False
    assert "broker_execution_edge_real_order_side_effect_count_invalid" in (
        malformed["record_blockers"]
    )


def test_record_is_idempotent_restart_safe_and_latest_failure_wins(tmp_path) -> None:
    db_path = tmp_path / "execution-edge.db"
    repository = BrokerExecutionEdgeConformanceRepository(db_path)
    passed = conformance_preview()

    first = record(repository, passed)
    replay = record(repository, passed)
    with pytest.raises(BrokerExecutionEdgeConformanceRejected) as conflict:
        record(repository, failed_preview(run_id=passed["run_id"]))
    restarted = BrokerExecutionEdgeConformanceRepository(
        db_path,
        ensure_schema=False,
    )
    clear = restarted.verify_manifest_binding(
        execution_edge_ref=passed["execution_edge_ref"],
        manifest_fingerprint=passed["manifest_fingerprint"],
    )
    failed = record(repository, failed_preview(run_id="fixture-execution-conf-v2"))
    blocked = restarted.verify_manifest_binding(
        execution_edge_ref=passed["execution_edge_ref"],
        manifest_fingerprint=passed["manifest_fingerprint"],
    )

    assert first["status"] == "passed"
    assert first["persisted"] is True
    assert replay["reused"] is True
    assert "broker_execution_edge_run_id_conflict" in (
        conflict.value.evidence["blockers"]
    )
    assert clear["status"] == "clear"
    assert failed["status"] == "blocked"
    assert blocked["status"] == "blocked"
    assert "broker_execution_edge_latest_report_not_passed" in blocked["blockers"]


def test_manifest_drift_and_report_tampering_fail_closed(tmp_path) -> None:
    db_path = tmp_path / "execution-edge.db"
    repository = BrokerExecutionEdgeConformanceRepository(db_path)
    preview = conformance_preview()
    record(repository, preview)

    drifted = repository.verify_manifest_binding(
        execution_edge_ref=preview["execution_edge_ref"],
        manifest_fingerprint="e" * 64,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE broker_execution_edge_conformance_reports
            SET report_json = '{}'
            WHERE run_id = ?
            """,
            (preview["run_id"],),
        )
        conn.commit()
    tampered = repository.verify_manifest_binding(
        execution_edge_ref=preview["execution_edge_ref"],
        manifest_fingerprint=preview["manifest_fingerprint"],
    )

    assert "broker_execution_edge_manifest_mismatch" in drifted["blockers"]
    assert "broker_execution_edge_report_integrity_invalid" in tampered["blockers"]
    assert "broker_execution_edge_report_structure_invalid" in tampered["blockers"]


def test_preview_and_lookup_create_no_domain_state(tmp_path) -> None:
    absent_path = tmp_path / "absent.db"
    read_only = BrokerExecutionEdgeConformanceRepository(
        absent_path,
        ensure_schema=False,
    )
    assert read_only.get_latest("fixture-execution-edge-v1")["status"] == (
        "not_configured"
    )
    assert absent_path.exists() is False

    db_path = tmp_path / "record.db"
    repository = BrokerExecutionEdgeConformanceRepository(db_path)
    record(repository, conformance_preview())
    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "broker_execution_edge_conformance_reports" in tables
    assert "oms_orders" not in tables
    assert "fills" not in tables
    assert "ledger_entries" not in tables
    assert "risk_decisions" not in tables
    assert "capital_authorizations" not in tables


def test_wrong_acknowledgement_records_no_report(tmp_path) -> None:
    repository = BrokerExecutionEdgeConformanceRepository(tmp_path / "record.db")
    with pytest.raises(BrokerExecutionEdgeConformanceRejected) as rejected:
        repository.record_report(conformance_preview(), acknowledgement="")

    assert "broker_execution_edge_acknowledgement_mismatch" in (
        rejected.value.evidence["blockers"]
    )
    assert repository.get_latest("fixture-execution-edge-v1")["status"] == ("not_found")
