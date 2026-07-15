from __future__ import annotations

import json

from account_truth.broker_adapter_conformance import (
    BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerAdapterConformanceRepository,
)
from scripts.run_broker_adapter_conformance import main
from tests.account_truth.test_broker_adapter_release import release_manifest


def test_cli_preview_is_side_effect_free_and_record_is_explicit(
    tmp_path, capsys
) -> None:
    manifest_path = tmp_path / "release.json"
    manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
    db_path = tmp_path / "conformance.db"

    preview_code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--run-id",
            "cli-conformance-v1",
        ]
    )
    preview = json.loads(capsys.readouterr().out)
    database_created_by_preview = db_path.exists()
    record_code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--run-id",
            "cli-conformance-v1",
            "--record",
            "--acknowledgement",
            BROKER_ADAPTER_CONFORMANCE_ACKNOWLEDGEMENT,
        ]
    )
    recorded = json.loads(capsys.readouterr().out)

    assert preview_code == 0
    assert preview["validation_status"] == "passed"
    assert len(preview["scenarios"]) == 12
    assert preview["provider_contacted"] is False
    assert preview["broker_write_contacted"] is False
    assert database_created_by_preview is False
    assert record_code == 0
    assert recorded["status"] == "passed"
    assert recorded["persisted"] is True
    assert recorded["authorizes_execution"] is False


def test_cli_wrong_acknowledgement_records_no_report(tmp_path, capsys) -> None:
    manifest_path = tmp_path / "release.json"
    manifest_path.write_text(json.dumps(release_manifest()), encoding="utf-8")
    db_path = tmp_path / "conformance.db"

    code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--run-id",
            "cli-conformance-wrong-ack",
            "--record",
        ]
    )
    rejected = json.loads(capsys.readouterr().out)
    status = BrokerAdapterConformanceRepository(
        db_path,
        ensure_schema=False,
    ).get_latest("fixture-release-reviewed-v1")

    assert code == 2
    assert rejected["status"] == "rejected"
    assert "broker_adapter_conformance_acknowledgement_mismatch" in (
        rejected["blockers"]
    )
    assert status["status"] == "not_found"
