from __future__ import annotations

import json

from account_truth.broker_execution_edge_conformance import (
    BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
    BrokerExecutionEdgeConformanceRepository,
)
from scripts.run_broker_execution_edge_conformance import main
from tests.account_truth.test_broker_execution_edge_conformance import (
    execution_edge_manifest,
)


def test_cli_preview_is_side_effect_free_and_record_is_explicit(
    tmp_path,
    capsys,
) -> None:
    manifest_path = tmp_path / "execution-edge.json"
    manifest_path.write_text(
        json.dumps(execution_edge_manifest()),
        encoding="utf-8",
    )
    db_path = tmp_path / "execution-edge.db"

    preview_code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--run-id",
            "cli-execution-edge-v1",
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
            "cli-execution-edge-v1",
            "--record",
            "--acknowledgement",
            BROKER_EXECUTION_EDGE_CONFORMANCE_ACKNOWLEDGEMENT,
        ]
    )
    recorded = json.loads(capsys.readouterr().out)

    assert preview_code == 0
    assert preview["validation_status"] == "passed"
    assert len(preview["scenarios"]) == 15
    assert preview["provider_contacted"] is False
    assert preview["production_broker_contacted"] is False
    assert preview["does_not_submit_broker_order"] is True
    assert preview["does_not_cancel_broker_order"] is True
    assert database_created_by_preview is False
    assert record_code == 0
    assert recorded["status"] == "passed"
    assert recorded["persisted"] is True
    assert recorded["authorizes_execution"] is False


def test_cli_wrong_acknowledgement_records_no_report(tmp_path, capsys) -> None:
    manifest_path = tmp_path / "execution-edge.json"
    manifest_path.write_text(
        json.dumps(execution_edge_manifest()),
        encoding="utf-8",
    )
    db_path = tmp_path / "execution-edge.db"

    code = main(
        [
            "--file",
            str(manifest_path),
            "--db",
            str(db_path),
            "--run-id",
            "cli-execution-edge-wrong-ack",
            "--record",
        ]
    )
    rejected = json.loads(capsys.readouterr().out)
    status = BrokerExecutionEdgeConformanceRepository(
        db_path,
        ensure_schema=False,
    ).get_latest("fixture-execution-edge-v1")

    assert code == 2
    assert rejected["status"] == "rejected"
    assert "broker_execution_edge_acknowledgement_mismatch" in (rejected["blockers"])
    assert status["status"] == "not_found"
