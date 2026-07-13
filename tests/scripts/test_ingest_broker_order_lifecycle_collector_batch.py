from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
)
from scripts.ingest_broker_order_lifecycle_collector_batch import main


def _payload() -> dict:
    captured_at = datetime.now(UTC)
    return {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": "script-fixture-run-1",
        "collector_id": "script-fixture-collector",
        "deployment_id": "script-fixture-deployment",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "f" * 64,
        "release_evidence_ref": "script-fixture-release",
        "release_review_status": "unreviewed",
        "adapter_authorization_ref": "test-only-user-authorization",
        "provider": "script_fixture",
        "gateway_id": "script-fixture-gateway",
        "account_id": "private-script-fixture-account",
        "account_alias": "script-fixture-account",
        "collection_mode": "fixture",
        "source_contact_status": "not_contacted",
        "connection_status": "not_applicable",
        "batch_status": "complete",
        "cursor": {"previous": 0, "current": 1},
        "captured_at": captured_at.isoformat(),
        "event_count": 1,
        "callbacks_received": 0,
        "duplicate_callbacks_dropped": 0,
        "out_of_order_callbacks_dropped": 0,
        "lifecycle": {
            "schema_version": "karkinos.broker_order_lifecycle_export.v1",
            "provider": "script_fixture",
            "snapshot_kind": "exact_order_lifecycle",
            "gateway_id": "script-fixture-gateway",
            "account_id": "private-script-fixture-account",
            "account_alias": "script-fixture-account",
            "captured_at": captured_at.isoformat(),
            "source_sequence": 1,
            "orders": [
                {
                    "broker_order_id": "SCRIPT-FIXTURE-ORDER-1",
                    "client_order_id": "KARK-script-fixture-client-1",
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
        },
    }


def test_cli_preview_is_side_effect_free_and_record_is_explicit(
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "collector-batch.json"
    source.write_text(json.dumps(_payload()), encoding="utf-8")
    db_path = tmp_path / "collector.db"

    preview_code = main(["--file", str(source), "--db", str(db_path)])
    preview = json.loads(capsys.readouterr().out)
    database_created_by_preview = db_path.exists()
    record_code = main(
        [
            "--file",
            str(source),
            "--db",
            str(db_path),
            "--record",
            "--acknowledgement",
            BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
        ]
    )
    recorded = json.loads(capsys.readouterr().out)

    assert preview_code == 0
    assert preview["ready_to_advance_cursor"] is True
    assert database_created_by_preview is False
    assert db_path.exists() is True
    assert record_code == 0
    assert recorded["run_status"] == "recorded"
    assert recorded["provider_contacted"] is False
    assert recorded["broker_submission_enabled"] is False
