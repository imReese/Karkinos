from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
)
from scripts.import_qmt_order_lifecycle import main


def _payload() -> dict:
    captured_at = datetime.now(UTC)
    return {
        "schema_version": "karkinos.qmt_order_lifecycle_export.v1",
        "provider": "qmt",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "qmt-controlled-write-1",
        "account_id": "private-qmt-account-001",
        "account_alias": "main-cn-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": 1,
        "orders": [
            {
                "broker_order_id": "QMT-ORDER-1",
                "client_order_id": "KARK-client-order-1",
                "symbol": "600519",
                "side": "buy",
                "status": "open",
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": (captured_at - timedelta(seconds=2)).isoformat(),
                "updated_at": (captured_at - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": [],
    }


def test_cli_defaults_to_preview_without_creating_database(tmp_path, capsys) -> None:
    source = tmp_path / "qmt-lifecycle.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    db_path = tmp_path / "lifecycle.db"

    exit_code = main(["--file", str(source), "--db", str(db_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation_status"] == "pass"
    assert output["ready_to_record"] is True
    assert output["provider_contacted"] is False
    assert output["broker_submission_enabled"] is False
    assert db_path.exists() is False


def test_cli_requires_exact_acknowledgement_before_recording(tmp_path, capsys) -> None:
    source = tmp_path / "qmt-lifecycle.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    db_path = tmp_path / "lifecycle.db"

    rejected_code = main(["--file", str(source), "--db", str(db_path), "--record"])
    rejected = json.loads(capsys.readouterr().out)
    recorded_code = main(
        [
            "--file",
            str(source),
            "--db",
            str(db_path),
            "--record",
            "--acknowledgement",
            BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
        ]
    )
    recorded = json.loads(capsys.readouterr().out)

    assert rejected_code == 2
    assert rejected["status"] == "rejected"
    assert "qmt_order_lifecycle_acknowledgement_mismatch" in rejected["blockers"]
    assert recorded_code == 0
    assert recorded["validation_status"] == "pass"
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path, ensure_schema=False
        ).list_observations(limit=10)[0]["observation_id"]
        == recorded["observation_id"]
    )
