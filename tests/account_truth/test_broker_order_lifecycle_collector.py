from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from account_truth.broker_order_lifecycle import (
    BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleEvidenceRepository,
    preview_broker_order_lifecycle_export,
)
from account_truth.broker_order_lifecycle_collector import (
    BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    BrokerOrderLifecycleCollectorRejected,
    BrokerOrderLifecycleCollectorRepository,
    preview_broker_order_lifecycle_collector_batch,
)

NOW = datetime(2026, 7, 13, 8, 0, 0, tzinfo=UTC)


def _lifecycle(
    *,
    cursor: int = 1,
    captured_at: datetime = NOW,
    status: str = "open",
    broker_order_id: str = "FIXTURE-ORDER-1",
) -> dict:
    return {
        "schema_version": "karkinos.broker_order_lifecycle_export.v1",
        "provider": "deterministic_fixture",
        "snapshot_kind": "exact_order_lifecycle",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "captured_at": captured_at.isoformat(),
        "source_sequence": cursor,
        "orders": [
            {
                "broker_order_id": broker_order_id,
                "client_order_id": "KARK-fixture-client-order-1",
                "symbol": "600519",
                "side": "buy",
                "status": status,
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


def _batch(
    *,
    run_id: str = "collector-run-1",
    cursor_previous: int = 0,
    cursor_current: int = 1,
    captured_at: datetime = NOW,
    lifecycle: dict | None = None,
    deployment_fingerprint: str = "d" * 64,
    release_review_status: str = "unreviewed",
    collection_mode: str = "fixture",
    source_contact_status: str = "not_contacted",
    connection_status: str = "not_applicable",
    batch_status: str = "complete",
    event_count: int = 1,
    callbacks_received: int = 0,
    duplicate_callbacks_dropped: int = 0,
    out_of_order_callbacks_dropped: int = 0,
) -> dict:
    return {
        "schema_version": "karkinos.broker_order_lifecycle_collector_batch.v1",
        "run_id": run_id,
        "collector_id": "deterministic-fixture-collector",
        "deployment_id": "fixture-deployment-1",
        "collector_version": "fixture-v1",
        "deployment_fingerprint": deployment_fingerprint,
        "release_evidence_ref": "fixture-release-unreviewed",
        "release_review_status": release_review_status,
        "adapter_authorization_ref": "test-only-user-authorization",
        "provider": "deterministic_fixture",
        "gateway_id": "fixture-gateway-1",
        "account_id": "private-fixture-account-001",
        "account_alias": "fixture-account",
        "collection_mode": collection_mode,
        "source_contact_status": source_contact_status,
        "connection_status": connection_status,
        "batch_status": batch_status,
        "cursor": {
            "previous": cursor_previous,
            "current": cursor_current,
        },
        "captured_at": captured_at.isoformat(),
        "event_count": event_count,
        "callbacks_received": callbacks_received,
        "duplicate_callbacks_dropped": duplicate_callbacks_dropped,
        "out_of_order_callbacks_dropped": out_of_order_callbacks_dropped,
        "lifecycle": (
            lifecycle
            if lifecycle is not None
            else _lifecycle(cursor=cursor_current, captured_at=captured_at)
        ),
    }


def _preview(payload: dict) -> dict:
    return preview_broker_order_lifecycle_collector_batch(
        json.dumps(payload),
        source_name="deterministic broker collector fixture",
        clock=lambda: NOW,
    )


def _ingest(repository, preview: dict) -> dict:
    return repository.ingest(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )


def test_complete_batch_records_lifecycle_and_advances_cursor(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    preview = _preview(_batch())

    result = _ingest(repository, preview)
    state = repository.get_state(
        provider="deterministic_fixture",
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
    )
    lifecycle = BrokerOrderLifecycleEvidenceRepository(
        db_path,
        ensure_schema=False,
    ).resolve_order(
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
        broker_order_id="FIXTURE-ORDER-1",
        client_order_id="KARK-fixture-client-order-1",
    )

    assert preview["validation_status"] == "pass"
    assert result["run_status"] == "recorded"
    assert result["provider_contacted"] is False
    assert result["default_registered"] is False
    assert result["does_not_mutate_oms"] is True
    assert result["does_not_mutate_fills"] is True
    assert result["does_not_mutate_production_ledger"] is True
    assert result["does_not_mutate_risk_state"] is True
    assert result["does_not_mutate_kill_switch"] is True
    assert result["does_not_mutate_capital_authority"] is True
    assert state["status"] == "found"
    assert state["last_cursor"] == 1
    assert lifecycle["status"] == "found"
    assert lifecycle["order"]["status"] == "open"

    database_text = db_path.read_bytes().decode("utf-8", errors="ignore")
    assert "private-fixture-account-001" not in database_text


def test_same_run_and_same_evidence_with_new_run_are_idempotent(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    first_preview = _preview(_batch())
    first = _ingest(repository, first_preview)
    same_run = _ingest(repository, first_preview)
    duplicate_payload = _batch(run_id="collector-run-duplicate")
    duplicate = _ingest(repository, _preview(duplicate_payload))

    assert first["run_status"] == "recorded"
    assert same_run["run_status"] == "recorded"
    assert same_run["reused"] is True
    assert duplicate["run_status"] == "duplicate"
    assert duplicate["lifecycle_observation_id"] == first["lifecycle_observation_id"]
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            tmp_path / "collector.db",
            ensure_schema=False,
        ).list_observations(limit=10)
        != []
    )
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                tmp_path / "collector.db",
                ensure_schema=False,
            ).list_observations(limit=10)
        )
        == 1
    )


def test_same_cursor_with_different_evidence_is_blocked(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    _ingest(repository, _preview(_batch()))
    changed = _batch(
        run_id="collector-run-conflict",
        lifecycle=_lifecycle(status="rejected"),
    )

    result = _ingest(repository, _preview(changed))
    state = repository.get_state(
        provider="deterministic_fixture",
        gateway_id="fixture-gateway-1",
        account_alias="fixture-account",
    )

    assert result["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_evidence_conflict" in (
        result["blockers"]
    )
    assert state["last_cursor"] == 1


def test_gap_and_out_of_order_cursor_do_not_advance_state(tmp_path) -> None:
    gap_repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "gap.db")
    gap_payload = _batch(
        run_id="collector-gap",
        cursor_previous=2,
        cursor_current=3,
        captured_at=NOW,
        lifecycle=_lifecycle(cursor=3),
    )
    gap = _ingest(gap_repository, _preview(gap_payload))

    out_of_order_db = tmp_path / "out-of-order.db"
    lifecycle_preview = preview_broker_order_lifecycle_export(
        json.dumps(_lifecycle(cursor=2)),
        source_name="deterministic preexisting lifecycle",
        clock=lambda: NOW,
    )
    BrokerOrderLifecycleEvidenceRepository(out_of_order_db).record(
        lifecycle_preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_RECORD_ACKNOWLEDGEMENT,
    )
    out_of_order_repository = BrokerOrderLifecycleCollectorRepository(out_of_order_db)
    old_payload = _batch(
        run_id="collector-out-of-order",
        cursor_previous=0,
        cursor_current=1,
        lifecycle=_lifecycle(cursor=1),
    )
    out_of_order = _ingest(out_of_order_repository, _preview(old_payload))

    assert gap["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_gap" in gap["blockers"]
    assert (
        gap_repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )
    assert out_of_order["run_status"] == "blocked"
    assert "broker_order_lifecycle_collector_cursor_out_of_order" in (
        out_of_order["blockers"]
    )


@pytest.mark.parametrize(
    ("collection_mode", "connection_status", "batch_status", "expected_blocker"),
    [
        (
            "callback",
            "disconnected",
            "partial",
            "broker_order_lifecycle_collector_disconnected",
        ),
        (
            "poll",
            "not_applicable",
            "partial",
            "broker_order_lifecycle_collector_partial_batch",
        ),
    ],
)
def test_disconnect_and_partial_batch_are_persisted_without_cursor_advance(
    tmp_path,
    collection_mode: str,
    connection_status: str,
    batch_status: str,
    expected_blocker: str,
) -> None:
    db_path = tmp_path / f"{connection_status}-{batch_status}.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    payload = _batch(
        run_id=f"collector-{connection_status}-{batch_status}",
        collection_mode=collection_mode,
        source_contact_status="read_only_contact",
        release_review_status="reviewed",
        connection_status=connection_status,
        batch_status=batch_status,
        event_count=0,
    )
    payload["lifecycle"] = None

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "blocked"
    assert expected_blocker in result["blockers"]
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )


def test_process_restart_replays_prepared_preview_without_duplicate_fact(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    first_process = BrokerOrderLifecycleCollectorRepository(db_path)
    preview = _preview(_batch(run_id="collector-restart-run"))

    prepared = first_process.prepare(
        preview,
        acknowledgement=BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT,
    )
    assert prepared["run_status"] == "prepared"
    assert (
        BrokerOrderLifecycleEvidenceRepository(
            db_path,
            ensure_schema=False,
        ).list_observations()
        == []
    )

    restarted_process = BrokerOrderLifecycleCollectorRepository(db_path)
    recorded = restarted_process.commit_prepared("collector-restart-run")
    replayed = restarted_process.commit_prepared("collector-restart-run")

    assert recorded["run_status"] == "recorded"
    assert replayed["run_status"] == "recorded"
    assert replayed["reused"] is True
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                db_path,
                ensure_schema=False,
            ).list_observations()
        )
        == 1
    )


def test_deployment_drift_blocks_next_cursor(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    _ingest(repository, _preview(_batch()))
    second_payload = _batch(
        run_id="collector-run-2",
        cursor_previous=1,
        cursor_current=2,
        captured_at=NOW + timedelta(seconds=1),
        lifecycle=_lifecycle(
            cursor=2,
            captured_at=NOW + timedelta(seconds=1),
        ),
        deployment_fingerprint="e" * 64,
    )

    result = _ingest(repository, _preview(second_payload))

    assert result["run_status"] == "blocked"
    assert (
        "broker_order_lifecycle_collector_deployment_fingerprint_changed"
        in result["blockers"]
    )
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["last_cursor"]
        == 1
    )


def test_duplicate_and_out_of_order_callback_telemetry_cannot_add_facts(
    tmp_path,
) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    payload = _batch(
        collection_mode="callback",
        source_contact_status="read_only_contact",
        connection_status="connected",
        release_review_status="reviewed",
        callbacks_received=4,
        duplicate_callbacks_dropped=2,
        out_of_order_callbacks_dropped=1,
    )

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "recorded"
    assert result["callbacks_received"] == 4
    assert result["duplicate_callbacks_dropped"] == 2
    assert result["out_of_order_callbacks_dropped"] == 1
    assert (
        len(
            BrokerOrderLifecycleEvidenceRepository(
                db_path,
                ensure_schema=False,
            ).list_observations()
        )
        == 1
    )


def test_live_source_requires_reviewed_read_only_adapter_authorization(
    tmp_path,
) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    payload = _batch(
        collection_mode="callback",
        connection_status="connected",
        callbacks_received=1,
    )

    result = _ingest(repository, _preview(payload))

    assert result["run_status"] == "blocked"
    assert (
        "broker_order_lifecycle_collector_live_source_contact_not_read_only"
        in result["blockers"]
    )
    assert (
        "broker_order_lifecycle_collector_adapter_release_not_reviewed"
        in result["blockers"]
    )
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_found"
    )


def test_preview_drift_and_wrong_acknowledgement_are_rejected(tmp_path) -> None:
    repository = BrokerOrderLifecycleCollectorRepository(tmp_path / "collector.db")
    preview = _preview(_batch())
    drifted = deepcopy(preview)
    drifted["cursor_current"] = 2

    with pytest.raises(BrokerOrderLifecycleCollectorRejected) as wrong_ack:
        repository.prepare(preview, acknowledgement="")
    with pytest.raises(BrokerOrderLifecycleCollectorRejected) as drift:
        repository.prepare(
            drifted,
            acknowledgement=(BROKER_ORDER_LIFECYCLE_COLLECTOR_RECORD_ACKNOWLEDGEMENT),
        )

    assert "broker_order_lifecycle_collector_acknowledgement_mismatch" in (
        wrong_ack.value.evidence["blockers"]
    )
    assert "broker_order_lifecycle_collector_preview_fingerprint_drift" in (
        drift.value.evidence["blockers"]
    )


def test_read_only_repository_does_not_create_absent_database(tmp_path) -> None:
    db_path = tmp_path / "absent.db"
    repository = BrokerOrderLifecycleCollectorRepository(
        db_path,
        ensure_schema=False,
    )

    assert repository.list_runs() == []
    assert (
        repository.get_state(
            provider="deterministic_fixture",
            gateway_id="fixture-gateway-1",
            account_alias="fixture-account",
        )["status"]
        == "not_configured"
    )
    assert db_path.exists() is False


def test_only_expected_evidence_tables_are_created(tmp_path) -> None:
    db_path = tmp_path / "collector.db"
    repository = BrokerOrderLifecycleCollectorRepository(db_path)
    _ingest(repository, _preview(_batch()))

    with sqlite3.connect(db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "oms_orders" not in tables
    assert "fills" not in tables
    assert "capital_authorizations" not in tables
    assert {
        "broker_order_lifecycle_collector_runs",
        "broker_order_lifecycle_collector_state",
        "broker_order_lifecycle_observations",
        "broker_order_lifecycle_orders",
        "broker_order_lifecycle_fills",
    }.issubset(tables)
