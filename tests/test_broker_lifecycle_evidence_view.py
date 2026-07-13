from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)
from server.db import AppDatabase
from server.services.broker_lifecycle_evidence_view import (
    BrokerLifecycleEvidenceViewService,
)

NOW = datetime(2026, 7, 13, 8, 0, 0, tzinfo=UTC)


def _record_collector_run(
    db: AppDatabase,
    *,
    release_review_status: str = "reviewed",
) -> dict:
    lifecycle = {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "deterministic_fixture",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "captured_at": NOW.isoformat(),
        "source_sequence": 1,
        "orders": [
            {
                "broker_order_id": "FIXTURE-ORDER-1",
                "client_order_id": "KARK-fixture-client-order-1",
                "symbol": "600519",
                "side": "buy",
                "status": "open",
                "order_quantity": "100",
                "cumulative_filled_quantity": "0",
                "cancelled_quantity": "0",
                "average_fill_price": None,
                "submitted_at": (NOW - timedelta(seconds=2)).isoformat(),
                "updated_at": (NOW - timedelta(seconds=1)).isoformat(),
            }
        ],
        "fills": [],
    }
    batch = {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": "collector-run-1",
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "fixture-deployment-1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": "d" * 64,
        "release_evidence_ref": "fixture-release-reviewed",
        "release_review_status": release_review_status,
        "adapter_authorization_ref": "test-only-user-authorization",
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "collection_mode": "fixture",
        "source_contact_status": "not_contacted",
        "connection_status": "not_applicable",
        "batch_status": "complete",
        "cursor": {"previous": 0, "current": 1},
        "captured_at": NOW.isoformat(),
        "event_count": 1,
        "callbacks_received": 0,
        "duplicate_callbacks_dropped": 0,
        "out_of_order_callbacks_dropped": 0,
        "lifecycle": lifecycle,
    }
    preview = preview_broker_order_lifecycle_collector_batch(
        json.dumps(batch),
        source_name="deterministic broker lifecycle fixture",
        clock=lambda: NOW,
    )
    return BrokerOrderLifecycleCollectorRepository(db._path).ingest(
        preview,
        acknowledgement=(BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT),
    )


def test_persisted_collector_run_is_broker_neutral_health_source(tmp_path) -> None:
    db = AppDatabase(tmp_path / "operator-view.db")
    db.init_sync()
    run = _record_collector_run(db)

    service = BrokerLifecycleEvidenceViewService(db=db)
    health = service.list_health()
    query = service.query("fixture-gateway-1")

    assert run["run_status"] == "recorded"
    assert len(health) == 1
    item = health[0]
    assert item["schema_version"] == ("karkinos.broker_lifecycle_evidence_health.v1")
    assert item["connector_id"] == "fixture-gateway-1"
    assert item["provider"] == "deterministic_fixture"
    assert item["registered"] is False
    assert item["default_registered"] is False
    assert item["status"] == "collector_evidence_clear"
    assert item["provider_contact_performed"] is False
    assert item["reads_persisted_facts_only"] is True
    assert item["can_submit_orders"] is False
    assert item["can_cancel_orders"] is False
    assert item["latest_collector_runs"][0]["run_id"] == "collector-run-1"
    assert query["status"] == "persisted_evidence_clear"
    assert query["account_facts_included"] is False
    assert query["does_not_mutate_oms"] is True
    assert query["does_not_mutate_production_ledger"] is True
    assert query["does_not_mutate_risk_state"] is True
    assert query["does_not_mutate_capital_authority"] is True
    encoded = json.dumps(query, ensure_ascii=False)
    assert "private-fixture-account-001" not in encoded
    assert "qmt" not in encoded.lower()


def test_unreviewed_adapter_release_blocks_clear_health(tmp_path) -> None:
    db = AppDatabase(tmp_path / "operator-view.db")
    db.init_sync()
    _record_collector_run(db, release_review_status="unreviewed")

    item = BrokerLifecycleEvidenceViewService(db=db).list_health()[0]

    assert item["status"] == "collector_evidence_blocked"
    assert "broker_lifecycle_collector_release_not_reviewed" in item["blockers"]
    assert item["third_party_adapter_review_required"] is True
    assert item["provider_contact_performed"] is False
    assert item["can_submit_orders"] is False
